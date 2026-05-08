"""Formatage des valeurs pour l'affichage CLI."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.markup import escape
from rich.panel import Panel

ABSENT = "—"

LIBELLES_ETAT = {
    "brouillon": "brouillon",
    "a_verifier": "à vérifier",
    "verifie": "vérifié",
    "valide": "validé",
    "a_corriger": "à corriger",
    "actif": "actif",
    "remplace": "remplacé",
    "corbeille": "corbeille",
}


def formater_date(valeur: str | None) -> str:
    """Affiche une date EDTF ou un timestamp tel quel, ABSENT si None."""
    if valeur is None or valeur == "":
        return ABSENT
    if isinstance(valeur, datetime):
        return valeur.strftime("%Y-%m-%d %H:%M")
    return str(valeur)


def formater_liste(valeurs: list[Any] | None, separateur: str = ", ") -> str:
    if not valeurs:
        return ABSENT
    return separateur.join(str(v) for v in valeurs)


def formater_etat(etat: str | None) -> str:
    """Retourne le libellé de l'état entouré du style Rich correspondant.

    Le style `etat.<valeur>` est défini dans `console.THEME`. Les valeurs
    inconnues sont rendues sans style mais le libellé reste affiché.
    """
    if etat is None:
        return ABSENT
    libelle = LIBELLES_ETAT.get(etat, etat)
    return f"[etat.{etat}]{escape(libelle)}[/etat.{etat}]"


def temps_relatif(dt: datetime | None) -> str:
    """`datetime` → « il y a 3h » approximatif. None → tiret.

    Utilisé à la fois comme filtre Jinja (`temps_relatif`) et par les
    services qui pré-formatent un `modifie_depuis` pour les composants
    Claude Design (qui attendent une chaîne déjà rendue).
    """
    if dt is None:
        return ABSENT
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


def formater_taille_octets(n: int | None) -> str:
    """Affichage humain (KB, MB, GB) avec une décimale."""
    if n is None:
        return ABSENT
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def tronquer(texte: str | None, longueur: int = 80) -> str:
    if texte is None or texte == "":
        return ABSENT
    txt = str(texte).replace("\n", " ").replace("\r", " ")
    if len(txt) <= longueur:
        return txt
    return txt[: longueur - 1] + "…"


def panel_kv(
    titre: str,
    paires: list[tuple[str, str]],
    *,
    expand: bool = False,
) -> Panel:
    """Panneau Rich « clé : valeur » à partir d'une liste de paires.

    Évite la répétition du motif `[cle]X[/cle] : [valeur]Y[/valeur]\\n`
    dans les rapports (qa, renamer, derivatives, exports).
    """
    corps = "\n".join(
        f"[cle]{cle}[/cle] : [valeur]{valeur}[/valeur]" for cle, valeur in paires
    )
    return Panel(corps, title=f"[titre]{titre}[/titre]", expand=expand)


def barre_progression(ratio: float, largeur: int = 10) -> str:
    """Mini-graphe ASCII de proportion : ▓▓▓░░ par exemple."""
    ratio = max(0.0, min(1.0, ratio))
    pleins = round(ratio * largeur)
    return "▓" * pleins + "░" * (largeur - pleins)
