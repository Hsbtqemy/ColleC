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


def test_vignette_fallback_nakala_si_pas_de_locale() -> None:
    """#1 V0.9.2-import : pour un Fichier Nakala-only sans vignette
    locale dérivée, on fallback sur la thumb IIIF Nakala (`!200,200`).
    Sinon le panneau fichiers afficherait juste des numéros de page
    sans aperçu — critique sur les items à 39+ scans."""
    fichier = _f(
        racine=None,
        chemin_relatif=None,
        nom_fichier="scan.jpg",
        vignette_chemin=None,
        iiif_url_nakala="https://api.nakala.fr/iiif/10.1/x/abc/info.json",
    )
    src = resoudre_source_image(fichier)
    assert src.vignette_url == (
        "https://api.nakala.fr/iiif/10.1/x/abc/full/!200,200/0/default.jpg"
    )


def test_vignette_locale_prime_sur_fallback_nakala() -> None:
    """Si une vignette locale dérivée existe, elle est préférée
    (offline, plus rapide). Le fallback Nakala ne s'active que si
    la vignette locale est absente."""
    fichier = _f(
        vignette_chemin="vignette/x.jpg",
        iiif_url_nakala="https://api.nakala.fr/iiif/10.1/x/abc/info.json",
    )
    src = resoudre_source_image(fichier)
    assert src.vignette_url == "/derives/miniatures/vignette/x.jpg"


def test_vignette_url_externe_non_nakala_pas_de_fallback() -> None:
    """Si l'iiif_url_nakala est une URL externe non-Nakala (cas rare),
    on n'invente pas de thumb — vignette_url reste None."""
    fichier = _f(
        racine=None,
        chemin_relatif=None,
        nom_fichier="scan.jpg",
        vignette_chemin=None,
        iiif_url_nakala="https://example.com/iiif/abc/info.json",
    )
    src = resoudre_source_image(fichier)
    assert src.vignette_url is None


def test_vignette_pas_de_fallback_nakala_si_pdf() -> None:
    """Garde extension : Nakala ne sert pas IIIF pour les PDF/vidéo/etc.
    Sans cette garde, le panneau fichiers afficherait une image cassée
    (URL thumb en 404). On préfère retomber sur le placeholder textuel
    « pdf »."""
    fichier = _f(
        racine=None,
        chemin_relatif=None,
        nom_fichier="numero.pdf",
        vignette_chemin=None,
        iiif_url_nakala="https://api.nakala.fr/data/10.1/x/abc",
    )
    src = resoudre_source_image(fichier)
    assert src.vignette_url is None


def test_vignette_pas_de_fallback_nakala_si_json() -> None:
    """Idem JSON (autre cas typique des exports Nakala : metadata JSON
    accompagnant les scans)."""
    fichier = _f(
        racine=None,
        chemin_relatif=None,
        nom_fichier="metadata.json",
        vignette_chemin=None,
        iiif_url_nakala="https://api.nakala.fr/data/10.1/x/abc",
    )
    src = resoudre_source_image(fichier)
    assert src.vignette_url is None
