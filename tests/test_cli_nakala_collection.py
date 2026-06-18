"""Tests de la CLI `nakala rapatrier-collection` (Lot 2, T2.2) — client mocké."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

import archives_tool.cli as cli_mod
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fonds, Item

runner = CliRunner()

_DOI_COL = "10.34847/nkl.collec01"
_NKL = "http://nakala.fr/terms#"


def _donnee(suffixe: str) -> dict:
    return {
        "identifier": f"10.34847/nkl.{suffixe}",
        "uri": f"https://nakala.fr/{suffixe}",
        "status": "published",
        "version": 1,
        "metas": [{"propertyUri": f"{_NKL}title", "value": f"Donnée {suffixe}"}],
        "files": [],
    }


class _FakeClient:
    base_url = "https://apitest.nakala.fr"

    def __init__(self, *a, **k) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *a) -> bool:
        return False

    def lire_collection(self, doi: str) -> dict:
        return {
            "identifier": doi,
            "metas": [{"propertyUri": f"{_NKL}title", "value": "Col"}],
        }

    def lister_depots_collection(
        self, doi: str, *, page: int = 1, taille: int = 50
    ) -> dict:
        data = [_donnee("aaa1"), _donnee("bbb2")] if page == 1 else []
        return {"data": data, "currentPage": page, "lastPage": 1}


@pytest.fixture(autouse=True)
def _mock_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "ClientLectureNakala", _FakeClient)


@pytest.fixture
def config_nakala(tmp_path: Path) -> Path:
    cfg = tmp_path / "config_local.yaml"
    cfg.write_text(
        "utilisateur: T\nnakala:\n  base_url: https://apitest.nakala.fr\n  api_key: k\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def db_vide(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def test_dry_run_par_defaut_n_ecrit_rien(config_nakala: Path, db_vide: Path) -> None:
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier-collection",
            _DOI_COL,
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output and "2 créé(s)" in r.output
    with _session(db_vide) as s:
        assert s.scalar(select(func.count(Item.id))) == 0
        assert s.scalar(select(func.count(Fonds.id))) == 0


def test_reel_cree_fonds_et_items(config_nakala: Path, db_vide: Path) -> None:
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier-collection",
            _DOI_COL,
            "--no-dry-run",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "RÉEL" in r.output and "2 créé(s)" in r.output
    with _session(db_vide) as s:
        assert s.scalar(select(func.count(Item.id))) == 2
        assert s.scalar(select(func.count(Fonds.id))) == 1


def test_fonds_inexistant_exit1(config_nakala: Path, db_vide: Path) -> None:
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier-collection",
            _DOI_COL,
            "--fonds",
            "ABSENT",
            "--no-dry-run",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 1
    assert "introuvable" in r.output.lower()


def test_sans_config_nakala_exit2(tmp_path: Path, db_vide: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("utilisateur: x\n", encoding="utf-8")
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier-collection",
            _DOI_COL,
            "--config",
            str(cfg),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 2


# ---------------------------------------------------------------------------
# rafraichir-collection (T2.3)
# ---------------------------------------------------------------------------


def test_rafraichir_collection_donnees_non_liees(
    config_nakala: Path, db_vide: Path
) -> None:
    """Base sans items liés → tout est « non lié », pas d'erreur."""
    r = runner.invoke(
        app,
        [
            "nakala",
            "rafraichir-collection",
            _DOI_COL,
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output and "2 non lié(s)" in r.output


def test_rafraichir_collection_applique_overwrite(
    config_nakala: Path, db_vide: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1) rapatrier → 2 items liés (titres "Donnée aaa1"/"Donnée bbb2").
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier-collection",
            _DOI_COL,
            "--no-dry-run",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 0, r.output

    # 2) la collection renvoie désormais un titre modifié pour aaa1.
    class _FakeClientModifie(_FakeClient):
        def lister_depots_collection(self, doi, *, page=1, taille=50):
            d1 = _donnee("aaa1")
            d1["metas"] = [{"propertyUri": f"{_NKL}title", "value": "Titre RÉVISÉ"}]
            data = [d1, _donnee("bbb2")] if page == 1 else []
            return {"data": data, "currentPage": page, "lastPage": 1}

    monkeypatch.setattr(cli_mod, "ClientLectureNakala", _FakeClientModifie)
    r = runner.invoke(
        app,
        [
            "nakala",
            "rafraichir-collection",
            _DOI_COL,
            "--no-dry-run",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "1 modifié(s)" in r.output
    with _session(db_vide) as s:
        item = s.scalar(select(Item).where(Item.doi_nakala == "10.34847/nkl.aaa1"))
        assert item.titre == "Titre RÉVISÉ"


# ---------------------------------------------------------------------------
# Passe 20 — Dette AD : --format json sur commandes collection
# ---------------------------------------------------------------------------


def test_rapatrier_collection_format_json(
    config_nakala: Path,
    db_vide: Path,
) -> None:
    """`rapatrier-collection --format json` : structure complete."""
    import json

    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier-collection",
            _DOI_COL,
            "--format",
            "json",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["doi_collection"] == _DOI_COL
    assert data["dry_run"] is True
    # En dry-run, fonds n'est pas reellement cree (seulement projete)
    assert data["fonds_cree"] is False
    assert isinstance(data["crees"], list)
    assert len(data["crees"]) == 2
    assert data["deja_existants"] == []
    assert data["erreurs"] == []


def test_rafraichir_collection_format_json(
    config_nakala: Path,
    db_vide: Path,
) -> None:
    """`rafraichir-collection --format json` : structure complete avec
    diffs imbriques."""
    import json

    # Setup : créer un item lié au DOI pour qu'il y ait un rapport
    with _session(db_vide) as s:
        from archives_tool.api.services.fonds import (
            FormulaireFonds,
            creer_fonds,
        )
        from archives_tool.api.services.items import (
            FormulaireItem,
            creer_item,
        )

        f = creer_fonds(s, FormulaireFonds(cote="X", titre="X"))
        item = creer_item(
            s,
            FormulaireItem(
                cote="X-aaa1",
                titre="Ancien",
                fonds_id=f.id,
            ),
        )
        item.doi_nakala = "10.34847/nkl.aaa1"
        s.commit()

    r = runner.invoke(
        app,
        [
            "nakala",
            "rafraichir-collection",
            _DOI_COL,
            "--format",
            "json",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_vide),
        ],
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["doi_collection"] == _DOI_COL
    assert data["dry_run"] is True
    # Au moins 1 item modifie (titre)
    assert isinstance(data["modifies"], list)
    assert "inchanges" in data
    assert "non_lies" in data
    assert "erreurs" in data
