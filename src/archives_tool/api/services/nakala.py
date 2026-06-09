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

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.external.nakala.mapper import DepotNakala
from archives_tool.models import (
    Item,
    LienExterneItem,
    RessourceExterne,
    SourceExterne,
)

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
