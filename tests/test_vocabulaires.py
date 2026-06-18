"""Tests des vocabulaires et helpers (V0.9.2-import #2 type COAR auto)."""

from __future__ import annotations

from archives_tool.api.services.vocabulaires import normaliser_type_coar


def test_normaliser_type_coar_journal() -> None:
    # URI Périodique corrigée V0.9.10 : c_3e5a (invalide) → c_2fe3.
    assert normaliser_type_coar("journal") == (
        "http://purl.org/coar/resource_type/c_2fe3"
    )


def test_normaliser_type_coar_periodique_avec_accent() -> None:
    """Les accents sont normalisés (NFD + drop diacritiques)."""
    assert normaliser_type_coar("périodique") == (
        "http://purl.org/coar/resource_type/c_2fe3"
    )
    assert normaliser_type_coar("Périodique") == (
        "http://purl.org/coar/resource_type/c_2fe3"
    )


def test_normaliser_type_coar_numero_de_periodique() -> None:
    """Expression multi-mots reconnue. V0.9.10 : « numéro » est replié
    sur Périodique (c_2fe3) — un numéro est un Item dans un Fonds, pas
    un type COAR distinct (COAR n'a d'ailleurs pas de « journal issue »)."""
    assert normaliser_type_coar("numéro de périodique") == (
        "http://purl.org/coar/resource_type/c_2fe3"
    )
    assert normaliser_type_coar("Numero de Periodique") == (
        "http://purl.org/coar/resource_type/c_2fe3"
    )


def test_normaliser_type_coar_uri_canonique_inchangee() -> None:
    """Si la valeur est déjà une URI COAR, retourne `None` — le caller
    garde la valeur brute (pas besoin de re-mapper)."""
    assert normaliser_type_coar("http://purl.org/coar/resource_type/c_2fe3") is None


def test_normaliser_type_coar_inconnu() -> None:
    """Libellé inconnu : retourne `None`, le caller gardera la valeur
    brute (l'utilisateur pourra éditer via inline)."""
    assert normaliser_type_coar("foobar") is None
    assert normaliser_type_coar("monographie de la salle 7") is None


def test_normaliser_type_coar_vide() -> None:
    assert normaliser_type_coar("") is None
    assert normaliser_type_coar("   ") is None
    assert normaliser_type_coar(None) is None
    assert normaliser_type_coar(42) is None  # type-safe


def test_normaliser_type_coar_alias_variantes() -> None:
    """Couvre les principaux alias multilingues et synonymes."""
    # URIs corrigées V0.9.10 (cf. nakala-depot-future.md).
    cases = {
        "revue": "c_2fe3",
        "magazine": "c_2fe3",
        "issue": "c_2fe3",
        "article": "c_6501",
        "livre": "c_2f33",
        "book": "c_2f33",
        "chapitre": "c_3248",
        "manuscrit": "c_0040",
        "photo": "c_ecc8",
        "carte": "c_12cd",
        "video": "c_12ce",
        "audio": "c_18cc",
    }
    for libelle, code in cases.items():
        uri = normaliser_type_coar(libelle)
        assert uri is not None, f"Pas d'URI pour {libelle!r}"
        assert uri.endswith("/" + code), f"{libelle!r} → {uri!r}, attendu code {code!r}"
