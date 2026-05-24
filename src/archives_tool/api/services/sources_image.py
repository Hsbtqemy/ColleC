"""Résolution de la source d'image à passer à OpenSeadragon.

Priorité (du plus précis au plus dégradé) :
1. IIIF Nakala (`Fichier.iiif_url_nakala`) — info.json distant ;
2. DZI local (`Fichier.dzi_chemin`) — réservé V2+, jamais rempli en V0.6 ;
3. Aperçu local (`Fichier.apercu_chemin`) — JPEG 1200 px sous /derives/.

Le frontend reçoit `{ "type": "iiif"|"dzi"|"image", "url": "<url>" }`.
La visionneuse JS adapte au format attendu par OpenSeadragon (string
pour iiif/dzi, objet `{type, url}` pour image plate).
"""

from __future__ import annotations

from dataclasses import dataclass

from archives_tool.models import Fichier

RACINE_DERIVES_DEFAUT = "miniatures"


@dataclass
class SourceImage:
    """Source primaire à charger dans la visionneuse, plus un fallback
    optionnel utilisé sur l'événement OpenSeadragon `open-failed`.
    """

    primary: dict[str, str] | None
    fallback: dict[str, str] | None = None
    vignette_url: str | None = None


def _url_locale(racine: str, chemin_relatif: str) -> str:
    return f"/derives/{racine}/{chemin_relatif}"


def resoudre_source_image(
    fichier: Fichier,
    *,
    racine_derives: str = RACINE_DERIVES_DEFAUT,
) -> SourceImage:
    """Construit la `SourceImage` à passer à OpenSeadragon.

    Si plusieurs sources existent, la première est primary et la
    suivante fallback. La vignette (si disponible) est exposée à
    part pour le panneau latéral.

    Pour les Fichier Nakala-only sans vignette locale dérivée, on
    fallback sur la thumb IIIF Nakala (`!200,200`). Sinon le panneau
    fichiers afficherait juste des numéros de page sans aperçu.
    """
    from archives_tool.files.nakala import est_extension_image_iiif, vers_thumb

    sources: list[dict[str, str]] = []

    if fichier.iiif_url_nakala:
        sources.append({"type": "iiif", "url": fichier.iiif_url_nakala})

    if fichier.dzi_chemin:
        sources.append(
            {"type": "dzi", "url": _url_locale(racine_derives, fichier.dzi_chemin)}
        )

    if fichier.apercu_chemin:
        sources.append(
            {"type": "image", "url": _url_locale(racine_derives, fichier.apercu_chemin)}
        )

    if fichier.vignette_chemin:
        vignette_url = _url_locale(racine_derives, fichier.vignette_chemin)
    elif fichier.iiif_url_nakala and est_extension_image_iiif(fichier.nom_fichier):
        # Fallback Nakala : reconstruit l'URL thumb depuis l'URL
        # IIIF info.json (ou data brute pour les non-images).
        # Garde extension : Nakala ne sert pas IIIF pour les PDF/vidéo,
        # `vers_thumb` retournerait une URL en 404 → image cassée dans
        # le panneau fichiers. On préfère laisser le placeholder
        # textuel (« pdf », « zip »…).
        vignette_url = vers_thumb(fichier.iiif_url_nakala)
    else:
        vignette_url = None

    return SourceImage(
        primary=sources[0] if sources else None,
        fallback=sources[1] if len(sources) >= 2 else None,
        vignette_url=vignette_url,
    )


__all__ = ["RACINE_DERIVES_DEFAUT", "SourceImage", "resoudre_source_image"]
