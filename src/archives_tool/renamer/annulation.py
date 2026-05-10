"""Annulation d'un batch de renommage par son `batch_id`.

Mêmes garanties transactionnelles qu'à l'exécution : deux phases sur
disque et en base, rollback compensateur si une opération échoue
mid-batch. Les `OperationFichier` originales sont marquées avec
`annule_par_batch_id`, et de nouvelles `OperationFichier(type=restore)`
sont insérées avec le nouveau `batch_id`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.files.paths import chemin_existe_nfc_ou_nfd, resoudre_chemin
from archives_tool.models import (
    Fichier,
    OperationFichier,
    StatutOperation,
    TypeOperationFichier,
)

from .execution import invalider_derives
from .rapport import RapportAnnulation


@dataclass
class _MouvementInverse:
    op: OperationFichier
    fichier: Fichier
    dst: Path  # chemin disque actuel (= chemin_apres de l'op originale)
    tmp: Path  # chemin disque temporaire
    src: Path  # chemin disque cible (= chemin_avant de l'op originale)
    tmp_relatif: str


def _renommer_signaler(src: Path, dst: Path, erreurs: list[str]) -> bool:
    try:
        src.rename(dst)
        return True
    except OSError as e:
        erreurs.append(f"Compensation impossible {src} → {dst} : {e}")
        return False


def _construire_mouvements(
    ops_originales: list[OperationFichier],
    racines: Mapping[str, Path],
    session: Session,
) -> tuple[list[_MouvementInverse], list[str]]:
    """Valide chaque opération originale et construit le mouvement inverse.

    Retourne (mouvements, erreurs). Si la liste d'erreurs est non
    vide, aucun mouvement ne doit être appliqué.
    """
    erreurs: list[str] = []
    ids = [op.fichier_id for op in ops_originales]
    fichiers = {
        f.id: f
        for f in session.scalars(select(Fichier).where(Fichier.id.in_(ids))).all()
    }

    mouvements: list[_MouvementInverse] = []
    for op in ops_originales:
        fichier = fichiers.get(op.fichier_id)
        if fichier is None:
            erreurs.append(f"Op {op.id} : fichier {op.fichier_id} introuvable en base.")
            continue
        if fichier.chemin_relatif != op.chemin_apres:
            erreurs.append(
                f"Op {op.id} : la base a divergé "
                f"(actuel={fichier.chemin_relatif!r}, attendu={op.chemin_apres!r})."
            )
            continue
        racine = op.racine_apres or op.racine_avant
        if racine not in racines:
            erreurs.append(f"Op {op.id} : racine {racine!r} non configurée.")
            continue
        if not chemin_existe_nfc_ou_nfd(racines[racine], op.chemin_apres):
            erreurs.append(
                f"Op {op.id} : fichier absent sur disque ({racine}:{op.chemin_apres})."
            )
            continue

        dst = resoudre_chemin(racines, racine, op.chemin_apres)
        src = resoudre_chemin(racines, op.racine_avant or racine, op.chemin_avant)
        tmp_nom = f".tmp_undo_{uuid.uuid4().hex[:12]}_{dst.name}"
        tmp = dst.parent / tmp_nom
        parent_rel = PurePosixPath(op.chemin_apres).parent
        tmp_relatif = (parent_rel / tmp_nom).as_posix().lstrip("/")

        mouvements.append(
            _MouvementInverse(
                op=op,
                fichier=fichier,
                dst=dst,
                tmp=tmp,
                src=src,
                tmp_relatif=tmp_relatif,
            )
        )
    return mouvements, erreurs


def annuler_batch(
    session: Session,
    batch_id_original: str,
    *,
    racines: Mapping[str, Path],
    dry_run: bool = True,
    execute_par: str | None = None,
) -> RapportAnnulation:
    """Inverse un batch déjà appliqué. Idempotent : un batch déjà
    annulé ne peut pas être annulé une seconde fois."""
    debut = time.perf_counter()
    rap = RapportAnnulation(dry_run=dry_run, batch_id_original=batch_id_original)

    ops_originales = list(
        session.scalars(
            select(OperationFichier)
            .where(OperationFichier.batch_id == batch_id_original)
            .where(OperationFichier.statut == StatutOperation.REUSSIE.value)
            .where(OperationFichier.annule_par_batch_id.is_(None))
            .where(OperationFichier.type_operation == TypeOperationFichier.RENAME.value)
            .order_by(OperationFichier.id.desc())
        ).all()
    )

    if not ops_originales:
        rap.erreurs.append(
            f"Aucune opération à annuler pour le batch {batch_id_original!r} "
            f"(inconnu, vide ou déjà annulé)."
        )
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    mouvements, erreurs_etat = _construire_mouvements(ops_originales, racines, session)
    if erreurs_etat:
        rap.erreurs.extend(erreurs_etat)
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    if dry_run:
        rap.operations_inversees = len(mouvements)
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    nouveau_batch = str(uuid.uuid4())

    phase1 = 0
    try:
        for m in mouvements:
            m.dst.rename(m.tmp)
            phase1 += 1
            m.fichier.chemin_relatif = m.tmp_relatif
            m.fichier.nom_fichier = m.tmp.name
        session.flush()
    except Exception as e:
        for m in reversed(mouvements[:phase1]):
            _renommer_signaler(m.tmp, m.dst, rap.erreurs)
        session.rollback()
        rap.erreurs.insert(0, f"Échec phase 1 : {e}")
        rap.operations_echouees = phase1
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    phase2 = 0
    try:
        for m in mouvements:
            m.src.parent.mkdir(parents=True, exist_ok=True)
            m.tmp.rename(m.src)
            phase2 += 1
            m.fichier.chemin_relatif = m.op.chemin_avant
            m.fichier.nom_fichier = PurePosixPath(m.op.chemin_avant).name
            invalider_derives(m.fichier)
            m.op.annule_par_batch_id = nouveau_batch
            session.add(
                OperationFichier(
                    batch_id=nouveau_batch,
                    fichier_id=m.op.fichier_id,
                    type_operation=TypeOperationFichier.RESTORE.value,
                    racine_avant=m.op.racine_apres,
                    chemin_avant=m.op.chemin_apres,
                    racine_apres=m.op.racine_avant,
                    chemin_apres=m.op.chemin_avant,
                    statut=StatutOperation.REUSSIE.value,
                    execute_par=execute_par,
                )
            )
        session.commit()
    except Exception as e:
        for m in reversed(mouvements[:phase2]):
            _renommer_signaler(m.src, m.tmp, rap.erreurs)
        for m in reversed(mouvements):
            _renommer_signaler(m.tmp, m.dst, rap.erreurs)
        session.rollback()
        rap.erreurs.insert(0, f"Échec phase 2 : {e}")
        rap.operations_echouees = phase2
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    rap.batch_id_annulation = nouveau_batch
    rap.operations_inversees = len(mouvements)
    rap.duree_secondes = time.perf_counter() - debut
    return rap
