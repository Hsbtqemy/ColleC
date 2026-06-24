"""Tests du diagnostic web « comparer fichiers » (fiche item, lecture seule).

Le service `comparer_fichiers_item` est testé ailleurs (`test_nakala_fichiers`).
Ici on couvre la ROUTE + le FRAGMENT : garde DOI / config, rendu des catégories,
erreur réseau → message (jamais 500), et présence du bouton sur la fiche.
Client Nakala mocké (jamais de réseau réel).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import archives_tool.api.routes.nakala_web as nakala_web
from archives_tool.api.main import app
from archives_tool.db import assurer_tables_fts, creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.external.nakala.client import NakalaInjoignable
from archives_tool.models import Base, Fonds, Item


class _FakeClient:
    """Client lecture Nakala mocké. `FILES`/`STATUS` surchargés par sous-classe."""

    base_url = "https://apitest.nakala.fr"
    FILES: list[dict] = []
    STATUS = "pending"

    def __init__(self, *a, **k) -> None:
        pass

    def lire_depot(self, doi: str) -> dict:
        return {
            "status": self.STATUS,
            "files": list(self.FILES),
            "modDate": "2026-01-01",
        }

    def fermer(self) -> None:
        pass


def _amorcer(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    assurer_tables_fts(engine)
    engine.dispose()
    return db


def _inserer_items(db_path: Path) -> None:
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        f = Fonds(cote="HK", titre="Hara-Kiri")
        s.add(f)
        s.flush()
        s.add(
            Item(
                fonds_id=f.id,
                cote="HK-AVEC",
                titre="Avec DOI",
                etat_catalogage="brouillon",
                doi_nakala="10.34847/nkl.test",
            )
        )
        s.add(
            Item(
                fonds_id=f.id,
                cote="HK-SANS",
                titre="Sans DOI",
                etat_catalogage="brouillon",
            )
        )
        s.commit()
    engine.dispose()


def _ecrire_config(chemin: Path, *, avec_nakala: bool) -> None:
    data: dict = {"utilisateur": "testweb", "racines": {}}
    if avec_nakala:
        data["nakala"] = {"base_url": "https://apitest.nakala.fr"}
    chemin.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = _amorcer(tmp_path)
    _inserer_items(db)
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_nakala=True)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _FakeClient)
    return TestClient(app)


_URL = "/nakala/item/HK-AVEC/comparer-fichiers?fonds=HK"


def test_item_sans_doi_message(client: TestClient) -> None:
    resp = client.get("/nakala/item/HK-SANS/comparer-fichiers?fonds=HK")
    assert resp.status_code == 200
    assert "pas de DOI Nakala" in resp.text


def test_item_inconnu_404(client: TestClient) -> None:
    resp = client.get("/nakala/item/HK-XXX/comparer-fichiers?fonds=HK")
    assert resp.status_code == 404


def test_aucun_changement_depot_vide(client: TestClient) -> None:
    """Item sans fichiers + dépôt vide → synchronisé (no-op)."""
    resp = client.get(_URL)
    assert resp.status_code == 200
    assert "synchronisés avec Nakala" in resp.text


def test_orphelin_distant_signale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fichier distant sans pendant local → orphelin (serait retiré)."""

    class _AvecOrphelin(_FakeClient):
        FILES = [{"name": "page01.jpg", "sha1": "a" * 40, "size": "10"}]

    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _AvecOrphelin)
    resp = client.get(_URL)
    assert resp.status_code == 200
    assert "Distants sans local" in resp.text
    assert "page01.jpg" in resp.text


def test_statut_publie_avertit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Publie(_FakeClient):
        STATUS = "published"

    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _Publie)
    resp = client.get(_URL)
    assert resp.status_code == 200
    assert "publié" in resp.text


def test_erreur_reseau_message_pas_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Injoignable(_FakeClient):
        def lire_depot(self, doi: str) -> dict:
            raise NakalaInjoignable("timeout")

    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _Injoignable)
    resp = client.get(_URL)
    assert resp.status_code == 200  # best-effort, pas de 500
    assert "injoignable" in resp.text.lower()


def test_corps_non_json_message_pas_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`lire_depot` ne garde pas `.json()` : un corps 200 non-JSON
    (JSONDecodeError ⊂ ValueError) doit donner un message, pas une 500."""
    import json

    class _CorpsCasse(_FakeClient):
        def lire_depot(self, doi: str) -> dict:
            raise json.JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr(nakala_web, "ClientLectureNakala", _CorpsCasse)
    resp = client.get(_URL)
    assert resp.status_code == 200
    assert "illisible" in resp.text


def test_nakala_non_configure_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Config sans section `nakala:` → message, pas de crash."""
    db = _amorcer(tmp_path)
    _inserer_items(db)
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_nakala=False)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    resp = TestClient(app).get(_URL)
    assert resp.status_code == 200
    assert "pas configuré" in resp.text


# ---------------------------------------------------------------------------
# Bouton sur la fiche item (présent si DOI, absent sinon)
# ---------------------------------------------------------------------------


@pytest.fixture
def client_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "demo.db"
    peupler_base(db)
    # Pose un DOI sur HK-001 pour exposer le bloc Nakala de la fiche.
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        from sqlalchemy import select

        it = s.scalar(select(Item).where(Item.cote == "HK-001"))
        it.doi_nakala = "10.34847/nkl.demo1"
        s.commit()
    engine.dispose()
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return TestClient(app)


def test_bouton_present_si_doi(client_demo: TestClient) -> None:
    resp = client_demo.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    assert "Comparer avec Nakala" in resp.text
    assert "comparer-fichiers" in resp.text


def test_bouton_absent_si_pas_de_doi(client_demo: TestClient) -> None:
    """HK-002 n'a pas de DOI → pas de bloc Nakala sur sa fiche."""
    resp = client_demo.get("/item/HK-002?fonds=HK")
    assert resp.status_code == 200
    assert "Comparer avec Nakala" not in resp.text
