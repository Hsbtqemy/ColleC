"""Instance Jinja2Templates partagée et filtres exposés.

Vit ici pour éviter le cycle `main.py ↔ routes/*.py` quand une route a
besoin de `templates.TemplateResponse`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from archives_tool.affichage.formatters import formater_taille_octets
from archives_tool.models import PhaseChantier

RACINE_TEMPLATES = Path(__file__).resolve().parent.parent / "web" / "templates"


def _temps_relatif(dt: datetime | None) -> str:
    """`datetime` → « il y a 3h » approximatif. None → tiret."""
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


templates = Jinja2Templates(directory=RACINE_TEMPLATES)
templates.env.filters["libelle_phase"] = lambda p: (
    p.libelle if isinstance(p, PhaseChantier) else "—"
)
templates.env.filters["temps_relatif"] = _temps_relatif
templates.env.filters["taille_humaine"] = formater_taille_octets


def rendre_avec_partial(
    request,
    *,
    page_template: str,
    partial_template: str,
    contexte: dict,
):
    """Sert le template plein lors d'un accès direct, le partiel lors
    d'un swap HTMX (en-tête `HX-Request`). Permet une seule URL par
    onglet, à la fois bookmarkable et fluide.
    """
    nom = partial_template if request.headers.get("HX-Request") else page_template
    return templates.TemplateResponse(request, nom, contexte)
