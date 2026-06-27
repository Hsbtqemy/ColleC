"""Tests du service d'ingestion ShareDocs (Chantier 1, tranche 2).

Client réel `ClientShareDocs` + httpx `MockTransport` (aucun réseau), racine
locale sous `tmp_path`, base SQLite jetable. Couvre : dry-run (aucune
écriture), import réel (disque + Fichier), idempotence (en base / sur
disque), racine inconnue, namespacing par cote + ordre, succès partiel sur
échec de téléchargement.
"""

from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path

import httpx
import pytest

from archives_tool.config import ShareDocsConfig
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


def test_fichier_sur_disque_sans_pendant_est_rattache(env) -> None:
    """Reprise auto-réparante : un binaire déjà sur disque SANS Fichier en
    base (import précédent interrompu) est ADOPTÉ — pas re-téléchargé (le
    contenu reste celui du disque, pas `BYTES-…`), pas écrasé."""
    db, racines = env
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
    assert rapport.nb_retenus == 1
    assert rapport.fichiers[0].raison == "rattache_disque"
    assert cible.read_bytes() == b"DEJA-LA"  # NI écrasé NI re-téléchargé
    with _session(db) as s:
        fichiers = s.scalars(select(Fichier)).all()
        assert len(fichiers) == 1
        # Le hash est celui du contenu disque adopté, pas du faux download.
        assert fichiers[0].hash_sha256 == hashlib.sha256(b"DEJA-LA").hexdigest()


def test_collision_basename_intra_lot(env) -> None:
    """Deux chemins distants distincts de même basename → même cible. Le 2e
    est signalé `collision_nom` (pas perdu en silence), et le dry-run le
    prédit (aperçu honnête, ≠ ancien comportement)."""
    db, racines = env
    chemins = ["dossierA/p1.jpg", "dossierB/p1.jpg"]
    with _session(db) as s:
        apercu = importer_depuis_sharedocs(
            s,
            _client(),
            chemins,
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=True,
        )
    assert apercu.nb_retenus == 1  # le dry-run ne ment pas (1, pas 2)
    assert [f.raison for f in apercu.fichiers] == [None, "collision_nom"]
    with _session(db) as s:
        reel = importer_depuis_sharedocs(
            s,
            _client(),
            chemins,
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
        assert reel.nb_retenus == 1
        assert reel.fichiers[1].raison == "collision_nom"
        assert len(s.scalars(select(Fichier)).all()) == 1


def test_modifie_le_none_a_la_creation(env) -> None:
    """Un fichier importé est *ajouté*, pas *modifié* → `modifie_le` reste
    None (sinon il s'afficherait à tort comme « modifié il y a… »)."""
    db, racines = env
    with _session(db) as s:
        importer_depuis_sharedocs(
            s,
            _client(),
            ["d/a.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    with _session(db) as s:
        f = s.scalars(select(Fichier)).one()
        assert f.modifie_le is None
        assert f.ajoute_par is None  # défaut importe_par=None


def test_ordre_depuis_item_non_vide(env) -> None:
    """L'ordre repart de max(existants)+1, pas de 1 (sinon collision
    `uq_fichier_item_ordre`)."""
    db, racines = env
    with _session(db) as s:
        item = _item(s)
        for i, nom in enumerate(("x.jpg", "y.jpg", "z.jpg"), start=1):
            s.add(
                Fichier(
                    item_id=item.id,
                    racine="import",
                    chemin_relatif=f"pre/{nom}",
                    nom_fichier=nom,
                    ordre=i,
                )
            )
        s.commit()
    with _session(db) as s:
        importer_depuis_sharedocs(
            s,
            _client(),
            ["d/a.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    with _session(db) as s:
        nouveau = s.scalars(select(Fichier).where(Fichier.nom_fichier == "a.jpg")).one()
        assert nouveau.ordre == 4


def test_normalisation_nfc(env) -> None:
    """Le nom est stocké en NFC même si le chemin distant est en NFD
    (portabilité macOS, principe n°5) ; la clé d'idempotence reste stable."""
    nfd = "café.jpg"  # "café.jpg" décomposé
    db, racines = env
    with _session(db) as s:
        importer_depuis_sharedocs(
            s,
            _client(),
            [f"d/{nfd}"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    with _session(db) as s:
        f = s.scalars(select(Fichier)).one()
        assert unicodedata.is_normalized("NFC", f.nom_fichier)
        assert f.nom_fichier == unicodedata.normalize("NFC", nfd)
        # Re-import → reconnu déjà en base (clé NFC stable).
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            [f"d/{nfd}"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
        assert rapport.fichiers[0].raison == "deja_en_base"


def test_lot_mixte_deja_et_nouveau(env) -> None:
    """Lot où un fichier est déjà en base et deux sont nouveaux."""
    db, racines = env
    with _session(db) as s:
        importer_depuis_sharedocs(
            s,
            _client(),
            ["d/a.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    with _session(db) as s:
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            ["d/a.jpg", "d/b.jpg", "d/c.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
        assert rapport.nb_retenus == 2 and rapport.nb_sautes == 1
        assert rapport.fichiers[0].raison == "deja_en_base"
        assert len(s.scalars(select(Fichier)).all()) == 3


def test_echec_ecriture_consigne_et_continue(env) -> None:
    """Une OSError à l'écriture est consignée (echec_ecriture) sans casser le
    lot — ici le dossier de namespacing est occupé par un FICHIER."""
    db, racines = env
    # `<racine>/AS-001` est un fichier → mkdir du parent de la cible échoue.
    (racines["import"] / "AS-001").write_bytes(b"je-suis-un-fichier")
    with _session(db) as s:
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            ["d/a.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    assert rapport.nb_retenus == 0
    assert rapport.fichiers[0].raison == "echec_ecriture"
    with _session(db) as s:
        assert s.scalars(select(Fichier)).all() == []


def test_sharedocs_config_valide_https() -> None:
    """`ShareDocsConfig` exige https et strippe le `/` final ; refuse http."""
    cfg = ShareDocsConfig(base_url="https://sharedocs.huma-num.fr/dav/colleC/")
    assert cfg.base_url == "https://sharedocs.huma-num.fr/dav/colleC"
    assert cfg.hotes_autorises == []
    with pytest.raises(ValueError):
        ShareDocsConfig(base_url="http://sharedocs.huma-num.fr/dav")


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


def test_traversal_nom_distant_ne_sort_pas_de_racine(env) -> None:
    """Revue sécurité F1 : un chemin distant malveillant (antislashs Windows,
    remontée `..`) ne doit JAMAIS écrire hors de la racine. Le basename est
    extrait proprement (le fichier atterrit DANS la racine) ou le nom est
    rejeté — jamais de fichier au-dessus de la racine d'import."""
    db, racines = env
    racine = racines["import"]
    au_dessus = racine.parent  # tmp_path
    malveillants = [
        "..\\..\\evade.txt",  # remontée via séparateur Windows
        "x/../../../evade2.txt",  # remontée POSIX → basename seul retenu
        "sous\\..\\..\\evade3.txt",  # mixte
    ]
    with _session(db) as s:
        importer_depuis_sharedocs(
            s,
            _client(),
            malveillants,
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    # Aucun fichier créé au-dessus de la racine (à 1 ou 2 niveaux).
    for nom in ("evade.txt", "evade2.txt", "evade3.txt"):
        assert not (au_dessus / nom).exists()
        assert not (au_dessus.parent / nom).exists()
    # Tout fichier réellement écrit reste confiné sous la racine.
    racine_resolue = racine.resolve()
    for p in racine.rglob("*"):
        if p.is_file():
            assert racine_resolue in p.resolve().parents


def test_nom_nul_byte_ne_casse_pas_le_lot(env) -> None:
    """Revue sécurité F3 : un nom à NUL byte lève un `ValueError` (et non un
    `OSError`) — capté pour ne pas casser tout le lot. Le fichier valide du
    même lot est importé normalement."""
    db, racines = env
    with _session(db) as s:
        rapport = importer_depuis_sharedocs(
            s,
            _client(),
            ["d/a\x00.jpg", "d/ok.jpg"],
            _item(s),
            racine_cible="import",
            racines=racines,
            dry_run=False,
        )
    # Le lot n'a pas planté ; seul le fichier valide est retenu.
    assert rapport.nb_retenus == 1
    with _session(db) as s:
        noms = {f.nom_fichier for f in s.scalars(select(Fichier)).all()}
    assert noms == {"ok.jpg"}


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
