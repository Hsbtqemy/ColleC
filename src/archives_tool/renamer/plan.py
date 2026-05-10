"""Construction d'un plan de renommage et détection des conflits.

Trois familles de problèmes sont identifiées ici :
- collision intra-batch : plusieurs ops visent la même cible ;
- collision externe : la cible existe déjà sur disque hors du batch ;
- cycle de longueur >= 2 (A→B→A, A→B→C→A, ...). Résolu par
  l'exécuteur via un pivot temporaire, donc seulement *marqué* ici,
  pas bloqué.

Hypothèse TOCTOU : la vérification de collision externe passe par
`chemin_existe_nfc_ou_nfd` puis l'exécuteur fait `rename`. Entre les
deux, un fichier pourrait apparaître sur la cible. L'outil cible un
usage mono-utilisateur (cf. CLAUDE.md), donc on accepte ce risque ;
l'exécuteur déclenchera son rollback compensateur si l'erreur disque
remonte.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.files.paths import chemin_existe_nfc_ou_nfd, normaliser_nfc
from archives_tool.models import (
    EtatFichier,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
)

from .rapport import (
    CodeConflit,
    Conflit,
    OperationRenommage,
    RapportPlan,
    StatutPlan,
)
from .template import EchecTemplate, evaluer_template


def _selectionner_fichiers(
    session: Session,
    *,
    fonds_cote: str | None,
    collection_cote: str | None,
    collection_fonds_cote: str | None,
    item_cote: str | None,
    item_fonds_cote: str | None,
    fichier_ids: list[int] | None,
) -> list[tuple[Fichier, Item, Fonds]]:
    """Charge les fichiers du périmètre + leur item + fonds parent.

    Quatre modes (mutex) :
    - `fichier_ids` : ids explicites.
    - `item_cote` (+ `item_fonds_cote` pour désambiguïsation).
    - `collection_cote` (+ `collection_fonds_cote` si la cote est
      partagée) : items rattachés à la collection via la junction
      N-N `item_collection`.
    - `fonds_cote` : tous les items du fonds.
    """
    base_stmt = (
        select(Fichier, Item, Fonds)
        .join(Item, Fichier.item_id == Item.id)
        .join(Fonds, Item.fonds_id == Fonds.id)
        .where(Fichier.etat == EtatFichier.ACTIF.value)
    )

    if fichier_ids is not None:
        stmt = base_stmt.where(Fichier.id.in_(fichier_ids)).order_by(Fichier.id)
        return list(session.execute(stmt).all())

    if item_cote is not None:
        stmt = base_stmt.where(Item.cote == item_cote)
        if item_fonds_cote is not None:
            stmt = stmt.where(Fonds.cote == item_fonds_cote)
        return list(
            session.execute(stmt.order_by(Fichier.ordre, Fichier.id)).all()
        )

    if collection_cote is not None:
        # Imports locaux pour éviter une dépendance circulaire potentielle
        # avec les services (qui chargent renamer indirectement via cli.py).
        from archives_tool.api.services.collections import (
            CollectionIntrouvable,
            lire_collection_par_cote,
        )
        from archives_tool.api.services.fonds import (
            FondsIntrouvable,
            lire_fonds_par_cote,
        )

        fonds_id_filtre = None
        if collection_fonds_cote is not None:
            try:
                fonds_id_filtre = lire_fonds_par_cote(
                    session, collection_fonds_cote
                ).id
            except FondsIntrouvable as e:
                raise ValueError(str(e)) from e
        try:
            col = lire_collection_par_cote(
                session, collection_cote, fonds_id=fonds_id_filtre
            )
        except CollectionIntrouvable as e:
            raise ValueError(str(e)) from e

        stmt = base_stmt.where(
            Item.id.in_(
                select(ItemCollection.item_id).where(
                    ItemCollection.collection_id == col.id
                )
            )
        ).order_by(Item.cote, Fichier.ordre, Fichier.id)
        return list(session.execute(stmt).all())

    if fonds_cote is not None:
        stmt = base_stmt.where(Fonds.cote == fonds_cote).order_by(
            Item.cote, Fichier.ordre, Fichier.id
        )
        return list(session.execute(stmt).all())

    raise ValueError(
        "Aucun périmètre fourni : précisez fonds_cote, collection_cote, "
        "item_cote ou fichier_ids."
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
    fonds_cote: str | None = None,
    collection_cote: str | None = None,
    collection_fonds_cote: str | None = None,
    item_cote: str | None = None,
    item_fonds_cote: str | None = None,
    fichier_ids: list[int] | None = None,
) -> RapportPlan:
    """Construit le plan de renommage et signale les conflits.

    L'ensemble des fichiers sélectionnés est chargé en mémoire :
    acceptable jusqu'à quelques dizaines de milliers de lignes
    (ordre de grandeur du fonds documenté dans CLAUDE.md). Au-delà,
    streamer par lot.
    """
    debut = time.perf_counter()
    rap = RapportPlan()

    lignes = _selectionner_fichiers(
        session,
        fonds_cote=fonds_cote,
        collection_cote=collection_cote,
        collection_fonds_cote=collection_fonds_cote,
        item_cote=item_cote,
        item_fonds_cote=item_fonds_cote,
        fichier_ids=fichier_ids,
    )

    operations: list[OperationRenommage] = []
    for fichier, item, fonds in lignes:
        try:
            cible_brute = evaluer_template(template, fichier, item, fonds)
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
                    code=CodeConflit.TEMPLATE_INVALIDE,
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
                    code=CodeConflit.COLLISION_INTRA_BATCH,
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
                    code=CodeConflit.COLLISION_EXTERNE,
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
