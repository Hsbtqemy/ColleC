"""Instance Jinja2Templates partagée et filtres exposés.

Vit ici pour éviter le cycle `main.py ↔ routes/*.py` quand une route a
besoin de `templates.TemplateResponse`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from archives_tool.affichage.formatters import (
    LIBELLES_ETAT,
    formater_taille_octets,
    temps_relatif,
)
from archives_tool.models import EtatCatalogage, PhaseChantier

RACINE_TEMPLATES = Path(__file__).resolve().parent.parent / "web" / "templates"


def _libelle_etat(etat: EtatCatalogage | str | None) -> str:
    if etat is None:
        return "—"
    code = etat.value if isinstance(etat, EtatCatalogage) else etat
    return LIBELLES_ETAT.get(code, code)


templates = Jinja2Templates(directory=RACINE_TEMPLATES)
templates.env.filters["libelle_phase"] = lambda p: (
    p.libelle if isinstance(p, PhaseChantier) else "—"
)
templates.env.filters["libelle_etat"] = _libelle_etat
templates.env.filters["temps_relatif"] = temps_relatif
templates.env.filters["taille_humaine"] = formater_taille_octets
