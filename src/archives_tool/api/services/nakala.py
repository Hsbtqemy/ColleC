"""Service de cache + réconciliation Nakala (P1b).

Met en cache un dépôt Nakala (lu via `external/nakala`) dans les tables
externes (`SourceExterne` / `RessourceExterne`) et le réconcilie avec un
Item ColleC de même DOI (`Item.doi_nakala`) via `LienExterneItem`.

Ne **crée pas** d'item (c'est le rôle de `rapatrier`, P1c) : ici on ne
fait que cacher et lier ce qui existe déjà côté ColleC.

Le mapping dépôt→structure neutre est fait en amont par
`external.nakala.mapper.mapper_depot` ; ce service consomme un
:class:`DepotNakala` + le JSON brut.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import FormulaireInvalide
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    ItemInvalide,
    creer_item,
    formulaire_depuis_item,
    modifier_item,
)
from archives_tool.external.nakala.client import (
    ClientLectureNakala,
    normaliser_identifiant_nakala,
)
from archives_tool.external.nakala.collection import iterer_donnees_collection
from archives_tool.external.nakala.mapper import DepotNakala, mapper_depot
from archives_tool.files.nakala import construire_source_fichier_nakala
from archives_tool.models import (
    Collection,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
    LienExterneItem,
    RessourceExterne,
    SourceExterne,
    TypeCollection,
)


class RapatriementInvalide(FormulaireInvalide):
    """Données insuffisantes pour rapatrier (cote indérivable, etc.)."""


class RafraichissementImpossible(Exception):
    """Aucun item ColleC n'est lié au DOI demandé (rapatrier d'abord)."""

#: Code stable de la `SourceExterne` Nakala (unique en base).
SOURCE_NAKALA_CODE = "nakala"

#: `type_relation` du lien item ↔ ressource Nakala.
TYPE_RELATION_DEPOT = "depot_nakala"

_URL_BASE_DEFAUT = "https://api.nakala.fr"


def source_nakala(
    db: Session, *, url_base: str = _URL_BASE_DEFAUT
) -> SourceExterne:
    """Récupère (ou crée) la `SourceExterne` « nakala ». Idempotent.

    `url_base` ne sert qu'à la création initiale (informative) ; un appel
    ultérieur retourne la source existante sans la modifier.
    """
    source = db.scalar(
        select(SourceExterne).where(SourceExterne.code == SOURCE_NAKALA_CODE)
    )
    if source is None:
        source = SourceExterne(
            code=SOURCE_NAKALA_CODE,
            libelle="Nakala (Huma-Num)",
            type_api="nakala",
            url_base=url_base,
        )
        db.add(source)
        db.flush()
    return source


def upsert_ressource(
    db: Session,
    source: SourceExterne,
    depot: DepotNakala,
    brut: dict,
) -> RessourceExterne:
    """Insère ou met à jour la `RessourceExterne` du dépôt (clé : source +
    DOI). `recupere_le` est bumpé à chaque pull ; `metadonnees_brutes`
    stocke le JSON Nakala tel quel (forensique + base d'un futur diff)."""
    ressource = db.scalar(
        select(RessourceExterne).where(
            RessourceExterne.source_id == source.id,
            RessourceExterne.identifiant_externe == depot.identifiant,
        )
    )
    if ressource is None:
        ressource = RessourceExterne(
            source_id=source.id, identifiant_externe=depot.identifiant
        )
        db.add(ressource)
    ressource.type = depot.type_coar
    ressource.titre = depot.titre
    ressource.auteurs = depot.createurs or None
    ressource.date = depot.date
    ressource.metadonnees_brutes = brut
    ressource.statut = "actif"
    ressource.recupere_le = datetime.now()
    db.flush()
    return ressource


def reconcilier_item(
    db: Session, ressource: RessourceExterne, *, cree_par: str | None = None
) -> Item | None:
    """Lie la ressource à un Item ColleC de même DOI, si présent.

    Idempotent (le lien unique (item, ressource, type) n'est créé qu'une
    fois). Ne crée pas d'item : retourne `None` si aucun Item ne porte ce
    `doi_nakala` (le rapatriement éventuel relève de P1c).
    """
    item = db.scalar(
        select(Item).where(Item.doi_nakala == ressource.identifiant_externe)
    )
    if item is None:
        return None
    lien = db.scalar(
        select(LienExterneItem).where(
            LienExterneItem.item_id == item.id,
            LienExterneItem.ressource_externe_id == ressource.id,
            LienExterneItem.type_relation == TYPE_RELATION_DEPOT,
        )
    )
    if lien is None:
        db.add(
            LienExterneItem(
                item_id=item.id,
                ressource_externe_id=ressource.id,
                type_relation=TYPE_RELATION_DEPOT,
                cree_par=cree_par,
            )
        )
        db.flush()
    return item


def mettre_en_cache_depot(
    db: Session,
    depot: DepotNakala,
    brut: dict,
    *,
    url_base: str = _URL_BASE_DEFAUT,
    cree_par: str | None = None,
) -> tuple[RessourceExterne, Item | None]:
    """Orchestration P1b : source + upsert ressource + réconciliation,
    en une transaction (commit unique). Retourne la ressource cachée et
    l'Item lié (ou `None` si aucun Item ne porte ce DOI)."""
    source = source_nakala(db, url_base=url_base)
    ressource = upsert_ressource(db, source, depot, brut)
    item = reconcilier_item(db, ressource, cree_par=cree_par)
    db.commit()
    return ressource, item


# ---------------------------------------------------------------------------
# P1c — rapatrier (créer un item depuis un dépôt) / rafraîchir (re-pull)
# ---------------------------------------------------------------------------

#: Champs documentaires d'un item alimentés par Nakala (overwrite à
#: `rafraichir`). Les champs ColleC-only (cote, etat_catalogage,
#: notes_internes, numero*, fonds_id) sont préservés.
_CHAMPS_DOCUMENTAIRES: tuple[str, ...] = (
    "titre", "date", "type_coar", "langue", "description",
)


def _cote_depuis_doi(doi: str) -> str | None:
    """Dérive une cote ColleC depuis un DOI Nakala.

    `10.34847/nkl.abcdef12` → `abcdef12` ; versionné `...abcdef12.v2` →
    `abcdef12` (suffixe de version retiré). Garde uniquement
    `[A-Za-z0-9_-]` (conforme à `PATTERN_COTE`). Retourne `None` si rien
    d'exploitable (l'appelant devra fournir une cote explicite).
    """
    s = (doi or "").strip()
    if "nkl." in s:
        s = s.split("nkl.", 1)[1]
    else:
        s = s.rsplit("/", 1)[-1]
    s = s.split(".")[0]  # retire un éventuel suffixe de version .vN
    s = "".join(c for c in s if c.isalnum() or c in "_-")
    return s or None


def _metadonnees_nakala(depot: DepotNakala) -> dict[str, Any]:
    """Clés `metadonnees` alimentées par un dépôt Nakala.

    `createurs` / `sujets` / `licence` sont nommés comme les attend
    l'export (`exporters/nakala.py`, `mapping_dc`) ; `langues` n'est posé
    que s'il y en a plusieurs (la 1re va dans `Item.langue`). Le reste
    (`dcterms_*`) vient du catch-all du mapper.
    """
    m: dict[str, Any] = dict(depot.metadonnees)
    if depot.createurs:
        m["createurs"] = depot.createurs
    if depot.sujets:
        m["sujets"] = depot.sujets
    if depot.licence:
        m["licence"] = depot.licence
    if len(depot.langues) > 1:
        m["langues"] = depot.langues
    return m


def _depot_vers_formulaire(
    depot: DepotNakala,
    *,
    fonds_id: int,
    cote: str,
    base: FormulaireItem | None = None,
    doi_collection: str | None = None,
) -> FormulaireItem:
    """Construit un `FormulaireItem` depuis un dépôt.

    `base` (rafraîchir) : formulaire de l'item existant — on n'écrase que
    les champs documentaires + les clés `metadonnees` issues de Nakala,
    en préservant le reste (cote, état, notes, numéro, version). `None`
    (rapatrier) : création neuve (état brouillon par défaut).

    `doi_collection` (pull collection) : rattachement Nakala partagé, posé
    uniquement à la création (jamais en rafraîchir, pour ne pas écraser un
    choix local).
    """
    langue = depot.langues[0] if depot.langues else ""
    metadonnees = dict(base.metadonnees) if base else {}
    metadonnees.update(_metadonnees_nakala(depot))

    if base is not None:
        form = base.model_copy(deep=True)
        form.titre = depot.titre or ""
        form.date = depot.date or ""
        form.type_coar = depot.type_coar or ""
        form.langue = langue
        form.description = depot.description or ""
        form.doi_nakala = depot.identifiant
        form.metadonnees = metadonnees
        return form

    return FormulaireItem(
        cote=cote,
        titre=depot.titre or "",
        fonds_id=fonds_id,
        date=depot.date or "",
        type_coar=depot.type_coar or "",
        langue=langue,
        description=depot.description or "",
        doi_nakala=depot.identifiant,
        doi_collection_nakala=doi_collection or "",
        metadonnees=metadonnees,
    )


def materialiser_fichiers_nakala(
    db: Session,
    item: Item,
    brut: dict,
    *,
    base_url: str,
    ajoute_par: str | None = None,
) -> int:
    """Crée les `Fichier` ColleC d'un item depuis les fichiers d'un dépôt.

    Lit directement `brut["files"]` (clés réelles de l'API : `name`,
    `sha1`, `size`, `extension`, `mime_type`, `puid`, `embargoed`) plutôt
    que la projection `DepotNakala.fichiers` (lossy). Chaque fichier reçoit
    une `iiif_url_nakala` construite via `construire_source_fichier_nakala`
    (info.json pour les images, data URL sinon) — seule source disponible
    pour un fichier Nakala-only, et suffisante pour le CHECK.

    Le `sha1` Nakala est rangé dans `Fichier.sha1_nakala` (colonne dédiée
    posée par P3+a, cf. `nakala-depot-future.md` difficulté #4) **et**
    conservé en miroir dans `metadonnees["sha1"]` pour la rétrocompatibilité
    des consommateurs qui le lisaient là (exports, scripts ad-hoc). Surtout
    **pas** dans `hash_sha256` : algos différents (SHA-1 vs SHA-256),
    l'y mettre fausserait la détection de doublons QA.

    Retourne le nombre de fichiers créés. Les fichiers sans `sha1` (URL
    non constructible) sont ignorés.
    """
    doi = (brut.get("identifier") or "").strip()
    fichiers = brut.get("files") or []
    if not doi:
        return 0

    cree = 0
    for f in fichiers:
        sha1 = (f.get("sha1") or "").strip()
        if not sha1:
            continue  # sans sha1 : URL non constructible (CHECK), on saute
        nom = f.get("name") or sha1
        source = construire_source_fichier_nakala(
            base_url, doi, sha1, nom_fichier=str(nom)
        )
        taille = f.get("size")
        try:
            taille_octets = int(taille) if taille not in (None, "") else None
        except (TypeError, ValueError):
            taille_octets = None
        meta_fichier = {
            cle: f[cle]
            for cle in ("sha1", "mime_type", "puid", "embargoed")
            if f.get(cle) not in (None, "", [])
        }
        # `ordre` = rang parmi les fichiers réellement créés (contigu,
        # même si des fichiers sans sha1 ont été sautés) — évite un faux
        # « saut d'ordre » dans le panneau fichiers.
        cree += 1
        db.add(
            Fichier(
                item_id=item.id,
                nom_fichier=str(nom),
                ordre=cree,
                iiif_url_nakala=source,
                sha1_nakala=sha1,
                taille_octets=taille_octets,
                format=(f.get("extension") or None),
                # S7 — transcription/description publique du scan (round-trip
                # Nakala). `None` si le fichier distant n'en porte pas.
                description_externe=(f.get("description") or None),
                metadonnees=meta_fichier or None,
                ajoute_par=ajoute_par,
            )
        )
    return cree


@dataclass
class RapportRapatriement:
    """Résultat d'un `rapatrier`. `item_id`/`cote` None si dry-run pur."""

    cote: str
    fonds_id: int
    dry_run: bool
    deja_existant: bool
    item_id: int | None = None
    nb_fichiers: int = 0  # fichiers Nakala matérialisés (création réelle)
    #: S3 — cotes des Collections ColleC auxquelles l'item a été rattaché
    #: d'après les `collectionsIds` Nakala (réconciliation par doi_nakala).
    collections_liees: list[str] = field(default_factory=list)
    #: DOIs de collections Nakala dont aucune Collection ColleC ne porte le
    #: `doi_nakala` (signalées, jamais auto-créées — scope read-only du pull).
    collections_inconnues: list[str] = field(default_factory=list)


def _resoudre_collections_par_doi(
    db: Session, collections_ids: list[str]
) -> tuple[list[Collection], list[str]]:
    """DOIs Nakala (`collectionsIds`) → (Collections ColleC matchées, DOIs
    inconnus). Lecture seule.

    Matching **normalisé des deux côtés** : le `doi_nakala` stocké peut être
    une forme non canonique selon son origine (import d'un export Nakala avec
    un DOI en forme URL `https://nakala.fr/collection/…`), alors que le
    `collectionsIds` distant est un DOI nu. Sans normaliser le côté stocké, le
    match échouerait silencieusement. Déduplique les DOIs entrants (un même
    DOI listé deux fois ne donne qu'un match).
    """
    vus: set[str] = set()
    dois: list[str] = []
    for brut in collections_ids:
        d = normaliser_identifiant_nakala(brut)
        if d and d not in vus:
            vus.add(d)
            dois.append(d)
    if not dois:
        return [], []
    # Index normalisé des doi_nakala stockés (collections peu nombreuses →
    # une requête, négligeable même en boucle de pull collection).
    par_doi: dict[str, Collection] = {}
    for c in db.scalars(
        select(Collection).where(Collection.doi_nakala.isnot(None))
    ).all():
        cle = normaliser_identifiant_nakala(c.doi_nakala or "")
        if cle:
            par_doi.setdefault(cle, c)
    matchees: list[Collection] = []
    inconnues: list[str] = []
    for d in dois:
        coll = par_doi.get(d)
        if coll is not None:
            matchees.append(coll)
        else:
            inconnues.append(d)
    return matchees, inconnues


def _reconcilier_collections_nakala(
    db: Session,
    item: Item | None,
    fonds_id: int,
    collections_ids: list[str],
    *,
    ajoute_par: str | None = None,
    appliquer: bool = True,
) -> tuple[list[str], list[str]]:
    """Réconcilie l'appartenance d'un item aux collections Nakala (S3).

    Pour chaque DOI de `collections_ids`, trouve la Collection ColleC dont
    `doi_nakala` matche (normalisé des deux côtés) et, si `appliquer`, lie
    l'item via la junction `ItemCollection` (idempotent, **sans commit** : le
    commit englobant — `mettre_en_cache_depot` — persiste tout atomiquement).

    **Additif uniquement** : rejoue l'appartenance Nakala à chaque pull mais
    ne retire **jamais** de lien. Conséquences assumées : (a) les
    appartenances **ColleC-only** (collections sans pendant Nakala) sont
    préservées ; (b) une appartenance retirée manuellement côté ColleC mais
    **toujours présente sur Nakala** sera **ré-ajoutée** au prochain pull (le
    pull réaffirme l'état Nakala) ; (c) une appartenance disparue côté Nakala
    n'est pas retirée localement (pas de réconciliation des suppressions).

    **Ne crée aucune Collection** : un DOI sans pendant ColleC reste
    « inconnu » (signalé, jamais auto-créé — scope lecture). La **miroir du
    fonds** de l'item est **exclue** du rapport : `creer_item` la lie déjà
    automatiquement (invariant 6), ce n'est pas un rattachement S3.

    `appliquer=False` (aperçu / dry-run) : résout et rapporte sans écrire ;
    `item` peut alors être `None`.

    Retourne `(cotes_liees, dois_inconnus)` — `cotes_liees` = collections
    (hors miroir du fonds) auxquelles l'item appartient d'après Nakala.
    """
    matchees, inconnues = _resoudre_collections_par_doi(db, collections_ids)
    liees: list[str] = []
    for coll in matchees:
        # Miroir du fonds : déjà liée par creer_item → on ne la compte pas.
        if (
            coll.type_collection == TypeCollection.MIROIR.value
            and coll.fonds_id == fonds_id
        ):
            continue
        if appliquer and item is not None and (
            db.get(ItemCollection, (item.id, coll.id)) is None
        ):
            db.add(ItemCollection(
                item_id=item.id, collection_id=coll.id, ajoute_par=ajoute_par,
            ))
        liees.append(coll.cote)
    return liees, inconnues


def rapatrier(
    db: Session,
    depot: DepotNakala,
    brut: dict,
    *,
    fonds_id: int,
    cote: str | None = None,
    cree_par: str | None = None,
    dry_run: bool = False,
    doi_collection: str | None = None,
    base_url: str | None = None,
) -> RapportRapatriement:
    """Crée un Item ColleC depuis un dépôt Nakala, dans `fonds_id`.

    - `cote` explicite, sinon dérivée du DOI (`_cote_depuis_doi`) ;
    - si un item porte déjà ce DOI → ne recrée pas (`deja_existant=True`,
      utiliser `rafraichir`) ;
    - `dry_run` → aucune écriture, retourne juste le plan (cote, fonds,
      déjà-existant) ;
    - réel → `creer_item` + cache + lien (via `mettre_en_cache_depot`) ;
    - `base_url` fourni → matérialise aussi les fichiers Nakala en `Fichier`
      (`iiif_url_nakala`, T2.5), rendant l'item navigable. Absent → item seul
      (rétrocompat : appels directs sans hôte Nakala).
    """
    cote_finale = (cote or _cote_depuis_doi(depot.identifiant) or "").strip()
    if not cote_finale:
        raise RapatriementInvalide(
            {"cote": f"cote indérivable du DOI {depot.identifiant!r} — fournir --cote"}
        )

    deja = db.scalar(
        select(Item).where(Item.doi_nakala == depot.identifiant)
    )
    if deja is not None:
        # Item déjà présent (rapatrié, créé manuellement, ou échec partiel
        # d'un cache antérieur) : on ne recrée pas, mais sur un run réel on
        # garantit quand même le cache + le lien (idempotent). L'overwrite
        # des champs relève de `rafraichir`.
        # Réconcilie l'appartenance collection (S3). En dry-run : aperçu
        # lecture seule (appliquer=False) pour que le preview liste ce qui
        # SERAIT lié. En réel : lie (avant le commit du cache → atomique).
        liees, inconnues = _reconcilier_collections_nakala(
            db, deja, deja.fonds_id, depot.collections_ids,
            ajoute_par=cree_par, appliquer=not dry_run,
        )
        if not dry_run:
            mettre_en_cache_depot(db, depot, brut, cree_par=cree_par)
        return RapportRapatriement(
            cote=deja.cote, fonds_id=deja.fonds_id, dry_run=dry_run,
            deja_existant=True, item_id=deja.id,
            collections_liees=liees, collections_inconnues=inconnues,
        )

    if dry_run:
        # Aperçu lecture seule des collections qui seraient rattachées (S3).
        liees, inconnues = _reconcilier_collections_nakala(
            db, None, fonds_id, depot.collections_ids, appliquer=False,
        )
        return RapportRapatriement(
            cote=cote_finale, fonds_id=fonds_id, dry_run=True,
            deja_existant=False, item_id=None,
            collections_liees=liees, collections_inconnues=inconnues,
        )

    form = _depot_vers_formulaire(
        depot, fonds_id=fonds_id, cote=cote_finale, doi_collection=doi_collection
    )
    item = creer_item(db, form, cree_par=cree_par)
    nb_fichiers = 0
    if base_url:
        nb_fichiers = materialiser_fichiers_nakala(
            db, item, brut, base_url=base_url, ajoute_par=cree_par
        )
    # Réconcilie l'appartenance aux collections Nakala (S3) avant le commit
    # du cache → persisté atomiquement avec lui.
    liees, inconnues = _reconcilier_collections_nakala(
        db, item, item.fonds_id, depot.collections_ids,
        ajoute_par=cree_par, appliquer=True,
    )
    mettre_en_cache_depot(db, depot, brut, cree_par=cree_par)
    return RapportRapatriement(
        cote=item.cote, fonds_id=item.fonds_id, dry_run=False,
        deja_existant=False, item_id=item.id, nb_fichiers=nb_fichiers,
        collections_liees=liees, collections_inconnues=inconnues,
    )


@dataclass
class ChampDiff:
    champ: str
    avant: str | None
    apres: str | None


@dataclass
class RapportRafraichissement:
    """Diff d'un re-pull. `applique=False` en dry-run."""

    item_cote: str
    item_id: int
    diffs: list[ChampDiff] = field(default_factory=list)
    metadonnees_modifiees: bool = False
    applique: bool = False

    @property
    def a_des_changements(self) -> bool:
        return bool(self.diffs) or self.metadonnees_modifiees


def _item_lie_au_doi(db: Session, doi: str) -> Item:
    item = db.scalar(select(Item).where(Item.doi_nakala == doi))
    if item is None:
        raise RafraichissementImpossible(
            f"Aucun item ColleC ne porte le DOI {doi!r} — rapatrier d'abord."
        )
    return item


def rafraichir(
    db: Session,
    depot: DepotNakala,
    brut: dict,
    *,
    modifie_par: str | None = None,
    dry_run: bool = True,
) -> RapportRafraichissement:
    """Re-tire un dépôt et le compare à l'item lié (par DOI).

    `dry_run` (défaut **True**) : calcule le diff des champs documentaires
    + signale si les métadonnées changeraient, sans rien écrire — c'est
    le garde-fou contre l'écrasement silencieux d'un travail local
    (difficulté n°1 du chantier). `dry_run=False` applique l'overwrite
    des champs documentaires + métadonnées Nakala via `modifier_item`
    (bump version/traçabilité) et rafraîchit le cache.
    """
    item = _item_lie_au_doi(db, depot.identifiant)
    base = formulaire_depuis_item(item)
    cible = _depot_vers_formulaire(depot, fonds_id=item.fonds_id, cote=item.cote, base=base)

    diffs = [
        ChampDiff(champ=c, avant=getattr(base, c) or None, apres=getattr(cible, c) or None)
        for c in _CHAMPS_DOCUMENTAIRES
        if (getattr(base, c) or None) != (getattr(cible, c) or None)
    ]
    meta_modif = (base.metadonnees or {}) != (cible.metadonnees or {})

    rapport = RapportRafraichissement(
        item_cote=item.cote, item_id=item.id, diffs=diffs,
        metadonnees_modifiees=meta_modif, applique=False,
    )
    if dry_run or not rapport.a_des_changements:
        return rapport

    modifier_item(db, item.id, cible, modifie_par=modifie_par)
    mettre_en_cache_depot(db, depot, brut, cree_par=modifie_par)
    rapport.applique = True
    return rapport


# ---------------------------------------------------------------------------
# Lot 2 — rapatrier une collection entière (Fonds + N Items)
# ---------------------------------------------------------------------------

_NKL_TITLE = "http://nakala.fr/terms#title"


def titre_collection_nakala(meta: dict) -> str | None:
    """Extrait le `nkl:title` d'une collection Nakala (1er trouvé).

    Public : réutilisé par la CLI (`exporter-tableur`) pour titrer la feuille
    xlsx, en plus du pull collection.
    """
    for m in meta.get("metas") or []:
        if m.get("propertyUri") == _NKL_TITLE and m.get("value"):
            return str(m["value"]).strip()
    return None


def _poser_doi_miroir(db: Session, fonds: Fonds, doi_collection: str) -> None:
    """Pose le DOI de la collection Nakala sur la miroir du fonds.

    `Collection.doi_nakala` est UNIQUE : si le DOI est déjà pris par une
    autre collection, on annule (rollback) ce seul rattachement — le fonds
    déjà committé par `creer_fonds` reste intact."""
    miroir = db.scalar(
        select(Collection).where(
            Collection.fonds_id == fonds.id,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )
    if miroir is None:
        return
    miroir.doi_nakala = doi_collection
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


@dataclass
class RapportRapatriementCollection:
    """Résultat agrégé d'un `rapatrier_collection`."""

    doi_collection: str
    fonds_cote: str | None
    dry_run: bool
    fonds_cree: bool = False
    crees: list[str] = field(default_factory=list)
    deja_existants: list[str] = field(default_factory=list)
    erreurs: list[tuple[str, str]] = field(default_factory=list)
    fichiers_crees: int = 0  # total des fichiers Nakala matérialisés

    @property
    def total(self) -> int:
        return len(self.crees) + len(self.deja_existants) + len(self.erreurs)


def rapatrier_collection(
    db: Session,
    client: ClientLectureNakala,
    doi_collection: str,
    *,
    fonds_cote: str | None = None,
    cree_par: str | None = None,
    dry_run: bool = False,
) -> RapportRapatriementCollection:
    """Rapatrie tous les dépôts d'une collection Nakala dans un fonds ColleC.

    - **Cible** : `fonds_cote` fourni → fonds existant (lève
      `FondsIntrouvable` si absent) ; sinon un fonds est créé (cote dérivée
      du DOI collection, titre = titre Nakala, DOI posé sur la miroir). En
      dry-run sans fonds existant, aucun fonds n'est créé (rapport
      prévisionnel : tout serait créé).
    - **Boucle** : chaque donnée est mappée puis confiée au `rapatrier`
      unitaire (réutilisation directe : Item + Fichiers + cache + lien,
      `doi_collection_nakala` posé). Une donnée en échec (cote en collision)
      est collectée dans `erreurs` sans arrêter le lot.

    Le choix donnée/fichier ne s'applique pas ici : le modèle ColleC est
    nativement Item 1..n Fichier (une donnée → un Item portant ses fichiers).

    Les fichiers Nakala sont **matérialisés en `Fichier`** (T2.5) via
    `rapatrier(base_url=...)` : chaque fichier reçoit son `iiif_url_nakala`
    (info.json pour les images, data URL sinon), ce qui rend l'item
    navigable dans la visionneuse. Le JSON brut reste aussi caché dans
    `RessourceExterne.metadonnees_brutes`.
    """
    meta = client.lire_collection(doi_collection)
    titre = titre_collection_nakala(meta) or doi_collection

    cote_cible = fonds_cote or _cote_depuis_doi(doi_collection) or doi_collection
    fonds: Fonds | None = None
    fonds_cree = False
    if fonds_cote:
        fonds = lire_fonds_par_cote(db, fonds_cote)  # FondsIntrouvable si absent
    else:
        existant = db.scalar(select(Fonds).where(Fonds.cote == cote_cible))
        if existant is not None:
            fonds = existant
        elif not dry_run:
            fonds = creer_fonds(
                db, FormulaireFonds(cote=cote_cible, titre=titre), cree_par=cree_par
            )
            fonds_cree = True
            _poser_doi_miroir(db, fonds, doi_collection)

    rapport = RapportRapatriementCollection(
        doi_collection=doi_collection,
        fonds_cote=fonds.cote if fonds is not None else cote_cible,
        dry_run=dry_run,
        fonds_cree=fonds_cree,
    )

    for brut in iterer_donnees_collection(client, doi_collection):
        depot = mapper_depot(brut)
        if fonds is None:
            # Dry-run sur un fonds qui n'existe pas encore : tout serait créé.
            rapport.crees.append(_cote_depuis_doi(depot.identifiant) or depot.identifiant)
            continue
        try:
            r = rapatrier(
                db, depot, brut,
                fonds_id=fonds.id, cree_par=cree_par, dry_run=dry_run,
                doi_collection=doi_collection, base_url=client.base_url,
            )
        except (RapatriementInvalide, ItemInvalide) as e:
            detail = getattr(e, "erreurs", None) or str(e)
            rapport.erreurs.append((depot.identifiant, str(detail)))
            continue
        if r.deja_existant:
            rapport.deja_existants.append(r.cote)
        else:
            rapport.crees.append(r.cote)
            rapport.fichiers_crees += r.nb_fichiers

    return rapport


# ---------------------------------------------------------------------------
# T2.3 — rafraîchir une collection entière (re-pull + diff par item lié)
# ---------------------------------------------------------------------------


@dataclass
class RapportRafraichissementCollection:
    """Résultat agrégé d'un `rafraichir_collection`."""

    doi_collection: str
    dry_run: bool
    #: Diffs des données liées à un Item ColleC (modifiées ou non).
    rapports: list[RapportRafraichissement] = field(default_factory=list)
    #: DOIs présents dans la collection mais sans Item ColleC (à rapatrier).
    non_lies: list[str] = field(default_factory=list)
    erreurs: list[tuple[str, str]] = field(default_factory=list)

    @property
    def modifies(self) -> list[RapportRafraichissement]:
        return [r for r in self.rapports if r.a_des_changements]

    @property
    def inchanges(self) -> list[RapportRafraichissement]:
        return [r for r in self.rapports if not r.a_des_changements]


def rafraichir_collection(
    db: Session,
    client: ClientLectureNakala,
    doi_collection: str,
    *,
    modifie_par: str | None = None,
    dry_run: bool = True,
) -> RapportRafraichissementCollection:
    """Re-tire toute une collection Nakala et la compare aux items liés.

    Boucle le `rafraichir` unitaire sur chaque donnée :

    - donnée liée à un Item ColleC (par DOI) → diff documentaire + métadonnées
      (overwrite si ``dry_run=False`` et qu'il y a des changements) ;
    - donnée **sans** Item lié → ajoutée à ``non_lies`` (informatif : c'est
      attendu si la collection a grossi depuis le rapatriement — utiliser
      `rapatrier-collection` pour les nouvelles) ;
    - overwrite invalide (ex. dépôt sans titre) → collecté dans ``erreurs``.

    `dry_run` défaut **True** (garde-fou contre l'écrasement silencieux,
    cohérent avec `rafraichir`). Comme le `rafraichir` unitaire, **les
    fichiers ne sont pas re-synchronisés** (champs documentaires seulement).
    """
    rapport = RapportRafraichissementCollection(
        doi_collection=doi_collection, dry_run=dry_run
    )
    for brut in iterer_donnees_collection(client, doi_collection):
        depot = mapper_depot(brut)
        try:
            r = rafraichir(
                db, depot, brut, modifie_par=modifie_par, dry_run=dry_run
            )
        except RafraichissementImpossible:
            rapport.non_lies.append(depot.identifiant)
            continue
        except ItemInvalide as e:
            detail = getattr(e, "erreurs", None) or str(e)
            rapport.erreurs.append((depot.identifiant, str(detail)))
            continue
        rapport.rapports.append(r)
    return rapport
