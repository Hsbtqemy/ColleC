"""Tests du service `rapatrier_collection` (Lot 2, T2.1) — client mocké."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala import rapatrier_collection
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Collection, Fichier, Fonds, Item, TypeCollection

_DOI_COL = "10.34847/nkl.collec01"
_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"


def _donnee(suffixe: str, *, files: int = 1) -> dict:
    return {
        "identifier": f"10.34847/nkl.{suffixe}",
        "uri": f"https://nakala.fr/{suffixe}",
        "status": "published",
        "version": 1,
        "metas": [
            {"propertyUri": f"{_NKL}title", "value": f"Donnée {suffixe}"},
            {"propertyUri": f"{_NKL}created", "value": "1984"},
            {"propertyUri": f"{_DCT}language", "value": "es"},
        ],
        "files": [
            {"name": f"{suffixe}-{i}.jpg", "sha1": f"{suffixe}{i}", "size": 10,
             "mime_type": "image/jpeg"}
            for i in range(files)
        ],
    }


class _FakeClient:
    """Stub : collection de 3 données (2 fichiers chacune)."""

    base_url = "https://apitest.nakala.fr"

    def __init__(self, donnees: list[dict] | None = None) -> None:
        self._donnees = donnees if donnees is not None else [
            _donnee("aaa1", files=2), _donnee("bbb2", files=2), _donnee("ccc3", files=2)
        ]

    def lire_collection(self, doi: str) -> dict:
        return {"identifier": doi, "metas": [{"propertyUri": f"{_NKL}title",
                                              "value": "Collection Test"}]}

    def lister_depots_collection(self, doi: str, *, page: int = 1, taille: int = 50) -> dict:
        return {"data": self._donnees if page == 1 else [], "currentPage": page, "lastPage": 1}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    from archives_tool.models import Base

    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def test_cree_fonds_miroir_items_et_fichiers(db_path: Path) -> None:
    with _session(db_path) as s:
        rapport = rapatrier_collection(s, _FakeClient(), _DOI_COL, cree_par="T")
    assert rapport.fonds_cree is True
    assert len(rapport.crees) == 3
    assert rapport.deja_existants == [] and rapport.erreurs == []
    assert rapport.fichiers_crees == 6  # 3 données × 2 fichiers

    with _session(db_path) as s:
        assert s.scalar(select(func.count(Item.id))) == 3
        # T2.5 : les fichiers Nakala sont matérialisés en `Fichier` (3×2).
        assert s.scalar(select(func.count(Fichier.id))) == 6
        item = s.scalar(select(Item).where(Item.doi_nakala == "10.34847/nkl.aaa1"))
        fichiers = sorted(item.fichiers, key=lambda f: f.ordre)
        assert len(fichiers) == 2
        # Image (.jpg) → URL IIIF info.json construite depuis doi + sha1.
        assert fichiers[0].iiif_url_nakala == (
            "https://apitest.nakala.fr/iiif/10.34847/nkl.aaa1/aaa10/info.json"
        )
        assert fichiers[0].nom_fichier == "aaa1-0.jpg"
        # sha1 conservé en colonne dédiée `sha1_nakala` (P3+a) et en
        # miroir dans `metadonnees["sha1"]` (rétrocompat). PAS dans
        # `hash_sha256` qui est SHA-256 (algos différents).
        assert fichiers[0].hash_sha256 is None
        assert fichiers[0].sha1_nakala == "aaa10"
        assert fichiers[0].metadonnees["sha1"] == "aaa10"
        fonds = lire_fonds_par_cote(s, "collec01")  # cote dérivée du DOI
        assert fonds is not None
        # DOI collection posé sur la miroir + sur chaque item.
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        assert miroir.doi_nakala == _DOI_COL
        item = s.scalar(select(Item).where(Item.doi_nakala == "10.34847/nkl.aaa1"))
        assert item.doi_collection_nakala == _DOI_COL


def test_dry_run_n_ecrit_rien(db_path: Path) -> None:
    with _session(db_path) as s:
        rapport = rapatrier_collection(s, _FakeClient(), _DOI_COL, dry_run=True)
    assert rapport.dry_run is True
    assert rapport.fonds_cree is False
    assert len(rapport.crees) == 3  # prévisionnel
    with _session(db_path) as s:
        assert s.scalar(select(func.count(Fonds.id))) == 0
        assert s.scalar(select(func.count(Item.id))) == 0


def test_reexecution_tout_deja_existant(db_path: Path) -> None:
    with _session(db_path) as s:
        rapatrier_collection(s, _FakeClient(), _DOI_COL, cree_par="T")
    with _session(db_path) as s:
        rapport = rapatrier_collection(s, _FakeClient(), _DOI_COL, cree_par="T")
    assert len(rapport.deja_existants) == 3
    assert rapport.crees == []
    with _session(db_path) as s:
        assert s.scalar(select(func.count(Item.id))) == 3  # pas de doublon
        # Re-run sur déjà-existant : pas de re-matérialisation des fichiers.
        assert s.scalar(select(func.count(Fichier.id))) == 6


def test_fichier_non_image_donne_url_data(db_path: Path) -> None:
    donnee = {
        "identifier": "10.34847/nkl.pdf1",
        "uri": "https://nakala.fr/pdf1",
        "status": "published",
        "version": 1,
        "metas": [{"propertyUri": f"{_NKL}title", "value": "Un PDF"}],
        "files": [{"name": "numero.pdf", "sha1": "deadbeef", "size": "999",
                   "extension": "pdf", "mime_type": "application/pdf"}],
    }
    with _session(db_path) as s:
        rapatrier_collection(s, _FakeClient([donnee]), _DOI_COL, cree_par="T")
    with _session(db_path) as s:
        f = s.scalar(select(Fichier))
        # Non-image → URL data binaire (pas de IIIF info.json qui 404erait).
        assert f.iiif_url_nakala == "https://apitest.nakala.fr/data/10.34847/nkl.pdf1/deadbeef"
        assert f.format == "pdf"
        assert f.taille_octets == 999


def test_collision_cote_collectee_sans_arreter_le_lot(db_path: Path) -> None:
    # Pré-crée un item dont la cote = celle dérivée de la 2e donnée (bbb2),
    # mais avec un DOI différent → collision à la création.
    with _session(db_path) as s:
        f = creer_fonds(s, FormulaireFonds(cote="collec01", titre="Pré"))
        creer_item(s, FormulaireItem(cote="bbb2", titre="Occupant", fonds_id=f.id))
        s.commit()
    with _session(db_path) as s:
        rapport = rapatrier_collection(s, _FakeClient(), _DOI_COL, fonds_cote="collec01")
    assert len(rapport.erreurs) == 1
    assert rapport.erreurs[0][0] == "10.34847/nkl.bbb2"
    assert len(rapport.crees) == 2  # aaa1 + ccc3 passent
    with _session(db_path) as s:
        assert s.scalar(select(Item).where(Item.doi_nakala == "10.34847/nkl.aaa1")) is not None


def test_fonds_existant_reutilise(db_path: Path) -> None:
    with _session(db_path) as s:
        creer_fonds(s, FormulaireFonds(cote="MONFONDS", titre="Mon fonds"))
        s.commit()
    with _session(db_path) as s:
        rapport = rapatrier_collection(
            s, _FakeClient(), _DOI_COL, fonds_cote="MONFONDS", cree_par="T"
        )
    assert rapport.fonds_cree is False
    assert rapport.fonds_cote == "MONFONDS"
    assert len(rapport.crees) == 3
    with _session(db_path) as s:
        assert s.scalar(select(func.count(Fonds.id))) == 1


def test_fonds_cote_inexistant_leve(db_path: Path) -> None:
    with _session(db_path) as s, pytest.raises(FondsIntrouvable):
        rapatrier_collection(s, _FakeClient(), _DOI_COL, fonds_cote="ABSENT")
