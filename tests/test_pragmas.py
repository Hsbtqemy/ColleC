"""Vérifie que les pragmas SQLite critiques sont actifs."""

from __future__ import annotations

from sqlalchemy import Engine, text


def test_journal_mode_wal(engine: Engine) -> None:
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode == "wal"


def test_foreign_keys_on(engine: Engine) -> None:
    with engine.connect() as conn:
        fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert fk == 1


def test_synchronous_normal(engine: Engine) -> None:
    with engine.connect() as conn:
        sync = conn.execute(text("PRAGMA synchronous")).scalar()
    # NORMAL == 1
    assert sync == 1
