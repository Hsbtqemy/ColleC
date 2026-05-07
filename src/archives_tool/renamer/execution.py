"""Exécution transactionnelle d'un plan de renommage.

Stratégie en deux phases pour absorber les cycles à la fois sur disque
et en base (la contrainte UNIQUE sur `(racine, chemin_relatif)` ne
tolère pas les états intermédiaires) :

1. Phase 1 — chaque source est déplacée vers un nom temporaire unique
   sur disque, et `Fichier.chemin_relatif` est mis à jour vers ce
   temporaire. On `flush` à la fin de la phase : tous les rangs ont
   alors des chemins uniques (les UUID des temps).
2. Phase 2 — chaque temporaire est déplacé vers sa cible finale,
   `chemin_relatif` mis à jour, et une `OperationFichier(REUSSIE)`
   journalisée. `commit` à la fin.

En cas d'erreur disque ou base, un *rollback compensateur* rejoue les
renommages inverses sur les opérations déjà appliquées avant
`session.rollback()`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from archives_tool.models import (
    Fichier,
    OperationFichier,
    StatutOperation,
    TypeOperationFichier,
)

from .rapport import OperationRenommage, RapportExecution, RapportPlan, StatutPlan


@dataclass
class _Mouvement:
    op: OperationRenommage
    fichier: Fichier
    src: Path  # chemin disque initial
    tmp: Path  # chemin disque temporaire
    dst: Path  # chemin disque final
    tmp_relatif: str  # chemin_relatif POSIX correspondant à tmp


def _chemin_absolu(base: Path, chemin_relatif: str) -> Path:
    return base.joinpath(*chemin_relatif.split("/"))


def _operations_a_appliquer(plan: RapportPlan) -> list[OperationRenommage]:
    return [
        op
        for op in plan.operations
        if op.statut in (StatutPlan.PRET, StatutPlan.EN_CYCLE)
    ]


def _construire_mouvements(
    a_renommer: list[OperationRenommage],
    racines: Mapping[str, Path],
    session: Session,
) -> list[_Mouvement]:
    mouvements: list[_Mouvement] = []
    for op in a_renommer:
        base = racines[op.racine]
        src = _chemin_absolu(base, op.chemin_avant)
        dst = _chemin_absolu(base, op.chemin_apres)
        tmp_nom = f".tmp_rename_{uuid.uuid4().hex[:12]}_{src.name}"
        tmp = src.parent / tmp_nom
        parent_rel = PurePosixPath(op.chemin_avant).parent
        tmp_relatif = (parent_rel / tmp_nom).as_posix().lstrip("/")

        fichier = session.get(Fichier, op.fichier_id)
        if fichier is None:
            raise RuntimeError(f"Fichier {op.fichier_id} introuvable.")

        mouvements.append(
            _Mouvement(
                op=op,
                fichier=fichier,
                src=src,
                tmp=tmp,
                dst=dst,
                tmp_relatif=tmp_relatif,
            )
        )
    return mouvements


def _compenser(mouvements: list[_Mouvement], phase2_appliquees: int) -> int:
    """Rejoue les mouvements inverses, du plus récent au plus ancien.

    Retourne le nombre de mouvements compensés. Best-effort : une
    compensation qui échoue n'interrompt pas les suivantes.
    """
    compensees = 0
    for m in reversed(mouvements[:phase2_appliquees]):
        try:
            m.dst.rename(m.tmp)
            compensees += 1
        except OSError:
            pass
    for m in reversed(mouvements):
        try:
            m.tmp.rename(m.src)
            compensees += 1
        except OSError:
            pass
    return compensees


def executer_plan(
    session: Session,
    plan: RapportPlan,
    *,
    racines: Mapping[str, Path],
    dry_run: bool = True,
    execute_par: str | None = None,
) -> RapportExecution:
    """Applique un plan validé. Dry-run par défaut."""
    debut = time.perf_counter()
    rap = RapportExecution(dry_run=dry_run)

    if not plan.applicable:
        rap.erreurs.append(
            "Plan non applicable : conflits non résolus, exécution refusée."
        )
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    a_renommer = _operations_a_appliquer(plan)
    if not a_renommer:
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    if dry_run:
        rap.operations_reussies = len(a_renommer)
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    batch_id = str(uuid.uuid4())

    try:
        mouvements = _construire_mouvements(a_renommer, racines, session)
    except RuntimeError as e:
        rap.erreurs.append(str(e))
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    # Phase 1 — disque src→tmp et DB chemin_relatif=tmp.
    phase1_disque_appliquees = 0
    try:
        for m in mouvements:
            m.src.rename(m.tmp)
            phase1_disque_appliquees += 1
            m.fichier.chemin_relatif = m.tmp_relatif
            m.fichier.nom_fichier = m.tmp.name
        session.flush()
    except Exception as e:
        # Rollback compensateur phase 1 uniquement.
        for m in reversed(mouvements[:phase1_disque_appliquees]):
            try:
                m.tmp.rename(m.src)
            except OSError:
                pass
        session.rollback()
        rap.erreurs.append(f"Échec phase 1 : {e}")
        rap.operations_compensees = phase1_disque_appliquees
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    # Phase 2 — disque tmp→dst, DB chemin_relatif final, journal.
    phase2_appliquees = 0
    try:
        for m in mouvements:
            m.dst.parent.mkdir(parents=True, exist_ok=True)
            m.tmp.rename(m.dst)
            phase2_appliquees += 1
            m.fichier.chemin_relatif = m.op.chemin_apres
            m.fichier.nom_fichier = PurePosixPath(m.op.chemin_apres).name
            session.add(
                OperationFichier(
                    batch_id=batch_id,
                    fichier_id=m.op.fichier_id,
                    type_operation=TypeOperationFichier.RENAME.value,
                    racine_avant=m.op.racine,
                    chemin_avant=m.op.chemin_avant,
                    racine_apres=m.op.racine,
                    chemin_apres=m.op.chemin_apres,
                    statut=StatutOperation.REUSSIE.value,
                    execute_par=execute_par,
                )
            )
        session.commit()
    except Exception as e:
        compensees = _compenser(mouvements, phase2_appliquees)
        session.rollback()
        rap.erreurs.append(f"Échec phase 2 : {e}")
        rap.operations_compensees = compensees
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    rap.batch_id = batch_id
    rap.operations_reussies = len(mouvements)
    rap.duree_secondes = time.perf_counter() - debut
    return rap
