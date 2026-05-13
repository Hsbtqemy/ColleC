"""Tests du mode lecture seule (`config_local.yaml: lecture_seule: true`).

Quand le flag est actif, le middleware doit retourner 423 sur toute
mutation HTTP (POST/PUT/PATCH/DELETE) et laisser passer les GET.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from archives_tool.api.deps import est_lecture_seule
from archives_tool.api.main import app


def _ecrire_config(chemin: Path, lecture_seule: bool, racine_demo: Path) -> None:
    chemin.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "test",
                "racines": {"miniatures": str(racine_demo)},
                "lecture_seule": lecture_seule,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def config_lecture_seule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, lecture_seule=True, racine_demo=racine)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    return cfg


@pytest.fixture
def config_normale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, lecture_seule=False, racine_demo=racine)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    return cfg


def test_lecture_seule_flag_lu_depuis_config(config_lecture_seule: Path) -> None:
    assert est_lecture_seule() is True


def test_lecture_seule_flag_absent_par_defaut(config_normale: Path) -> None:
    assert est_lecture_seule() is False


def test_lecture_seule_absent_si_pas_de_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARCHIVES_CONFIG", str(tmp_path / "absent.yaml"))
    assert est_lecture_seule() is False


def test_post_renvoie_423_en_lecture_seule(config_lecture_seule: Path) -> None:
    client = TestClient(app)
    resp = client.post("/preferences/colonnes/items/1", data={})
    assert resp.status_code == 423
    assert "lecture seule" in resp.text.lower()


def test_get_passe_en_lecture_seule(config_lecture_seule: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200


def test_delete_renvoie_423_en_lecture_seule(config_lecture_seule: Path) -> None:
    client = TestClient(app)
    resp = client.delete("/collections/CHOSE")
    assert resp.status_code == 423


def test_banniere_lecture_seule_dans_html(config_lecture_seule: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Mode lecture seule" in resp.text


def test_pas_de_banniere_en_mode_normal(config_normale: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Mode lecture seule" not in resp.text


def test_post_passe_en_mode_normal(config_normale: Path) -> None:
    """En mode normal, le middleware n'intervient pas — on doit
    obtenir la vraie réponse du routeur (404 si la collection
    n'existe pas dans la base de test, 422 si le payload est
    refusé). Code 423 strictement interdit ici, et la réponse ne
    doit pas mentionner « lecture seule »."""
    client = TestClient(app)
    resp = client.post("/preferences/colonnes/items/1", data={})
    assert resp.status_code in {200, 303, 400, 404, 422}
    assert "lecture seule" not in resp.text.lower()
