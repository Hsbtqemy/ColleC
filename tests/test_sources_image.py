"""Tests de la résolution de source d'image pour la visionneuse."""

from __future__ import annotations

from archives_tool.api.services.sources_image import resoudre_source_image
from archives_tool.models import Fichier


def _f(**kwargs) -> Fichier:
    base = dict(
        item_id=1,
        racine="src",
        chemin_relatif="x.png",
        nom_fichier="x.png",
        ordre=1,
    )
    base.update(kwargs)
    return Fichier(**base)


def test_priorite_iiif_si_disponible() -> None:
    fichier = _f(
        iiif_url_nakala="https://api.nakala.fr/iiif/.../info.json",
        apercu_chemin="apercu/x.jpg",
        vignette_chemin="vignette/x.jpg",
    )
    src = resoudre_source_image(fichier)
    assert src.primary == {
        "type": "iiif",
        "url": "https://api.nakala.fr/iiif/.../info.json",
    }
    # Le fallback est l'aperçu local.
    assert src.fallback is not None
    assert src.fallback["type"] == "image"
    assert src.fallback["url"] == "/derives/miniatures/apercu/x.jpg"
    assert src.vignette_url == "/derives/miniatures/vignette/x.jpg"


def test_apercu_seul_quand_pas_de_iiif() -> None:
    fichier = _f(apercu_chemin="apercu/x.jpg", vignette_chemin="vignette/x.jpg")
    src = resoudre_source_image(fichier)
    assert src.primary == {"type": "image", "url": "/derives/miniatures/apercu/x.jpg"}
    assert src.fallback is None
    assert src.vignette_url == "/derives/miniatures/vignette/x.jpg"


def test_aucune_source() -> None:
    fichier = _f()
    src = resoudre_source_image(fichier)
    assert src.primary is None
    assert src.fallback is None
    assert src.vignette_url is None


def test_dzi_priorite_intermediaire() -> None:
    fichier = _f(
        dzi_chemin="dzi/x.dzi",
        apercu_chemin="apercu/x.jpg",
    )
    src = resoudre_source_image(fichier)
    assert src.primary == {"type": "dzi", "url": "/derives/miniatures/dzi/x.dzi"}
    assert src.fallback == {
        "type": "image",
        "url": "/derives/miniatures/apercu/x.jpg",
    }
