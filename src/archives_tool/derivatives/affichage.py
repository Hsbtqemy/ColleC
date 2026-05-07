"""Rendu Rich des rapports de dérivation."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table

from archives_tool.affichage import console as cons

from .rapport import RapportDerivation, StatutDerive

LIBELLES = {
    StatutDerive.GENERE: "généré",
    StatutDerive.DEJA_GENERE: "déjà généré",
    StatutDerive.NETTOYE: "nettoyé",
    StatutDerive.IGNORE: "ignoré",
    StatutDerive.ERREUR: "erreur",
}

STYLES = {
    StatutDerive.GENERE: "succes",
    StatutDerive.DEJA_GENERE: "cle",
    StatutDerive.NETTOYE: "succes",
    StatutDerive.IGNORE: "avertissement",
    StatutDerive.ERREUR: "erreur",
}


def afficher_rapport(rapport: RapportDerivation, *, limite: int = 30) -> None:
    mode = "DRY-RUN" if rapport.dry_run else "RÉEL"
    cons.console.print(
        Panel(
            f"[cle]Traités[/cle] : [valeur]{rapport.nb_traites}[/valeur]\n"
            f"[cle]Générés[/cle] : [valeur]{rapport.nb_generes}[/valeur]\n"
            f"[cle]Déjà générés[/cle] : [valeur]{rapport.nb_deja_generes}[/valeur]\n"
            f"[cle]Nettoyés[/cle] : [valeur]{rapport.nb_nettoyes}[/valeur]\n"
            f"[cle]Erreurs[/cle] : [valeur]{rapport.nb_erreurs}[/valeur]\n"
            f"[cle]Racine cible[/cle] : [valeur]{rapport.racine_cible}[/valeur]\n"
            f"[cle]Durée[/cle] : [valeur]{rapport.duree_secondes:.2f}s[/valeur]",
            title=f"[titre]Dérivation {mode}[/titre]",
            expand=False,
        )
    )

    erreurs = [r for r in rapport.resultats if r.statut == StatutDerive.ERREUR]
    if erreurs:
        cons.console.print()
        table = Table(show_header=True, header_style="sous_titre", expand=False)
        table.add_column("Fichier ID")
        table.add_column("Erreur")
        for r in erreurs[:limite]:
            table.add_row(str(r.fichier_id), r.message or "")
        cons.console.print(table)
        if len(erreurs) > limite:
            cons.console.print(f"  [cle]… {len(erreurs) - limite} de plus[/cle]")
