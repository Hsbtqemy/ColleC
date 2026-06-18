"""Tests de la CLI `archives-tool sharedocs` (Chantier 1, tranche 4).

CliRunner + `ClientShareDocs` patché sur un httpx `MockTransport` (aucun
réseau), config + base SQLite jetables, identifiants via variables d'env.
Couvre : lister (text/json), importer (dry-run/réel), et les sorties propres
(creds absents, base_url absente, racine inconnue, item introuvable).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

import archives_tool.cli as cli_mod
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.sharedocs import ClientShareDocs
from archives_tool.models import Base, Fichier
from sqlalchemy import select

runner = CliRunner()

_MS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:multistatus xmlns:d="DAV:">'
    "<d:response><d:href>/dav/colleC/</d:href><d:propstat><d:prop>"
    "<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>"
    "<d:response><d:href>/dav/colleC/a.jpg</d:href><d:propstat><d:prop>"
    "<d:resourcetype/><d:getcontentlength>5</d:getcontentlength>"
    "<d:displayname>a.jpg</d:displayname></d:prop></d:propstat></d:response>"
    "</d:multistatus>"
)


def _handler(req: httpx.Request) -> httpx.Response:
    if req.method == "PROPFIND":
        return httpx.Response(207, text=_MS)
    return httpx.Response(200, content=b"BYTES")


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remplace ClientShareDocs par une fabrique injectant le MockTransport
    (la vraie validation base_url/hôte/HTTPS reste exercée)."""

    def fabrique(base_url, user, password, **kw):
        kw.pop("transport", None)
        return ClientShareDocs(
            base_url, user, password, transport=httpx.MockTransport(_handler), **kw
        )

    monkeypatch.setattr(cli_mod, "ClientShareDocs", fabrique)


@pytest.fixture(autouse=True)
def _creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEC_SHAREDOCS_USER", "marie")
    monkeypatch.setenv("COLLEC_SHAREDOCS_PASS", "secret")


@pytest.fixture
def config(tmp_path: Path) -> Path:
    (tmp_path / "import").mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "T",
                "racines": {"import": str(tmp_path / "import")},
                "sharedocs": {"base_url": "https://sharedocs.huma-num.fr/dav/colleC"},
            }
        ),
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def db(tmp_path: Path) -> Path:
    chemin = tmp_path / "t.db"
    eng = creer_engine(chemin)
    Base.metadata.create_all(eng)
    with creer_session_factory(eng)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        creer_item(s, FormulaireItem(cote="AS-001", titre="x", fonds_id=f.id))
        s.commit()
    eng.dispose()
    return chemin


# --------------------------------------------------------------------------- #
# lister
# --------------------------------------------------------------------------- #


def test_lister_text(config: Path) -> None:
    r = runner.invoke(app, ["sharedocs", "lister", "--config", str(config)])
    assert r.exit_code == 0, r.output
    assert "a.jpg" in r.output


def test_lister_json(config: Path) -> None:
    r = runner.invoke(
        app, ["sharedocs", "lister", "--format", "json", "--config", str(config)]
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert any(e["chemin"] == "a.jpg" and e["taille"] == 5 for e in data)


def test_lister_creds_absents_exit2(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COLLEC_SHAREDOCS_USER", raising=False)
    monkeypatch.delenv("COLLEC_SHAREDOCS_PASS", raising=False)
    r = runner.invoke(app, ["sharedocs", "lister", "--config", str(config)])
    assert r.exit_code == 2
    assert "identifiants" in r.output.lower()


def test_lister_pas_de_base_url_exit2(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump({"utilisateur": "T"}), encoding="utf-8")
    r = runner.invoke(app, ["sharedocs", "lister", "--config", str(cfg)])
    assert r.exit_code == 2
    assert "base_url" in r.output.lower()


# --------------------------------------------------------------------------- #
# importer
# --------------------------------------------------------------------------- #


def test_importer_dry_run_par_defaut(config: Path, db: Path) -> None:
    r = runner.invoke(
        app,
        [
            "sharedocs",
            "importer",
            "AS-001",
            "d/a.jpg",
            "--fonds",
            "AS",
            "--racine",
            "import",
            "--config",
            str(config),
            "--db-path",
            str(db),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output
    eng = creer_engine(db)
    with creer_session_factory(eng)() as s:
        assert s.scalars(select(Fichier)).all() == []  # aucune écriture


def test_importer_reel_cree_fichier(config: Path, db: Path) -> None:
    r = runner.invoke(
        app,
        [
            "sharedocs",
            "importer",
            "AS-001",
            "d/a.jpg",
            "--fonds",
            "AS",
            "--racine",
            "import",
            "--no-dry-run",
            "--config",
            str(config),
            "--db-path",
            str(db),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "APPLIQUÉ" in r.output
    eng = creer_engine(db)
    with creer_session_factory(eng)() as s:
        f = s.scalars(select(Fichier)).one()
        assert f.chemin_relatif == "AS-001/a.jpg" and f.racine == "import"


def test_importer_json(config: Path, db: Path) -> None:
    r = runner.invoke(
        app,
        [
            "sharedocs",
            "importer",
            "AS-001",
            "d/a.jpg",
            "--fonds",
            "AS",
            "--racine",
            "import",
            "--format",
            "json",
            "--config",
            str(config),
            "--db-path",
            str(db),
        ],
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["dry_run"] is True and data["nb_retenus"] == 1


def test_importer_racine_inconnue_exit2(config: Path, db: Path) -> None:
    r = runner.invoke(
        app,
        [
            "sharedocs",
            "importer",
            "AS-001",
            "d/a.jpg",
            "--fonds",
            "AS",
            "--racine",
            "absente",
            "--config",
            str(config),
            "--db-path",
            str(db),
        ],
    )
    assert r.exit_code == 2
    assert "absente" in r.output.lower()


def test_importer_item_introuvable_exit1(config: Path, db: Path) -> None:
    r = runner.invoke(
        app,
        [
            "sharedocs",
            "importer",
            "AS-999",
            "d/a.jpg",
            "--fonds",
            "AS",
            "--racine",
            "import",
            "--config",
            str(config),
            "--db-path",
            str(db),
        ],
    )
    assert r.exit_code == 1
    assert "introuvable" in r.output.lower()
