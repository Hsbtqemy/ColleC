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


def _url_avec(base: str, **params: object) -> str:
    """Compose une URL avec les params donnés (remplace les existants).

    Préserve les autres params de la base. Une page paginée passant à
    une nouvelle valeur de `tri` doit aussi reset `page` — gérer côté
    appelant en passant `page=1` explicitement.
    """
    if "?" in base:
        racine, query = base.split("?", 1)
        keep = [
            p
            for p in query.split("&")
            if p and "=" in p and p.split("=", 1)[0] not in params
        ]
    else:
        racine, keep = base, []
    add = [f"{k}={v}" for k, v in params.items()]
    if not (keep or add):
        return racine
    return f"{racine}?{'&'.join(keep + add)}"


def _url_tri(base: str, key: str, current_tri: str, current_ordre: str) -> str:
    """Compose une URL de tri : si `key` est déjà actif, inverse l'ordre ;
    sinon on repart en `asc`. Reset `page` à 1 (un nouveau tri repagine).
    """
    if key == current_tri:
        ordre = "desc" if current_ordre == "asc" else "asc"
    else:
        ordre = "asc"
    return _url_avec(base, tri=key, ordre=ordre, page=1)


def _url_page(base: str, page: int) -> str:
    return _url_avec(base, page=page)


def _pages_visibles(courante: int, total: int) -> list[int | str]:
    """Liste compacte de pages à afficher dans un pager.

    [1, '…', cur-1, cur, cur+1, '…', N] avec collapses naturels quand
    les fenêtres se chevauchent. Pour `total <= 7`, retourne 1..N.
    """
    if total <= 7:
        return list(range(1, total + 1))
    pages: list[int | str] = [1]
    debut = max(2, courante - 1)
    fin = min(total - 1, courante + 1)
    if debut > 2:
        pages.append("…")
    for p in range(debut, fin + 1):
        pages.append(p)
    if fin < total - 1:
        pages.append("…")
    pages.append(total)
    return pages


templates = Jinja2Templates(directory=RACINE_TEMPLATES)
templates.env.filters["libelle_phase"] = lambda p: (
    p.libelle if isinstance(p, PhaseChantier) else "—"
)
templates.env.filters["libelle_etat"] = _libelle_etat
templates.env.filters["temps_relatif"] = temps_relatif
templates.env.filters["taille_humaine"] = formater_taille_octets
templates.env.filters["url_tri"] = _url_tri
templates.env.filters["url_page"] = _url_page
templates.env.globals["pages_visibles"] = _pages_visibles
