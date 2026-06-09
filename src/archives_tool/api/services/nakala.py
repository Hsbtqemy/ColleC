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
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import FormulaireInvalide
from archives_tool.api.services.items import (
    FormulaireItem,
    creer_item,
    formulaire_depuis_item,
    modifier_item,
)
from archives_tool.external.nakala.mapper import DepotNakala
from archives_tool.models import (
    Item,
    LienExterneItem,
    RessourceExterne,
    SourceExterne,
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
) -> FormulaireItem:
    """Construit un `FormulaireItem` depuis un dépôt.

    `base` (rafraîchir) : formulaire de l'item existant — on n'écrase que
    les champs documentaires + les clés `metadonnees` issues de Nakala,
    en préservant le reste (cote, état, notes, numéro, version). `None`
    (rapatrier) : création neuve (état brouillon par défaut).
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
        metadonnees=metadonnees,
    )


@dataclass
class RapportRapatriement:
    """Résultat d'un `rapatrier`. `item_id`/`cote` None si dry-run pur."""

    cote: str
    fonds_id: int
    dry_run: bool
    deja_existant: bool
    item_id: int | None = None


def rapatrier(
    db: Session,
    depot: DepotNakala,
    brut: dict,
    *,
    fonds_id: int,
    cote: str | None = None,
    cree_par: str | None = None,
    dry_run: bool = False,
) -> RapportRapatriement:
    """Crée un Item ColleC depuis un dépôt Nakala, dans `fonds_id`.

    - `cote` explicite, sinon dérivée du DOI (`_cote_depuis_doi`) ;
    - si un item porte déjà ce DOI → ne recrée pas (`deja_existant=True`,
      utiliser `rafraichir`) ;
    - `dry_run` → aucune écriture, retourne juste le plan (cote, fonds,
      déjà-existant) ;
    - réel → `creer_item` + cache + lien (via `mettre_en_cache_depot`).
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
        if not dry_run:
            mettre_en_cache_depot(db, depot, brut, cree_par=cree_par)
        return RapportRapatriement(
            cote=deja.cote, fonds_id=deja.fonds_id, dry_run=dry_run,
            deja_existant=True, item_id=deja.id,
        )

    if dry_run:
        return RapportRapatriement(
            cote=cote_finale, fonds_id=fonds_id, dry_run=True,
            deja_existant=False, item_id=None,
        )

    form = _depot_vers_formulaire(depot, fonds_id=fonds_id, cote=cote_finale)
    item = creer_item(db, form, cree_par=cree_par)
    mettre_en_cache_depot(db, depot, brut, cree_par=cree_par)
    return RapportRapatriement(
        cote=item.cote, fonds_id=item.fonds_id, dry_run=False,
        deja_existant=False, item_id=item.id,
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
