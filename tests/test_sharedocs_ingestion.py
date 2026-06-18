"""Tests du service d'ingestion ShareDocs (Chantier 1, tranche 2).

Client réel `ClientShareDocs` + httpx `MockTransport` (aucun réseau), racine
locale sous `tmp_path`, base SQLite jetable. Couvre : dry-run (aucune
écriture), import réel (disque + Fichier), idempotence (en base / sur
disque), racine inconnue, namespacing par cote + ordre, succès partiel sur
échec de téléchargement.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.sharedocs import (
    RacineCibleInconnue,
    importer_depuis_sharedocs,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.sharedocs import ClientShareDocs
from archives_tool.models import Base, Fichier, Item

_BASE = "https://sharedocs.huma-num.fr/dav/colleC"


def _client() -> ClientShareDocs:
    """Client dont `telecharger` renvoie `b"BYTES-<nom>"` ; 404 si le nom
    contient `boom` (pour tester le succès partiel)."""

    def handler(req: httpx.Request) -> httpx.Response:
        nom = str(req.url).rsplit("/", 1)[-1]
        if "boom" in nom:
            return httpx.Response(404)
        return httpx.Response(200, content=b"BYTES-" + nom.encode())

    return ClientShareDocs(_BASE, "u", "p", transport=httpx.MockTransport(handler))


@pytest.fixture
def env(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    """Base AS + item AS-001 + une racine logique `import` sous tmp_path."""
    racine = tmp_path / "import"
    racine.mkdir()
    db = tmp_path / "t.db"
    eng = creer_engine(db)
    Base.metadata.create_all(eng)
    with creer_session_factory(eng)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        creer_item(s, FormulaireItem(cote="AS-001", titre="x", fonds_id=f.id))
        s.commit()
    eng.dispose()
    return db, {"import": racine}


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _item(s) -> Item:
    return s.scalar(select(Item).where(Item.cote == "AS-001"))


# ---------------------------------------------------------------------------


def test_dry_run_n_ecrit_rien(env) -> None:
    db, racines = env
    with _session(db) as s:
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            ["dossier/a.jpg", "dossier/b.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=True,
        )
    assert rapport.dry_run is True
    assert rapport.nb_retenus == 2 and rapport.nb_sautes == 0
    # Aucune écriture disque, aucun Fichier en base.
    assert not (racines["import"] / "AS-001").exists()
    with _session(db) as s:
        assert s.scalars(select(Fichier)).all() == []


def test_import_reel_ecrit_disque_et_cree_fichiers(env) -> None:
    db, racines = env
    with _session(db) as s:
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            ["dossier/a.jpg", "dossier/b.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
            importe_par="marie",
        )
    assert rapport.nb_retenus == 2
    # Binaires écrits sous <racine>/AS-001/<nom>.
    a = racines["import"] / "AS-001" / "a.jpg"
    assert a.read_bytes() == b"BYTES-a.jpg"
    assert (racines["import"] / "AS-001" / "b.jpg").exists()
    # Fichier créés : racine, chemin relatif namespacé, hash, taille, ordre.
    with _session(db) as s:
        fichiers = s.scalars(
            select(Fichier)
            .join(Item)
            .where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        assert [f.chemin_relatif for f in fichiers] == ["AS-001/a.jpg", "AS-001/b.jpg"]
        assert all(f.racine == "import" for f in fichiers)
        assert all(f.hash_sha256 and f.taille_octets for f in fichiers)
        assert [f.ordre for f in fichiers] == [1, 2]
        assert fichiers[0].ajoute_par == "marie"


def test_idempotent_deja_en_base(env) -> None:
    db, racines = env
    chemins = ["dossier/a.jpg"]
    with _session(db) as s:
        importer_depuis_sharedocs(
            s,
            _client(),
            chemins,
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    # 2e passage : déjà en base → sauté, pas de doublon.
    with _session(db) as s:
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            chemins,
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
        assert rapport.nb_retenus == 0
        assert rapport.fichiers[0].raison == "deja_en_base"
        assert len(s.scalars(select(Fichier)).all()) == 1


def test_deja_sur_disque_saute_sans_telecharger(env) -> None:
    db, racines = env
    # Pré-crée le fichier cible → l'import ne doit pas l'écraser ni créer
    # de Fichier (pas de pendant en base).
    cible = racines["import"] / "AS-001" / "a.jpg"
    cible.parent.mkdir(parents=True)
    cible.write_bytes(b"DEJA-LA")
    with _session(db) as s:
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            ["dossier/a.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    assert rapport.nb_retenus == 0
    assert rapport.fichiers[0].raison == "deja_sur_disque"
    assert cible.read_bytes() == b"DEJA-LA"  # non écrasé
    with _session(db) as s:
        assert s.scalars(select(Fichier)).all() == []


def test_racine_inconnue_leve(env) -> None:
    db, racines = env
    with _session(db) as s:
        with pytest.raises(RacineCibleInconnue):
            importer_depuis_sharedocs(
                s,
                _client(),
                ["a.jpg"],
                _item(s),
                racine_cible="absente",
                racines=racines,
                dry_run=True,
            )


def test_echec_telechargement_partiel_continue(env) -> None:
    """Un fichier en échec (404) est consigné ; les autres passent."""
    db, racines = env
    with _session(db) as s:
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            ["d/ok.jpg", "d/boom.jpg", "d/ok2.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    assert rapport.nb_retenus == 2  # ok.jpg + ok2.jpg
    echec = next(f for f in rapport.fichiers if f.nom_fichier == "boom.jpg")
    assert echec.retenu is False and echec.raison == "echec_telechargement"
    with _session(db) as s:
        noms = {f.nom_fichier for f in s.scalars(select(Fichier)).all()}
    assert noms == {"ok.jpg", "ok2.jpg"}  # le fichier en échec n'est pas créé
