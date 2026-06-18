"""Tests de la CLI `nakala exporter-tableur` (Lot 1, T1.4) — client mocké."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from typer.testing import CliRunner

import archives_tool.cli as cli_mod
from archives_tool.cli import app

runner = CliRunner()

_DOI = "10.34847/nkl.collec01"
_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"

_COLLECTION_META = {
    "identifier": _DOI,
    "status": "public",
    "metas": [{"propertyUri": f"{_NKL}title", "value": "Ma collection test"}],
}

_DONNEES = [
    {
        "identifier": "10.34847/nkl.d1",
        "uri": "https://nakala.fr/d1",
        "status": "published",
        "version": 1,
        "metas": [
            {"propertyUri": f"{_NKL}title", "value": "Donnée 1"},
            {"propertyUri": f"{_DCT}subject", "value": "A"},
            {"propertyUri": f"{_DCT}subject", "value": "B"},
        ],
        "files": [
            {"name": "p1.jpg", "sha1": "aaa", "mime_type": "image/jpeg", "size": "10"},
            {"name": "p2.jpg", "sha1": "bbb", "mime_type": "image/jpeg", "size": "20"},
        ],
    },
    {
        "identifier": "10.34847/nkl.d2",
        "uri": "https://nakala.fr/d2",
        "status": "published",
        "version": 1,
        "metas": [{"propertyUri": f"{_NKL}title", "value": "Donnée 2"}],
        "files": [
            {"name": "q1.jpg", "sha1": "ccc", "mime_type": "image/jpeg", "size": "30"}
        ],
    },
]


class _FakeClient:
    def __init__(self, *a, **k) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *a) -> bool:
        return False

    def lire_collection(self, doi: str) -> dict:
        return _COLLECTION_META

    def lister_depots_collection(
        self, doi: str, *, page: int = 1, taille: int = 50
    ) -> dict:
        return {
            "data": _DONNEES if page == 1 else [],
            "currentPage": page,
            "lastPage": 1,
        }


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


def test_export_csv_niveau_donnee(config_nakala: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "out.csv"
    r = runner.invoke(
        app,
        [
            "nakala",
            "exporter-tableur",
            _DOI,
            "--config",
            str(config_nakala),
            "--sortie",
            str(sortie),
        ],
    )
    assert r.exit_code == 0, r.output
    assert sortie.exists()
    with open(sortie, encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.DictReader(f, delimiter=";"))
    assert len(lignes) == 2  # 1 ligne par donnée
    assert lignes[0]["nkl:title"] == "Donnée 1"
    assert lignes[0]["dcterms:subject"] == "A | B"


def test_export_csv_niveau_fichier_plus_de_lignes(
    config_nakala: Path, tmp_path: Path
) -> None:
    sortie = tmp_path / "out.csv"
    r = runner.invoke(
        app,
        [
            "nakala",
            "exporter-tableur",
            _DOI,
            "--granularite",
            "fichier",
            "--config",
            str(config_nakala),
            "--sortie",
            str(sortie),
        ],
    )
    assert r.exit_code == 0, r.output
    with open(sortie, encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.DictReader(f, delimiter=";"))
    assert len(lignes) == 3  # 2 fichiers (d1) + 1 fichier (d2)
    assert lignes[0]["fichier_nom"] == "p1.jpg"
    assert lignes[0]["nkl:title"] == "Donnée 1"  # métadonnée donnée recopiée


def test_export_xlsx(config_nakala: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "out.xlsx"
    r = runner.invoke(
        app,
        [
            "nakala",
            "exporter-tableur",
            _DOI,
            "--format",
            "xlsx",
            "--config",
            str(config_nakala),
            "--sortie",
            str(sortie),
        ],
    )
    assert r.exit_code == 0, r.output
    assert sortie.exists() and sortie.stat().st_size > 0


def test_sep_configurable(config_nakala: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "out.csv"
    r = runner.invoke(
        app,
        [
            "nakala",
            "exporter-tableur",
            _DOI,
            "--sep",
            ",",
            "--config",
            str(config_nakala),
            "--sortie",
            str(sortie),
        ],
    )
    assert r.exit_code == 0, r.output
    premiere = sortie.read_text(encoding="utf-8-sig").splitlines()[0]
    assert premiere.startswith("identifier,uri,status")


def test_sans_config_nakala_exit2(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("utilisateur: x\n", encoding="utf-8")
    r = runner.invoke(app, ["nakala", "exporter-tableur", _DOI, "--config", str(cfg)])
    assert r.exit_code == 2
    assert "nakala" in r.output.lower()


def test_url_collection_normalisee_en_doi(
    config_nakala: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passer l'URL de collection → le client reçoit le DOI nu (câblage)."""
    vus: dict[str, str] = {}

    class _ClientRecord(_FakeClient):
        def lire_collection(self, doi: str) -> dict:
            vus["doi"] = doi
            return _COLLECTION_META

        def lister_depots_collection(
            self, doi: str, *, page: int = 1, taille: int = 50
        ) -> dict:
            vus["doi_listing"] = doi
            return super().lister_depots_collection(doi, page=page, taille=taille)

    monkeypatch.setattr(cli_mod, "ClientLectureNakala", _ClientRecord)
    sortie = tmp_path / "out.csv"
    r = runner.invoke(
        app,
        [
            "nakala",
            "exporter-tableur",
            f"https://nakala.fr/collection/{_DOI}",
            "--config",
            str(config_nakala),
            "--sortie",
            str(sortie),
        ],
    )
    assert r.exit_code == 0, r.output
    assert vus["doi"] == _DOI and vus["doi_listing"] == _DOI


def test_collection_introuvable_exit1(
    config_nakala: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from archives_tool.external.nakala.client import NakalaIntrouvable

    class _Client404(_FakeClient):
        def lire_collection(self, doi: str) -> dict:
            raise NakalaIntrouvable(doi)

    monkeypatch.setattr(cli_mod, "ClientLectureNakala", _Client404)
    r = runner.invoke(
        app, ["nakala", "exporter-tableur", _DOI, "--config", str(config_nakala)]
    )
    assert r.exit_code == 1
    assert "introuvable" in r.output.lower()
