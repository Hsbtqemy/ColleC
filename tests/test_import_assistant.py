"""Tests des routes de l'assistant d'import web (V0.7, sous-étape 1).

Couvre le cycle de vie d'une SessionImport : accueil, création,
reprise, abandon, 404.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, SessionImport


@pytest.fixture
def client_vide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "vide.db"
    engine = creer_engine(db_path)
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    return TestClient(app)


def _sessions(db_path: Path) -> list[SessionImport]:
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        rows = list(s.scalars(select(SessionImport)).all())
        # Détacher pour lecture après fermeture.
        for r in rows:
            s.expunge(r)
    engine.dispose()
    return rows


def test_accueil_base_vide(client_vide: TestClient) -> None:
    resp = client_vide.get("/import")
    assert resp.status_code == 200
    assert "Aucun import en cours" in resp.text
    assert "Nouvel import" in resp.text


def test_nouveau_import_cree_session_et_redirige(client_vide: TestClient) -> None:
    resp = client_vide.post("/import/nouveau", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/import/")


def test_session_apparait_dans_accueil(client_vide: TestClient) -> None:
    client_vide.post("/import/nouveau")
    resp = client_vide.get("/import")
    assert "Imports en cours (1)" in resp.text


def test_page_session_affiche_etape_tableur(client_vide: TestClient) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    url = cree.headers["location"]
    resp = client_vide.get(url)
    assert resp.status_code == 200
    assert "tableur" in resp.text


def test_session_inexistante_404(client_vide: TestClient) -> None:
    resp = client_vide.get("/import/9999")
    assert resp.status_code == 404


def test_abandonner_passe_le_statut(
    client_vide: TestClient, tmp_path: Path
) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    session_id = int(cree.headers["location"].rsplit("/", 1)[1])
    resp = client_vide.post(
        f"/import/{session_id}/abandonner", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/import"

    rows = _sessions(tmp_path / "vide.db")
    assert len(rows) == 1
    assert rows[0].statut == "abandonnee"


def test_abandonner_retire_de_l_accueil(client_vide: TestClient) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    session_id = int(cree.headers["location"].rsplit("/", 1)[1])
    client_vide.post(f"/import/{session_id}/abandonner")
    resp = client_vide.get("/import")
    assert "Aucun import en cours" in resp.text


def test_abandonner_idempotent(client_vide: TestClient) -> None:
    """Ré-abandonner une session déjà abandonnée reste un 303 propre."""
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    session_id = int(cree.headers["location"].rsplit("/", 1)[1])
    r1 = client_vide.post(
        f"/import/{session_id}/abandonner", follow_redirects=False
    )
    r2 = client_vide.post(
        f"/import/{session_id}/abandonner", follow_redirects=False
    )
    assert r1.status_code == 303
    assert r2.status_code == 303


def test_abandonner_supprime_le_tableur_temporaire(
    client_vide: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Abandonner une session efface son tableur temporaire du disque."""
    from archives_tool.api.services import import_web

    # Rediriger le dossier de travail des tableurs vers le tmp du test.
    racine_tmp = tmp_path / "import_tmp"
    racine_tmp.mkdir()
    monkeypatch.setattr(import_web, "RACINE_IMPORT_TMP", racine_tmp)

    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    session_id = int(cree.headers["location"].rsplit("/", 1)[1])

    # Simuler un tableur uploadé attaché à la session.
    tableur = racine_tmp / f"session_{session_id}.xlsx"
    tableur.write_bytes(b"fake")
    engine = creer_engine(tmp_path / "vide.db")
    factory = creer_session_factory(engine)
    with factory() as s:
        sess = s.get(SessionImport, session_id)
        sess.chemin_tableur = tableur.name
        s.commit()
    engine.dispose()

    assert tableur.is_file()
    client_vide.post(f"/import/{session_id}/abandonner")
    assert not tableur.exists()
