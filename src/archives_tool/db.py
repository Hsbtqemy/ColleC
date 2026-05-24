"""Session SQLAlchemy et configuration SQLite (pragmas WAL, FK)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
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


#: SQL des 3 tables virtuelles FTS5 + triggers de synchro. Centralisé
#: ici pour pouvoir être réutilisé par `assurer_tables_fts()`
#: (startup app + tests qui partent de zéro via `Base.metadata.create_all`)
#: et par la migration Alembic `m1q2r3s4t5u6_fts5_recherche`. Source
#: de vérité unique — si on change le schéma FTS, modifier ici ET
#: ajouter une migration de migration.
_SQL_TABLES_FTS: list[str] = [
    # Mode "standard" (pas de content=) : FTS5 stocke l'index ET le
    # texte original. Permet `snippet()` qui surligne les matchs
    # dans le texte indexé. Le mode "external content" (content='item')
    # plante sur `metadonnees_text` (colonne DÉRIVÉE flatten JSON
    # qui n'existe pas dans la table `item`). Le mode "contentless"
    # (content='') évite ce plantage mais perd `snippet()`.
    # Coût stockage acceptable : on duplique les champs textuels
    # courts (titres, descriptions) — pas un souci aux volumes
    # ColleC (quelques milliers d'items).
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS item_fts USING fts5(
        cote, titre, description, notes_internes, metadonnees_text,
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fonds_fts USING fts5(
        cote, titre, description, description_publique, description_interne,
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS collection_fts USING fts5(
        cote, titre, description, description_publique,
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
]


#: SQL des triggers FTS5 — synchronisent l'index avec la table source
#: (pattern external content). Source de vérité unique réimportée
#: par `assurer_tables_fts()` et par la migration Alembic
#: `m1q2r3s4t5u6_fts5_recherche`. Le dossier `alembic/` ne peut pas
#: contenir d'imports applicatifs (conflit nom avec la lib alembic
#: installée — l'import `from alembic.helpers` résout vers la lib).
_SQL_TRIGGERS_FTS: list[str] = [
    # item_fts — pattern DELETE+INSERT classique (mode FTS5 standard,
    # pas external content). COALESCE pour ne pas planter sur les
    # champs NULL (Item.metadonnees peut être null). GROUP_CONCAT
    # flatten les valeurs top-level du JSON metadonnees pour
    # l'indexation full-text.
    """
    CREATE TRIGGER item_fts_insert AFTER INSERT ON item BEGIN
      INSERT INTO item_fts(rowid, cote, titre, description, notes_internes, metadonnees_text)
      VALUES (new.id,
              COALESCE(new.cote, ''), COALESCE(new.titre, ''),
              COALESCE(new.description, ''), COALESCE(new.notes_internes, ''),
              COALESCE((SELECT GROUP_CONCAT(value, ' ') FROM json_each(new.metadonnees)), ''));
    END
    """,
    """
    CREATE TRIGGER item_fts_delete AFTER DELETE ON item BEGIN
      DELETE FROM item_fts WHERE rowid = old.id;
    END
    """,
    """
    CREATE TRIGGER item_fts_update AFTER UPDATE ON item BEGIN
      DELETE FROM item_fts WHERE rowid = old.id;
      INSERT INTO item_fts(rowid, cote, titre, description, notes_internes, metadonnees_text)
      VALUES (new.id,
              COALESCE(new.cote, ''), COALESCE(new.titre, ''),
              COALESCE(new.description, ''), COALESCE(new.notes_internes, ''),
              COALESCE((SELECT GROUP_CONCAT(value, ' ') FROM json_each(new.metadonnees)), ''));
    END
    """,
    # fonds_fts
    """
    CREATE TRIGGER fonds_fts_insert AFTER INSERT ON fonds BEGIN
      INSERT INTO fonds_fts(rowid, cote, titre, description, description_publique, description_interne)
      VALUES (new.id,
              COALESCE(new.cote, ''), COALESCE(new.titre, ''),
              COALESCE(new.description, ''),
              COALESCE(new.description_publique, ''),
              COALESCE(new.description_interne, ''));
    END
    """,
    """
    CREATE TRIGGER fonds_fts_delete AFTER DELETE ON fonds BEGIN
      DELETE FROM fonds_fts WHERE rowid = old.id;
    END
    """,
    """
    CREATE TRIGGER fonds_fts_update AFTER UPDATE ON fonds BEGIN
      DELETE FROM fonds_fts WHERE rowid = old.id;
      INSERT INTO fonds_fts(rowid, cote, titre, description, description_publique, description_interne)
      VALUES (new.id,
              COALESCE(new.cote, ''), COALESCE(new.titre, ''),
              COALESCE(new.description, ''),
              COALESCE(new.description_publique, ''),
              COALESCE(new.description_interne, ''));
    END
    """,
    # collection_fts
    """
    CREATE TRIGGER collection_fts_insert AFTER INSERT ON collection BEGIN
      INSERT INTO collection_fts(rowid, cote, titre, description, description_publique)
      VALUES (new.id,
              COALESCE(new.cote, ''), COALESCE(new.titre, ''),
              COALESCE(new.description, ''),
              COALESCE(new.description_publique, ''));
    END
    """,
    """
    CREATE TRIGGER collection_fts_delete AFTER DELETE ON collection BEGIN
      DELETE FROM collection_fts WHERE rowid = old.id;
    END
    """,
    """
    CREATE TRIGGER collection_fts_update AFTER UPDATE ON collection BEGIN
      DELETE FROM collection_fts WHERE rowid = old.id;
      INSERT INTO collection_fts(rowid, cote, titre, description, description_publique)
      VALUES (new.id,
              COALESCE(new.cote, ''), COALESCE(new.titre, ''),
              COALESCE(new.description, ''),
              COALESCE(new.description_publique, ''));
    END
    """,
]


def assurer_tables_fts(engine: Engine) -> None:
    """Crée les tables virtuelles FTS5 + leurs triggers de synchro si
    pas déjà présentes. Idempotent (CREATE TABLE IF NOT EXISTS,
    DROP TRIGGER IF EXISTS + CREATE).

    À appeler après `Base.metadata.create_all(engine)` dans les tests
    et au startup de l'app (la migration Alembic le fait aussi mais
    ne couvre pas les bases créées à zéro hors d'Alembic).

    Ne peuple pas les tables FTS avec les données existantes — utile
    seulement quand on crée la base de toutes pièces (où les tables
    source sont vides). Pour une réindexation manuelle d'une base
    avec données, voir `archives-tool reindex` (TODO).
    """
    with engine.begin() as conn:
        for sql in _SQL_TABLES_FTS:
            conn.execute(text(sql))
        for trigger in (
            "item_fts_insert", "item_fts_delete", "item_fts_update",
            "fonds_fts_insert", "fonds_fts_delete", "fonds_fts_update",
            "collection_fts_insert", "collection_fts_delete", "collection_fts_update",
        ):
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        for sql in _SQL_TRIGGERS_FTS:
            conn.execute(text(sql))
