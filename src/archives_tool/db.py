"""Session SQLAlchemy et configuration SQLite (pragmas WAL, FK)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def configurer_sqlite(engine: Engine) -> None:
    """Active WAL, FK, et réglages perf sur chaque connexion SQLite.

    Note : si la base est un jour mise sur partage réseau, repasser en
    mode journal DELETE (plus fiable sur SMB/NFS).
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=268435456")
        cursor.close()


def creer_engine(chemin_db: Path | str, *, echo: bool = False) -> Engine:
    """Crée un engine SQLite et applique les pragmas."""
    url = f"sqlite:///{Path(chemin_db).as_posix()}"
    engine = create_engine(url, echo=echo, future=True)
    configurer_sqlite(engine)
    return engine


def creer_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
