"""Instance Console partagée et helpers de styles."""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

THEME = Theme(
    {
        "titre": "bold cyan",
        "sous_titre": "cyan",
        "cle": "dim",
        "valeur": "white",
        "succes": "green",
        "avertissement": "yellow",
        "erreur": "bold red",
        "etat.brouillon": "dim",
        "etat.a_verifier": "yellow",
        "etat.verifie": "blue",
        "etat.valide": "green",
        "etat.a_corriger": "red",
        "etat.actif": "green",
        "etat.remplace": "yellow",
        "etat.corbeille": "dim",
    }
)

console: Console = Console(theme=THEME)


def silencer_pour_tests() -> None:
    """Reconfigure la console globale pour les tests (couleurs OFF,
    largeur fixe, force_terminal=False) — sortie déterministe pour
    pouvoir asserter du contenu textuel."""
    global console
    console = Console(theme=THEME, no_color=True, force_terminal=False, width=120)
