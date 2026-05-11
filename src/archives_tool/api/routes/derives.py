"""Service des dérivés (vignettes, aperçus) sous /derives/<racine>/<chemin>."""

from __future__ import annotations

import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from archives_tool.api.deps import get_racines
from archives_tool.files.paths import valider_chemin_relatif

router = APIRouter()


def _resoudre_disque(base: Path, rel: str) -> Path | None:
    """Retourne le chemin disque effectif, en testant NFC puis NFD.

    Indispensable pour servir des dérivés produits sur Mac (NFD natif)
    depuis Windows / Linux (qui préservent la forme exacte).
    """
    cible_nfc = (base / rel).resolve()
    if cible_nfc.is_file():
        return cible_nfc
    parts = rel.split("/")
    cible_nfd = (
        base / Path(*(unicodedata.normalize("NFD", p) for p in parts))
    ).resolve()
    if cible_nfd.is_file():
        return cible_nfd
    return None


@router.get("/{racine}/{chemin:path}")
def servir_derive(
    racine: str,
    chemin: str,
    racines: dict[str, Path] = Depends(get_racines),
) -> FileResponse:
    """Sert un fichier dérivé depuis le disque.

    Sécurité :
    - racine inconnue → 403 ;
    - chemin contenant `..` ou absolu → 403 ;
    - fichier résolu hors de la racine déclarée → 403 ;
    - fichier inexistant (ni en NFC ni en NFD) → 404.
    """
    if racine not in racines:
        raise HTTPException(status_code=403, detail="Racine inconnue.")

    try:
        rel = str(valider_chemin_relatif(chemin))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None

    base = racines[racine].resolve()
    cible = _resoudre_disque(base, rel)
    if cible is None:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    if not cible.is_relative_to(base):
        raise HTTPException(status_code=403, detail="Hors racine.")
    # Aperçus / vignettes sont régénérés par `archives-tool deriver` —
    # le poste local peut les cacher 1 jour sans souci. Évite de
    # revalider 50 vignettes à chaque navigation prev/next dans la
    # page item.
    return FileResponse(cible, headers={"Cache-Control": "private, max-age=86400"})
