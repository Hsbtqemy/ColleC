"""Tests du générateur de squelette de profil YAML."""

from __future__ import annotations

from pathlib import Path

import pytest

from archives_tool.profils import (
    analyser_tableur,
    charger_profil,
    generer_squelette,
)
from archives_tool.profils.generateur import _slugifier

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


def _ecrire_yaml_co_localise(yaml_str: str, dossier: Path) -> Path:
    """Écrit un YAML temporaire et retourne son chemin."""
    chemin = dossier / "profil.yaml"
    chemin.write_text(yaml_str, encoding="utf-8")
    return chemin


# ---------- generer_squelette ----------


def test_generer_squelette_minimal_contient_sections() -> None:
    yml = generer_squelette("HK", "Hara-Kiri", "tableur.csv")
    # Sections obligatoires présentes.
    assert "version_profil: 1" in yml
    assert "collection:" in yml
    assert '  cote: "HK"' in yml
    assert '  titre: "Hara-Kiri"' in yml
    assert "tableur:" in yml
    assert '  chemin: "tableur.csv"' in yml
    assert "granularite_source: item" in yml
    assert "mapping:" in yml
    # TODO visible.
    assert "TODO" in yml
    assert "⚠" in yml


def test_generer_squelette_charge_avec_placeholder(tmp_path: Path) -> None:
    # Le squelette init contient un placeholder cote: "A_REMPLACER"
    # qui rend le profil chargeable mais inutilisable tel quel.
    # L'import échouera avec un message explicite pointant le placeholder.
    (tmp_path / "tableur.csv").write_text("X\n", encoding="utf-8")
    yml = generer_squelette("X", "X", "tableur.csv")
    chemin = _ecrire_yaml_co_localise(yml, tmp_path)
    profil = charger_profil(chemin)
    assert profil.collection.cote == "X"
    assert "cote" in profil.mapping.champs
    # Le placeholder est bien là, repérable par l'utilisateur.
    assert "A_REMPLACER" in yml


def test_generer_squelette_apres_completion_charge(tmp_path: Path) -> None:
    (tmp_path / "tableur.csv").write_text("Cote\nHK-1\n", encoding="utf-8")
    yml = generer_squelette("HK", "Hara-Kiri", "tableur.csv")
    # Remplacer le placeholder par un vrai mapping.
    yml = yml.replace('"A_REMPLACER"', '"Cote"')
    chemin = _ecrire_yaml_co_localise(yml, tmp_path)
    profil = charger_profil(chemin)
    assert profil.mapping.champs["cote"].source == "Cote"


def test_generer_squelette_granularite_fichier() -> None:
    yml = generer_squelette("PF", "Por Favor", "x.csv", granularite="fichier")
    assert "granularite_source: fichier" in yml


def test_generer_squelette_titre_avec_apostrophe(tmp_path: Path) -> None:
    # Apostrophe dans le titre : doit produire un YAML valide et
    # rechargeable. JSON-quoting n'échappe pas l'apostrophe simple.
    yml = generer_squelette("X", "Titre de l'œuvre", "tableur.csv")
    assert '"Titre de l\'œuvre"' in yml
    (tmp_path / "tableur.csv").write_text("X\n", encoding="utf-8")
    chemin = _ecrire_yaml_co_localise(yml, tmp_path)
    profil = charger_profil(chemin)
    assert profil.collection.titre == "Titre de l'œuvre"


def test_generer_squelette_reproductible() -> None:
    a = generer_squelette("X", "Y", "z.csv")
    b = generer_squelette("X", "Y", "z.csv")
    # Reproductibilité : même entrée → même sortie (modulo la date
    # qui apparaît dans le commentaire d'en-tête).
    assert a == b


# ---------- analyser_tableur ----------


def test_analyser_tableur_cas_item_simple(tmp_path: Path) -> None:
    yml = analyser_tableur(FIXTURES / "cas_item_simple" / "tableur.csv")
    # "Cote" et "Titre" doivent être détectés et mappés vers les
    # champs dédiés.
    assert 'cote: "Cote"  # détecté' in yml
    assert 'titre: "Titre"  # détecté' in yml
    # Les colonnes restantes vont dans metadonnees.<slug>.
    assert "metadonnees.collaborateurs:" in yml
    assert "metadonnees.notes:" in yml
    assert "metadonnees.rubrique:" in yml
    # YAML chargeable après écriture co-localisée.
    chemin_tableur_abs = (FIXTURES / "cas_item_simple" / "tableur.csv").as_posix()
    yml = yml.replace(
        '  chemin: "tableur.csv"',
        f'  chemin: "{chemin_tableur_abs}"',
    )
    chemin = _ecrire_yaml_co_localise(yml, tmp_path)
    profil = charger_profil(chemin)
    assert "cote" in profil.mapping.champs
    assert "titre" in profil.mapping.champs


def test_analyser_tableur_cas_uri_dc(tmp_path: Path) -> None:
    yml = analyser_tableur(FIXTURES / "cas_uri_dc" / "tableur.csv")
    # Les URI Dublin Core sont reconnues et mappées vers les champs
    # dédiés correspondants.
    assert 'cote: "http://purl.org/dc/terms/identifier"  # détecté' in yml
    assert 'titre: "http://purl.org/dc/terms/title"  # détecté' in yml
    assert 'date: "http://purl.org/dc/terms/date"  # détecté' in yml
    # Colonnes non-DC vont dans metadonnees.
    assert "metadonnees.sujet_1_fr" in yml
    assert "metadonnees.creator_1" in yml


def test_analyser_tableur_cas_hierarchie_cote(tmp_path: Path) -> None:
    yml = analyser_tableur(FIXTURES / "cas_hierarchie_cote" / "tableur.csv")
    assert 'cote: "Cote"  # détecté' in yml
    assert 'titre: "Titre"  # détecté' in yml
    # Colonne "Type" non détectée comme structurante (heuristique
    # conservatrice, car type_coar attend une URI), reste en metadonnees.
    assert "metadonnees.type:" in yml
    assert "metadonnees.serie_visible:" in yml


def test_analyser_tableur_fichier_inexistant(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="introuvable"):
        analyser_tableur(tmp_path / "n_existe_pas.csv")


def test_analyser_tableur_extension_inconnue(tmp_path: Path) -> None:
    fichier = tmp_path / "x.txt"
    fichier.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="Extension"):
        analyser_tableur(fichier)


def test_analyser_tableur_dedoublonnage_slug(tmp_path: Path) -> None:
    # Deux noms de colonnes distincts qui produisent le même slug
    # ("Sujet (FR)" et "Sujet_FR" → "sujet_fr"). Le second doit être
    # suffixé "_2" au lieu d'être perdu silencieusement.
    csv = tmp_path / "doublon.csv"
    csv.write_text(
        "Cote;Sujet (FR);Sujet_FR\nX1;a;b\n",
        encoding="utf-8",
    )
    yml = analyser_tableur(csv)
    # Les deux colonnes apparaissent avec des clés metadonnees.* distinctes.
    assert "metadonnees.sujet_fr:" in yml
    assert "metadonnees.sujet_fr_2:" in yml


def test_analyser_tableur_personnalise_collection(tmp_path: Path) -> None:
    yml = analyser_tableur(
        FIXTURES / "cas_item_simple" / "tableur.csv",
        cote_collection="MA-COTE",
        titre_collection="Mon titre",
    )
    assert '  cote: "MA-COTE"' in yml
    assert '  titre: "Mon titre"' in yml


# ---------- _slugifier ----------


@pytest.mark.parametrize(
    "entree,attendu",
    [
        ("Cote", "cote"),
        ("Sujet 1 (FR)", "sujet_1_fr"),
        ("Année", "annee"),
        ("http://purl.org/dc/terms/title", "http_purl_org_dc_terms_title"),
        ("  espaces  ", "espaces"),
        ("---___", "champ"),  # tout vide après normalisation
        ("Œuvre n°2", "uvre_n_2"),  # oe collés deviennent juste 'u' après NFD
    ],
)
def test_slugifier(entree: str, attendu: str) -> None:
    assert _slugifier(entree) == attendu
