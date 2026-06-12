"""Tests de l'UI web de push Nakala (U5) — clients lecture+écriture mockés.

Pendant écriture du Lot 3 (pull) : aperçu dry-run en GET (lecture seule OK)
→ confirmation POST (bloquée 423 en lecture seule par le middleware). On
monkeypatche `nakala_web.ClientLectureNakala` **et** `NakalaEcritureClient`
par un faux client combiné dont les métas distantes sont configurables.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from sqlalchemy import select

import archives_tool.api.routes.nakala_web as nakala_web
from archives_tool.api.main import app
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.db import (
    assurer_tables_fts,
    creer_engine,
    creer_session_factory,
)
from archives_tool.models import Base, Collection

_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"
_DOI_ITEM = "10.34847/nkl.x1"
_DOI_COL = "10.34847/nkl.col1"


def _nkl_title(v: str, lang: str | None = None) -> dict:
    m: dict = {"propertyUri": f"{_NKL}title", "value": v}
    if lang:
        m["lang"] = lang
    return m


def _faire_fake_rw(metas_distantes: list[dict] | None = None,
                   metas_collection: list[dict] | None = None):
    """Fabrique une classe de faux client lecture+écriture, état par-classe
    (les routes instancient lecture et écriture séparément → état partagé)."""

    class _FakeRW:
        base_url = "https://apitest.nakala.fr"
        _metas = list(metas_distantes if metas_distantes is not None else [])
        _metas_col = list(metas_collection if metas_collection is not None else [])
        puts: list[dict] = []
        puts_collection: list[dict] = []

        def __init__(self, *a, **k) -> None:
            pass

        def lire_depot(self, doi: str) -> dict:
            return {"identifier": doi, "metas": list(type(self)._metas),
                    "modDate": "2024-01-01", "files": [], "status": "pending"}

        def modifier_depot(self, identifiant, *, metas, status=None):
            type(self).puts.append({"doi": identifiant, "metas": metas,
                                    "status": status})
            type(self)._metas = metas
            return {}

        def lire_collection(self, doi: str) -> dict:
            return {"identifier": doi, "metas": list(type(self)._metas_col),
                    "status": "private"}

        def modifier_collection(self, identifiant, *, metas, status=None):
            type(self).puts_collection.append({"doi": identifiant, "metas": metas,
                                               "status": status})
            type(self)._metas_col = metas
            return {}

        def fermer(self) -> None:
            pass

    return _FakeRW


def _amorcer_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    assurer_tables_fts(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _seed_item(
    db: Path, *, doi: str | None = _DOI_ITEM, doi_collection: str | None = None
) -> None:
    """Fonds AS + miroir AS + item AS-001 (avec doi_nakala par défaut)."""
    with _session(db) as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="Armonía Somers"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="Titre local", fonds_id=f.id, date="1984",
            langue="spa", description="Roman",
            type_coar="http://purl.org/coar/resource_type/c_2f33",
            metadonnees={"createurs": ["Somers, Armonía"], "sujets": ["Literatura"]},
        ))
        item.doi_nakala = doi
        if doi_collection:
            miroir = s.scalar(
                select(Collection).where(
                    Collection.cote == "AS",
                    Collection.type_collection == "miroir",
                )
            )
            miroir.doi_nakala = doi_collection
        s.commit()


def _ecrire_config(
    chemin: Path, *, avec_api_key: bool = True, lecture_seule: bool = False
) -> None:
    data: dict = {"utilisateur": "testpush", "lecture_seule": lecture_seule}
    nak: dict = {"base_url": "https://apitest.nakala.fr"}
    if avec_api_key:
        nak["api_key"] = "01234567-89ab-cdef-0123-456789abcdef"
    data["nakala"] = nak
    chemin.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _faire_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
    fake_cls, avec_api_key: bool = True, lecture_seule: bool = False,
    doi_item: str | None = _DOI_ITEM, doi_collection: str | None = None,
) -> TestClient:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_api_key=avec_api_key, lecture_seule=lecture_seule)
    db = _amorcer_db(tmp_path)
    _seed_item(db, doi=doi_item, doi_collection=doi_collection)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    monkeypatch.setattr(nakala_web, "ClientLectureNakala", fake_cls)
    monkeypatch.setattr(nakala_web, "NakalaEcritureClient", fake_cls)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Item — pousser
# ---------------------------------------------------------------------------


def test_apercu_pousser_item_montre_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([_nkl_title("Titre distant", lang="spa")])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.get("/nakala/pousser", params={"cote": "AS-001", "fonds": "AS"})
    assert r.status_code == 200
    assert "Pousser les métadonnées vers Nakala" in r.text
    assert "Titre distant" in r.text and "Titre local" in r.text


def test_executer_pousser_item_appelle_put(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([_nkl_title("Titre distant", lang="spa")])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.post("/nakala/pousser", data={"cote": "AS-001", "fonds": "AS"},
                follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/item/AS-001?fonds=AS&nakala_pousse=")
    assert fake.puts and fake.puts[0]["doi"] == _DOI_ITEM


def test_pousser_item_sans_doi_redirige_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake, doi_item=None)
    r = tc.get("/nakala/pousser", params={"cote": "AS-001", "fonds": "AS"},
               follow_redirects=False)
    assert r.status_code == 303
    assert "/item/AS-001?fonds=AS&nakala_erreur=" in r.headers["location"]


def test_post_pousser_bloque_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([_nkl_title("Titre distant")])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake, lecture_seule=True)
    r = tc.post("/nakala/pousser", data={"cote": "AS-001", "fonds": "AS"},
                follow_redirects=False)
    assert r.status_code == 423


def test_pousser_sans_api_key_redirige(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake, avec_api_key=False)
    r = tc.get("/nakala/pousser", params={"cote": "AS-001", "fonds": "AS"},
               follow_redirects=False)
    assert r.status_code == 303
    assert "nakala_erreur=" in r.headers["location"]


def test_sans_api_key_ne_construit_aucun_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Régression fuite : sans api_key, on redirige AVANT d'instancier un
    client (les __init__ ouvrent un httpx.Client → en construire un puis
    l'abandonner sur l'early-return fuirait la connexion)."""
    fake = _faire_fake_rw([])
    fake.instances = 0
    base_init = fake.__init__

    def _compteur(self, *a, **k):  # noqa: ANN001
        type(self).instances += 1
        base_init(self, *a, **k)

    fake.__init__ = _compteur
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake, avec_api_key=False)
    for chemin, params in [
        ("/nakala/pousser", {"cote": "AS-001", "fonds": "AS"}),
        ("/nakala/publier", {"cote": "AS-001", "fonds": "AS"}),
        ("/nakala/pousser-collection", {"cote": "AS", "fonds": "AS"}),
        ("/nakala/publier-collection", {"cote": "AS", "fonds": "AS"}),
    ]:
        r = tc.get(chemin, params=params, follow_redirects=False)
        assert r.status_code == 303
    assert fake.instances == 0


# ---------------------------------------------------------------------------
# Item — publier (irréversible)
# ---------------------------------------------------------------------------


def test_apercu_publier_item_avertit_irreversible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.get("/nakala/publier", params={"cote": "AS-001", "fonds": "AS"})
    assert r.status_code == 200
    assert "irréversible" in r.text.lower()
    assert "Publier définitivement" in r.text


def test_executer_publier_item_put_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.post("/nakala/publier", data={"cote": "AS-001", "fonds": "AS"},
                follow_redirects=False)
    assert r.status_code == 303
    assert "nakala_publie=1" in r.headers["location"]
    assert fake.puts and fake.puts[0]["status"] == "published"


def test_publier_item_sans_doi_redirige(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake, doi_item=None)
    r = tc.get("/nakala/publier", params={"cote": "AS-001", "fonds": "AS"},
               follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/item/AS-001?fonds=AS&nakala_erreur=")


# ---------------------------------------------------------------------------
# Collection — pousser & publier
# ---------------------------------------------------------------------------


def test_apercu_pousser_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([_nkl_title("Titre distant", lang="spa")])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.get("/nakala/pousser-collection", params={"cote": "AS", "fonds": "AS"})
    assert r.status_code == 200
    assert "Pousser la collection vers Nakala" in r.text
    assert "item(s) à pousser" in r.text


def test_executer_pousser_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([_nkl_title("Titre distant", lang="spa")])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.post("/nakala/pousser-collection", data={"cote": "AS", "fonds": "AS"},
                follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/fonds/AS?nakala_pousse_items=")
    assert fake.puts  # au moins l'item AS-001 poussé


def test_apercu_publier_collection_irreversible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.get("/nakala/publier-collection", params={"cote": "AS", "fonds": "AS"})
    assert r.status_code == 200
    assert "irréversible" in r.text.lower()
    assert "item(s) à publier" in r.text


def test_executer_publier_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.post("/nakala/publier-collection", data={"cote": "AS", "fonds": "AS"},
                follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/fonds/AS?nakala_publie_items=")
    assert fake.puts and fake.puts[0]["status"] == "published"


def test_post_publier_collection_bloque_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake, lecture_seule=True)
    r = tc.post("/nakala/publier-collection", data={"cote": "AS", "fonds": "AS"},
                follow_redirects=False)
    assert r.status_code == 423


def test_pousser_collection_pousse_entite_si_doi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # La miroir a un doi_nakala + un titre distant différent → meta_collection.
    fake = _faire_fake_rw(
        [_nkl_title("Titre distant", lang="spa")],
        metas_collection=[_nkl_title("Ancien titre collection")],
    )
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake,
                       doi_collection=_DOI_COL)
    r = tc.post("/nakala/pousser-collection", data={"cote": "AS", "fonds": "AS"},
                follow_redirects=False)
    assert r.status_code == 303
    assert fake.puts_collection and fake.puts_collection[0]["doi"] == _DOI_COL


# ---------------------------------------------------------------------------
# Aperçu accessible en lecture seule mais confirmation masquée
# ---------------------------------------------------------------------------


def test_apercu_pousser_confirmation_cachee_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([_nkl_title("Titre distant")])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake, lecture_seule=True)
    r = tc.get("/nakala/pousser", params={"cote": "AS-001", "fonds": "AS"})
    assert r.status_code == 200
    assert "Push désactivé (mode lecture seule)" in r.text
    assert 'action="/nakala/pousser"' not in r.text


# ---------------------------------------------------------------------------
# Points d'entrée (boutons) sur fiche item & page fonds
# ---------------------------------------------------------------------------


def test_boutons_nakala_sur_fiche_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake)
    r = tc.get("/item/AS-001", params={"fonds": "AS"})
    assert r.status_code == 200
    assert "/nakala/pousser?cote=AS-001&fonds=AS" in r.text
    assert "/nakala/publier?cote=AS-001&fonds=AS" in r.text


def test_pas_de_boutons_si_item_sans_doi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake, doi_item=None)
    r = tc.get("/item/AS-001", params={"fonds": "AS"})
    assert r.status_code == 200
    assert "/nakala/pousser?cote=AS-001" not in r.text


def test_boutons_collection_sur_fonds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _faire_fake_rw([])
    tc = _faire_client(tmp_path, monkeypatch, fake_cls=fake,
                       doi_collection=_DOI_COL)
    r = tc.get("/fonds/AS")
    assert r.status_code == 200
    assert "/nakala/pousser-collection?cote=AS&fonds=AS" in r.text
    assert "/nakala/publier-collection?cote=AS&fonds=AS" in r.text
