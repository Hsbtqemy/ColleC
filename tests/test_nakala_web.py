"""Tests de l'UI web Nakala (Lot 3) — client Nakala mocké, DB amorcée."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import archives_tool.api.routes.nakala_web as nakala_web
from archives_tool.api.main import app
from archives_tool.db import assurer_tables_fts, creer_engine, creer_session_factory
from archives_tool.models import Base, Fonds, Item

_DOI_COL = "10.34847/nkl.col1"
_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"


def _donnee(suffixe: str, titre: str) -> dict:
    return {
        "identifier": f"10.34847/nkl.{suffixe}",
        "uri": f"https://nakala.fr/{suffixe}",
        "status": "published",
        "version": 1,
        "metas": [
            {"propertyUri": f"{_NKL}title", "value": titre},
            {"propertyUri": f"{_DCT}subject", "value": "Sujet"},
        ],
        "files": [{"name": f"{suffixe}.jpg", "sha1": f"{suffixe}sha", "size": "10",
                   "extension": "jpg", "mime_type": "image/jpeg"}],
    }


class _FakeClient:
    base_url = "https://apitest.nakala.fr"

    def __init__(self, *a, **k) -> None:
        pass

    def lire_collection(self, doi: str) -> dict:
        return {"identifier": doi, "metas": [{"propertyUri": f"{_NKL}title",
                                              "value": "Collection Test"}]}

    def lister_depots_collection(self, doi: str, *, page: int = 1, taille: int = 50) -> dict:
        data = [_donnee("aaa1", "Titre A"), _donnee("bbb2", "Titre B")] if page == 1 else []
        return {"data": data, "currentPage": page, "lastPage": 1}

    def fermer(self) -> None:
        pass


def _amorcer_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    assurer_tables_fts(engine)
    engine.dispose()
    return db


def _ecrire_config(chemin: Path, *, avec_nakala: bool, lecture_seule: bool = False) -> None:
    data: dict = {"utilisateur": "testweb", "lecture_seule": lecture_seule}
    if avec_nakala:
        data["nakala"] = {"base_url": "https://apitest.nakala.fr"}
    chemin.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_nakala=True)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _FakeClient)
    return TestClient(app)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    # Le chemin réel est dérivé de ARCHIVES_DB ; ce helper relit la même base.
    return tmp_path / "test.db"


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


# ---------------------------------------------------------------------------
# Page d'accueil
# ---------------------------------------------------------------------------


def test_page_nakala_rendue(client: TestClient) -> None:
    r = client.get("/nakala")
    assert r.status_code == 200
    assert "Exporter un tableur" in r.text
    assert "Rapatrier en base" in r.text


def test_page_nakala_non_configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_nakala=False)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _FakeClient)
    r = TestClient(app).get("/nakala")
    assert r.status_code == 200
    assert "n'est pas configuré" in r.text


# ---------------------------------------------------------------------------
# Export tableur (download)
# ---------------------------------------------------------------------------


def test_export_csv_telechargement(client: TestClient) -> None:
    r = client.get("/nakala/tableur", params={"doi": _DOI_COL, "format": "csv"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].endswith('_donnee.csv"')
    # BOM utf-8-sig + entête.
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert "nkl:title" in r.text


def test_export_xlsx_telechargement(client: TestClient) -> None:
    r = client.get("/nakala/tableur", params={"doi": _DOI_COL, "format": "xlsx",
                                              "granularite": "fichier"})
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert len(r.content) > 0


def test_export_url_acceptee(client: TestClient) -> None:
    r = client.get("/nakala/tableur",
                   params={"doi": f"https://nakala.fr/collection/{_DOI_COL}"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]


def test_export_sans_nakala_redirige(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_nakala=False)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _FakeClient)
    r = TestClient(app).get("/nakala/tableur", params={"doi": _DOI_COL},
                            follow_redirects=False)
    assert r.status_code == 303
    assert "/nakala?erreur=" in r.headers["location"]


# ---------------------------------------------------------------------------
# Rapatrier
# ---------------------------------------------------------------------------


def test_apercu_rapatrier(client: TestClient) -> None:
    r = client.get("/nakala/rapatrier", params={"doi": _DOI_COL})
    assert r.status_code == 200
    assert "Aperçu du rapatriement" in r.text
    assert "item(s) à créer" in r.text


def test_executer_rapatrier_cree_fonds_items(client: TestClient, db_path: Path) -> None:
    r = client.post("/nakala/rapatrier", data={"doi": _DOI_COL, "fonds": ""},
                    follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/fonds/col1") and "nakala_crees=2" in loc
    with _session(db_path) as s:
        assert s.scalar(select(func.count(Item.id))) == 2
        assert s.scalar(select(func.count(Fonds.id))) == 1


def test_post_rapatrier_bloque_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_nakala=True, lecture_seule=True)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _FakeClient)
    r = TestClient(app).post("/nakala/rapatrier", data={"doi": _DOI_COL},
                             follow_redirects=False)
    assert r.status_code == 423


# ---------------------------------------------------------------------------
# Rafraîchir + bouton fonds
# ---------------------------------------------------------------------------


def test_apercu_rafraichir_apres_pull(client: TestClient) -> None:
    # Rapatrier d'abord (POST), puis aperçu rafraîchir → 2 inchangés.
    client.post("/nakala/rapatrier", data={"doi": _DOI_COL, "fonds": ""})
    r = client.get("/nakala/rafraichir", params={"doi": _DOI_COL})
    assert r.status_code == 200
    assert "Aperçu du rafraîchissement" in r.text
    assert "inchangé(s)" in r.text


def test_bouton_rafraichir_sur_fonds(client: TestClient) -> None:
    client.post("/nakala/rapatrier", data={"doi": _DOI_COL, "fonds": ""})
    r = client.get("/fonds/col1")
    assert r.status_code == 200
    assert "Rafraîchir depuis Nakala" in r.text
    assert f"/nakala/rafraichir?doi={_DOI_COL}" in r.text


def test_executer_rafraichir_applique_overwrite(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1) rapatrier (titres d'origine).
    client.post("/nakala/rapatrier", data={"doi": _DOI_COL, "fonds": ""})

    # 2) la collection renvoie un titre modifié pour aaa1.
    class _ClientModifie(_FakeClient):
        def lister_depots_collection(self, doi, *, page=1, taille=50):
            d1 = _donnee("aaa1", "Titre A RÉVISÉ")
            data = [d1, _donnee("bbb2", "Titre B")] if page == 1 else []
            return {"data": data, "currentPage": page, "lastPage": 1}

    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _ClientModifie)
    r = client.post("/nakala/rafraichir", data={"doi": _DOI_COL},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "nakala_modifies=1" in r.headers["location"]
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.doi_nakala == "10.34847/nkl.aaa1"))
        assert item.titre == "Titre A RÉVISÉ"


def test_apercu_rapatrier_cache_confirmation_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_nakala=True, lecture_seule=True)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _FakeClient)
    # L'aperçu (GET) reste accessible en lecture seule…
    r = TestClient(app).get("/nakala/rapatrier", params={"doi": _DOI_COL})
    assert r.status_code == 200
    # …mais le bouton de confirmation (POST) est masqué.
    assert "Confirmer le rapatriement" not in r.text
    assert "lecture seule" in r.text


def test_export_erreur_nakala_redirige(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from archives_tool.external.nakala.client import NakalaIntrouvable

    class _Client404(_FakeClient):
        def lire_collection(self, doi):
            raise NakalaIntrouvable(doi)

    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _Client404)
    r = client.get("/nakala/tableur", params={"doi": _DOI_COL},
                   follow_redirects=False)
    assert r.status_code == 303
    assert "/nakala?erreur=" in r.headers["location"]
    assert "introuvable" in r.headers["location"]
