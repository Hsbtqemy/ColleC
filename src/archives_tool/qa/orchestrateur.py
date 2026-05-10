"""Orchestrateur : compose le périmètre, exécute la suite de contrôles.

Tous les contrôles sont en lecture seule (pas de db.add / db.commit).
Le module qa peut donc être utilisé sur une base de production sans
risque.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.models import Collection, Fichier, Fonds, Item
from archives_tool.qa._commun import (
    PerimetreControle,
    RapportQa,
    ResultatControle,
)
from archives_tool.qa.cross import (
    controler_cross_cote_dupliquee_fonds,
    controler_cross_fonds_vide,
)
from archives_tool.qa.fichiers import (
    controler_file_hash_duplique,
    controler_file_hash_manquant,
    controler_file_item_vide,
    controler_file_missing,
)
from archives_tool.qa.invariants import (
    controler_inv1_miroir_unique,
    controler_inv2_miroir_avec_fonds,
    controler_inv4_item_avec_fonds,
    controler_inv6_item_dans_miroir,
)
from archives_tool.qa.metadonnees import (
    controler_meta_annee_implausible,
    controler_meta_cote_invalide,
    controler_meta_date_invalide,
    controler_meta_titre_vide,
)

VERSION_QA = "0.9.0"

# Type d'un contrôle qa : (db, perimetre) → ResultatControle.
# Certains contrôles acceptent des kwargs (racines, plages d'année) ;
# `executer_controles` les passe via une closure quand fournis.
ControleSimple = Callable[[Session, PerimetreControle], ResultatControle]


CONTROLES_DISPONIBLES: tuple[ControleSimple, ...] = (
    controler_inv1_miroir_unique,
    controler_inv2_miroir_avec_fonds,
    controler_inv4_item_avec_fonds,
    controler_inv6_item_dans_miroir,
    controler_file_missing,
    controler_file_item_vide,
    controler_file_hash_duplique,
    controler_file_hash_manquant,
    controler_meta_cote_invalide,
    controler_meta_titre_vide,
    controler_meta_date_invalide,
    controler_meta_annee_implausible,
    controler_cross_cote_dupliquee_fonds,
    controler_cross_fonds_vide,
)


def composer_perimetre(
    db: Session,
    *,
    fonds_id: int | None = None,
    collection_id: int | None = None,
) -> PerimetreControle:
    """Calcule les compteurs de contexte pour le bandeau de tête.

    Les compteurs sont **globaux** quel que soit le périmètre : ils
    décrivent la base, pas la portion contrôlée. Les contrôles eux
    filtrent par `perimetre.fonds_id` / `collection_id`.
    """
    nb_fonds = db.scalar(select(func.count(Fonds.id))) or 0
    nb_collections = db.scalar(select(func.count(Collection.id))) or 0
    nb_items = db.scalar(select(func.count(Item.id))) or 0
    nb_fichiers = db.scalar(select(func.count(Fichier.id))) or 0

    if fonds_id is not None and collection_id is not None:
        raise ValueError(
            "fonds_id et collection_id sont mutuellement exclusifs."
        )
    type_perimetre = (
        "fonds"
        if fonds_id is not None
        else "collection"
        if collection_id is not None
        else "base_complete"
    )
    return PerimetreControle(
        type=type_perimetre,
        fonds_id=fonds_id,
        collection_id=collection_id,
        fonds_count=nb_fonds,
        collections_count=nb_collections,
        items_count=nb_items,
        fichiers_count=nb_fichiers,
    )


def executer_controles(
    db: Session,
    perimetre: PerimetreControle,
    *,
    racines: Mapping[str, Path] | None = None,
    controles: tuple[ControleSimple, ...] | None = None,
) -> RapportQa:
    """Exécute la suite de contrôles sur le périmètre donné.

    `racines` est passé à `controler_file_missing` quand fourni — sinon
    le contrôle remonte les fichiers comme « racine non configurée ».
    """
    suite = controles or CONTROLES_DISPONIBLES
    resultats: list[ResultatControle] = []
    for ctrl in suite:
        if ctrl is controler_file_missing:
            resultats.append(ctrl(db, perimetre, racines=racines))  # type: ignore[call-arg]
        else:
            resultats.append(ctrl(db, perimetre))
    return RapportQa(
        version_qa=VERSION_QA,
        horodatage=datetime.now(timezone.utc),
        perimetre=perimetre,
        controles=tuple(resultats),
    )
