"""Tests des vocabulaires et helpers (V0.9.2-import #2 type COAR auto)."""

from __future__ import annotations

from archives_tool.api.services.vocabulaires import normaliser_type_coar


def test_normaliser_type_coar_journal() -> None:
    assert normaliser_type_coar("journal") == (
        "http://purl.org/coar/resource_type/c_3e5a"
    )


def test_normaliser_type_coar_periodique_avec_accent() -> None:
    """Les accents sont normalisés (NFD + drop diacritiques)."""
    assert normaliser_type_coar("périodique") == (
        "http://purl.org/coar/resource_type/c_3e5a"
    )
    assert normaliser_type_coar("Périodique") == (
        "http://purl.org/coar/resource_type/c_3e5a"
    )


def test_normaliser_type_coar_numero_de_periodique() -> None:
    """Expression multi-mots reconnue."""
    assert normaliser_type_coar("numéro de périodique") == (
        "http://purl.org/coar/resource_type/c_0640"
    )
    assert normaliser_type_coar("Numero de Periodique") == (
        "http://purl.org/coar/resource_type/c_0640"
    )


def test_normaliser_type_coar_uri_canonique_inchangee() -> None:
    """Si la valeur est déjà une URI COAR, retourne `None` — le caller
    garde la valeur brute (pas besoin de re-mapper)."""
    assert normaliser_type_coar("http://purl.org/coar/resource_type/c_3e5a") is None


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
    cases = {
        "revue": "c_3e5a",
        "magazine": "c_3e5a",
        "issue": "c_0640",
        "article": "c_6501",
        "livre": "c_2f33",
        "book": "c_2f33",
        "chapitre": "c_3248",
        "manuscrit": "c_8a7e",
        "photo": "c_18cd",
        "carte": "c_ecc8",
        "video": "c_12cd",
        "audio": "c_18cc",
    }
    for libelle, code in cases.items():
        uri = normaliser_type_coar(libelle)
        assert uri is not None, f"Pas d'URI pour {libelle!r}"
        assert uri.endswith("/" + code), (
            f"{libelle!r} → {uri!r}, attendu code {code!r}"
        )
