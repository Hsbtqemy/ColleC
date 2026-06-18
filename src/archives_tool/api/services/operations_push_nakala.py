"""Journal des push fichiers Nakala (principe directeur n°4).

`OperationFichier` ne couvre que les opérations sur disque local.
`OperationEntite` couvre les suppressions d'entités. Les push vers
Nakala n'étaient pas tracés : un ``PUT /datas/{id}`` avec ``files=[...]``
réduit RETIRE silencieusement les fichiers absents de la liste cible
(H1 — sémantique « remplace intégralement »).

Ce module construit et insère une ligne :class:`OperationPushNakala`
**dans la même transaction** que les mutations DB du service push
(`Fichier.sha1_nakala`, `iiif_url_nakala`, dérivés invalidés…). Le
caller fait un commit unique → journal et mutations sont atomiques
(les deux, ou rien).

Phase 1 : audit + snapshot forensique des `files[]` avant/après PUT,
+ liste des sha1 uploadés et retirés. Pas d'undo (cf. dette
`OperationEntite` : réversibilité asymétrique).

Listing : :func:`lister_push_nakala`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import OperationPushNakala


def nouveau_batch_id() -> str:
    """UUID compatible avec le format des autres journaux
    (`OperationFichier`, `OperationImport`)."""
    return str(uuid.uuid4())


def journaliser_push_fichiers(
    db: Session,
    *,
    batch_id: str,
    cote_item: str,
    fonds_cote: str | None,
    doi: str,
    snapshot_avant: list[dict[str, Any]],
    snapshot_apres: list[dict[str, Any]],
    sha1s_uploades: list[str],
    sha1s_retires: list[str],
    execute_par: str | None,
) -> OperationPushNakala:
    """Insère une ligne `OperationPushNakala` (sans commit).

    Le caller doit faire le commit final pour atomicité avec les
    autres mutations DB du service push.

    - ``snapshot_avant`` : liste de dicts `{sha1, name, size?, mime?}`
      depuis ``lire_depot`` (avant PUT). Préserve uniquement les
      champs identifiants — le reste (embargo, puid) n'est pas
      pertinent pour l'audit.
    - ``snapshot_apres`` : liste de dicts `{sha1, name}` envoyée au
      PUT (= ``files_cible``).
    - ``sha1s_uploades`` : sha1 fraîchement uploadés pendant le push.
    - ``sha1s_retires`` : sha1 distants retirés (orphelins +
      non-ACTIF avec pendant Nakala).

    Tous les champs JSON sont stockés en `Text` (sérialisés via
    `json.dumps`) pour compat retro avec SQLite — la requête de
    listing les désérialise.
    """
    op = OperationPushNakala(
        batch_id=batch_id,
        type_operation="push_fichiers",
        cote_item=cote_item,
        fonds_cote=fonds_cote,
        doi=doi,
        snapshot_avant=json.dumps(snapshot_avant, ensure_ascii=False),
        snapshot_apres=json.dumps(snapshot_apres, ensure_ascii=False),
        sha1s_uploades=json.dumps(sha1s_uploades, ensure_ascii=False),
        sha1s_retires=json.dumps(sha1s_retires, ensure_ascii=False),
        execute_par=execute_par,
    )
    db.add(op)
    db.flush()  # pour exposer l'id à l'appelant sans forcer commit
    return op


def lister_push_nakala(
    db: Session,
    *,
    doi: str | None = None,
    cote_item: str | None = None,
    limite: int = 50,
) -> list[OperationPushNakala]:
    """Liste les opérations push journalisées, plus récentes en
    premier. Filtres optionnels `doi` / `cote_item`."""
    stmt = select(OperationPushNakala).order_by(OperationPushNakala.execute_le.desc())
    if doi:
        stmt = stmt.where(OperationPushNakala.doi == doi)
    if cote_item:
        stmt = stmt.where(OperationPushNakala.cote_item == cote_item)
    stmt = stmt.limit(limite)
    return list(db.scalars(stmt).all())
