"""Tests isolés de `rapport.verifier_pre_export`."""

from __future__ import annotations

from archives_tool.exporters.rapport import RapportExport, verifier_pre_export
from archives_tool.models import Collection, Item


def _item(**kwargs) -> Item:
    base = {
        "collection": Collection(
            cote_collection=f"T-{kwargs.get('cote', 'X')}", titre="T"
        ),
        "cote": "X",
    }
    base.update(kwargs)
    return Item(**base)


def test_tous_champs_obligatoires_presents() -> None:
    items = [_item(cote="A", titre="Un", date="1923")]
    rapport = verifier_pre_export(items, ["cote", "titre", "date"], format="test")
    assert rapport.items_incomplets == []
    assert rapport.nb_items_selectionnes == 1


def test_item_manquant_plusieurs_champs() -> None:
    items = [_item(cote="B", titre=None, date=None)]
    rapport = verifier_pre_export(items, ["titre", "date"], format="test")
    assert rapport.items_incomplets == [("B", ["titre", "date"])]


def test_chaine_vide_compte_comme_absente() -> None:
    items = [_item(cote="C", titre="   ", date="1923")]
    rapport = verifier_pre_export(items, ["titre"], format="test")
    assert rapport.items_incomplets == [("C", ["titre"])]


def test_type_coar_hors_uri_signale() -> None:
    items = [_item(cote="D", titre="T", type_coar="article")]  # pas une URI
    rapport = verifier_pre_export(items, [], format="test")
    assert ("type_coar", "article") in rapport.valeurs_non_mappees


def test_type_coar_uri_valide_ok() -> None:
    items = [
        _item(
            cote="E",
            titre="T",
            type_coar="http://purl.org/coar/resource_type/c_2fe3",
        )
    ]
    rapport = verifier_pre_export(items, [], format="test")
    assert rapport.valeurs_non_mappees == []


def test_langue_hors_iso_signale() -> None:
    items = [_item(cote="F", titre="T", langue="français")]
    rapport = verifier_pre_export(items, [], format="test")
    assert ("langue", "français") in rapport.valeurs_non_mappees


def test_langue_iso_639_3_ok() -> None:
    items = [_item(cote="G", titre="T", langue="fra")]
    rapport = verifier_pre_export(items, [], format="test")
    assert rapport.valeurs_non_mappees == []


def test_rapport_format_transmis() -> None:
    r = verifier_pre_export([], [], format="dc_xml")
    assert isinstance(r, RapportExport)
    assert r.format == "dc_xml"
    assert r.nb_items_selectionnes == 0
