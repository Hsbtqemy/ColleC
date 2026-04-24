"""Tests du lecteur de tableur."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from archives_tool.importers.lecteur_tableur import (
    LectureTableurErreur,
    lire_tableur,
)
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


def _charger(cas: str):
    chemin = FIXTURES / cas / "profil.yaml"
    return charger_profil(chemin), chemin


def test_lecture_cas_item_simple() -> None:
    profil, chemin = _charger("cas_item_simple")
    lignes = lire_tableur(profil, chemin)
    assert len(lignes) == 5
    assert lignes[0]["Cote"] == "HK-1960-01"
    assert lignes[0]["Numero"] == "1"
    # Valeur "none" de la liste valeurs_nulles → None.
    assert lignes[1]["Notes"] is None
    # Valeur "n/a" aussi.
    assert lignes[2]["Notes"] is None
    # Cellule vide (CSV sans valeur) → None.
    assert lignes[0]["Notes"] is None


def test_lecture_cas_fichier_groupe() -> None:
    profil, chemin = _charger("cas_fichier_groupe")
    lignes = lire_tableur(profil, chemin)
    assert len(lignes) == 3
    assert lignes[0]["cote_item"] == "PF-001"
    assert lignes[0]["doi_item"].startswith("10.34847/nkl")


def test_lecture_cas_hierarchie_cote() -> None:
    profil, chemin = _charger("cas_hierarchie_cote")
    lignes = lire_tableur(profil, chemin)
    assert len(lignes) == 4
    # Date incertaine préservée en l'état (pas d'inférence).
    assert lignes[2]["Date"] == "vers 1924"


def test_lecture_cas_uri_dc() -> None:
    profil, chemin = _charger("cas_uri_dc")
    lignes = lire_tableur(profil, chemin)
    assert len(lignes) == 2
    # Colonnes nommées par URI, accessibles tels quels.
    assert lignes[0]["http://purl.org/dc/terms/title"] == "Étude café"
    # Cellule vide ("" est dans valeurs_nulles) → None.
    assert lignes[1]["sujet 2_fr"] is None
    assert lignes[1]["creator_2"] is None


def test_accents_nfc(tmp_path: Path) -> None:
    # On écrit un CSV avec un titre en NFD et on vérifie que la
    # lecture renvoie du NFC.
    nfd = unicodedata.normalize("NFD", "café")
    csv = tmp_path / "t.csv"
    csv.write_text(f"Cote;Titre\nX1;{nfd}\n", encoding="utf-8")
    yml = tmp_path / "p.yaml"
    yml.write_text(
        """
version_profil: 1
collection:
  cote: "X"
  titre: "Test NFC"
tableur:
  chemin: "t.csv"
  separateur_csv: ";"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    lignes = lire_tableur(profil, yml)
    assert lignes[0]["Titre"] == "café"
    assert unicodedata.is_normalized("NFC", lignes[0]["Titre"])


def test_fichier_inexistant(tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    yml.write_text(
        """
version_profil: 1
collection:
  cote: "X"
  titre: "Fichier absent"
tableur:
  chemin: "n_existe_pas.csv"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    with pytest.raises(LectureTableurErreur, match="introuvable"):
        lire_tableur(profil, yml)


def test_extension_non_supportee(tmp_path: Path) -> None:
    txt = tmp_path / "t.txt"
    txt.write_text("x", encoding="utf-8")
    yml = tmp_path / "p.yaml"
    yml.write_text(
        """
version_profil: 1
collection:
  cote: "X"
  titre: "Mauvais format"
tableur:
  chemin: "t.txt"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    with pytest.raises(LectureTableurErreur, match="Extension"):
        lire_tableur(profil, yml)
