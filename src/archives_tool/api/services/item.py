"""Vue item : détail + liste des fichiers avec sources d'image résolues."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from archives_tool.api.services.sources_image import (
    SourceImage,
    resoudre_source_image,
)
from archives_tool.models import Collection, EtatCatalogage, Item, PhaseChantier


class ItemIntrouvable(LookupError):
    """La cote demandée n'existe dans aucune collection."""


# Couples (libellé, attribut) affichés dans la zone métadonnées de
# la vue item. L'ordre est celui d'affichage. Filtrer sur la valeur
# se fait au moment du rendu (template ou caller) pour ne pas figer
# la liste.
CHAMPS_METADONNEES_AFFICHES: tuple[tuple[str, str], ...] = (
    ("Numéro", "numero"),
    ("Date", "date"),
    ("Année", "annee"),
    ("Langue", "langue"),
    ("Type COAR", "type_coar"),
    ("DOI Nakala", "doi_nakala"),
    ("DOI collection", "doi_collection_nakala"),
)


@dataclass
class FichierVue:
    id: int
    nom_fichier: str
    ordre: int
    type_page: str
    folio: str | None
    largeur_px: int | None
    hauteur_px: int | None
    source: SourceImage


@dataclass
class ItemDetail:
    id: int
    cote: str
    collection_cote: str
    collection_titre: str
    collection_phase: PhaseChantier
    titre: str | None
    numero: str | None
    date: str | None
    annee: int | None
    langue: str | None
    type_coar: str | None
    description: str | None
    notes_internes: str | None
    doi_nakala: str | None
    doi_collection_nakala: str | None
    etat: EtatCatalogage
    metadonnees: dict[str, Any] = field(default_factory=dict)
    fichiers: list[FichierVue] = field(default_factory=list)


def item_detail(
    session: Session, cote: str, collection_cote: str | None = None
) -> ItemDetail:
    """Charge l'item + sa collection + tous ses fichiers résolus.

    Si la cote item n'est pas unique et `collection_cote` n'est pas
    fourni, le premier match (ordre id) est retourné — même contrat
    que `archives-tool montrer item`.
    """
    stmt = (
        select(Item, Collection)
        .join(Collection, Item.collection_id == Collection.id)
        .where(Item.cote == cote)
        .options(selectinload(Item.fichiers))
    )
    if collection_cote is not None:
        stmt = stmt.where(Collection.cote_collection == collection_cote)
    stmt = stmt.order_by(Item.id).limit(1)

    row = session.execute(stmt).first()
    if row is None:
        raise ItemIntrouvable(cote)

    item, collection = row

    fichiers_vues = [
        FichierVue(
            id=f.id,
            nom_fichier=f.nom_fichier,
            ordre=f.ordre,
            type_page=f.type_page,
            folio=f.folio,
            largeur_px=f.largeur_px,
            hauteur_px=f.hauteur_px,
            source=resoudre_source_image(f),
        )
        for f in item.fichiers
    ]

    return ItemDetail(
        id=item.id,
        cote=item.cote,
        collection_cote=collection.cote_collection,
        collection_titre=collection.titre,
        collection_phase=PhaseChantier(collection.phase),
        titre=item.titre,
        numero=item.numero,
        date=item.date,
        annee=item.annee,
        langue=item.langue,
        type_coar=item.type_coar,
        description=item.description,
        notes_internes=item.notes_internes,
        doi_nakala=item.doi_nakala,
        doi_collection_nakala=item.doi_collection_nakala,
        etat=EtatCatalogage(item.etat_catalogage),
        metadonnees=item.metadonnees or {},
        fichiers=fichiers_vues,
    )


def metadonnees_affichables(detail: ItemDetail) -> list[tuple[str, str]]:
    """Liste ordonnée (label, valeur) des champs non vides à afficher."""
    paires: list[tuple[str, str]] = []
    for label, attribut in CHAMPS_METADONNEES_AFFICHES:
        valeur = getattr(detail, attribut)
        if valeur:
            paires.append((label, str(valeur)))
    return paires


def sources_pour_visionneuse(detail: ItemDetail) -> dict[int, dict[str, dict | None]]:
    """Map fichier_id → {primary, fallback} embarquée dans la page item.

    La visionneuse JS lit ce blob dans `<script id="sources-fichiers">`
    et appelle `viewer.open(...)` au click sur une vignette.
    """
    return {
        f.id: {"primary": f.source.primary, "fallback": f.source.fallback}
        for f in detail.fichiers
    }
