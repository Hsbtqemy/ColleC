"""Tests des utilitaires de mapping DC (`extraire_valeur`, `valeur_en_liste`).

Couverture unitaire **unique** : la branche imbriquée d'`extraire_valeur`
(`metadonnees.hierarchie.fonds`) et les cas-limites de `valeur_en_liste`
(scalaire non-str, filtrage des None, tri) ne sont exercés qu'ici.

Migré V0.9.0 (2026-06-18) : `extraire_valeur` ne lit que les attributs de
l'item et `metadonnees` — item construit en mémoire, sans relation
`collection` (le helper d'origine utilisait le champ supprimé
`Collection.cote_collection`)."""

from __future__ import annotations

from archives_tool.exporters.mapping_dc import (
    DC,
    MAPPING_DC,
    extraire_valeur,
    valeur_en_liste,
)
from archives_tool.models import Item


def _item_synthetique() -> Item:
    return Item(
        cote="T-1",
        titre="Un titre",
        date="1923",
        langue="fra",
        metadonnees={
            "auteurs": ["Dupont", "Martin"],
            "sujets": "Histoire | Gastronomie",
            "hierarchie": {"fonds": "FA", "serie": "01"},
        },
    )


def test_mapping_couvre_colonnes_et_metadonnees() -> None:
    assert MAPPING_DC["cote"] == f"{DC}identifier"
    assert MAPPING_DC["titre"] == f"{DC}title"
    assert MAPPING_DC["metadonnees.auteurs"] == f"{DC}creator"


def test_extraire_colonne_dediee() -> None:
    item = _item_synthetique()
    assert extraire_valeur(item, "cote") == "T-1"
    assert extraire_valeur(item, "titre") == "Un titre"


def test_extraire_metadonnees_plat() -> None:
    item = _item_synthetique()
    assert extraire_valeur(item, "metadonnees.auteurs") == ["Dupont", "Martin"]
    assert extraire_valeur(item, "metadonnees.sujets") == "Histoire | Gastronomie"


def test_extraire_metadonnees_imbriquees() -> None:
    item = _item_synthetique()
    # Accès à un champ de hierarchie via "metadonnees.hierarchie.fonds".
    assert extraire_valeur(item, "metadonnees.hierarchie.fonds") == "FA"
    assert extraire_valeur(item, "metadonnees.hierarchie.serie") == "01"


def test_extraire_absent_retourne_none() -> None:
    item = _item_synthetique()
    assert extraire_valeur(item, "description") is None
    assert extraire_valeur(item, "metadonnees.absent") is None
    assert extraire_valeur(item, "metadonnees.hierarchie.absent") is None


def test_valeur_en_liste() -> None:
    assert valeur_en_liste(None) == []
    assert valeur_en_liste("") == []
    assert valeur_en_liste("  ") == []
    assert valeur_en_liste("unique") == ["unique"]
    # Tri alphabétique pour reproductibilité.
    assert valeur_en_liste(["Martin", "Dupont"]) == ["Dupont", "Martin"]
    assert valeur_en_liste([None, "X", "  ", "A"]) == ["A", "X"]
    # Scalaire non-str : converti.
    assert valeur_en_liste(42) == ["42"]
