"""Rapport qa au format texte (avec couleurs Rich si TTY)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from archives_tool.qa._commun import (
    RapportQa,
    ResultatControle,
    Severite,
)

# Mapping sévérité → (symbole, style Rich) ; le style est repris du
# THEME global d'archives_tool.affichage.console.
_SYMBOLES: dict[tuple[Severite, bool], tuple[str, str]] = {
    (Severite.ERREUR, False): ("✗", "erreur"),
    (Severite.ERREUR, True): ("✓", "succes"),
    (Severite.AVERTISSEMENT, False): ("⚠", "avertissement"),
    (Severite.AVERTISSEMENT, True): ("✓", "succes"),
    (Severite.INFO, False): ("⚠", "avertissement"),
    (Severite.INFO, True): ("✓", "succes"),
}

_LIBELLES_FAMILLE: dict[str, str] = {
    "invariants": "Famille 1 — Invariants du modèle",
    "fichiers": "Famille 2 — Cohérence des fichiers",
    "metadonnees": "Famille 3 — Cohérence des métadonnées",
    "cross": "Famille 4 — Cohérence cross-entités",
}


def _ligne_controle(ctrl: ResultatControle) -> str:
    """Une ligne par contrôle avec symbole, id, libellé et compteurs."""
    symbole, style = _SYMBOLES[(ctrl.severite, ctrl.passe)]
    statut = (
        f"{ctrl.compte_total - ctrl.compte_problemes}/{ctrl.compte_total} OK"
        if ctrl.compte_total
        else "rien à vérifier"
    )
    return (
        f"  [{style}]{symbole}[/{style}] [bold]{ctrl.id}[/bold] "
        f"({ctrl.libelle}) : {statut}"
    )


def formatter_rapport_text(rapport: RapportQa, *, max_exemples: int = 5) -> str:
    """Génère un rapport texte structuré.

    Couleurs émises uniquement si la sortie est un TTY (Rich gère
    automatiquement la dégradation pour les pipes / fichiers)."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=100)

    p = rapport.perimetre
    console.print(
        f"[bold]Contrôle qa[/bold] — {p.fonds_count} fonds, "
        f"{p.collections_count} collections, {p.items_count} items, "
        f"{p.fichiers_count} fichiers"
    )
    console.print(f"[dim]Périmètre : {p.type}[/dim]")
    console.print()

    par_famille: dict[str, list[ResultatControle]] = {}
    for ctrl in rapport.controles:
        par_famille.setdefault(ctrl.famille, []).append(ctrl)

    for famille, controles in par_famille.items():
        console.print(
            f"[bold cyan]{_LIBELLES_FAMILLE.get(famille, famille)}[/bold cyan]"
        )
        for ctrl in controles:
            console.print(_ligne_controle(ctrl))
            for ex in ctrl.exemples[:max_exemples]:
                console.print(f"      [dim]- {ex.message}[/dim]")
        console.print()

    bilan = (
        f"[bold]Bilan :[/bold] "
        f"[erreur]{rapport.nb_erreurs} erreur(s)[/erreur], "
        f"[avertissement]{rapport.nb_avertissements} avertissement(s)[/avertissement], "
        f"[dim]{rapport.nb_infos} info(s)[/dim]"
    )
    console.print(bilan)
    return buf.getvalue()
