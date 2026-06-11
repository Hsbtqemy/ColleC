"""Tests de l'aplatisseur de dépôt Nakala (P2/A2) — porté de madbot."""

from __future__ import annotations

import pytest

from archives_tool.external.nakala.depot_mapper import (
    MetaInvalide,
    parse_creator,
    parse_created,
    slugs_vers_metas,
    slugs_inconnus,
)

_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"


def _uris(metas: list[dict]) -> list[str]:
    return [m["propertyUri"] for m in metas]


def test_parse_creator_structure() -> None:
    assert parse_creator("Cortázar, Julio [0000-0002-1825-0097]") == {
        "surname": "Cortázar",
        "givenname": "Julio",
        "orcid": "0000-0002-1825-0097",
    }
    assert parse_creator("Somers, Armonía") == {
        "surname": "Somers",
        "givenname": "Armonía",
    }


def test_parse_creator_anonyme() -> None:
    for v in (None, "[s.n.]", "anonyme"):
        assert parse_creator(v) is None


def test_parse_creator_invalide_leve() -> None:
    with pytest.raises(MetaInvalide):
        parse_creator("juste un nom sans virgule")


def test_parse_created_inconnu() -> None:
    for v in (None, "[s.d.]", "inconnue"):
        assert parse_created(v) is None
    assert parse_created("1984-12") == "1984-12"


def test_creator_et_created_emettent_toujours_une_meta() -> None:
    # Champs obligatoires niveau dépôt : meta présente même si null.
    metas = slugs_vers_metas({"nkl_creator": None, "nkl_created": None})
    assert {f"{_NKL}creator", f"{_NKL}created"} <= set(_uris(metas))
    for m in metas:
        assert m["value"] is None


def test_multilingue_titre_et_description() -> None:
    metas = slugs_vers_metas({
        "nkl_title": [{"value": "Titre", "lang": "fr"}, {"value": "Title", "lang": "en"}],
        "dcterms_description": [{"value": "Desc", "lang": "fr"}],
    })
    titres = [m for m in metas if m["propertyUri"] == f"{_NKL}title"]
    assert len(titres) == 2
    assert titres[0]["lang"] == "fr" and titres[1]["lang"] == "en"


def test_creator_liste_et_sujets() -> None:
    metas = slugs_vers_metas({
        "nkl_creator": ["Somers, Armonía", "[s.n.]"],
        "dcterms_subject": [{"value": "Littérature", "lang": "es"}],
        "dcterms_language": ["spa", "fra"],
    })
    creators = [m for m in metas if m["propertyUri"] == f"{_NKL}creator"]
    assert creators[0]["value"] == {"surname": "Somers", "givenname": "Armonía"}
    assert creators[1]["value"] is None  # [s.n.] → null
    langs = [m["value"] for m in metas if m["propertyUri"] == f"{_DCT}language"]
    assert langs == ["spa", "fra"]


def test_scalaires_type_license() -> None:
    metas = slugs_vers_metas({
        "nkl_type": "http://purl.org/coar/resource_type/c_2f33",
        "nkl_license": "CC-BY-4.0",
    })
    by = {m["propertyUri"]: m for m in metas}
    assert by[f"{_NKL}type"]["value"].endswith("c_2f33")
    assert by[f"{_NKL}type"]["typeUri"] == "http://www.w3.org/2001/XMLSchema#anyURI"
    assert by[f"{_NKL}license"]["value"] == "CC-BY-4.0"


def test_spatial_point_en_dcsv() -> None:
    metas = slugs_vers_metas({
        "dcterms_spatial": [{"kind": "Point", "east": "2.35", "north": "48.85",
                             "name": "Paris", "lang": "fr"}],
    })
    m = [m for m in metas if m["propertyUri"] == f"{_DCT}spatial"][0]
    assert "east=2.35" in m["value"] and "north=48.85" in m["value"]
    assert m["typeUri"] == "http://purl.org/dc/terms/Point"
    assert m["lang"] == "fr"


def test_temporal_periode_en_dcsv() -> None:
    metas = slugs_vers_metas({
        "dcterms_temporal": [{"start": "1960", "end": "1969", "name": "60s", "lang": "fr"}],
    })
    m = [m for m in metas if m["propertyUri"] == f"{_DCT}temporal"][0]
    assert "start=1960" in m["value"] and "end=1969" in m["value"]
    assert m["typeUri"] == "http://purl.org/dc/terms/Period"


def test_slug_inconnu_ignore() -> None:
    metas = slugs_vers_metas({"champ_bidon": "x", "nkl_title": [{"value": "T", "lang": "fr"}]})
    assert _uris(metas) == [f"{_NKL}title"]
    assert slugs_inconnus({"champ_bidon": "x", "nkl_title": []}) == ["champ_bidon"]


def test_dcterms_dates_et_relations() -> None:
    metas = slugs_vers_metas({
        "dcterms_isPartOf": ["Collection mère"],
        "dcterms_issued": ["1984"],
    })
    by = {m["propertyUri"]: m for m in metas}
    assert by[f"{_DCT}isPartOf"]["value"] == "Collection mère"
    assert by[f"{_DCT}issued"]["typeUri"] == "http://purl.org/dc/terms/W3CDTF"
