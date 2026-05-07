"""Rendu Rich des rapports de contrôle (lecture seule)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.table import Table

from archives_tool.affichage import console as cons
from archives_tool.affichage.formatters import panel_kv

from .rapport import RapportControle, RapportQa

LIMITE_DETAILS_DEFAUT = 20


def _en_tete_controle(rap: RapportControle) -> str:
    if rap.nb_anomalies == 0 and not rap.avertissements:
        marqueur = "[succes]✓[/succes]"
    elif rap.nb_anomalies == 0:
        marqueur = "[avertissement]![/avertissement]"
    else:
        marqueur = "[erreur]✗[/erreur]"
    return (
        f"{marqueur} [titre]{rap.libelle}[/titre] "
        f"— {rap.nb_anomalies} anomalie(s), "
        f"{rap.duree_secondes:.2f}s"
    )


def _afficher_avertissements(rap: RapportControle) -> None:
    for av in rap.avertissements:
        cons.console.print(f"  [avertissement]⚠ {av}[/avertissement]")


def _afficher_table(
    rap: RapportControle,
    limite: int,
    colonnes: list[str],
    ligne: Callable[[Any], tuple[str, ...]],
) -> None:
    """Rendu commun des contrôles à anomalies tabulaires."""
    cons.console.print(_en_tete_controle(rap))
    _afficher_avertissements(rap)
    if not rap.anomalies:
        return
    table = Table(show_header=True, header_style="sous_titre", expand=False)
    for nom in colonnes:
        table.add_column(nom)
    montres = rap.anomalies[:limite] if limite > 0 else rap.anomalies
    for a in montres:
        table.add_row(*ligne(a))
    cons.console.print(table)
    reste = len(rap.anomalies) - len(montres)
    if reste > 0:
        cons.console.print(f"  [cle]… {reste} de plus[/cle]")


def _afficher_doublons(rap: RapportControle, limite: int) -> None:
    cons.console.print(_en_tete_controle(rap))
    _afficher_avertissements(rap)
    if not rap.anomalies:
        return
    montres = rap.anomalies[:limite] if limite > 0 else rap.anomalies
    for groupe in montres:
        cons.console.print(
            f"  [cle]hash[/cle] [valeur]{groupe.hash_sha256[:16]}…[/valeur] "
            f"({len(groupe.fichiers)} fichiers)"
        )
        for f in groupe.fichiers:
            cons.console.print(
                f"    [cyan]{f.item_cote}[/cyan]  {f.racine}:{f.chemin_relatif}"
            )
    reste = len(rap.anomalies) - len(montres)
    if reste > 0:
        cons.console.print(f"  [cle]… {reste} groupes de plus[/cle]")


_RENDU: dict[str, Callable[[RapportControle, int], None]] = {
    "fichiers-manquants": lambda rap, lim: _afficher_table(
        rap,
        lim,
        ["Item", "Racine", "Chemin relatif"],
        lambda a: (a.item_cote, a.racine, a.chemin_relatif),
    ),
    "orphelins-disque": lambda rap, lim: _afficher_table(
        rap,
        lim,
        ["Racine", "Chemin relatif"],
        lambda a: (a.racine, a.chemin_relatif),
    ),
    "items-vides": lambda rap, lim: _afficher_table(
        rap,
        lim,
        ["Collection", "Cote item"],
        lambda a: (a.collection_cote, a.cote),
    ),
    "doublons": _afficher_doublons,
}


def afficher_rapport_qa(
    rapport: RapportQa,
    *,
    limite_details: int = LIMITE_DETAILS_DEFAUT,
) -> None:
    """Rendu complet d'un `RapportQa`.

    `limite_details` plafonne le nombre de lignes par contrôle (0 =
    illimité). Les avertissements sont toujours intégralement rendus.
    """
    cons.console.print(
        panel_kv(
            "Contrôles de cohérence",
            [
                ("Portée", rapport.portee),
                ("Contrôles", str(len(rapport.controles))),
                ("Anomalies totales", str(rapport.nb_anomalies)),
                ("Durée", f"{rapport.duree_secondes:.2f}s"),
            ],
        )
    )
    for ctrl in rapport.controles:
        cons.console.print()
        rendu = _RENDU.get(ctrl.code)
        if rendu is not None:
            rendu(ctrl, limite_details)
        else:
            cons.console.print(_en_tete_controle(ctrl))
