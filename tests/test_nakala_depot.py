"""Tests du service de dépôt Nakala (P2/A4) — write client mocké."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds, lire_fonds_par_cote
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import (
    DepotImpossible,
    deposer_item,
    item_vers_slugs,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.depot_mapper import MetaInvalide
from archives_tool.models import Base, Fichier, Item

_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"


class _FakeWriteClient:
    """Enregistre les uploads + le corps de création ; renvoie un DOI."""

    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.depot_cree: dict | None = None
        self.supprimes: list[str] = []

    def uploader_fichier(self, chemin, nom=None):
        self.uploads.append(nom or Path(chemin).name)
        return {"name": nom or Path(chemin).name, "sha1": f"sha-{len(self.uploads)}"}

    def creer_depot(self, *, metas, files, status="pending", collections_ids=None):
        self.depot_cree = {
            "metas": metas, "files": files, "status": status,
            "collectionsIds": collections_ids,
        }
        return {"payload": {"id": "10.34847/nkl.cree1"}}

    def supprimer_upload(self, sha1):
        self.supprimes.append(sha1)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _item_avec_fichier_local(
    s, tmp_path: Path, *, createurs=("Somers, Armonía",), date="1984"
) -> Item:
    """Crée un fonds + item + 1 Fichier dont le binaire existe sur disque."""
    f = creer_fonds(s, FormulaireFonds(cote="AS", titre="Armonía Somers"))
    item = creer_item(s, FormulaireItem(
        cote="AS-001", titre="La mujer desnuda", fonds_id=f.id,
        date=date, langue="spa", description="Roman",
        type_coar="http://purl.org/coar/resource_type/c_2f33",
        metadonnees={"createurs": list(createurs), "sujets": ["Literatura"]},
    ))
    # Fichier avec binaire local.
    (tmp_path / "scans").mkdir(exist_ok=True)
    (tmp_path / "scans" / "as001.jpg").write_bytes(b"\xff\xd8\xff img")
    s.add(Fichier(
        item_id=item.id, nom_fichier="as001.jpg", racine="scans",
        chemin_relatif="as001.jpg", ordre=1,
    ))
    s.commit()
    return item


def test_item_vers_slugs_coeur() -> None:
    class _I:
        titre = "T"
        langue = "spa"
        date = "1984"
        description = "Desc"
        type_coar = "http://purl.org/coar/resource_type/c_2f33"
        metadonnees = {"createurs": ["Somers, Armonía"], "sujets": ["Lit"],
                       "dcterms_publisher": "CNRS", "dcterms_issued": "1984"}
    slugs = item_vers_slugs(_I())
    assert slugs["nkl_title"] == [{"value": "T", "lang": "spa"}]
    assert slugs["nkl_creator"] == ["Somers, Armonía"]
    assert slugs["nkl_created"] == "1984"
    assert slugs["nkl_type"].endswith("c_2f33")
    assert slugs["dcterms_subject"] == [{"value": "Lit", "lang": "spa"}]
    assert slugs["dcterms_language"] == ["spa"]
    # Extra multilingue coercé, extra date en liste de chaînes.
    assert slugs["dcterms_publisher"] == [{"value": "CNRS", "lang": "spa"}]
    assert slugs["dcterms_issued"] == ["1984"]


def test_dry_run_ne_depose_rien(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        rapport = deposer_item(s, client, item, racines=racines, dry_run=True)
    assert rapport.dry_run and rapport.doi is None
    assert rapport.nb_fichiers == 1 and rapport.fichiers == ["as001.jpg"]
    # metas contient titre + créateur + date.
    uris = [m["propertyUri"] for m in rapport.metas]
    assert f"{_NKL}title" in uris and f"{_NKL}creator" in uris
    assert client.uploads == [] and client.depot_cree is None  # rien envoyé


def test_reel_upload_et_cree_depot(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        rapport = deposer_item(s, client, item, racines=racines, dry_run=False,
                               collection_doi="10.34847/nkl.col1", cree_par="T")
    assert rapport.doi == "10.34847/nkl.cree1"
    assert client.uploads == ["as001.jpg"]
    assert client.depot_cree["status"] == "pending"
    assert client.depot_cree["files"] == [{"sha1": "sha-1", "name": "as001.jpg"}]
    assert client.depot_cree["collectionsIds"] == ["10.34847/nkl.col1"]
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        assert item.doi_nakala == "10.34847/nkl.cree1"


def test_deja_depose_saute(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        item.doi_nakala = "10.34847/nkl.deja"
        s.commit()
        rapport = deposer_item(s, client, item, racines=racines, dry_run=False)
    assert rapport.deja_depose and rapport.doi == "10.34847/nkl.deja"
    assert client.depot_cree is None  # rien créé


def test_sans_fichier_local_refuse(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        item = creer_item(s, FormulaireItem(cote="AS-002", titre="T", fonds_id=f.id,
                                            date="1984", metadonnees={"createurs": ["X, Y"]}))
        # Fichier Nakala-only (pas de chemin local).
        s.add(Fichier(item_id=item.id, nom_fichier="x.jpg", ordre=1,
                      iiif_url_nakala="https://api.nakala.fr/iiif/a/b/info.json"))
        s.commit()
        with pytest.raises(DepotImpossible):
            deposer_item(s, client, item, racines=racines, dry_run=True)


def test_preflight_echoue_sans_createur_ni_date(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        # Pas de créateur, pas de date → cascade preflight insatisfiable.
        item = _item_avec_fichier_local(s, tmp_path, createurs=(), date="")
        with pytest.raises(MetaInvalide):
            deposer_item(s, client, item, racines=racines, dry_run=True)


def test_echec_creation_nettoie_les_uploads_orphelins(
    db_path: Path, tmp_path: Path
) -> None:
    """Si POST /datas échoue après upload, les uploads sont supprimés et
    l'erreur propage (Item.doi_nakala non posé)."""
    from archives_tool.external.nakala.write_client import NakalaSoumissionInvalide

    class _ClientCreationKO(_FakeWriteClient):
        def creer_depot(self, *, metas, files, status="pending", collections_ids=None):
            raise NakalaSoumissionInvalide("422 boom")

    racines = {"scans": tmp_path / "scans"}
    client = _ClientCreationKO()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        with pytest.raises(NakalaSoumissionInvalide):
            deposer_item(s, client, item, racines=racines, dry_run=False)
    # L'upload a eu lieu puis a été nettoyé ; le DOI n'est pas posé.
    assert client.uploads == ["as001.jpg"]
    assert client.supprimes == ["sha-1"]
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        assert item.doi_nakala is None


# ---------------------------------------------------------------------------
# deposer_collection (B2)
# ---------------------------------------------------------------------------


class _FakeWriteClientCol(_FakeWriteClient):
    def __init__(self) -> None:
        super().__init__()
        self.collections: list[dict] = []

    def creer_collection(self, *, metas, status="private", datas=None):
        self.collections.append({"status": status, "metas": metas})
        return {"payload": {"id": "10.34847/nkl.colNEW"}}


def _collection_miroir(s, cote: str):
    from archives_tool.models import Collection, TypeCollection

    return s.scalar(
        select(Collection).where(
            Collection.cote == cote,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )


def test_deposer_collection_dry_run_ne_cree_rien(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    with _session(db_path) as s:
        _item_avec_fichier_local(s, tmp_path)
        miroir = _collection_miroir(s, "AS")
        rapport = deposer_collection(s, client, miroir, racines=racines, dry_run=True)
    assert rapport.dry_run and not rapport.collection_creee
    assert len(rapport.deposes) == 1
    assert client.collections == [] and client.depot_cree is None  # rien envoyé
    with _session(db_path) as s:
        assert _collection_miroir(s, "AS").doi_nakala is None


def test_deposer_collection_reel_cree_et_pose_doi(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    with _session(db_path) as s:
        _item_avec_fichier_local(s, tmp_path)
        miroir = _collection_miroir(s, "AS")
        rapport = deposer_collection(s, client, miroir, racines=racines, dry_run=False,
                                     cree_par="T")
    assert rapport.collection_creee and rapport.collection_doi == "10.34847/nkl.colNEW"
    assert len(rapport.deposes) == 1
    with _session(db_path) as s:
        assert _collection_miroir(s, "AS").doi_nakala == "10.34847/nkl.colNEW"


def test_deposer_collection_item_sans_fichier_local_collecte(
    db_path: Path, tmp_path: Path
) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    with _session(db_path) as s:
        # 1 item avec fichier local + 1 item Nakala-only (non déposable).
        _item_avec_fichier_local(s, tmp_path)
        f = lire_fonds_par_cote(s, "AS")
        item2 = creer_item(s, FormulaireItem(cote="AS-002", titre="T2", fonds_id=f.id,
                                             date="1985", metadonnees={"createurs": ["X, Y"]}))
        s.add(Fichier(item_id=item2.id, nom_fichier="y.jpg", ordre=1,
                      iiif_url_nakala="https://api.nakala.fr/iiif/a/b/info.json"))
        s.commit()
        miroir = _collection_miroir(s, "AS")
        rapport = deposer_collection(s, client, miroir, racines=racines, dry_run=False)
    assert len(rapport.deposes) == 1
    assert rapport.non_deposables == ["AS-002"]
    assert rapport.erreurs == []
