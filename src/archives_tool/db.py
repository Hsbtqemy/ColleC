"""Session SQLAlchemy et configuration SQLite (pragmas WAL, FK)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
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


# ---------------------------------------------------------------------------
# Helper public d'ouverture de session pour les notebooks / scripts
# ---------------------------------------------------------------------------

#: Chemin par défaut de la base si `ARCHIVES_DB` n'est pas posée.
#: Aligné sur `api/deps.py::CHEMIN_DB_DEFAUT` (même valeur).
_CHEMIN_DB_DEFAUT = "data/archives.db"


@lru_cache(maxsize=4)
def _factory_pour(chemin_resolu: str) -> sessionmaker[Session]:
    """Engine + factory cachés par chemin pour ne pas re-créer à chaque
    ouverture. Borné à 4 entrées (l'usage notebook typique alterne entre
    base de prod + base de demo au pire).

    Note : la fonction homonyme dans ``api/deps.py`` est dédiée aux
    requêtes FastAPI et reste séparée. Toute déduplication entraînerait
    une dépendance non-désirée services métier → couche routes.
    """
    return creer_session_factory(creer_engine(chemin_resolu))


@contextmanager
def obtenir_session(chemin_db: Path | str | None = None) -> Iterator[Session]:
    """Ouvre une session SQLAlchemy en context manager — pratique pour
    les scripts ad-hoc et les notebooks Jupyter (cf.
    ``docs/guide/notebook.md``).

    Args:
        chemin_db: Chemin vers le fichier SQLite. Si ``None`` (défaut),
            utilise ``ARCHIVES_DB`` (variable d'env) ou
            ``data/archives.db`` en dernier recours.

    Yields:
        Une session SQLAlchemy fermée automatiquement à la sortie du
        ``with``. L'engine sous-jacent est **réutilisé** entre les
        appels (cache par chemin) — pas besoin de le disposer dans les
        notebooks.

    Exemple :
        >>> from archives_tool.db import obtenir_session
        >>> from archives_tool.api.services.fonds import lister_fonds
        >>> with obtenir_session() as db:
        ...     for f in lister_fonds(db):
        ...         print(f.cote, f.titre)

    Pour cibler une base spécifique :
        >>> with obtenir_session("data/demo.db") as db:
        ...     ...

    Garde : `with obtenir_session() as db:` à chaque opération — ne pas
    laisser une session ouverte sur la durée du notebook (verrous
    résiduels). cf. ``notebooks-sdk-future.md`` section *Pièges*.
    """
    if chemin_db is None:
        chemin_db = os.environ.get("ARCHIVES_DB", _CHEMIN_DB_DEFAUT)
    factory = _factory_pour(str(chemin_db))
    with factory() as session:
        yield session


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


#: SQL de peuplement initial des tables FTS depuis les tables source.
#: Source unique réutilisée par `reindexer_fts()` (réindex manuel
#: d'une base existante) et par la migration `m1q2r3s4t5u6_fts5_recherche`
#: (peuplement à l'upgrade). Cohérent avec les triggers
#: `_SQL_TRIGGERS_FTS` qui font la même chose en INSERT/UPDATE.
_SQL_PEUPLEMENT_FTS: list[str] = [
    """
    INSERT INTO item_fts(rowid, cote, titre, description, notes_internes, metadonnees_text)
    SELECT id,
           COALESCE(cote, ''), COALESCE(titre, ''),
           COALESCE(description, ''), COALESCE(notes_internes, ''),
           COALESCE((SELECT GROUP_CONCAT(value, ' ') FROM json_each(item.metadonnees)), '')
    FROM item
    """,
    """
    INSERT INTO fonds_fts(rowid, cote, titre, description, description_publique, description_interne)
    SELECT id,
           COALESCE(cote, ''), COALESCE(titre, ''),
           COALESCE(description, ''),
           COALESCE(description_publique, ''),
           COALESCE(description_interne, '')
    FROM fonds
    """,
    """
    INSERT INTO collection_fts(rowid, cote, titre, description, description_publique)
    SELECT id,
           COALESCE(cote, ''), COALESCE(titre, ''),
           COALESCE(description, ''),
           COALESCE(description_publique, '')
    FROM collection
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
    avec données, utiliser `reindexer_fts(engine)`.
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


def reindexer_fts(engine: Engine) -> dict[str, int]:
    """Vide puis repeuple les 3 tables FTS depuis les tables source.

    À appeler :
    - après un upgrade qui ajoute le FTS sur une base existante
      pré-FTS (la migration le fait, mais si quelqu'un a créé la
      base via `create_all` puis ajouté du contenu avant d'appliquer
      la migration FTS, il faut réindexer)
    - en CLI `archives-tool reindex` (TODO V0.9.x)
    - en cas de corruption suspectée de l'index

    Idempotent et atomique (1 transaction). Les triggers ne se
    déclenchent pas pendant INSERT INTO ... SELECT (ils sont AFTER
    INSERT sur la table SOURCE — ici on insère directement dans FTS).

    Retourne le nombre d'entrées indexées par table.
    """
    counts: dict[str, int] = {}
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM item_fts"))
        conn.execute(text("DELETE FROM fonds_fts"))
        conn.execute(text("DELETE FROM collection_fts"))
        for sql in _SQL_PEUPLEMENT_FTS:
            conn.execute(text(sql))
        counts["item"] = conn.execute(
            text("SELECT COUNT(*) FROM item_fts")
        ).scalar_one()
        counts["fonds"] = conn.execute(
            text("SELECT COUNT(*) FROM fonds_fts")
        ).scalar_one()
        counts["collection"] = conn.execute(
            text("SELECT COUNT(*) FROM collection_fts")
        ).scalar_one()
    return counts
