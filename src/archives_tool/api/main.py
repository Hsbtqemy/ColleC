"""Application FastAPI : montage des routes et des fichiers statiques."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from archives_tool.api.routes import dashboard, derives
from archives_tool.affichage.formatters import formater_taille_octets

RACINE_WEB = Path(__file__).resolve().parent.parent / "web"
RACINE_STATIC = RACINE_WEB / "static"
RACINE_TEMPLATES = RACINE_WEB / "templates"

app = FastAPI(
    title="archives-tool",
    description="Outil de gestion de collections numérisées",
    version="0.5.0",
)

app.mount("/static", StaticFiles(directory=RACINE_STATIC), name="static")
app.include_router(dashboard.router)
app.include_router(derives.router, prefix="/derives")

templates = Jinja2Templates(directory=RACINE_TEMPLATES)


def _libelle_phase(phase: object) -> str:
    """Filtre Jinja : enum PhaseChantier → libellé français."""
    return getattr(phase, "libelle", str(phase))


def _temps_relatif(dt: datetime | None) -> str:
    """Filtre Jinja : datetime → 'il y a 3h' (approximatif)."""
    if dt is None:
        return "—"
    delta = datetime.now() - dt
    secondes = int(delta.total_seconds())
    if secondes < 60:
        return "à l'instant"
    if secondes < 3600:
        return f"il y a {secondes // 60} min"
    if secondes < 86400:
        return f"il y a {secondes // 3600} h"
    if secondes < 86400 * 7:
        return f"il y a {secondes // 86400} j"
    return dt.strftime("%Y-%m-%d")


templates.env.filters["libelle_phase"] = _libelle_phase
templates.env.filters["temps_relatif"] = _temps_relatif
templates.env.filters["taille_humaine"] = formater_taille_octets
