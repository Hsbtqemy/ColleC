"""Construction d'un plan de renommage et détection des conflits.

Trois familles de problèmes sont identifiées ici :
- collision intra-batch : plusieurs ops visent la même cible ;
- collision externe : la cible existe déjà sur disque hors du batch ;
- cycle : A→B et B→A. Résolu par l'exécuteur via un pivot temporaire,
  donc seulement *marqué* ici, pas bloqué.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.files.paths import chemin_existe_nfc_ou_nfd, normaliser_nfc
from archives_tool.models import Collection, EtatFichier, Fichier, Item

from .rapport import (
    Conflit,
    OperationRenommage,
    RapportPlan,
    StatutPlan,
)
from .template import EchecTemplate, evaluer_template


def _ids_arbre(racine: Collection) -> list[int]:
    ids = [racine.id]
    a_visiter = list(racine.enfants)
    while a_visiter:
        n = a_visiter.pop(0)
        ids.append(n.id)
        a_visiter.extend(n.enfants)
    return ids


def _selectionner_fichiers(
    session: Session,
    *,
    collection_cote: str | None,
    item_cote: str | None,
    fichier_ids: list[int] | None,
    recursif: bool,
) -> list[tuple[Fichier, Item, Collection]]:
    if fichier_ids is not None:
        stmt = (
            select(Fichier, Item, Collection)
            .join(Item, Fichier.item_id == Item.id)
            .join(Collection, Item.collection_id == Collection.id)
            .where(Fichier.id.in_(fichier_ids))
            .where(Fichier.etat == EtatFichier.ACTIF.value)
            .order_by(Fichier.id)
        )
        return list(session.execute(stmt).all())

    if item_cote is not None:
        stmt = (
            select(Fichier, Item, Collection)
            .join(Item, Fichier.item_id == Item.id)
            .join(Collection, Item.collection_id == Collection.id)
            .where(Item.cote == item_cote)
            .where(Fichier.etat == EtatFichier.ACTIF.value)
            .order_by(Fichier.ordre, Fichier.id)
        )
        return list(session.execute(stmt).all())

    if collection_cote is not None:
        col = session.scalar(
            select(Collection).where(Collection.cote_collection == collection_cote)
        )
        if col is None:
            raise ValueError(f"Collection {collection_cote!r} introuvable.")
        ids = _ids_arbre(col) if recursif else [col.id]
        stmt = (
            select(Fichier, Item, Collection)
            .join(Item, Fichier.item_id == Item.id)
            .join(Collection, Item.collection_id == Collection.id)
            .where(Item.collection_id.in_(ids))
            .where(Fichier.etat == EtatFichier.ACTIF.value)
            .order_by(Item.cote, Fichier.ordre, Fichier.id)
        )
        return list(session.execute(stmt).all())

    raise ValueError(
        "Aucun périmètre fourni : précisez collection_cote, item_cote ou fichier_ids."
    )


def _detecter_cycles(
    ops: list[OperationRenommage],
) -> set[int]:
    """Retourne l'ensemble des indices d'ops appartenant à un cycle.

    Modèle : un cycle existe quand la cible d'une op est elle-même la
    source (chemin_avant) d'une autre op du batch, et qu'on revient au
    point de départ en suivant cette chaîne.
    """
    par_source = {(op.racine, op.chemin_avant): i for i, op in enumerate(ops)}

    indices_en_cycle: set[int] = set()
    for depart in range(len(ops)):
        if depart in indices_en_cycle:
            continue
        visites: list[int] = [depart]
        cur = ops[depart]
        while True:
            cle = (cur.racine, cur.chemin_apres)
            suivant = par_source.get(cle)
            if suivant is None:
                break
            if suivant == depart:
                indices_en_cycle.update(visites)
                break
            if suivant in visites:
                break
            visites.append(suivant)
            cur = ops[suivant]
    return indices_en_cycle


def construire_plan(
    session: Session,
    *,
    template: str,
    racines: Mapping[str, Path],
    collection_cote: str | None = None,
    item_cote: str | None = None,
    fichier_ids: list[int] | None = None,
    recursif: bool = False,
) -> RapportPlan:
    """Construit le plan de renommage et signale les conflits."""
    debut = time.perf_counter()
    rap = RapportPlan()

    lignes = _selectionner_fichiers(
        session,
        collection_cote=collection_cote,
        item_cote=item_cote,
        fichier_ids=fichier_ids,
        recursif=recursif,
    )

    operations: list[OperationRenommage] = []
    for fichier, item, collection in lignes:
        try:
            cible_brute = evaluer_template(template, fichier, item, collection)
        except EchecTemplate as e:
            op = OperationRenommage(
                fichier_id=fichier.id,
                racine=fichier.racine,
                chemin_avant=fichier.chemin_relatif,
                chemin_apres=fichier.chemin_relatif,
                statut=StatutPlan.BLOQUE,
                raison=str(e),
            )
            rap.conflits.append(
                Conflit(
                    code="template_invalide",
                    message=f"Fichier {fichier.id} : {e}",
                    fichier_ids=[fichier.id],
                )
            )
            operations.append(op)
            continue

        chemin_apres = normaliser_nfc(cible_brute)
        statut = (
            StatutPlan.NO_OP
            if chemin_apres == normaliser_nfc(fichier.chemin_relatif)
            else StatutPlan.PRET
        )
        operations.append(
            OperationRenommage(
                fichier_id=fichier.id,
                racine=fichier.racine,
                chemin_avant=fichier.chemin_relatif,
                chemin_apres=chemin_apres,
                statut=statut,
            )
        )

    # Détection des collisions intra-batch (sur les ops PRET, pas NO_OP/BLOQUE).
    par_cible: dict[tuple[str, str], list[int]] = {}
    for i, op in enumerate(operations):
        if op.statut != StatutPlan.PRET:
            continue
        par_cible.setdefault((op.racine, op.chemin_apres), []).append(i)
    for (racine, cible), indices in par_cible.items():
        if len(indices) > 1:
            ids = [operations[i].fichier_id for i in indices]
            rap.conflits.append(
                Conflit(
                    code="collision_intra_batch",
                    message=(
                        f"{len(indices)} fichiers visent la même cible {racine}:{cible}"
                    ),
                    fichier_ids=ids,
                )
            )
            for i in indices:
                operations[i].statut = StatutPlan.BLOQUE
                operations[i].raison = "collision intra-batch"

    # Cycles : à marquer avant la détection des collisions externes,
    # car un fichier squatté par un autre op du batch n'est pas une collision.
    indices_cycles = _detecter_cycles(
        [op for op in operations if op.statut == StatutPlan.PRET]
    )
    pret_indices = [
        i for i, op in enumerate(operations) if op.statut == StatutPlan.PRET
    ]
    indices_cycles_globaux = {pret_indices[i] for i in indices_cycles}
    for i in indices_cycles_globaux:
        operations[i].statut = StatutPlan.EN_CYCLE

    # Sources libérées par le batch : un fichier qu'on déplace cesse de
    # squatter sa source initiale.
    sources_liberees: set[tuple[str, str]] = {
        (op.racine, op.chemin_avant)
        for op in operations
        if op.statut in (StatutPlan.PRET, StatutPlan.EN_CYCLE)
    }

    # Collisions externes : la cible existe sur disque ET n'est pas une
    # source libérée par une autre op.
    for op in operations:
        if op.statut not in (StatutPlan.PRET, StatutPlan.EN_CYCLE):
            continue
        cle = (op.racine, op.chemin_apres)
        if cle in sources_liberees:
            continue
        base = racines.get(op.racine)
        if base is None:
            continue  # racine non configurée : on n'avertit pas ici
        if chemin_existe_nfc_ou_nfd(base, op.chemin_apres):
            rap.conflits.append(
                Conflit(
                    code="collision_externe",
                    message=(
                        f"Fichier {op.fichier_id} : la cible "
                        f"{op.racine}:{op.chemin_apres} existe déjà sur disque."
                    ),
                    fichier_ids=[op.fichier_id],
                )
            )
            op.statut = StatutPlan.BLOQUE
            op.raison = "collision externe sur disque"

    rap.operations = operations
    rap.duree_secondes = time.perf_counter() - debut
    return rap
