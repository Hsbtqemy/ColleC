"""Tests du transformateur ligne → ItemPrepare."""

from __future__ import annotations

from pathlib import Path

import pytest

from archives_tool.importers.transformateur import (
    ItemPrepare,
    transformer_ligne,
)
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


def _profil(cas: str):
    return charger_profil(FIXTURES / cas / "profil.yaml")


def test_cas_simple() -> None:
    profil = _profil("cas_item_simple")
    ligne = {
        "Cote": "HK-1960-01",
        "Numero": "1",
        "Titre": "Premier numéro",
        "Date": "1960-10",
        "Annee": "1960",
        "Rubrique": "Couverture",
        "Collaborateurs": "Cavanna / Choron / Fournier",
        "Notes": None,
    }
    item = transformer_ligne(ligne, 2, profil)
    assert isinstance(item, ItemPrepare)
    assert item.cote == "HK-1960-01"
    assert item.champs_colonne["titre"] == "Premier numéro"
    # Forme 2 : séparateur " / " → liste.
    assert item.metadonnees["collaborateurs"] == ["Cavanna", "Choron", "Fournier"]
    # Valeur par défaut copiée.
    assert item.champs_colonne["langue"] == "fra"
    assert item.champs_colonne["etat_catalogage"] == "brouillon"


def test_agregation_sujets() -> None:
    profil = _profil("cas_uri_dc")
    ligne = {
        "http://purl.org/dc/terms/identifier": "NKLDC-001",
        "http://purl.org/dc/terms/title": "Étude café",
        "http://purl.org/dc/terms/date": "1923",
        "sujet 1_fr": "Histoire",
        "sujet 2_fr": "Gastronomie",
        "sujet 3_fr": None,
        "creator_1": "Dupont",
        "creator_2": "Martin",
        "fichier": "nkl_abc123_page01.png",
    }
    item = transformer_ligne(ligne, 2, profil)
    assert item is not None
    # Forme 3 : sujets agrégés avec " | ", sujet 3_fr (None) ignoré.
    assert item.metadonnees["sujets"] == "Histoire | Gastronomie"
    # Créateurs avec séparateur " / ".
    assert item.metadonnees["createurs"] == "Dupont / Martin"


def test_agregation_une_seule_valeur() -> None:
    profil = _profil("cas_uri_dc")
    ligne = {
        "http://purl.org/dc/terms/identifier": "NKLDC-002",
        "http://purl.org/dc/terms/title": "Étude thé",
        "http://purl.org/dc/terms/date": None,
        "sujet 1_fr": "Histoire",
        "sujet 2_fr": None,
        "sujet 3_fr": None,
        "creator_1": "Dupont",
        "creator_2": None,
        "fichier": "x.png",
    }
    item = transformer_ligne(ligne, 3, profil)
    assert item is not None
    assert item.metadonnees["sujets"] == "Histoire"
    assert item.metadonnees["createurs"] == "Dupont"


def test_decomposition_cote_et_type() -> None:
    profil = _profil("cas_hierarchie_cote")
    ligne = {
        "Cote": "FA-AA-01-01",
        "Titre": "Lettre",
        "Date": "1923-04-12",
        "Type": "Correspondance | Courrier entrant | Envoi",
        "Serie_visible": "SERIE-01",
    }
    item = transformer_ligne(ligne, 2, profil)
    assert item is not None
    assert item.hierarchie == {
        "fonds": "FA",
        "sous_fonds": "AA",
        "serie": "01",
        "numero": "01",
    }
    assert item.typologie == {
        "categorie": "Correspondance",
        "sous_categorie": "Courrier entrant",
        "specifique": "Envoi",
    }


def test_decomposition_cote_non_matchante() -> None:
    # Cote qui ne matche pas la regex : hierarchie = None, pas d'erreur.
    profil = _profil("cas_hierarchie_cote")
    ligne = {
        "Cote": "FORMAT_EXOTIQUE",
        "Titre": "...",
        "Date": None,
        "Type": None,
        "Serie_visible": None,
    }
    item = transformer_ligne(ligne, 5, profil)
    assert item is not None
    assert item.hierarchie is None


def test_ligne_toute_vide_retourne_none() -> None:
    profil = _profil("cas_item_simple")
    ligne = {
        "Cote": None,
        "Numero": None,
        "Titre": None,
        "Date": None,
        "Annee": None,
        "Rubrique": None,
        "Collaborateurs": None,
        "Notes": None,
    }
    assert transformer_ligne(ligne, 42, profil) is None


def test_cote_manquante_leve() -> None:
    profil = _profil("cas_item_simple")
    ligne = {
        "Cote": None,
        "Numero": None,
        "Titre": "Mais un titre",
        "Date": None,
        "Annee": None,
        "Rubrique": None,
        "Collaborateurs": None,
        "Notes": None,
    }
    with pytest.raises(ValueError, match="cote"):
        transformer_ligne(ligne, 3, profil)


def test_cote_caractere_interdit() -> None:
    profil = _profil("cas_item_simple")
    ligne = {
        "Cote": "HK/slash",
        "Numero": "1",
        "Titre": "X",
        "Date": None,
        "Annee": None,
        "Rubrique": None,
        "Collaborateurs": None,
        "Notes": None,
    }
    with pytest.raises(ValueError, match="interdit"):
        transformer_ligne(ligne, 4, profil)


def test_valeur_par_defaut_nonecrase_valeur_tableur(tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    yml.write_text(
        """
version_profil: 1
collection:
  cote: "X"
  titre: "Défauts"
tableur:
  chemin: "t.csv"
mapping:
  cote: "Cote"
  langue: "Lang"
valeurs_par_defaut:
  langue: "fra"
  etat_catalogage: "a_verifier"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    ligne = {"Cote": "Y1", "Lang": "spa"}
    item = transformer_ligne(ligne, 2, profil)
    # Tableur prime sur default : "spa" l'emporte.
    assert item.champs_colonne["langue"] == "spa"
    # Default complète les absents : etat_catalogage non mappé, repris.
    assert item.champs_colonne["etat_catalogage"] == "a_verifier"


@pytest.mark.parametrize(
    "transformation,entree,attendu",
    [
        ("upper", "abc", "ABC"),
        ("lower", "ABc", "abc"),
        ("strip", "  hello  ", "hello"),
        ("strip_accents", "Éléphant café", "Elephant cafe"),
        ("slug", "Titre d'été — version #2", "titre-d-ete-version-2"),
    ],
)
def test_transformations(
    transformation: str, entree: str, attendu: str, tmp_path: Path
) -> None:
    yml = tmp_path / "p.yaml"
    yml.write_text(
        f"""
version_profil: 1
collection:
  cote: "X"
  titre: "Transformations"
tableur:
  chemin: "t.csv"
mapping:
  cote: "Cote"
  metadonnees.slug:
    source: "Titre"
    transformation: "{transformation}"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    ligne = {"Cote": "T1", "Titre": entree}
    item = transformer_ligne(ligne, 2, profil)
    assert item.metadonnees["slug"] == attendu
