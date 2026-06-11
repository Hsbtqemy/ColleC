"""Tests des CLI `nakala deposer` / `deposer-collection` (P2/A5+B3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from typer.testing import CliRunner

import archives_tool.cli as cli_mod
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Collection, Fichier, Item, TypeCollection

runner = CliRunner()


class _FakeWriteClient:
    instances: list["_FakeWriteClient"] = []

    def __init__(self, *a, **k) -> None:
        self.uploads: list[str] = []
        self.depots: list[dict] = []
        self.collections: list[dict] = []
        self.puts: list[dict] = []
        _FakeWriteClient.instances.append(self)

    def __enter__(self) -> "_FakeWriteClient":
        return self

    def __exit__(self, *a) -> bool:
        return False

    def uploader_fichier(self, chemin, nom=None):
        n = nom or Path(chemin).name
        self.uploads.append(n)
        return {"name": n, "sha1": f"sha-{len(self.uploads)}"}

    def creer_depot(self, *, metas, files, status="pending", collections_ids=None):
        self.depots.append({"status": status, "collectionsIds": collections_ids})
        return {"payload": {"id": f"10.34847/nkl.d{len(self.depots)}"}}

    def creer_collection(self, *, metas, status="private", datas=None):
        self.collections.append({"status": status})
        return {"payload": {"id": "10.34847/nkl.colNEW"}}

    def supprimer_upload(self, sha1):
        pass

    def modifier_depot(self, identifiant, *, metas, status=None):
        self.puts.append({"id": identifiant, "metas": metas, "status": status})
        return {}


class _FakeReadClient:
    """Faux client lecture pour les push : lire_depot configurable."""

    metas_distantes: list[dict] = []
    mod_date: str = "2024-01-01"

    def __init__(self, *a, **k) -> None:
        pass

    def __enter__(self) -> "_FakeReadClient":
        return self

    def __exit__(self, *a) -> bool:
        return False

    def lire_depot(self, doi: str) -> dict:
        return {"identifier": doi, "metas": list(_FakeReadClient.metas_distantes),
                "modDate": _FakeReadClient.mod_date, "files": [], "status": "pending"}


@pytest.fixture(autouse=True)
def _mock_write_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeWriteClient.instances.clear()
    _FakeReadClient.metas_distantes = []
    monkeypatch.setattr(cli_mod, "NakalaEcritureClient", _FakeWriteClient)
    monkeypatch.setattr(cli_mod, "ClientLectureNakala", _FakeReadClient)


@pytest.fixture
def config_nakala(tmp_path: Path, *, api_key: str = "cle-write") -> Path:
    (tmp_path / "scans").mkdir(exist_ok=True)
    cfg = tmp_path / "config.yaml"
    data: dict = {
        "utilisateur": "T",
        "racines": {"scans": str(tmp_path / "scans")},
        "nakala": {"base_url": "https://apitest.nakala.fr", "api_key": api_key},
    }
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return cfg


@pytest.fixture
def db_avec_item(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    (tmp_path / "scans").mkdir(exist_ok=True)
    (tmp_path / "scans" / "x.jpg").write_bytes(b"\xff\xd8\xff img")
    with creer_session_factory(engine)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="Armonía Somers"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="La mujer desnuda", fonds_id=f.id, date="1984",
            langue="spa", type_coar="http://purl.org/coar/resource_type/c_2f33",
            metadonnees={"createurs": ["Somers, Armonía"]},
        ))
        s.add(Fichier(item_id=item.id, nom_fichier="x.jpg", racine="scans",
                      chemin_relatif="x.jpg", ordre=1))
        s.commit()
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def test_deposer_dry_run_par_defaut(config_nakala: Path, db_avec_item: Path) -> None:
    r = runner.invoke(app, [
        "nakala", "deposer", "AS-001", "--fonds", "AS",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output and "1 fichier(s)" in r.output
    # Rien envoyé, DOI non posé.
    assert _FakeWriteClient.instances[0].depots == []
    with _session(db_avec_item) as s:
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        assert item.doi_nakala is None


def test_deposer_reel(config_nakala: Path, db_avec_item: Path) -> None:
    r = runner.invoke(app, [
        "nakala", "deposer", "AS-001", "--fonds", "AS", "--no-dry-run",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 0, r.output
    assert "déposé" in r.output
    client = _FakeWriteClient.instances[0]
    assert client.uploads == ["x.jpg"] and len(client.depots) == 1
    with _session(db_avec_item) as s:
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        assert item.doi_nakala == "10.34847/nkl.d1"


def test_deposer_sans_api_key_exit2(tmp_path: Path, db_avec_item: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        yaml.safe_dump({"utilisateur": "T", "racines": {"scans": str(tmp_path / "scans")},
                        "nakala": {"base_url": "https://apitest.nakala.fr"}}),
        encoding="utf-8",
    )
    r = runner.invoke(app, [
        "nakala", "deposer", "AS-001", "--fonds", "AS",
        "--config", str(cfg), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 2
    assert "api_key" in r.output


def test_deposer_item_introuvable_exit1(config_nakala: Path, db_avec_item: Path) -> None:
    r = runner.invoke(app, [
        "nakala", "deposer", "INEXISTANT", "--fonds", "AS",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 1
    assert "introuvable" in r.output.lower()


def test_deposer_collection_reel(config_nakala: Path, db_avec_item: Path) -> None:
    # La miroir du fonds AS contient l'item AS-001.
    r = runner.invoke(app, [
        "nakala", "deposer-collection", "AS", "--fonds", "AS", "--no-dry-run",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 0, r.output
    assert "1 déposé(s)" in r.output
    client = _FakeWriteClient.instances[0]
    assert len(client.collections) == 1  # collection Nakala créée
    assert len(client.depots) == 1
    with _session(db_avec_item) as s:
        miroir = s.scalar(
            select(Collection).where(
                Collection.cote == "AS",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        assert miroir.doi_nakala == "10.34847/nkl.colNEW"


# ---------------------------------------------------------------------------
# pousser / publier (P3)
# ---------------------------------------------------------------------------

_NKL = "http://nakala.fr/terms#"


def _poser_doi(db: Path, cote: str, doi: str) -> None:
    with _session(db) as s:
        item = s.scalar(select(Item).where(Item.cote == cote))
        item.doi_nakala = doi
        s.commit()


def test_pousser_sans_doi_exit1(config_nakala: Path, db_avec_item: Path) -> None:
    r = runner.invoke(app, [
        "nakala", "pousser", "AS-001", "--fonds", "AS",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 1
    assert "deposer" in r.output.lower()


def test_pousser_dry_run_montre_diff(config_nakala: Path, db_avec_item: Path) -> None:
    _poser_doi(db_avec_item, "AS-001", "10.34847/nkl.x1")
    # Distant : titre différent du local ("La mujer desnuda").
    _FakeReadClient.metas_distantes = [{"propertyUri": f"{_NKL}title", "value": "Ancien"}]
    r = runner.invoke(app, [
        "nakala", "pousser", "AS-001", "--fonds", "AS",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output and "nkl:title" in r.output
    assert _FakeWriteClient.instances[0].puts == []  # rien poussé


def test_pousser_reel_applique_put(config_nakala: Path, db_avec_item: Path) -> None:
    _poser_doi(db_avec_item, "AS-001", "10.34847/nkl.x1")
    _FakeReadClient.metas_distantes = [{"propertyUri": f"{_NKL}title", "value": "Ancien"}]
    r = runner.invoke(app, [
        "nakala", "pousser", "AS-001", "--fonds", "AS", "--no-dry-run",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 0, r.output
    assert "poussées" in r.output
    puts = _FakeWriteClient.instances[0].puts
    assert len(puts) == 1 and puts[0]["id"] == "10.34847/nkl.x1"


def test_publier_dry_run(config_nakala: Path, db_avec_item: Path) -> None:
    _poser_doi(db_avec_item, "AS-001", "10.34847/nkl.x1")
    r = runner.invoke(app, [
        "nakala", "publier", "AS-001", "--fonds", "AS",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output and "IRRÉVERSIBLE" in r.output
    assert _FakeWriteClient.instances[0].puts == []


def test_publier_reel(config_nakala: Path, db_avec_item: Path) -> None:
    _poser_doi(db_avec_item, "AS-001", "10.34847/nkl.x1")
    r = runner.invoke(app, [
        "nakala", "publier", "AS-001", "--fonds", "AS", "--no-dry-run",
        "--config", str(config_nakala), "--db-path", str(db_avec_item),
    ])
    assert r.exit_code == 0, r.output
    assert "publié" in r.output
    puts = _FakeWriteClient.instances[0].puts
    assert puts[0]["status"] == "published"
