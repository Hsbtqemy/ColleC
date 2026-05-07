"""Service des dérivés (vignettes, aperçus) sous /derives/<racine>/<chemin>."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from archives_tool.api.deps import get_racines
from archives_tool.files.paths import valider_chemin_relatif

router = APIRouter()


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
    - fichier inexistant → 404.
    """
    if racine not in racines:
        raise HTTPException(status_code=403, detail="Racine inconnue.")

    try:
        rel = valider_chemin_relatif(chemin)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None

    base = racines[racine].resolve()
    cible = (base / rel).resolve()
    # Garde-fou supplémentaire : malgré la validation, on s'assure que le
    # chemin résolu reste sous la racine (suit les éventuels symlinks).
    if not cible.is_relative_to(base):
        raise HTTPException(status_code=403, detail="Hors racine.")

    if not cible.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    return FileResponse(cible)
