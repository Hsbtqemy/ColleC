"""Tests des vocabulaires Nakala snapshotés + résolution de libellé langue.

Données vendorisées sous `archives_tool/reference/vocabulaires_nakala/`
(cf. PROVENANCE.md). Couvre les loaders et la cascade `libelle_langue`,
y compris l'impédance de schéma ISO 639-1 (Nakala majeurs) vs 639-3
(stockage ColleC).
"""

from __future__ import annotations

from archives_tool.api.services.vocabulaires import (
    TYPES_COAR_OPTIONS,
    libelle_langue,
    normaliser_type_coar,
    resoudre_vocabulaire,
    type_coar_pour_nakala,
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


# ---------------------------------------------------------------------------
# COAR : vocabulaire interne corrigé + projection vers le set Nakala
# ---------------------------------------------------------------------------


def test_tous_types_internes_projettent_vers_set_nakala() -> None:
    """Invariant de sûreté du dépôt : chaque type COAR interne se projette
    (directement ou via la carte) vers une URI acceptée par Nakala."""
    nset = set(types_coar_nakala())
    for uri, label in TYPES_COAR_OPTIONS:
        projete = type_coar_pour_nakala(uri)
        assert projete in nset, f"{label} ({uri}) ne projette pas vers Nakala"


def test_type_coar_pour_nakala_cas() -> None:
    C = "http://purl.org/coar/resource_type"
    # Les 3 extras (genres COAR valides hors set Nakala) → projetés.
    assert type_coar_pour_nakala(f"{C}/c_ecc8") == f"{C}/c_c513"  # Photo → image
    assert type_coar_pour_nakala(f"{C}/c_3248") == f"{C}/c_18cf"  # Chapitre → texte
    assert (
        type_coar_pour_nakala(f"{C}/c_8042") == f"{C}/c_816b"
    )  # Doc travail → préprint
    # Type déjà accepté Nakala → inchangé (identité).
    assert type_coar_pour_nakala(f"{C}/c_2fe3") == f"{C}/c_2fe3"  # Périodique
    assert type_coar_pour_nakala(f"{C}/c_18cf") == f"{C}/c_18cf"  # Texte
    # Inconnu / non projetable → None.
    assert type_coar_pour_nakala(f"{C}/c_zzzz") is None
    assert type_coar_pour_nakala(None) is None


def test_normaliser_type_coar_pointe_vers_uris_corrigees() -> None:
    """Les alias textuels résolvent vers les URIs internes corrigées."""
    valides = {uri for uri, _ in TYPES_COAR_OPTIONS}
    for terme in ["journal", "périodique", "carte", "vidéo", "manuscrit", "photo"]:
        uri = normaliser_type_coar(terme)
        assert uri in valides, f"{terme} → {uri} hors vocabulaire interne"
    C = "http://purl.org/coar/resource_type"
    assert normaliser_type_coar("carte") == f"{C}/c_12cd"
    assert normaliser_type_coar("vidéo") == f"{C}/c_12ce"
    assert normaliser_type_coar("manuscrit") == f"{C}/c_0040"
