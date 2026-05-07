"""Annulation d'un batch de renommage par son `batch_id`.

On rejoue les mouvements inverses (chemin_apres → chemin_avant) en
deux phases comme à l'exécution. Les `OperationFichier` originales
sont marquées avec `annule_par_batch_id`, et de nouvelles
`OperationFichier(type=restore)` sont insérées avec le nouveau
`batch_id`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.files.paths import chemin_existe_nfc_ou_nfd
from archives_tool.models import (
    Fichier,
    OperationFichier,
    StatutOperation,
    TypeOperationFichier,
)

from .rapport import RapportAnnulation


def _chemin_absolu(base: Path, chemin_relatif: str) -> Path:
    return base.joinpath(*chemin_relatif.split("/"))


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

    # Vérifications préalables : chaque fichier doit être dans son état
    # post-renommage (chemin_relatif == chemin_apres) sur disque ET en base.
    erreurs_etat: list[str] = []
    for op in ops_originales:
        fichier = session.get(Fichier, op.fichier_id)
        if fichier is None:
            erreurs_etat.append(
                f"Op {op.id} : fichier {op.fichier_id} introuvable en base."
            )
            continue
        if fichier.chemin_relatif != op.chemin_apres:
            erreurs_etat.append(
                f"Op {op.id} : la base a divergé "
                f"(actuel={fichier.chemin_relatif!r}, attendu={op.chemin_apres!r})."
            )
            continue
        base = racines.get(op.racine_apres or op.racine_avant)
        if base is None:
            erreurs_etat.append(
                f"Op {op.id} : racine {op.racine_apres!r} non configurée."
            )
            continue
        if not chemin_existe_nfc_ou_nfd(base, op.chemin_apres):
            erreurs_etat.append(
                f"Op {op.id} : fichier absent sur disque "
                f"({op.racine_apres}:{op.chemin_apres})."
            )

    if erreurs_etat:
        rap.erreurs.extend(erreurs_etat)
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    if dry_run:
        rap.operations_inversees = len(ops_originales)
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    nouveau_batch = str(uuid.uuid4())

    # Phase 1 — disque dst→tmp et DB chemin_relatif=tmp.
    mouvements: list[tuple[OperationFichier, Fichier, Path, Path, Path, str]] = []
    for op in ops_originales:
        base = racines[op.racine_apres or op.racine_avant]
        fichier = session.get(Fichier, op.fichier_id)
        assert fichier is not None
        dst = _chemin_absolu(base, op.chemin_apres)
        src = _chemin_absolu(base, op.chemin_avant)
        tmp_nom = f".tmp_undo_{uuid.uuid4().hex[:12]}_{dst.name}"
        tmp = dst.parent / tmp_nom
        parent_rel = PurePosixPath(op.chemin_apres).parent
        tmp_relatif = (parent_rel / tmp_nom).as_posix().lstrip("/")
        mouvements.append((op, fichier, dst, tmp, src, tmp_relatif))

    phase1 = 0
    try:
        for _op, fichier, dst, tmp, _src, tmp_relatif in mouvements:
            dst.rename(tmp)
            phase1 += 1
            fichier.chemin_relatif = tmp_relatif
            fichier.nom_fichier = tmp.name
        session.flush()
    except Exception as e:
        for _op, _f, dst, tmp, _src, _tr in reversed(mouvements[:phase1]):
            try:
                tmp.rename(dst)
            except OSError:
                pass
        session.rollback()
        rap.erreurs.append(f"Échec phase 1 : {e}")
        rap.operations_echouees = phase1
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    # Phase 2 — disque tmp→src et DB chemin_relatif=chemin_avant ; journal.
    phase2 = 0
    try:
        for op, fichier, _dst, tmp, src, _tr in mouvements:
            src.parent.mkdir(parents=True, exist_ok=True)
            tmp.rename(src)
            phase2 += 1
            fichier.chemin_relatif = op.chemin_avant
            fichier.nom_fichier = PurePosixPath(op.chemin_avant).name
            op.annule_par_batch_id = nouveau_batch
            session.add(
                OperationFichier(
                    batch_id=nouveau_batch,
                    fichier_id=op.fichier_id,
                    type_operation=TypeOperationFichier.RESTORE.value,
                    racine_avant=op.racine_apres,
                    chemin_avant=op.chemin_apres,
                    racine_apres=op.racine_avant,
                    chemin_apres=op.chemin_avant,
                    statut=StatutOperation.REUSSIE.value,
                    execute_par=execute_par,
                )
            )
        session.commit()
    except Exception as e:
        # Compensation : remonter phase 2 et phase 1.
        for _op, _f, _dst, tmp, src, _tr in reversed(mouvements[:phase2]):
            try:
                src.rename(tmp)
            except OSError:
                pass
        for _op, _f, dst, tmp, _src, _tr in reversed(mouvements):
            try:
                tmp.rename(dst)
            except OSError:
                pass
        session.rollback()
        rap.erreurs.append(f"Échec phase 2 : {e}")
        rap.operations_echouees = phase2
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    rap.batch_id_annulation = nouveau_batch
    rap.operations_inversees = len(mouvements)
    rap.duree_secondes = time.perf_counter() - debut
    return rap
