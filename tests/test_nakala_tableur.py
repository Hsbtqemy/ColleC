"""Tests de l'aplatisseur tableur Nakala (Lot 1, T1.2) — fonctions pures."""

from __future__ import annotations

from archives_tool.external.nakala.tableur import (
    lignes_niveau_donnee,
    lignes_niveau_fichier,
)

_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"


def _donnee(
    metas: list[dict], *, ident: str = "d1", files: list[dict] | None = None
) -> dict:
    return {
        "identifier": ident,
        "uri": f"https://nakala.fr/{ident}",
        "status": "published",
        "version": 1,
        "metas": metas,
        "files": files or [],
    }


def test_niveau_donnee_une_ligne_par_donnee_et_colonnes_fixes() -> None:
    d = _donnee(
        [
            {"propertyUri": f"{_NKL}title", "value": "Titre", "lang": None},
            {"propertyUri": f"{_NKL}created", "value": "1984"},
        ]
    )
    t = lignes_niveau_donnee([d])
    assert len(t.lignes) == 1
    for col in ("identifier", "uri", "status", "version"):
        assert col in t.colonnes
    ligne = t.lignes[0]
    assert ligne["identifier"] == "d1"
    assert ligne["nkl:title"] == "Titre"
    assert ligne["nkl:created"] == "1984"


def test_valeurs_multiples_jointes_pipe() -> None:
    d = _donnee(
        [
            {"propertyUri": f"{_DCT}subject", "value": "A"},
            {"propertyUri": f"{_DCT}subject", "value": "B"},
            {"propertyUri": f"{_DCT}subject", "value": "C"},
        ]
    )
    t = lignes_niveau_donnee([d])
    assert t.lignes[0]["dcterms:subject"] == "A | B | C"


def test_createur_structure_et_lang() -> None:
    d = _donnee(
        [
            {
                "propertyUri": f"{_NKL}creator",
                "value": {
                    "surname": "Cortázar",
                    "givenname": "Julio",
                    "orcid": "0000-1",
                },
            },
            {"propertyUri": f"{_DCT}title", "value": "Título", "lang": "es"},
        ]
    )
    t = lignes_niveau_donnee([d])
    assert t.lignes[0]["nkl:creator"] == "Cortázar, Julio [0000-1]"
    assert t.lignes[0]["dcterms:title"] == "[es] Título"


def test_createur_orcid_url_rendu_nu() -> None:
    """L'export tableur normalise l'ORCID en forme nue (cohérent avec la
    fiche item et le diff — Nakala le stocke en URL)."""
    d = _donnee(
        [
            {
                "propertyUri": f"{_NKL}creator",
                "value": {
                    "surname": "Cortázar",
                    "givenname": "Julio",
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                },
            },
        ]
    )
    t = lignes_niveau_donnee([d])
    assert t.lignes[0]["nkl:creator"] == "Cortázar, Julio [0000-0001-2345-6789]"


def test_union_colonnes_ordre_prefere() -> None:
    # Deux données aux propriétés disjointes : l'union couvre les deux,
    # avec les nkl: avant les dcterms:.
    d1 = _donnee([{"propertyUri": f"{_NKL}title", "value": "T"}], ident="d1")
    d2 = _donnee([{"propertyUri": f"{_DCT}subject", "value": "S"}], ident="d2")
    t = lignes_niveau_donnee([d1, d2])
    assert "nkl:title" in t.colonnes and "dcterms:subject" in t.colonnes
    assert t.colonnes.index("nkl:title") < t.colonnes.index("dcterms:subject")
    # La donnée d1 n'a pas de dcterms:subject → cellule absente/vide.
    assert t.lignes[0].get("dcterms:subject", "") == ""


def test_niveau_fichier_repete_donnee_et_ajoute_colonnes_fichier() -> None:
    files = [
        {
            "name": "p1.jpg",
            "extension": "jpg",
            "size": "123",
            "mime_type": "image/jpeg",
            "sha1": "aaa",
            "embargoed": "2023-06-16T00:00:00+02:00",
            "description": "couv",
            "puid": "fmt/1507",
            "format": "JPEG",
        },
        {
            "name": "p2.jpg",
            "extension": "jpg",
            "size": "456",
            "mime_type": "image/jpeg",
            "sha1": "bbb",
            "embargoed": None,
            "description": "",
            "puid": "fmt/1507",
            "format": "JPEG",
        },
    ]
    d = _donnee([{"propertyUri": f"{_NKL}title", "value": "Titre"}], files=files)
    t = lignes_niveau_fichier([d])
    assert len(t.lignes) == 2  # une ligne par fichier
    for col in (
        "fichier_nom",
        "fichier_sha1",
        "fichier_mime",
        "fichier_taille",
        "fichier_embargo",
        "fichier_extension",
        "fichier_description",
        "fichier_puid",
        "fichier_format",
    ):
        assert col in t.colonnes
    # Métadonnées donnée recopiées sur chaque ligne fichier.
    assert t.lignes[0]["nkl:title"] == "Titre"
    assert t.lignes[1]["nkl:title"] == "Titre"
    assert t.lignes[0]["fichier_nom"] == "p1.jpg"
    assert t.lignes[0]["fichier_sha1"] == "aaa"
    assert t.lignes[1]["fichier_nom"] == "p2.jpg"


def test_niveau_fichier_donnee_sans_fichier_donne_une_ligne_vide() -> None:
    d = _donnee([{"propertyUri": f"{_NKL}title", "value": "Titre"}], files=[])
    t = lignes_niveau_fichier([d])
    assert len(t.lignes) == 1  # la donnée n'est pas perdue
    assert t.lignes[0]["nkl:title"] == "Titre"
    assert t.lignes[0].get("fichier_nom", "") == ""
