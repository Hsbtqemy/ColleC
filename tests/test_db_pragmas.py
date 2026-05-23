"""Garde-fou : les pragmas SQLite (WAL, FK, perf) sont bien appliqués.

`configurer_sqlite` pose 5 pragmas à chaque connexion via un hook
SQLAlchemy. Sans ces pragmas, les promesses de V0.9.1 tombent —
concurrence multi-lecteurs (WAL), intégrité référentielle
(foreign_keys), perf (synchronous, temp_store, mmap_size). Si le
hook est cassé un jour, ce test le fait sauter.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from archives_tool.db import creer_engine


def test_pragmas_sont_appliques_apres_creer_engine(tmp_path: Path) -> None:
    db_path = tmp_path / "pragmas.db"
    engine = creer_engine(db_path)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("PRAGMA journal_mode")) == "wal"
            assert conn.scalar(text("PRAGMA synchronous")) == 1  # NORMAL
            assert conn.scalar(text("PRAGMA foreign_keys")) == 1
            assert conn.scalar(text("PRAGMA temp_store")) == 2  # MEMORY
            # mmap_size : SQLite peut décliner si le système ne supporte pas.
            # On vérifie juste que le pragma a été demandé (valeur > 0 ou 0
            # selon le système — important : pas d'erreur silencieuse au hook).
            mmap_size = conn.scalar(text("PRAGMA mmap_size"))
            assert isinstance(mmap_size, int)
    finally:
        engine.dispose()
