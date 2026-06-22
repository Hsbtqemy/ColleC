"""Tests de la page web de contrôles de cohérence (`/controler`, lecture seule).

Surface UI du module `qa` (déjà testé unitairement) : on vérifie le
composeur (résolution de périmètre, options, note racines) et le rendu de
la page (bandeau bilan, sélecteur de fonds, sections problèmes / OK).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.api.services.controle_web import composer_page_controle
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    # Config locale temp à racines vides : isole du `config_local.yaml` du
    # poste (sinon `get_racines()` renverrait ses racines réelles → la note
    # FILE-MISSING serait absente, test dépendant de l'environnement).
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump({"utilisateur": "test", "racines": {}}, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    return db


@pytest.fixture
def session_demo(base_demo: Path) -> Iterator[Session]:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        yield s
    engine.dispose()


# ---------------------------------------------------------------------------
# Service composeur
# ---------------------------------------------------------------------------


def test_composer_base_entiere(session_demo: Session) -> None:
    vue = composer_page_controle(session_demo, racines={}, fonds=None)
    assert vue.scope_label == "Base entière"
    assert vue.fonds_cote is None
    assert vue.racines_configurees is False
    # La base démo a plusieurs fonds → le sélecteur a des options.
    assert len(vue.fonds_options) >= 1
    assert any(cote == "HK" for cote, _ in vue.fonds_options)
    # 14 contrôles exécutés (problèmes + OK).
    assert len(vue.controles_problemes) + len(vue.controles_ok) == 14


def test_composer_perimetre_fonds(session_demo: Session) -> None:
    fonds = lire_fonds_par_cote(session_demo, "HK")
    vue = composer_page_controle(session_demo, racines={}, fonds=fonds)
    assert vue.fonds_cote == "HK"
    assert vue.scope_label.startswith("Fonds HK")


def test_composer_racines_configurees_flag(session_demo: Session) -> None:
    vue = composer_page_controle(
        session_demo, racines={"scans": Path("/tmp/x")}, fonds=None
    )
    assert vue.racines_configurees is True


def test_horodatage_affichage_est_naif(session_demo: Session) -> None:
    """Le rapport qa horodate en UTC aware ; la vue l'expose naïf local pour
    rester compatible avec `temps_relatif` (sinon TypeError au rendu)."""
    vue = composer_page_controle(session_demo, racines={}, fonds=None)
    assert vue.rapport.horodatage.tzinfo is not None  # source aware
    assert vue.horodatage_affichage.tzinfo is None  # vue naïve


def test_problemes_tries_erreur_avant_info(session_demo: Session) -> None:
    """Les problèmes sont triés erreur → avertissement → info."""
    vue = composer_page_controle(session_demo, racines={}, fonds=None)
    rangs = {"erreur": 0, "avertissement": 1, "info": 2}
    vals = [rangs[c.severite] for c in vue.controles_problemes]
    assert vals == sorted(vals)


# ---------------------------------------------------------------------------
# Page web
# ---------------------------------------------------------------------------


def test_page_base_200(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/controler")
    assert resp.status_code == 200
    assert "Contrôles de cohérence" in resp.text
    assert "Base entière" in resp.text
    # Bandeau périmètre + sélecteur de fonds.
    assert "fonds" in resp.text
    assert 'name="fonds"' in resp.text
    # Toujours des contrôles passés sur une base démo valide → repli présent.
    assert "Contrôles passés" in resp.text


def test_page_note_racines_non_configurees(base_demo: Path) -> None:
    """Sans config (cas TestClient par défaut), la note FILE-MISSING apparaît."""
    client = TestClient(app)
    resp = client.get("/controler")
    assert "Racines de fichiers non configurées" in resp.text


def test_page_scope_fonds_preselectionne(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/controler?fonds=HK")
    assert resp.status_code == 200
    assert "Fonds HK" in resp.text
    # L'option HK est marquée selected dans le picker.
    assert 'value="HK" selected' in resp.text


def test_page_fonds_inconnu_404(base_demo: Path) -> None:
    client = TestClient(app)
    assert client.get("/controler?fonds=NOPE").status_code == 404


def test_page_fonds_vide_equivaut_base(base_demo: Path) -> None:
    """`?fonds=` (vide) ne doit pas 404 — c'est la base entière."""
    client = TestClient(app)
    resp = client.get("/controler?fonds=")
    assert resp.status_code == 200
    assert "Base entière" in resp.text


def test_lien_header_present(base_demo: Path) -> None:
    """Le lien « Contrôler » est dans le header (entrée vers la page)."""
    client = TestClient(app)
    resp = client.get("/")
    assert 'href="/controler"' in resp.text
