"""Vue item : détail + liste des fichiers avec sources d'image résolues.

Schémas exposés :
- `ItemDetail` agrège les champs de l'item ET de la collection parente
  pour alimenter directement les composants Claude Design (bandeau_item,
  panneau_fichiers, cartouche_metadonnees).
- Les helpers `bandeau_ctx`, `panneau_ctx`, `breadcrumb_ctx` produisent
  les dicts attendus par les macros — pas de logique métier dans la
  route ni dans le template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from archives_tool.affichage.formatters import date_incertaine, temps_relatif
from archives_tool.api.services.sources_image import (
    SourceImage,
    resoudre_source_image,
)
from archives_tool.models import Collection, EtatCatalogage, Item, PhaseChantier


class ItemIntrouvable(LookupError):
    """La cote demandée n'existe dans aucune collection."""


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
    date_incertaine: bool
    annee: int | None
    langue: str | None
    type_coar: str | None
    description: str | None
    notes_internes: str | None
    doi_nakala: str | None
    doi_collection_nakala: str | None
    etat: EtatCatalogage
    modifie_par: str | None = None
    modifie_le: datetime | None = None
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
        date_incertaine=date_incertaine(item.date),
        annee=item.annee,
        langue=item.langue,
        type_coar=item.type_coar,
        description=item.description,
        notes_internes=item.notes_internes,
        doi_nakala=item.doi_nakala,
        doi_collection_nakala=item.doi_collection_nakala,
        etat=EtatCatalogage(item.etat_catalogage),
        modifie_par=item.modifie_par,
        modifie_le=item.modifie_le,
        metadonnees=item.metadonnees or {},
        fichiers=fichiers_vues,
    )


def sources_pour_visionneuse(detail: ItemDetail) -> dict[int, dict[str, dict | None]]:
    """Map fichier_id → {primary, fallback} embarquée dans la page item.

    La visionneuse JS lit ce blob dans `<script id="sources-fichiers">`
    et appelle `viewer.open(...)` au click sur une vignette.
    """
    return {
        f.id: {"primary": f.source.primary, "fallback": f.source.fallback}
        for f in detail.fichiers
    }


# ---------------------------------------------------------------------------
# Adaptateurs vers les schémas du bundle handoff (composants Claude Design)
# ---------------------------------------------------------------------------


def breadcrumb_ctx(detail: ItemDetail) -> list[dict[str, Any]]:
    """Fil d'Ariane attendu par bandeau_item : [{label, href, mono?}]."""
    return [
        {"label": "Tableau de bord", "href": "/"},
        {
            "label": detail.collection_cote,
            "href": f"/collection/{detail.collection_cote}",
            "mono": True,
        },
    ]


def bandeau_ctx(detail: ItemDetail) -> dict[str, Any]:
    """Dict consommé par bandeau_item du bundle.

    Les URLs précédent / suivant / vue fichiers sont des placeholders
    en V0.6 — la navigation séquentielle entre items et la vue fichiers
    plein écran arrivent en V0.7.
    """
    return {
        "cote": detail.cote,
        "titre": detail.titre or detail.cote,
        "etat": detail.etat.value,
        "nb_fichiers": len(detail.fichiers),
        "phase": detail.collection_phase.libelle,
        "modifie_par": detail.modifie_par,
        "modifie_depuis": temps_relatif(detail.modifie_le),
        "url_vue_fichiers": f"/collection/{detail.collection_cote}/fichiers",
        "url_precedent": "#",
        "url_suivant": "#",
    }


_LIBELLES_TYPE_PAGE = {
    "page": "page",
    "couverture": "couverture",
    "supplement": "supplément",
}


def panneau_ctx(
    detail: ItemDetail,
    *,
    fichier_initial_id: int | None = None,
    etat: str = "collapsed",
) -> dict[str, Any]:
    """Dict consommé par panneau_fichiers du bundle.

    `etat` est l'état d'affichage initial ('collapsed' ou 'pinned').
    `fichier_initial_id` marque le fichier courant pour le surlignage.
    """
    fichiers = []
    for f in detail.fichiers:
        fichiers.append(
            {
                "id": f.id,  # exposé pour le câblage data-fichier-id de visionneuse.js
                "ordre": f.ordre,
                "nom": f.nom_fichier,
                "type": _LIBELLES_TYPE_PAGE.get(f.type_page, f.type_page),
                "vignette_url": f.source.vignette_url,
                "courant": f.id == fichier_initial_id,
                "href": f"?fichier={f.id}",
            }
        )
    # TODO V0.7 : url_ajout pointant vers le formulaire d'ajout.
    return {
        "etat": etat,
        "nb_fichiers": len(detail.fichiers),
        "fichiers": fichiers,
        "url_vue_fichiers": f"/collection/{detail.collection_cote}/fichiers",
        "url_ajout": "#",
    }
