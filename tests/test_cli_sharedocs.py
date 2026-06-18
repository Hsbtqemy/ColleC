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


def _make_fabrique(handler):
    """Fabrique de ClientShareDocs injectant un MockTransport (la vraie
    validation base_url/hôte/HTTPS reste exercée par le constructeur)."""

    def fabrique(base_url, user, password, **kw):
        kw.pop("transport", None)
        return ClientShareDocs(
            base_url, user, password, transport=httpx.MockTransport(handler), **kw
        )

    return fabrique


def _patch_handler(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Réinstalle la fabrique avec un handler custom (override de l'autouse)."""
    monkeypatch.setattr(cli_mod, "ClientShareDocs", _make_fabrique(handler))


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "ClientShareDocs", _make_fabrique(_handler))


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


def _importer(config, db, *extra):
    return runner.invoke(
        app,
        [
            "sharedocs",
            "importer",
            "AS-001",
            *extra,
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


# --- correctifs de la passe de revue ---------------------------------------


def test_lister_chemin_invalide_exit2(config: Path) -> None:
    """`lister ../x` (traversal) = erreur de SAISIE → exit 2 (pas 1)."""
    r = runner.invoke(
        app, ["sharedocs", "lister", "../secret", "--config", str(config)]
    )
    assert r.exit_code == 2


def test_importer_echec_total_reel_exit1(
    config: Path, db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Échec TOTAL en --no-dry-run (tous les GET échouent) → exit 1 (scripting),
    aucun Fichier créé."""
    _patch_handler(monkeypatch, lambda req: httpx.Response(500))
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
    assert r.exit_code == 1
    assert "echec_telechargement" in r.output
    with creer_session_factory(creer_engine(db))() as s:
        assert s.scalars(select(Fichier)).all() == []


def test_lister_hote_interdit_via_base_url_exit2(config: Path) -> None:
    """--base-url hors allowlist → ShareDocsHoteInterdit câblé en exit 2 (anti-SSRF)."""
    r = runner.invoke(
        app,
        [
            "sharedocs",
            "lister",
            "--base-url",
            "https://evil.example.com/dav",
            "--config",
            str(config),
        ],
    )
    assert r.exit_code == 2


def test_lister_base_url_http_exit2(config: Path) -> None:
    """--base-url en http → refusé (Basic Auth jamais en clair) → exit 2."""
    r = runner.invoke(
        app,
        [
            "sharedocs",
            "lister",
            "--base-url",
            "http://sharedocs.huma-num.fr/dav",
            "--config",
            str(config),
        ],
    )
    assert r.exit_code == 2


def test_lister_auth_refusee_exit1(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_handler(monkeypatch, lambda req: httpx.Response(403))
    r = runner.invoke(app, ["sharedocs", "lister", "--config", str(config)])
    assert r.exit_code == 1
    assert "refus" in r.output.lower()


def test_lister_base_url_override_sans_section_sharedocs(tmp_path: Path) -> None:
    """--base-url sauve une config sans section `sharedocs`."""
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump({"utilisateur": "T"}), encoding="utf-8")
    r = runner.invoke(
        app,
        [
            "sharedocs",
            "lister",
            "--base-url",
            "https://sharedocs.huma-num.fr/dav/x",
            "--config",
            str(cfg),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "a.jpg" in r.output


def test_importer_idempotent_et_multi_chemins(config: Path, db: Path) -> None:
    """Multi-chemins en un appel (ordres 1,2), puis re-run → deja_en_base."""
    r1 = _importer(config, db, "d/a.jpg", "d/b.jpg", "--no-dry-run")
    assert r1.exit_code == 0, r1.output
    with creer_session_factory(creer_engine(db))() as s:
        fichiers = s.scalars(select(Fichier).order_by(Fichier.ordre)).all()
        assert [f.ordre for f in fichiers] == [1, 2]
    r2 = _importer(config, db, "d/a.jpg", "--no-dry-run")
    assert r2.exit_code == 0
    assert "deja_en_base" in r2.output
    with creer_session_factory(creer_engine(db))() as s:
        assert len(s.scalars(select(Fichier)).all()) == 2  # pas de doublon


def test_importer_propage_utilisateur(config: Path, db: Path) -> None:
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
            "--utilisateur",
            "Marie",
            "--config",
            str(config),
            "--db-path",
            str(db),
        ],
    )
    assert r.exit_code == 0, r.output
    with creer_session_factory(creer_engine(db))() as s:
        f = s.scalars(select(Fichier)).one()
        assert f.ajoute_par == "Marie"
        assert f.taille_octets == len(b"BYTES")


def test_importer_sans_chemin_exit2(config: Path, db: Path) -> None:
    """Argument variadique requis vide → Typer exit 2 (saisie)."""
    r = _importer(config, db)  # aucun chemin
    assert r.exit_code == 2


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
