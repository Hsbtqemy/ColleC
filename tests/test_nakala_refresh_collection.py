"""Tests du service `rafraichir_collection` (T2.3) — client mocké."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from archives_tool.api.services.nakala import (
    rafraichir_collection,
    rapatrier_collection,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Item

_DOI_COL = "10.34847/nkl.collec01"
_NKL = "http://nakala.fr/terms#"


def _donnee(suffixe: str, titre: str) -> dict:
    return {
        "identifier": f"10.34847/nkl.{suffixe}",
        "uri": f"https://nakala.fr/{suffixe}",
        "status": "published",
        "version": 1,
        "metas": [
            {"propertyUri": f"{_NKL}title", "value": titre},
            {"propertyUri": f"{_NKL}created", "value": "1984"},
        ],
        "files": [{"name": f"{suffixe}.jpg", "sha1": f"{suffixe}sha", "size": 1,
                   "mime_type": "image/jpeg"}],
    }


class _FakeClient:
    base_url = "https://apitest.nakala.fr"

    def __init__(self, donnees: list[dict]) -> None:
        self._donnees = donnees

    def lire_collection(self, doi: str) -> dict:
        return {"identifier": doi, "metas": [{"propertyUri": f"{_NKL}title", "value": "C"}]}

    def lister_depots_collection(self, doi: str, *, page: int = 1, taille: int = 50) -> dict:
        return {"data": self._donnees if page == 1 else [], "currentPage": page, "lastPage": 1}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _amorcer_deux_items(db: Path) -> None:
    """Rapatrie 2 données (titres d'origine) → 2 items liés."""
    initial = [_donnee("aaa1", "Titre A"), _donnee("bbb2", "Titre B")]
    with _session(db) as s:
        rapatrier_collection(s, _FakeClient(initial), _DOI_COL, cree_par="T")


def test_inchange_quand_identique(db_path: Path) -> None:
    _amorcer_deux_items(db_path)
    meme = [_donnee("aaa1", "Titre A"), _donnee("bbb2", "Titre B")]
    with _session(db_path) as s:
        rapport = rafraichir_collection(s, _FakeClient(meme), _DOI_COL)
    assert len(rapport.inchanges) == 2
    assert rapport.modifies == []
    assert rapport.non_lies == [] and rapport.erreurs == []


def test_dry_run_montre_diff_sans_appliquer(db_path: Path) -> None:
    _amorcer_deux_items(db_path)
    modifie = [_donnee("aaa1", "Titre A MODIFIÉ"), _donnee("bbb2", "Titre B")]
    with _session(db_path) as s:
        rapport = rafraichir_collection(s, _FakeClient(modifie), _DOI_COL, dry_run=True)
    assert len(rapport.modifies) == 1
    assert rapport.modifies[0].applique is False
    # DB inchangée.
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.doi_nakala == "10.34847/nkl.aaa1"))
        assert item.titre == "Titre A"


def test_no_dry_run_applique_overwrite(db_path: Path) -> None:
    _amorcer_deux_items(db_path)
    modifie = [_donnee("aaa1", "Titre A MODIFIÉ"), _donnee("bbb2", "Titre B")]
    with _session(db_path) as s:
        rapport = rafraichir_collection(s, _FakeClient(modifie), _DOI_COL, dry_run=False)
    assert len(rapport.modifies) == 1
    assert rapport.modifies[0].applique is True
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.doi_nakala == "10.34847/nkl.aaa1"))
        assert item.titre == "Titre A MODIFIÉ"


def test_overwrite_invalide_collecte_en_erreur(db_path: Path) -> None:
    """Une donnée sans titre exploitable → overwrite invalide collecté en
    erreur, sans interrompre le traitement des autres."""
    _amorcer_deux_items(db_path)
    # aaa1 renvoyé sans titre (value vide → titre None) ; bbb2 inchangé.
    casse = [_donnee("aaa1", ""), _donnee("bbb2", "Titre B")]
    with _session(db_path) as s:
        rapport = rafraichir_collection(s, _FakeClient(casse), _DOI_COL, dry_run=False)
    assert len(rapport.erreurs) == 1
    assert rapport.erreurs[0][0] == "10.34847/nkl.aaa1"
    # bbb2 a bien été traité (la session n'est pas restée cassée).
    assert any(r.item_cote == "bbb2" for r in rapport.rapports)
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.doi_nakala == "10.34847/nkl.aaa1"))
        assert item.titre == "Titre A"  # overwrite échoué → titre conservé


def test_donnee_non_liee_signalee_pas_erreur(db_path: Path) -> None:
    _amorcer_deux_items(db_path)
    # ccc3 n'a jamais été rapatriée → non liée.
    avec_nouvelle = [
        _donnee("aaa1", "Titre A"),
        _donnee("bbb2", "Titre B"),
        _donnee("ccc3", "Nouvelle donnée"),
    ]
    with _session(db_path) as s:
        rapport = rafraichir_collection(s, _FakeClient(avec_nouvelle), _DOI_COL)
    assert rapport.non_lies == ["10.34847/nkl.ccc3"]
    assert len(rapport.inchanges) == 2
    assert rapport.erreurs == []
