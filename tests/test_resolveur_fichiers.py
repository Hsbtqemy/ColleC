"""Tests du résolveur de fichiers."""

from __future__ import annotations

from pathlib import Path

import pytest

from archives_tool.config import ConfigLocale
from archives_tool.importers.resolveur_fichiers import (
    ResolutionFichiersErreur,
    resoudre_fichiers_pour_item,
)
from archives_tool.importers.transformateur import ItemPrepare, transformer_ligne
from archives_tool.importers.lecteur_tableur import lire_tableur
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


def _config(racines: dict[str, Path]) -> ConfigLocale:
    return ConfigLocale(utilisateur="Test", racines=racines)


def test_template_cas_item_simple() -> None:
    profil = charger_profil(FIXTURES / "cas_item_simple" / "profil.yaml")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    # On prend la deuxième ligne du tableur (numero=2) → attend 02.png
    lignes = lire_tableur(profil, FIXTURES / "cas_item_simple" / "profil.yaml")
    item = transformer_ligne(lignes[1], 3, profil)
    fichiers = resoudre_fichiers_pour_item(item, profil, config)
    assert len(fichiers) == 1
    assert fichiers[0].nom_fichier == "02.png"
    assert fichiers[0].racine == "scans_revues"
    assert fichiers[0].chemin_relatif == "02.png"
    assert fichiers[0].ordre == 1
    assert fichiers[0].hash_sha256 is None  # pas demandé → pas calculé
    assert fichiers[0].format == "png"


def test_template_filtre_extensions() -> None:
    # Le dossier contient aussi un notes.txt — doit être ignoré.
    profil = charger_profil(FIXTURES / "cas_item_simple" / "profil.yaml")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    item = ItemPrepare(cote="HK-1960-01", champs_colonne={"numero": "1"})
    fichiers = resoudre_fichiers_pour_item(item, profil, config)
    # .txt est filtré car hors extensions autorisées du profil.
    assert all(not f.nom_fichier.endswith(".txt") for f in fichiers)
    assert len(fichiers) == 1


def test_template_aucun_match() -> None:
    profil = charger_profil(FIXTURES / "cas_item_simple" / "profil.yaml")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    item = ItemPrepare(cote="INEXISTANT", champs_colonne={"numero": "99"})
    fichiers = resoudre_fichiers_pour_item(item, profil, config)
    assert fichiers == []


def test_regex_cas_hierarchie_cote() -> None:
    profil = charger_profil(FIXTURES / "cas_hierarchie_cote" / "profil.yaml")
    config = _config({"scans_archives": FIXTURES / "cas_hierarchie_cote" / "arbre"})
    lignes = lire_tableur(profil, FIXTURES / "cas_hierarchie_cote" / "profil.yaml")
    # Ligne 1 : cote = FA-AA-01-01, attendu FA-AA-01-01.png sous SERIE-01/
    item = transformer_ligne(lignes[0], 2, profil)
    fichiers = resoudre_fichiers_pour_item(item, profil, config)
    assert len(fichiers) == 1
    assert fichiers[0].chemin_relatif == "SERIE-01/FA-AA-01-01.png"


def test_regex_coherence_groupes() -> None:
    # La regex exige groupe cote==item.cote : un item avec une autre
    # cote ne doit pas matcher les fichiers nommés autrement.
    profil = charger_profil(FIXTURES / "cas_hierarchie_cote" / "profil.yaml")
    config = _config({"scans_archives": FIXTURES / "cas_hierarchie_cote" / "arbre"})
    item = ItemPrepare(cote="FA-AA-01-01", champs_colonne={})
    fichiers = resoudre_fichiers_pour_item(item, profil, config)
    assert {f.chemin_relatif for f in fichiers} == {"SERIE-01/FA-AA-01-01.png"}


def test_racine_inconnue() -> None:
    profil = charger_profil(FIXTURES / "cas_item_simple" / "profil.yaml")
    config = _config({})  # aucune racine déclarée
    item = ItemPrepare(cote="X", champs_colonne={"numero": "1"})
    with pytest.raises(ResolutionFichiersErreur, match="Racine logique inconnue"):
        resoudre_fichiers_pour_item(item, profil, config)


def test_profil_sans_section_fichiers(tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    yml.write_text(
        """
version_profil: 1
collection:
  cote: "X"
  titre: "Sans fichiers"
tableur:
  chemin: "t.csv"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    config = _config({})
    item = ItemPrepare(cote="X1", champs_colonne={})
    assert resoudre_fichiers_pour_item(item, profil, config) == []


def test_hash_calcule_si_demande() -> None:
    profil = charger_profil(FIXTURES / "cas_item_simple" / "profil.yaml")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    item = ItemPrepare(cote="HK-1960-01", champs_colonne={"numero": "1"})
    fichiers = resoudre_fichiers_pour_item(item, profil, config, avec_hash=True)
    assert fichiers[0].hash_sha256 is not None
    assert len(fichiers[0].hash_sha256) == 64


def test_tri_alphabetique_nfc() -> None:
    # Trois items partageant une recherche multi-fichiers : vérifions
    # que l'ordre de sortie est bien alphabétique sur le chemin NFC.
    profil = charger_profil(FIXTURES / "cas_fichier_groupe" / "profil.yaml")
    config = _config({"scans_revues": FIXTURES / "cas_fichier_groupe" / "arbre"})
    # Template "{fichier_source}" → matche un seul fichier par item ;
    # pour tester le tri on bâtit un item synthétique avec un glob.
    item = ItemPrepare(cote="PF-001", metadonnees={"fichier_source": "pf_001_p*.png"})
    fichiers = resoudre_fichiers_pour_item(item, profil, config)
    assert len(fichiers) == 2
    assert fichiers[0].chemin_relatif < fichiers[1].chemin_relatif
    assert [f.ordre for f in fichiers] == [1, 2]
