"""Tests des vocabulaires Nakala snapshotés + résolution de libellé langue.

Données vendorisées sous `archives_tool/reference/vocabulaires_nakala/`
(cf. PROVENANCE.md). Couvre les loaders et la cascade `libelle_langue`,
y compris l'impédance de schéma ISO 639-1 (Nakala majeurs) vs 639-3
(stockage ColleC).
"""

from __future__ import annotations

from archives_tool.api.services.vocabulaires import (
    libelle_langue,
    resoudre_vocabulaire,
)
from archives_tool.reference.loaders import (
    langues_iso639,
    licences_spdx,
    types_coar_nakala,
)


def test_loaders_chargent_les_snapshots() -> None:
    assert len(langues_iso639()) > 8000
    assert len(types_coar_nakala()) == 29
    assert len(licences_spdx()) > 600
    # Forme des entrées.
    coar = types_coar_nakala()
    une = next(iter(coar.values()))
    assert {"uri", "en", "fr"} <= set(une)


def test_libelle_langue_curee_prioritaire() -> None:
    # Code de la liste curée : libellé FR du dropdown.
    assert libelle_langue("fra") == "Français"
    assert libelle_langue("spa") == "Espagnol"


def test_libelle_langue_longue_traine_iso639_3() -> None:
    # Codes 639-3 de la longue traîne, hors liste curée, présents dans
    # le snapshot Nakala → résolus depuis la table complète.
    assert libelle_langue("cmn") == "Mandarin Chinese"
    assert libelle_langue("alu") == "'Are'are"


def test_libelle_langue_inconnu_retourne_brut() -> None:
    assert libelle_langue("zzz") == "zzz"
    assert libelle_langue(None) is None


def test_libelle_langue_impedance_schema_majeurs_639_3() -> None:
    """Documente l'impédance : un majeur en 639-3 hors liste curée ne
    résout pas via le snapshot (Nakala stocke ces majeurs en 639-1).
    `ron` (roumain 639-3) absent → code brut ; `ro` (639-1) résout."""
    assert libelle_langue("ron") == "ron"  # 639-3 majeur, non curé → brut
    assert libelle_langue("ro") == "Romanian"  # 639-1, présent dans Nakala


def test_resoudre_vocabulaire_langue_garde_options_curees() -> None:
    """Le dropdown reste la liste curée (raisonnable), mais le libellé
    est résolu sur la table complète."""
    options, libelle = resoudre_vocabulaire("langue", "cmn")
    assert options is not None  # liste curée pour le <select>
    assert ("fra", "Français") in options
    assert libelle == "Mandarin Chinese"  # résolu hors liste curée
