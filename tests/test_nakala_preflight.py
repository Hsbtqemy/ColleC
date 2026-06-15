"""Tests de la cascade pré-dépôt Nakala (P2/A3)."""

from __future__ import annotations

import pytest

from archives_tool.external.nakala.depot_mapper import MetaInvalide
from archives_tool.external.nakala.preflight import (
    URI_DC_CONTRIBUTOR,
    URI_DC_CREATOR,
    URI_DC_DATE,
    URI_NKL_CREATED,
    URI_NKL_CREATOR,
    preflight_appliquer,
)


def _m(uri: str, value: object, typ: str | None = None) -> dict:
    d: dict = {"propertyUri": uri, "value": value}
    if typ:
        d["typeUri"] = typ
    return d


def _createurs(metas: list[dict]) -> list[object]:
    return [m["value"] for m in metas if m["propertyUri"] == URI_NKL_CREATOR]


def test_rien_a_faire_si_creator_et_created_presents() -> None:
    metas = [
        _m(URI_NKL_CREATOR, {"surname": "S", "givenname": "A"}),
        _m(URI_NKL_CREATED, "1984"),
    ]
    out, warns = preflight_appliquer(list(metas))
    assert warns == []
    assert _createurs(out) == [{"surname": "S", "givenname": "A"}]


def test_promotion_creator_depuis_dcterms() -> None:
    metas = [
        _m(URI_NKL_CREATOR, None),
        _m(URI_DC_CREATOR, "Somers, Armonía"),
        _m(URI_NKL_CREATED, "1984"),
    ]
    out, warns = preflight_appliquer(metas)
    assert any("Auto-promotion" in w and "creator" in w for w in warns)
    # nkl:creator devient l'objet structuré, dcterms:creator conservé.
    assert {"surname": "Somers", "givenname": "Armonía"} in _createurs(out)
    assert any(m["propertyUri"] == URI_DC_CREATOR for m in out)


def test_creator_null_accepte_si_contributeur_present() -> None:
    metas = [
        _m(URI_NKL_CREATOR, None),
        _m(URI_DC_CONTRIBUTOR, "Éditeur : X"),
        _m(URI_NKL_CREATED, "1984"),
    ]
    out, warns = preflight_appliquer(metas)
    # Pas de promotion (contributeur non promouvable), mais accepté ; nkl:creator null conservé.
    assert None in _createurs(out)


def test_creator_null_sans_tracabilite_leve() -> None:
    metas = [_m(URI_NKL_CREATOR, None), _m(URI_NKL_CREATED, "1984")]
    with pytest.raises(MetaInvalide) as exc:
        preflight_appliquer(metas)
    # T1 : le message doit signaler que c'est une règle ColleC, pas une
    # exigence Nakala (Nakala accepte un dépôt sans créateur).
    msg = str(exc.value)
    assert "ColleC" in msg and "Nakala" in msg


def test_promotion_created_depuis_dcterms_date() -> None:
    metas = [
        _m(URI_NKL_CREATOR, {"surname": "S", "givenname": "A"}),
        _m(URI_NKL_CREATED, None),
        _m(URI_DC_DATE, "1969-09"),
    ]
    out, warns = preflight_appliquer(metas)
    assert any("created" in w for w in warns)
    createds = [m["value"] for m in out if m["propertyUri"] == URI_NKL_CREATED]
    assert "1969-09" in createds


def test_created_null_sans_date_leve() -> None:
    metas = [
        _m(URI_NKL_CREATOR, {"surname": "S", "givenname": "A"}),
        _m(URI_NKL_CREATED, None),
    ]
    with pytest.raises(MetaInvalide) as exc:
        preflight_appliquer(metas)
    # T1 : message explicite « règle ColleC, pas exigence Nakala ».
    msg = str(exc.value)
    assert "ColleC" in msg and "Nakala" in msg
