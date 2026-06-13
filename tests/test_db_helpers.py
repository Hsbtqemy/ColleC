"""Tests des helpers publics de `archives_tool.db` (chantier #3 petites
portees : `obtenir_session` pour l'usage notebook).

Cf. `docs/guide/notebook.md` et `notebooks-sdk-future.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from archives_tool.db import (
    _factory_pour,
    creer_engine,
    obtenir_session,
)
from archives_tool.models import Base


@pytest.fixture
def base_vide(tmp_path: Path) -> Path:
    """Une base SQLite avec juste le schéma — pas peuplée."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def test_obtenir_session_avec_chemin_explicite(base_vide: Path) -> None:
    """`obtenir_session(chemin)` ouvre une session sur la base ciblée
    et la ferme à la sortie du `with`."""
    with obtenir_session(base_vide) as db:
        assert isinstance(db, Session)
        # La session est utilisable.
        from sqlalchemy import text

        assert db.scalar(text("SELECT 1")) == 1
    # Pas de erreur à la sortie : le context manager a bien close.


def test_obtenir_session_sans_chemin_lit_archives_db(
    base_vide: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sans argument, `obtenir_session()` lit `ARCHIVES_DB`."""
    monkeypatch.setenv("ARCHIVES_DB", str(base_vide))
    with obtenir_session() as db:
        from sqlalchemy import text

        assert db.scalar(text("SELECT 1")) == 1


def test_obtenir_session_reutilise_engine_via_cache(base_vide: Path) -> None:
    """Appels successifs avec le même chemin réutilisent la factory
    (lru_cache) — pas de re-création d'engine à chaque `with`. Pratique
    notebook : ouvre/ferme des dizaines de sessions sans fuite."""
    _factory_pour.cache_clear()  # reset pour avoir un état propre

    with obtenir_session(base_vide):
        pass
    info_apres_1 = _factory_pour.cache_info()
    assert info_apres_1.hits == 0
    assert info_apres_1.misses == 1

    with obtenir_session(base_vide):
        pass
    info_apres_2 = _factory_pour.cache_info()
    # 2e appel : hit du cache, pas de nouveau miss.
    assert info_apres_2.hits == 1
    assert info_apres_2.misses == 1


def test_obtenir_session_chemin_str_et_path_equivalent(base_vide: Path) -> None:
    """`obtenir_session(str)` et `obtenir_session(Path)` donnent la même
    entrée de cache — clé normalisée."""
    _factory_pour.cache_clear()
    with obtenir_session(base_vide):  # Path
        pass
    with obtenir_session(str(base_vide)):  # str
        pass
    # 2 appels, 1 miss + 1 hit = clé partagée.
    info = _factory_pour.cache_info()
    assert info.misses == 1
    assert info.hits == 1


def test_obtenir_session_propage_exception_sans_fuir(base_vide: Path) -> None:
    """Si le bloc `with` lève, la session est quand même fermée."""

    class BoumTest(Exception):
        pass

    with pytest.raises(BoumTest):
        with obtenir_session(base_vide) as db:
            assert isinstance(db, Session)
            raise BoumTest("test")
    # Pas de session orpheline (vérifié indirectement : le test suivant
    # qui ouvre une nouvelle session fonctionne).
    with obtenir_session(base_vide) as db:
        from sqlalchemy import text

        assert db.scalar(text("SELECT 1")) == 1
