"""Rendu Rich des rapports de contrôle (lecture seule)."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table

from archives_tool.affichage import console as cons

from .rapport import (
    AnomalieFichierManquant,
    AnomalieItemVide,
    AnomalieOrphelinDisque,
    GroupeDoublons,
    RapportControle,
    RapportQa,
)

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


def _afficher_fichiers_manquants(rap: RapportControle, limite: int) -> None:
    cons.console.print(_en_tete_controle(rap))
    _afficher_avertissements(rap)
    if not rap.anomalies:
        return
    table = Table(show_header=True, header_style="sous_titre", expand=False)
    table.add_column("Item")
    table.add_column("Racine")
    table.add_column("Chemin relatif")
    montres = rap.anomalies[:limite] if limite > 0 else rap.anomalies
    for a in montres:
        assert isinstance(a, AnomalieFichierManquant)
        table.add_row(a.item_cote, a.racine, a.chemin_relatif)
    cons.console.print(table)
    if limite > 0 and len(rap.anomalies) > limite:
        cons.console.print(f"  [cle]… {len(rap.anomalies) - limite} de plus[/cle]")


def _afficher_orphelins(rap: RapportControle, limite: int) -> None:
    cons.console.print(_en_tete_controle(rap))
    _afficher_avertissements(rap)
    if not rap.anomalies:
        return
    table = Table(show_header=True, header_style="sous_titre", expand=False)
    table.add_column("Racine")
    table.add_column("Chemin relatif")
    montres = rap.anomalies[:limite] if limite > 0 else rap.anomalies
    for a in montres:
        assert isinstance(a, AnomalieOrphelinDisque)
        table.add_row(a.racine, a.chemin_relatif)
    cons.console.print(table)
    if limite > 0 and len(rap.anomalies) > limite:
        cons.console.print(f"  [cle]… {len(rap.anomalies) - limite} de plus[/cle]")


def _afficher_items_vides(rap: RapportControle, limite: int) -> None:
    cons.console.print(_en_tete_controle(rap))
    _afficher_avertissements(rap)
    if not rap.anomalies:
        return
    table = Table(show_header=True, header_style="sous_titre", expand=False)
    table.add_column("Collection")
    table.add_column("Cote item")
    montres = rap.anomalies[:limite] if limite > 0 else rap.anomalies
    for a in montres:
        assert isinstance(a, AnomalieItemVide)
        table.add_row(a.collection_cote, a.cote)
    cons.console.print(table)
    if limite > 0 and len(rap.anomalies) > limite:
        cons.console.print(f"  [cle]… {len(rap.anomalies) - limite} de plus[/cle]")


def _afficher_doublons(rap: RapportControle, limite: int) -> None:
    cons.console.print(_en_tete_controle(rap))
    _afficher_avertissements(rap)
    if not rap.anomalies:
        return
    montres = rap.anomalies[:limite] if limite > 0 else rap.anomalies
    for groupe in montres:
        assert isinstance(groupe, GroupeDoublons)
        cons.console.print(
            f"  [cle]hash[/cle] [valeur]{groupe.hash_sha256[:16]}…[/valeur] "
            f"({len(groupe.fichiers)} fichiers)"
        )
        for f in groupe.fichiers:
            cons.console.print(
                f"    [cyan]{f.item_cote}[/cyan]  {f.racine}:{f.chemin_relatif}"
            )
    if limite > 0 and len(rap.anomalies) > limite:
        cons.console.print(
            f"  [cle]… {len(rap.anomalies) - limite} groupes de plus[/cle]"
        )


_RENDU = {
    "fichiers-manquants": _afficher_fichiers_manquants,
    "orphelins-disque": _afficher_orphelins,
    "items-vides": _afficher_items_vides,
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
        Panel(
            f"[cle]Portée[/cle] : [valeur]{rapport.portee}[/valeur]\n"
            f"[cle]Contrôles[/cle] : [valeur]{len(rapport.controles)}[/valeur]\n"
            f"[cle]Anomalies totales[/cle] : "
            f"[valeur]{rapport.nb_anomalies}[/valeur]\n"
            f"[cle]Durée[/cle] : [valeur]{rapport.duree_secondes:.2f}s[/valeur]",
            title="[titre]Contrôles de cohérence[/titre]",
            expand=False,
        )
    )
    for ctrl in rapport.controles:
        cons.console.print()
        rendu = _RENDU.get(ctrl.code)
        if rendu is not None:
            rendu(ctrl, limite_details)
        else:
            cons.console.print(_en_tete_controle(ctrl))
