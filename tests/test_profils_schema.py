"""Tests du schéma Pydantic des profils d'import."""

from __future__ import annotations

from pathlib import Path

import pytest

from archives_tool.profils import (
    MappingAgrege,
    MappingSimple,
    MappingTransforme,
    ProfilInvalide,
    charger_profil,
)

FIXTURES = Path(__file__).parent / "fixtures" / "profils"
VALIDES = ["cas_item_simple", "cas_fichier_groupe", "cas_hierarchie_cote", "cas_uri_dc"]


@pytest.mark.parametrize("cas", VALIDES)
def test_fixture_valide_charge(cas: str) -> None:
    profil = charger_profil(FIXTURES / cas / "profil.yaml")
    assert profil.version_profil == 1
    assert profil.collection.cote
    assert profil.collection.titre
    assert profil.mapping.champs  # au moins un mapping


def test_cas_item_simple_details() -> None:
    p = charger_profil(FIXTURES / "cas_item_simple" / "profil.yaml")
    assert p.granularite_source == "item"
    assert p.collection.editeur == "Éditions du Square (fictif)"
    # Forme 1 : mapping simple chaîne → MappingSimple
    assert isinstance(p.mapping.champs["cote"], MappingSimple)
    assert p.mapping.champs["cote"].source == "Cote"
    # Forme 2 : mapping objet avec séparateur → MappingTransforme
    collab = p.mapping.champs["metadonnees.collaborateurs"]
    assert isinstance(collab, MappingTransforme)
    assert collab.separateur == " / "
    assert p.valeurs_par_defaut == {"langue": "fra", "etat_catalogage": "brouillon"}


def test_cas_fichier_groupe_details() -> None:
    p = charger_profil(FIXTURES / "cas_fichier_groupe" / "profil.yaml")
    assert p.granularite_source == "fichier"
    assert "cote" in p.mapping.champs  # requis pour fichier
    assert p.collection.doi_nakala == "10.34847/nkl.fakepfcoll"


def test_cas_hierarchie_cote_details() -> None:
    p = charger_profil(FIXTURES / "cas_hierarchie_cote" / "profil.yaml")
    assert p.decomposition_cote is not None
    assert "(?P<fonds>" in p.decomposition_cote.regex
    assert p.decomposition_cote.stockage == "hierarchie"
    assert p.decomposition_type is not None
    assert p.decomposition_type.niveaux == [
        "categorie",
        "sous_categorie",
        "specifique",
    ]
    # motif_chemin en mode regex doit compiler
    assert p.fichiers is not None
    assert p.fichiers.type_motif == "regex"


def test_cas_uri_dc_agregations() -> None:
    p = charger_profil(FIXTURES / "cas_uri_dc" / "profil.yaml")
    # Forme 3 : mapping objet avec `sources` → MappingAgrege
    sujets = p.mapping.champs["metadonnees.sujets"]
    assert isinstance(sujets, MappingAgrege)
    assert sujets.sources == ["sujet 1_fr", "sujet 2_fr", "sujet 3_fr"]
    assert sujets.separateur_sortie == " | "
    createurs = p.mapping.champs["metadonnees.createurs"]
    assert isinstance(createurs, MappingAgrege)
    assert createurs.separateur_sortie == " / "
    # Clé source sous forme d'URI — doit fonctionner tel quel.
    assert p.mapping.champs["cote"].source == "http://purl.org/dc/terms/identifier"


def test_les_trois_formes_coexistent() -> None:
    # Le profil cas_item_simple contient Forme 1 (str) et Forme 2 (objet
    # avec source+separateur). cas_uri_dc contient Forme 3 (sources).
    # Vérification croisée que les trois formes se côtoient sans
    # collision dans le discriminateur `_parse_mapping_champ`.
    p_simple = charger_profil(FIXTURES / "cas_item_simple" / "profil.yaml")
    p_uri = charger_profil(FIXTURES / "cas_uri_dc" / "profil.yaml")
    assert isinstance(p_simple.mapping.champs["cote"], MappingSimple)
    assert isinstance(
        p_simple.mapping.champs["metadonnees.collaborateurs"], MappingTransforme
    )
    assert isinstance(p_uri.mapping.champs["metadonnees.sujets"], MappingAgrege)


def test_chemin_tableur_resolu_relativement_au_profil(tmp_path: Path) -> None:
    # On duplique le profil à un endroit arbitraire avec son CSV ;
    # charger_profil doit résoudre le chemin du tableur depuis le
    # dossier du profil, pas depuis le cwd.
    destination = tmp_path / "ailleurs"
    destination.mkdir()
    source = FIXTURES / "cas_item_simple"
    (destination / "profil.yaml").write_bytes((source / "profil.yaml").read_bytes())
    (destination / "tableur.csv").write_bytes((source / "tableur.csv").read_bytes())

    p = charger_profil(destination / "profil.yaml")
    assert Path(p.tableur.chemin) == (destination / "tableur.csv").resolve()


# -------- Erreurs --------


INVALIDES = FIXTURES / "invalides"


def test_version_absente() -> None:
    with pytest.raises(ProfilInvalide) as exc:
        charger_profil(INVALIDES / "version_absente.yaml")
    assert "version_profil" in str(exc.value)


def test_version_future() -> None:
    with pytest.raises(ProfilInvalide) as exc:
        charger_profil(INVALIDES / "version_future.yaml")
    # Le message doit pointer sur la version.
    assert "version_profil" in str(exc.value)


def test_cle_inconnue_dans_collection() -> None:
    with pytest.raises(ProfilInvalide) as exc:
        charger_profil(INVALIDES / "cle_mal_orthographiee.yaml")
    # Pydantic remonte l'identité de la clé fautive.
    assert "eitdeur" in str(exc.value)


def test_regex_cassee() -> None:
    with pytest.raises(ProfilInvalide) as exc:
        charger_profil(INVALIDES / "regex_cassee.yaml")
    assert "regex" in str(exc.value).lower()


def test_granularite_fichier_sans_cote() -> None:
    with pytest.raises(ProfilInvalide) as exc:
        charger_profil(INVALIDES / "fichier_sans_cote.yaml")
    assert "cote" in str(exc.value).lower()
