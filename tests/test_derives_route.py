"""Tests de la route de service des dérivés."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from archives_tool.api.main import app


@pytest.fixture
def racine_avec_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    racine = tmp_path / "miniatures"
    (racine / "vignette" / "HK").mkdir(parents=True)
    (racine / "vignette" / "HK" / "01.jpg").write_bytes(b"\xff\xd8\xff fake jpg")

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump({"utilisateur": "T", "racines": {"miniatures": str(racine)}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    return racine


def test_servir_fichier_existant(racine_avec_image: Path) -> None:
    client = TestClient(app)
    resp = client.get("/derives/miniatures/vignette/HK/01.jpg")
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xff\xd8\xff")


def test_racine_inconnue_403(racine_avec_image: Path) -> None:
    client = TestClient(app)
    resp = client.get("/derives/inexistante/foo.jpg")
    assert resp.status_code == 403


def test_traversee_de_chemin_403(racine_avec_image: Path) -> None:
    client = TestClient(app)
    # `..` interdit même via URL-encodage.
    resp = client.get("/derives/miniatures/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code == 403


def test_fichier_inexistant_404(racine_avec_image: Path) -> None:
    client = TestClient(app)
    resp = client.get("/derives/miniatures/vignette/HK/absent.jpg")
    assert resp.status_code == 404
