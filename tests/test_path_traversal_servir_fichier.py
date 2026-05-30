"""Garde-fou path traversal sur GET /item/<cote>/fichiers/<id>.

Trouve a l'audit security : aucune validation de `chemin_relatif`
avant `racine / chemin_relatif`. `pathlib.Path("/racine") / "/etc/passwd"`
retourne `/etc/passwd` (documente : si le RHS est absolu, le LHS est
ignore). Avec une valeur DB malformee, le serveur servait du contenu
hors racine.

Pattern de defense applique : valider_chemin_relatif (rejette `..`
et chemin absolu) + is_relative_to apres resolve (rejette symlinks
qui sortent + edge cases).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Fichier, Fonds, Item


@pytest.fixture
def base_demo_avec_racine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """Peuple + configure une racine reelle pour servir des fichiers.

    Retourne (chemin_db, chemin_racine)."""
    db = tmp_path / "demo.db"
    peupler_base(db)
    racine = tmp_path / "scans"
    racine.mkdir()
    # Cree un fichier legitime dans la racine
    (racine / "valide.jpg").write_bytes(b"fake jpg content")

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nracines:\n  scans: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db, racine


def _patch_fichier_chemin(db: Path, cote_item: str, chemin: str) -> int:
    """Force le chemin_relatif d'un fichier d'un item dans la base."""
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == cote_item))
        f = s.scalar(
            select(Fichier).where(Fichier.item_id == item.id).limit(1)
        )
        assert f is not None
        f.racine = "scans"
        f.chemin_relatif = chemin
        s.commit()
        fid = f.id
    engine.dispose()
    return fid


def _ids_pour_servir(
    db: Path,
) -> tuple[str, str]:
    """Retourne (cote_fonds, cote_item) de la demo pour les tests."""
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).order_by(Item.id).limit(1))
        fonds = s.scalar(select(Fonds).where(Fonds.id == item.fonds_id))
    engine.dispose()
    return fonds.cote, item.cote


def test_servir_fichier_chemin_valide_marche(
    base_demo_avec_racine: tuple[Path, Path],
) -> None:
    """Cas nominal : un chemin_relatif sain → le binaire est servi."""
    db, _ = base_demo_avec_racine
    cote_fonds, cote_item = _ids_pour_servir(db)
    fid = _patch_fichier_chemin(db, cote_item, "valide.jpg")

    client = TestClient(app)
    r = client.get(f"/item/{cote_item}/fichiers/{fid}?fonds={cote_fonds}")
    assert r.status_code == 200
    assert r.content == b"fake jpg content"


def test_servir_fichier_chemin_avec_sous_dossier(
    base_demo_avec_racine: tuple[Path, Path],
) -> None:
    """Cas reel : chemin avec sous-dossier (`images/page-1.jpg`)
    est legitime et doit etre servi normalement."""
    db, racine = base_demo_avec_racine
    sous_dossier = racine / "images"
    sous_dossier.mkdir()
    (sous_dossier / "page-1.jpg").write_bytes(b"page 1 binaire")
    cote_fonds, cote_item = _ids_pour_servir(db)
    fid = _patch_fichier_chemin(db, cote_item, "images/page-1.jpg")

    client = TestClient(app)
    r = client.get(f"/item/{cote_item}/fichiers/{fid}?fonds={cote_fonds}")
    assert r.status_code == 200
    assert r.content == b"page 1 binaire"


def test_servir_fichier_refuse_chemin_absolu(
    base_demo_avec_racine: tuple[Path, Path], tmp_path: Path
) -> None:
    """`chemin_relatif = '/etc/passwd'` (absolu) → 403, pas 200.

    Sans la garde, `racine / '/etc/passwd'` = `/etc/passwd` en pathlib,
    et le serveur exposerait n'importe quel fichier lisible.

    Verification de contenu (pas de chemin) : sur Linux/Mac le detail
    403 « Chemin relatif invalide en base » ne contient pas le chemin
    soumis (defense-in-depth). Sur Windows, c'est is_relative_to qui
    catch (path POSIX validation n'attrape pas un chemin Windows).
    Quel que soit le chemin, on verifie que le contenu MARQUEUR_SECRET
    du fichier hors-racine ne se retrouve PAS dans la reponse."""
    db, _ = base_demo_avec_racine
    cote_fonds, cote_item = _ids_pour_servir(db)
    # Cree un fichier hors racine avec un marqueur improbable dans
    # le chemin lui-meme — pour separer leak du chemin vs leak du
    # contenu si l'assertion casse.
    hors_racine = tmp_path / "fichier_hors_racine.txt"
    hors_racine.write_bytes(b"MARQUEUR_CONTENU_PRIVE_42")
    fid = _patch_fichier_chemin(db, cote_item, str(hors_racine))

    client = TestClient(app)
    r = client.get(f"/item/{cote_item}/fichiers/{fid}?fonds={cote_fonds}")
    assert r.status_code == 403
    # Verifie sur le content (bytes) — couvre le cas
    # FileResponse qui aurait expose le binaire ainsi que les details
    # d'erreur JSON qui auraient pu inclure le contenu.
    assert b"MARQUEUR_CONTENU_PRIVE_42" not in r.content


def test_servir_fichier_refuse_dotdot(
    base_demo_avec_racine: tuple[Path, Path], tmp_path: Path
) -> None:
    """`chemin_relatif = '../fichier_hors.txt'` → 403."""
    db, racine = base_demo_avec_racine
    cote_fonds, cote_item = _ids_pour_servir(db)
    cible = racine.parent / "fichier_hors.txt"
    cible.write_bytes(b"MARQUEUR_DOTDOT_43")
    fid = _patch_fichier_chemin(db, cote_item, "../fichier_hors.txt")

    client = TestClient(app)
    r = client.get(f"/item/{cote_item}/fichiers/{fid}?fonds={cote_fonds}")
    assert r.status_code == 403
    assert b"MARQUEUR_DOTDOT_43" not in r.content


def test_servir_fichier_refuse_symlink_sortant_de_racine(
    base_demo_avec_racine: tuple[Path, Path], tmp_path: Path
) -> None:
    """Un fichier dans la racine qui est en realite un symlink vers
    /etc/passwd doit etre refuse (is_relative_to apres resolve)."""
    db, racine = base_demo_avec_racine
    cote_fonds, cote_item = _ids_pour_servir(db)

    cible_secret = tmp_path / "vrai_fichier_hors.txt"
    cible_secret.write_bytes(b"MARQUEUR_SYMLINK_44")
    lien = racine / "lien.jpg"
    try:
        lien.symlink_to(cible_secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks pas supportes sur ce poste")

    fid = _patch_fichier_chemin(db, cote_item, "lien.jpg")
    client = TestClient(app)
    r = client.get(f"/item/{cote_item}/fichiers/{fid}?fonds={cote_fonds}")
    assert r.status_code == 403
    assert b"MARQUEUR_SYMLINK_44" not in r.content


def test_servir_fichier_404_si_absent_avec_chemin_valide(
    base_demo_avec_racine: tuple[Path, Path],
) -> None:
    """Chemin valide mais fichier absent du disque → 404 (pas 403)."""
    db, _ = base_demo_avec_racine
    cote_fonds, cote_item = _ids_pour_servir(db)
    fid = _patch_fichier_chemin(db, cote_item, "n_existe_pas.jpg")

    client = TestClient(app)
    r = client.get(f"/item/{cote_item}/fichiers/{fid}?fonds={cote_fonds}")
    assert r.status_code == 404
