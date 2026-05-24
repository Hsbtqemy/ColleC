"""Tests des helpers Nakala (`files/nakala.py`)."""

from __future__ import annotations

from archives_tool.files.nakala import vers_data, vers_iiif_info_json

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DOI = "10.34847/nkl.abc"


def test_vers_iiif_info_json_depuis_data() -> None:
    src = f"https://api.nakala.fr/data/{DOI}/{SHA}"
    assert vers_iiif_info_json(src) == (
        f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    )


def test_vers_iiif_info_json_depuis_thumb() -> None:
    """Pattern `thumb` = `/iiif/<doi>/<sha>/full/!200,200/0/default.jpg`
    — on extrait juste la base et reconstruit info.json."""
    src = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/full/!200,200/0/default.jpg"
    assert vers_iiif_info_json(src) == (
        f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    )


def test_vers_iiif_info_json_hostname_preserve() -> None:
    src = f"https://api-test.nakala.fr/data/{DOI}/{SHA}"
    assert vers_iiif_info_json(src) == (
        f"https://api-test.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    )


def test_vers_iiif_info_json_non_nakala_inchangee() -> None:
    for url in (
        "https://example.com/image.jpg",
        f"https://evil-nakala.fr/data/{DOI}/{SHA}",  # faux positif domain
        f"https://nakala.fr.attacker.com/data/{DOI}/{SHA}",
    ):
        assert vers_iiif_info_json(url) == url


def test_vers_data_depuis_iiif_info_json() -> None:
    """Inverse de vers_iiif_info_json — récupère l'URL data binaire
    depuis l'URL IIIF info.json. Sert au bouton « Télécharger » de
    la visionneuse pour les Fichier Nakala-only (sinon la route
    locale `/item/.../fichiers/<id>` retournerait 404)."""
    src = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    assert vers_data(src) == f"https://api.nakala.fr/data/{DOI}/{SHA}"


def test_vers_data_depuis_iiif_image_full() -> None:
    """Une URL IIIF image (full/...) est aussi convertible — on
    extrait `(doi, sha)` et on reconstruit `/data/`."""
    src = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/full/!200,200/0/default.jpg"
    assert vers_data(src) == f"https://api.nakala.fr/data/{DOI}/{SHA}"


def test_vers_data_depuis_data_url_inchangee() -> None:
    """Si déjà une URL data, on l'extrait et la reconstruit
    identique."""
    src = f"https://api.nakala.fr/data/{DOI}/{SHA}"
    assert vers_data(src) == src


def test_vers_data_hostname_preserve() -> None:
    src = f"https://api-test.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    assert vers_data(src) == f"https://api-test.nakala.fr/data/{DOI}/{SHA}"


def test_vers_data_non_nakala_retourne_none() -> None:
    """Si pas une URL Nakala reconnue, retourne `None` — le caller
    doit fallback (route locale, message…)."""
    for url in (
        "https://example.com/image.jpg",
        f"https://evil-nakala.fr/iiif/{DOI}/{SHA}/info.json",
        "",
    ):
        assert vers_data(url) is None
