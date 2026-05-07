"""Rendu Rich des rapports de dérivation."""

from __future__ import annotations

from rich.table import Table

from archives_tool.affichage import console as cons
from archives_tool.affichage.formatters import panel_kv

from .rapport import RapportDerivation, StatutDerive

LIBELLES = {
    StatutDerive.GENERE: "généré",
    StatutDerive.DEJA_GENERE: "déjà généré",
    StatutDerive.NETTOYE: "nettoyé",
    StatutDerive.ERREUR: "erreur",
}

STYLES = {
    StatutDerive.GENERE: "succes",
    StatutDerive.DEJA_GENERE: "cle",
    StatutDerive.NETTOYE: "succes",
    StatutDerive.ERREUR: "erreur",
}


def afficher_rapport(rapport: RapportDerivation, *, limite: int = 30) -> None:
    mode = "DRY-RUN" if rapport.dry_run else "RÉEL"
    cons.console.print(
        panel_kv(
            f"Dérivation {mode}",
            [
                ("Traités", str(rapport.nb_traites)),
                ("Générés", str(rapport.nb_generes)),
                ("Déjà générés", str(rapport.nb_deja_generes)),
                ("Nettoyés", str(rapport.nb_nettoyes)),
                ("Erreurs", str(rapport.nb_erreurs)),
                ("Racine cible", rapport.racine_cible),
                ("Durée", f"{rapport.duree_secondes:.2f}s"),
            ],
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
