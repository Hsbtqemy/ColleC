"""Service de dépôt (création) vers Nakala (P2/A4).

Orchestre la création d'un dépôt Nakala depuis un Item ColleC :

1. `item_vers_slugs` : Item (colonnes + `metadonnees`) → dict slug → valeur,
   en réutilisant le savoir interne→Nakala de `exporters/nakala.py`
   (createur, type projeté, langue, sujets, dcterms_* extras).
2. `depot_mapper.slugs_vers_metas` → `metas[]` Nakala (carte 57 champs).
3. `preflight.preflight_appliquer` → cascade créateur/date + avertissements.
4. upload des **fichiers locaux** (`files/paths.resoudre_chemin`) puis
   `POST /datas` (statut `pending` par défaut → réversible).

Garde-fous : Item déjà déposé (`doi_nakala`) sauté ; aucun fichier local →
refus (un Item Nakala-only n'est pas re-déposable) ; cleanup des uploads
orphelins si le `POST /datas` échoue après upload ; **dry-run par défaut**
(plan + warnings sans aucune écriture, ni locale ni distante).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from archives_tool.api.services.nakala import mettre_en_cache_depot
from archives_tool.api.services.vocabulaires import type_coar_pour_nakala
from archives_tool.external.nakala.client import ClientLectureNakala, ErreurNakala
from archives_tool.external.nakala.depot_mapper import (
    MULTILINGUE_SLUGS,
    SLUG_TO_NAKALA,
    STRUCTURE_SLUGS,
    MetaInvalide,
    slugs_vers_metas,
)
from archives_tool.external.nakala.mapper import mapper_depot
from archives_tool.external.nakala.preflight import preflight_appliquer
from archives_tool.external.nakala.write_client import (
    NakalaEcritureClient,
    extraire_doi,
)
from archives_tool.models import Collection, Item, RessourceExterne

#: Licence par défaut si l'item n'en porte pas (alignée sur l'export CSV).
LICENCE_DEFAUT = "CC-BY-NC-ND-4.0"


class DepotImpossible(Exception):
    """Le dépôt ne peut pas avoir lieu (déjà déposé géré à part, ici :
    aucun fichier local déposable, ou métadonnées insuffisantes)."""


def _liste(valeur: Any) -> list[str]:
    """Normalise une valeur metadonnees (str | list | None) en liste de str."""
    if valeur is None:
        return []
    if isinstance(valeur, list):
        return [str(v) for v in valeur if v not in (None, "")]
    return [str(valeur)] if str(valeur).strip() else []


def _coercer_extra(slug: str, valeur: Any, lang: str | None) -> Any:
    """Adapte une valeur `metadonnees.dcterms_*` (plate) à la forme attendue
    par le mapper, selon la catégorie du slug. Renvoie `None` si non
    coercible (ex. spatial/temporal structuré) → l'extra est alors sauté."""
    valeurs = _liste(valeur)
    if not valeurs:
        return None
    if slug in STRUCTURE_SLUGS:
        return None  # spatial/temporal : pas de forme plate fiable
    if slug in MULTILINGUE_SLUGS:
        return [{"value": v, "lang": lang} for v in valeurs]
    # langue, tableaux de chaînes, relations, dates → liste de chaînes
    return valeurs


def item_vers_slugs(item: Item, *, licence_defaut: str = LICENCE_DEFAUT) -> dict[str, Any]:
    """Construit le dict slug → valeur d'un Item pour le dépôt Nakala.

    Champs cœur depuis les colonnes (titre, créateur, date, type projeté,
    licence, description, sujet, langue) ; extras `dcterms_*` repris de
    `metadonnees` avec coercition de forme (best-effort)."""
    meta = item.metadonnees or {}
    lang = item.langue or None

    slugs: dict[str, Any] = {}
    # Titre (multilingue, toujours présent).
    slugs["nkl_title"] = [{"value": item.titre or "", "lang": lang}]
    # Créateur (toujours émis ; null/anonyme si absent → traité par preflight).
    createurs = _liste(
        meta.get("createurs") or meta.get("auteurs")
        or meta.get("createur") or meta.get("auteur")
    )
    slugs["nkl_creator"] = createurs or None
    # Date (toujours émise).
    slugs["nkl_created"] = item.date or None
    # Type COAR projeté vers le set Nakala.
    if item.type_coar:
        slugs["nkl_type"] = type_coar_pour_nakala(item.type_coar) or item.type_coar
    # Licence (repli défaut).
    licence = meta.get("licence") or meta.get("rights") or licence_defaut
    if licence:
        slugs["nkl_license"] = licence
    # Description (multilingue).
    if item.description:
        slugs["dcterms_description"] = [{"value": item.description, "lang": lang}]
    # Sujets (multilingue).
    sujets = _liste(meta.get("sujets") or meta.get("sujet"))
    if sujets:
        slugs["dcterms_subject"] = [{"value": s, "lang": lang} for s in sujets]
    # Langue (code).
    if lang:
        slugs["dcterms_language"] = [lang]

    # Extras dcterms_* présents dans metadonnees (publisher, source, relation,
    # dates, contributor, identifier…) — coercion best-effort, sauté si non
    # coercible ou déjà couvert par le cœur.
    for cle, val in meta.items():
        if not cle.startswith("dcterms_") or cle in slugs or cle not in SLUG_TO_NAKALA:
            continue
        coerce = _coercer_extra(cle, val, lang)
        if coerce is not None:
            slugs[cle] = coerce
    return slugs


@dataclass
class RapportDepot:
    """Résultat d'un `deposer_item`. En dry-run : `doi` None, `metas`/`fichiers`
    décrivent ce qui serait envoyé."""

    cote: str
    dry_run: bool
    deja_depose: bool = False
    doi: str | None = None
    nb_fichiers: int = 0
    fichiers: list[str] = field(default_factory=list)
    metas: list[dict[str, Any]] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)


def _fichiers_locaux(
    item: Item, racines: Mapping[str, Path]
) -> list[tuple[Path, str]]:
    """Résout les Fichier de l'item ayant un binaire local existant.

    Renvoie `[(chemin_absolu, nom_fichier)]` trié par `ordre`. Les Fichier
    Nakala-only (pas de `chemin_relatif`/`racine`) ou introuvables sur disque
    sont ignorés."""
    from archives_tool.files.paths import resoudre_chemin

    locaux: list[tuple[Path, str]] = []
    for f in sorted(item.fichiers, key=lambda x: x.ordre):
        if not f.racine or not f.chemin_relatif:
            continue
        try:
            chemin = resoudre_chemin(racines, f.racine, f.chemin_relatif)
        except (KeyError, ValueError):
            continue
        if chemin.is_file():
            locaux.append((chemin, f.nom_fichier))
    return locaux


def deposer_item(
    db: Any,
    client: NakalaEcritureClient,
    item: Item,
    *,
    racines: Mapping[str, Path],
    statut: str = "pending",
    collection_doi: str | None = None,
    cree_par: str | None = None,
    dry_run: bool = True,
    licence_defaut: str = LICENCE_DEFAUT,
) -> RapportDepot:
    """Crée un dépôt Nakala depuis un Item ColleC.

    - Item déjà déposé (`doi_nakala`) → `deja_depose=True`, rien fait.
    - Aucun fichier local → `DepotImpossible`.
    - métadonnées insuffisantes → `MetaInvalide` (preflight).
    - dry-run (défaut) → renvoie le plan (metas, fichiers, avertissements)
      sans écrire. Réel → upload + `POST /datas` + pose `Item.doi_nakala`.
    """
    if item.doi_nakala:
        return RapportDepot(
            cote=item.cote, dry_run=dry_run, deja_depose=True, doi=item.doi_nakala
        )

    locaux = _fichiers_locaux(item, racines)
    if not locaux:
        raise DepotImpossible(
            f"Item {item.cote!r} : aucun fichier local à déposer "
            "(les Fichier Nakala-only ne sont pas re-déposables)."
        )

    slugs = item_vers_slugs(item, licence_defaut=licence_defaut)
    metas = slugs_vers_metas(slugs)
    metas, avertissements = preflight_appliquer(metas)  # peut lever MetaInvalide

    if dry_run:
        return RapportDepot(
            cote=item.cote, dry_run=True, doi=None,
            nb_fichiers=len(locaux), fichiers=[nom for _, nom in locaux],
            metas=metas, avertissements=avertissements,
        )

    # Réel : upload des fichiers puis création du dépôt.
    uploades: list[dict[str, Any]] = []
    sha1s: list[str] = []
    try:
        for chemin, nom in locaux:
            desc = client.uploader_fichier(chemin, nom)
            uploades.append({"sha1": desc["sha1"], "name": desc.get("name") or nom})
            sha1s.append(desc["sha1"])
        reponse = client.creer_depot(
            metas=metas, files=uploades, status=statut,
            collections_ids=[collection_doi] if collection_doi else None,
        )
    except ErreurNakala:
        # Cleanup best-effort des uploads orphelins (le POST a échoué après upload).
        for sha1 in sha1s:
            try:
                client.supprimer_upload(sha1)
            except ErreurNakala:
                pass
        raise

    doi = extraire_doi(reponse)
    item.doi_nakala = doi
    item.modifie_par = cree_par
    item.modifie_le = datetime.now()
    db.commit()

    return RapportDepot(
        cote=item.cote, dry_run=False, doi=doi,
        nb_fichiers=len(locaux), fichiers=[nom for _, nom in locaux],
        metas=metas, avertissements=avertissements,
    )


# ---------------------------------------------------------------------------
# Stage B — orchestration : créer la collection Nakala + déposer ses items
# ---------------------------------------------------------------------------


#: propertyUri des champs de collection que ColleC modélise et **possède**
#: (titre + description) — pour la fusion au push (cf.
#: `pousser_metadonnees_collection`). Doit rester aligné sur les slugs émis
#: par `collection_vers_metas`.
_PROPRIETES_COLLECTION_GEREES: frozenset[str] = frozenset({
    SLUG_TO_NAKALA["nkl_title"]["propertyUri"],
    SLUG_TO_NAKALA["dcterms_description"]["propertyUri"],
})


def collection_vers_metas(collection: Collection) -> list[dict[str, Any]]:
    """Métadonnées Nakala d'une collection (titre + description).

    Les collections Nakala sont plus légères que les données (pas de
    créateur/date/type obligatoires) : titre suffit. ColleC ne modélise que
    ces deux champs (cf. `_PROPRIETES_COLLECTION_GEREES`)."""
    slugs: dict[str, Any] = {"nkl_title": [{"value": collection.titre or "", "lang": None}]}
    if collection.description:
        slugs["dcterms_description"] = [{"value": collection.description, "lang": None}]
    return slugs_vers_metas(slugs)


@dataclass
class RapportDepotCollection:
    """Résultat agrégé d'un `deposer_collection`."""

    collection_cote: str
    dry_run: bool
    collection_doi: str | None = None
    collection_creee: bool = False
    deposes: list[RapportDepot] = field(default_factory=list)
    sautes: list[str] = field(default_factory=list)  # déjà déposés
    non_deposables: list[str] = field(default_factory=list)  # aucun fichier local
    erreurs: list[tuple[str, str]] = field(default_factory=list)


def deposer_collection(
    db: Any,
    client: NakalaEcritureClient,
    collection: Collection,
    *,
    racines: Mapping[str, Path],
    statut_donnee: str = "pending",
    statut_collection: str = "private",
    cree_par: str | None = None,
    dry_run: bool = True,
    licence_defaut: str = LICENCE_DEFAUT,
) -> RapportDepotCollection:
    """Crée la collection Nakala puis y dépose ses items.

    - Collection déjà déposée (`doi_nakala`) → réutilisée (pas recréée).
    - Dry-run (défaut) : ne crée rien ; renvoie le plan par item.
    - Réel : `POST /collections` → pose `Collection.doi_nakala`, puis
      `deposer_item` par item déposable en rattachant. Items déjà déposés →
      `sautes` ; sans fichier local → `non_deposables` ; échec mapping/Nakala
      → `erreurs` (n'arrête pas le lot).
    """
    rapport = RapportDepotCollection(
        collection_cote=collection.cote, dry_run=dry_run,
        collection_doi=collection.doi_nakala,
    )

    # Cible collection : existante, créée (réel), ou prévue (dry-run).
    if not collection.doi_nakala and not dry_run:
        reponse = client.creer_collection(
            metas=collection_vers_metas(collection), status=statut_collection
        )
        rapport.collection_doi = extraire_doi(reponse)
        rapport.collection_creee = True
        collection.doi_nakala = rapport.collection_doi
        db.commit()

    for item in collection.items:
        try:
            r = deposer_item(
                db, client, item, racines=racines, statut=statut_donnee,
                collection_doi=rapport.collection_doi, cree_par=cree_par,
                dry_run=dry_run, licence_defaut=licence_defaut,
            )
        except DepotImpossible:
            rapport.non_deposables.append(item.cote)
            continue
        except (MetaInvalide, ErreurNakala) as exc:
            rapport.erreurs.append((item.cote, str(exc)))
            continue
        if r.deja_depose:
            rapport.sautes.append(item.cote)
        else:
            rapport.deposes.append(r)
    return rapport


# ---------------------------------------------------------------------------
# P3 — round-trip : pousser les modifs de métadonnées + publier
# ---------------------------------------------------------------------------


@dataclass
class ChampPushDiff:
    """Une propriété dont la valeur diffère entre Nakala (avant) et le local
    (apres) — rendus lisibles, ordre-insensible."""

    property_uri: str
    avant: list[str]
    apres: list[str]


def _canon_valeur(v: Any) -> Any:
    """Forme canonique d'une valeur de meta pour la comparaison de diff.

    Nakala **enrichit** les créateurs au stockage : on envoie
    `{givenname, surname}` et il renvoie `{authorId, fullName, givenname,
    orcid: null, surname}`. Pour ne pas voir un faux changement à chaque push,
    on ne compare que les champs **identifiants** que ColleC contrôle
    (`surname`, `givenname`, `orcid` non nul) et on ignore les champs ajoutés
    par Nakala (`authorId`, `fullName`, `orcid: null`)."""
    if isinstance(v, dict):
        canon: dict[str, Any] = {}
        for cle in ("surname", "givenname"):
            if v.get(cle):
                canon[cle] = v[cle]
        if v.get("orcid"):
            canon["orcid"] = v["orcid"]
        return canon
    return v


def _cle_valeur(v: Any) -> str:
    """Forme canonique comparable d'une valeur de meta (str | dict | None)."""
    return json.dumps(_canon_valeur(v), sort_keys=True, ensure_ascii=False)


def _grouper_metas(metas: list[dict[str, Any]]) -> dict[str, list[tuple[str, Any]]]:
    groupes: dict[str, list[tuple[str, Any]]] = {}
    for m in metas:
        uri = m.get("propertyUri")
        if not uri:
            continue
        groupes.setdefault(uri, []).append((_cle_valeur(m.get("value")), m.get("lang")))
    return groupes


def _rendre(paires: list[tuple[str, Any]]) -> list[str]:
    out: list[str] = []
    for cle, lang in paires:
        v = json.loads(cle)
        if v is None:
            rendu = "∅"
        elif isinstance(v, str):
            rendu = v
        else:
            rendu = json.dumps(v, ensure_ascii=False)
        out.append(f"[{lang}] {rendu}" if lang else rendu)
    return out


def diff_push(
    metas_distantes: list[dict[str, Any]], metas_locales: list[dict[str, Any]]
) -> list[ChampPushDiff]:
    """Diff par propertyUri (multiset value/lang, insensible à l'ordre).

    Renvoie une entrée par propriété dont l'ensemble des valeurs diffère.
    Liste vide = round-trip idempotent (le local correspond au distant)."""
    gd = _grouper_metas(metas_distantes)
    gl = _grouper_metas(metas_locales)
    diffs: list[ChampPushDiff] = []
    for uri in sorted(set(gd) | set(gl)):
        if Counter(gd.get(uri, [])) != Counter(gl.get(uri, [])):
            diffs.append(
                ChampPushDiff(uri, _rendre(gd.get(uri, [])), _rendre(gl.get(uri, [])))
            )
    return diffs


@dataclass
class RapportPush:
    """Résultat d'un `pousser_item`. En dry-run : `applique=False`, `diffs`
    décrit ce qui changerait sur Nakala."""

    cote: str
    doi: str
    dry_run: bool
    diffs: list[ChampPushDiff] = field(default_factory=list)
    derive: bool = False  # le distant a changé depuis notre dernier fetch
    applique: bool = False

    @property
    def a_des_changements(self) -> bool:
        return bool(self.diffs)


def _metas_locales(item: Item, licence_defaut: str = LICENCE_DEFAUT) -> list[dict[str, Any]]:
    metas = slugs_vers_metas(item_vers_slugs(item, licence_defaut=licence_defaut))
    metas, _ = preflight_appliquer(metas)
    return metas


def _baseline_moddate(db: Any, doi: str) -> str | None:
    """`modDate` du dernier dépôt caché pour ce DOI (None si pas de cache)."""
    ressource = db.scalar(
        select(RessourceExterne).where(RessourceExterne.identifiant_externe == doi)
    )
    if ressource is not None and ressource.metadonnees_brutes:
        return ressource.metadonnees_brutes.get("modDate")
    return None


def pousser_item(
    db: Any,
    client_lecture: ClientLectureNakala,
    client_ecriture: NakalaEcritureClient,
    item: Item,
    *,
    dry_run: bool = True,
    modifie_par: str | None = None,
    licence_defaut: str = LICENCE_DEFAUT,
) -> RapportPush:
    """Pousse les métadonnées locales d'un Item vers son dépôt Nakala existant.

    Exige `item.doi_nakala` (sinon `DepotImpossible` : utiliser `deposer`).
    Re-tire le dépôt distant pour calculer le **diff** (par propriété) + un
    drapeau de **dérive** (le distant a-t-il changé depuis notre dernier
    fetch ?). Dry-run (défaut) → renvoie le diff sans écrire. Réel →
    `PUT /datas/{id}` (remplace les metas) puis rafraîchit le cache.
    """
    if not item.doi_nakala:
        raise DepotImpossible(
            f"Item {item.cote!r} n'a pas de DOI Nakala — utiliser `deposer`."
        )
    brut = client_lecture.lire_depot(item.doi_nakala)
    metas_distantes = brut.get("metas") or []
    metas_locales = _metas_locales(item, licence_defaut)  # peut lever MetaInvalide

    diffs = diff_push(metas_distantes, metas_locales)
    baseline = _baseline_moddate(db, item.doi_nakala)
    distant_mod = brut.get("modDate")
    derive = bool(baseline and distant_mod and str(distant_mod) > str(baseline))

    rapport = RapportPush(
        cote=item.cote, doi=item.doi_nakala, dry_run=dry_run,
        diffs=diffs, derive=derive,
    )
    if dry_run or not diffs:
        return rapport

    client_ecriture.modifier_depot(item.doi_nakala, metas=metas_locales)
    # Rafraîchit la baseline (recupere_le + metadonnees_brutes) pour le prochain push.
    brut2 = client_lecture.lire_depot(item.doi_nakala)
    mettre_en_cache_depot(db, mapper_depot(brut2), brut2, cree_par=modifie_par)
    rapport.applique = True
    return rapport


@dataclass
class RapportPublication:
    cote: str
    doi: str
    dry_run: bool
    applique: bool = False


def publier_item(
    db: Any,
    client_lecture: ClientLectureNakala,
    client_ecriture: NakalaEcritureClient,
    item: Item,
    *,
    dry_run: bool = True,
    modifie_par: str | None = None,
    licence_defaut: str = LICENCE_DEFAUT,
) -> RapportPublication:
    """Publie un dépôt (`pending → published`, **irréversible**).

    Le `PUT` remplaçant les metas, on renvoie la liste complète + `status=
    published`. Exige `item.doi_nakala`. Dry-run (défaut) → ne publie pas."""
    if not item.doi_nakala:
        raise DepotImpossible(
            f"Item {item.cote!r} n'a pas de DOI Nakala — utiliser `deposer`."
        )
    rapport = RapportPublication(cote=item.cote, doi=item.doi_nakala, dry_run=dry_run)
    if dry_run:
        return rapport
    metas_locales = _metas_locales(item, licence_defaut)
    client_ecriture.modifier_depot(
        item.doi_nakala, metas=metas_locales, status="published"
    )
    brut2 = client_lecture.lire_depot(item.doi_nakala)
    mettre_en_cache_depot(db, mapper_depot(brut2), brut2, cree_par=modifie_par)
    rapport.applique = True
    return rapport


def pousser_metadonnees_collection(
    db: Any,
    client_lecture: ClientLectureNakala,
    client_ecriture: NakalaEcritureClient,
    collection: Collection,
    *,
    dry_run: bool = True,
    statut: str | None = None,
) -> RapportPush:
    """Pousse les métadonnées de l'**entité collection** (titre/description)
    vers sa collection Nakala (`PUT /collections/{id}`).

    ColleC ne modélise pour une collection que **titre + description**. Comme
    le `PUT` remplace tout, on procède par **fusion** : on préserve les metas
    Nakala que ColleC ne gère pas (sujet, créateur… d'une collection créée
    hors ColleC) et on ne remplace que titre + description. Sans ça, un push
    effacerait ces metas non modélisées.

    Exige `collection.doi_nakala` (sinon `DepotImpossible`). Réutilise
    `diff_push` (par propertyUri, ignore le `typeUri` que Nakala remet à
    null). Pas de drapeau de dérive : les collections Nakala n'exposent pas
    de `modDate`. Dry-run (défaut) → diff sans écrire ; réel → `PUT`.
    """
    if not collection.doi_nakala:
        raise DepotImpossible(
            f"Collection {collection.cote!r} n'a pas de DOI Nakala — "
            "la déposer d'abord (`deposer-collection`)."
        )
    distant = client_lecture.lire_collection(collection.doi_nakala).get("metas") or []
    gerees = collection_vers_metas(collection)  # titre + description (ColleC les possède)
    # Fusion : metas Nakala hors champs gérés + valeurs locales des champs gérés.
    preservees = [
        m for m in distant if m.get("propertyUri") not in _PROPRIETES_COLLECTION_GEREES
    ]
    fusionnees = preservees + gerees

    diffs = diff_push(distant, fusionnees)
    rapport = RapportPush(
        cote=collection.cote, doi=collection.doi_nakala, dry_run=dry_run, diffs=diffs,
    )
    if dry_run or not diffs:
        return rapport
    client_ecriture.modifier_collection(
        collection.doi_nakala, metas=fusionnees, status=statut
    )
    rapport.applique = True
    return rapport


@dataclass
class RapportPushCollection:
    collection_cote: str
    dry_run: bool
    #: Push de l'entité collection elle-même (None si pas de doi_nakala).
    meta_collection: RapportPush | None = None
    pousses: list[RapportPush] = field(default_factory=list)  # items avec diff
    inchanges: list[str] = field(default_factory=list)  # items diff vide
    non_lies: list[str] = field(default_factory=list)  # items sans doi_nakala
    erreurs: list[tuple[str, str]] = field(default_factory=list)


def pousser_collection(
    db: Any,
    client_lecture: ClientLectureNakala,
    client_ecriture: NakalaEcritureClient,
    collection: Collection,
    *,
    dry_run: bool = True,
    modifie_par: str | None = None,
    licence_defaut: str = LICENCE_DEFAUT,
) -> RapportPushCollection:
    """Pousse les métadonnées de la collection **puis** de ses items liés.

    L'entité collection (titre/description) est poussée si elle a un
    `doi_nakala` (`meta_collection`). Puis chaque item : sans DOI →
    `non_lies` ; sans diff → `inchanges` ; échec → `erreurs` (n'arrête pas
    le lot)."""
    rapport = RapportPushCollection(collection_cote=collection.cote, dry_run=dry_run)
    if collection.doi_nakala:
        try:
            rapport.meta_collection = pousser_metadonnees_collection(
                db, client_lecture, client_ecriture, collection, dry_run=dry_run
            )
        except (MetaInvalide, ErreurNakala) as exc:
            rapport.erreurs.append((f"collection:{collection.cote}", str(exc)))
    for item in collection.items:
        if not item.doi_nakala:
            rapport.non_lies.append(item.cote)
            continue
        try:
            r = pousser_item(
                db, client_lecture, client_ecriture, item,
                dry_run=dry_run, modifie_par=modifie_par, licence_defaut=licence_defaut,
            )
        except (MetaInvalide, ErreurNakala) as exc:
            rapport.erreurs.append((item.cote, str(exc)))
            continue
        if r.a_des_changements:
            rapport.pousses.append(r)
        else:
            rapport.inchanges.append(item.cote)
    return rapport


@dataclass
class RapportPublicationCollection:
    collection_cote: str
    dry_run: bool
    publies: list[str] = field(default_factory=list)  # items publiés (ou à publier)
    non_lies: list[str] = field(default_factory=list)  # items sans doi_nakala
    erreurs: list[tuple[str, str]] = field(default_factory=list)


def publier_collection(
    db: Any,
    client_lecture: ClientLectureNakala,
    client_ecriture: NakalaEcritureClient,
    collection: Collection,
    *,
    dry_run: bool = True,
    modifie_par: str | None = None,
    licence_defaut: str = LICENCE_DEFAUT,
) -> RapportPublicationCollection:
    """Publie tous les items liés (doi_nakala) d'une collection (**irréversible**).

    Boucle `publier_item`. Items sans DOI → `non_lies` ; échec → `erreurs`
    (n'arrête pas le lot). Dry-run (défaut) → liste ce qui serait publié."""
    rapport = RapportPublicationCollection(
        collection_cote=collection.cote, dry_run=dry_run
    )
    for item in collection.items:
        if not item.doi_nakala:
            rapport.non_lies.append(item.cote)
            continue
        try:
            publier_item(
                db, client_lecture, client_ecriture, item,
                dry_run=dry_run, modifie_par=modifie_par, licence_defaut=licence_defaut,
            )
        except (MetaInvalide, ErreurNakala) as exc:
            rapport.erreurs.append((item.cote, str(exc)))
            continue
        rapport.publies.append(item.cote)
    return rapport
