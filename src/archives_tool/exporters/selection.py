"""Sélection des items / fichiers à exporter.

Streaming via `yield` pour ne pas charger tout en mémoire sur les gros
fonds (type Ainsa, 6000 items avec métadonnées riches).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import Collection, EtatFichier, Fichier, Item


class SelectionErreur(Exception):
    """Erreur dans les critères de sélection (collection inexistante, ...)."""


@dataclass
class CritereSelection:
    collection_cote: str | None = None
    collection_id: int | None = None
    recursif: bool = False
    etats: list[str] | None = None
    granularite: Literal["item", "fichier"] = "item"


def _ids_collections_cibles(session: Session, critere: CritereSelection) -> list[int]:
    """Retourne la liste des collection_id concernés (la collection
    racine + ses enfants si récursif)."""
    if critere.collection_id is not None:
        racine = session.get(Collection, critere.collection_id)
    elif critere.collection_cote is not None:
        racine = session.scalar(
            select(Collection).where(
                Collection.cote_collection == critere.collection_cote
            )
        )
    else:
        raise SelectionErreur(
            "Critère vide : fournir collection_cote ou collection_id."
        )

    if racine is None:
        cible = critere.collection_cote or critere.collection_id
        raise SelectionErreur(f"Collection {cible!r} introuvable en base.")

    ids = [racine.id]
    if critere.recursif:
        # Parcours descendant via enfants (parcours en largeur).
        a_visiter = list(racine.enfants)
        while a_visiter:
            enfant = a_visiter.pop(0)
            ids.append(enfant.id)
            a_visiter.extend(enfant.enfants)
    return ids


def selectionner_items(
    session: Session,
    critere: CritereSelection,
) -> Iterable[Item]:
    """Itère sur les items correspondant aux critères, triés par cote."""
    ids = _ids_collections_cibles(session, critere)
    stmt = select(Item).where(Item.collection_id.in_(ids)).order_by(Item.cote)
    if critere.etats:
        stmt = stmt.where(Item.etat_catalogage.in_(critere.etats))
    # yield_per active le streaming côté SQLAlchemy.
    yield from session.scalars(stmt.execution_options(yield_per=200))


def selectionner_fichiers(
    session: Session,
    critere: CritereSelection,
) -> Iterable[tuple[Item, Fichier]]:
    """Itère sur les paires (item, fichier) triées par (cote, ordre).

    Seuls les fichiers actifs sont inclus.
    """
    for item in selectionner_items(session, critere):
        for fichier in sorted(item.fichiers, key=lambda f: f.ordre):
            if fichier.etat == EtatFichier.ACTIF.value:
                yield item, fichier
