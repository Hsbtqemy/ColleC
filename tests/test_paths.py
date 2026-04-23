"""Tests des utilitaires de manipulation de chemins."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from archives_tool.files.paths import (
    detecter_collisions_casse,
    hash_sha256,
    normaliser_nfc,
    resoudre_chemin,
    vers_posix,
)


def test_nfc_convertit_depuis_nfd() -> None:
    nfd = unicodedata.normalize("NFD", "éléphant")
    assert nfd != "éléphant"
    assert normaliser_nfc(nfd) == "éléphant"


def test_nfc_est_idempotent() -> None:
    assert normaliser_nfc(normaliser_nfc("café")) == "café"


def test_vers_posix_convertit_backslashes() -> None:
    assert vers_posix("a\\b\\c.tif") == "a/b/c.tif"


def test_vers_posix_depuis_pathlib(tmp_path: Path) -> None:
    assert "/" in vers_posix(tmp_path / "sous" / "dossier" / "fichier.tif")


def test_vers_posix_normalise_nfc() -> None:
    nfd = unicodedata.normalize("NFD", "café.tif")
    assert vers_posix(nfd) == "café.tif"


def test_resoudre_chemin_combine_racine_et_relatif(tmp_path: Path) -> None:
    racines = {"scans": tmp_path}
    chemin = resoudre_chemin(racines, "scans", "rev1/1923/0001.tif")
    assert chemin == tmp_path / "rev1" / "1923" / "0001.tif"


def test_resoudre_chemin_racine_inconnue(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        resoudre_chemin({"scans": tmp_path}, "miniatures", "a.tif")


def test_resoudre_chemin_rejette_remontee(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resoudre_chemin({"scans": tmp_path}, "scans", "../evade.tif")


def test_resoudre_chemin_rejette_absolu(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resoudre_chemin({"scans": tmp_path}, "scans", "/abs/chemin.tif")


def test_hash_sha256_valeur_connue(tmp_path: Path) -> None:
    fichier = tmp_path / "contenu.bin"
    fichier.write_bytes(b"hello")
    # SHA-256 de b"hello"
    attendu = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert hash_sha256(fichier) == attendu


def test_hash_sha256_buffer_petit_ok(tmp_path: Path) -> None:
    fichier = tmp_path / "gros.bin"
    fichier.write_bytes(b"x" * 10_000)
    # Un buffer volontairement petit doit donner le même résultat qu'un
    # buffer par défaut : vérifie la boucle de lecture multi-passes.
    h1 = hash_sha256(fichier)
    h2 = hash_sha256(fichier, taille_buffer=17)
    assert h1 == h2


def test_detecter_collisions_casse_basique() -> None:
    collisions = detecter_collisions_casse(["Image.TIF", "image.tif", "autre.tif"])
    assert collisions == [("Image.TIF", "image.tif")]


def test_detecter_collisions_casse_via_unicode() -> None:
    # NFD vs NFC — même nom sur Linux insensibilisé via NFC + casefold.
    nfd = unicodedata.normalize("NFD", "Café.tif")
    nfc = "café.tif"
    collisions = detecter_collisions_casse([nfd, nfc])
    assert len(collisions) == 1


def test_detecter_collisions_aucune() -> None:
    assert detecter_collisions_casse(["a.tif", "b.tif", "c.tif"]) == []
