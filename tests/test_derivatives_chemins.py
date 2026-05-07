"""Tests de la convention de chemins des dérivés."""

from __future__ import annotations

from archives_tool.derivatives.chemins import chemin_derive


def test_chemin_simple() -> None:
    assert chemin_derive("01.png", "vignette") == "vignette/01.jpg"


def test_chemin_avec_sous_dossier() -> None:
    assert chemin_derive("HK/01.png", "vignette") == "vignette/HK/01.jpg"


def test_chemin_imbrique() -> None:
    assert (
        chemin_derive("FA/serie-01/numero-01.tiff", "apercu")
        == "apercu/FA/serie-01/numero-01.jpg"
    )


def test_extension_remplacee() -> None:
    # source en TIFF → dérivé en JPG.
    assert chemin_derive("scan.TIF", "vignette").endswith(".jpg")
    assert chemin_derive("scan.pdf", "apercu").endswith(".jpg")
