"""Rendu Rich des rapports de renommage."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table

from archives_tool.affichage import console as cons

from .rapport import (
    RapportAnnulation,
    RapportExecution,
    RapportPlan,
    StatutPlan,
)

LIBELLES_STATUT = {
    StatutPlan.PRET: "prêt",
    StatutPlan.NO_OP: "no-op",
    StatutPlan.EN_CYCLE: "cycle",
    StatutPlan.BLOQUE: "bloqué",
}

STYLES_STATUT = {
    StatutPlan.PRET: "succes",
    StatutPlan.NO_OP: "cle",
    StatutPlan.EN_CYCLE: "avertissement",
    StatutPlan.BLOQUE: "erreur",
}


def afficher_plan(rapport: RapportPlan, *, limite: int = 50) -> None:
    cons.console.print(
        Panel(
            f"[cle]Total opérations[/cle] : "
            f"[valeur]{len(rapport.operations)}[/valeur]\n"
            f"[cle]À renommer[/cle] : [valeur]{rapport.nb_renommages}[/valeur]\n"
            f"[cle]No-op[/cle] : [valeur]{rapport.nb_no_op}[/valeur]\n"
            f"[cle]Bloqués[/cle] : [valeur]{rapport.nb_bloques}[/valeur]\n"
            f"[cle]Conflits[/cle] : [valeur]{len(rapport.conflits)}[/valeur]\n"
            f"[cle]Applicable[/cle] : "
            f"[{'succes' if rapport.applicable else 'erreur'}]"
            f"{rapport.applicable}"
            f"[/{'succes' if rapport.applicable else 'erreur'}]",
            title="[titre]Plan de renommage[/titre]",
            expand=False,
        )
    )

    if rapport.conflits:
        cons.console.print()
        cons.console.print("[sous_titre]Conflits[/sous_titre]")
        for c in rapport.conflits:
            cons.console.print(f"  [erreur]✗ {c.code}[/erreur] : {c.message}")

    if rapport.operations:
        cons.console.print()
        table = Table(show_header=True, header_style="sous_titre", expand=False)
        table.add_column("ID")
        table.add_column("Statut")
        table.add_column("Avant")
        table.add_column("Après")
        montres = rapport.operations[:limite] if limite > 0 else rapport.operations
        for op in montres:
            statut = StatutPlan(op.statut)
            style = STYLES_STATUT[statut]
            libelle = LIBELLES_STATUT[statut]
            table.add_row(
                str(op.fichier_id),
                f"[{style}]{libelle}[/{style}]",
                f"{op.racine}:{op.chemin_avant}",
                op.chemin_apres,
            )
        cons.console.print(table)
        reste = len(rapport.operations) - len(montres)
        if reste > 0:
            cons.console.print(f"  [cle]… {reste} de plus[/cle]")


def afficher_execution(rapport: RapportExecution) -> None:
    mode = "DRY-RUN" if rapport.dry_run else "RÉEL"
    titre = f"[titre]Exécution {mode}[/titre]"
    if rapport.batch_id:
        titre = f"{titre} — batch [valeur]{rapport.batch_id}[/valeur]"
    cons.console.print(
        Panel(
            f"[cle]Réussies[/cle] : [valeur]{rapport.operations_reussies}[/valeur]\n"
            f"[cle]Échouées[/cle] : [valeur]{rapport.operations_echouees}[/valeur]\n"
            f"[cle]Compensées (rollback)[/cle] : "
            f"[valeur]{rapport.operations_compensees}[/valeur]\n"
            f"[cle]Durée[/cle] : [valeur]{rapport.duree_secondes:.2f}s[/valeur]",
            title=titre,
            expand=False,
        )
    )
    for e in rapport.erreurs:
        cons.console.print(f"  [erreur]✗ {e}[/erreur]")


def afficher_annulation(rapport: RapportAnnulation) -> None:
    mode = "DRY-RUN" if rapport.dry_run else "RÉEL"
    titre = f"[titre]Annulation {mode}[/titre] — batch [cle]{rapport.batch_id_original}[/cle]"
    if rapport.batch_id_annulation:
        titre += f" → [valeur]{rapport.batch_id_annulation}[/valeur]"
    cons.console.print(
        Panel(
            f"[cle]Inversées[/cle] : [valeur]{rapport.operations_inversees}[/valeur]\n"
            f"[cle]Échouées[/cle] : [valeur]{rapport.operations_echouees}[/valeur]\n"
            f"[cle]Durée[/cle] : [valeur]{rapport.duree_secondes:.2f}s[/valeur]",
            title=titre,
            expand=False,
        )
    )
    for e in rapport.erreurs:
        cons.console.print(f"  [erreur]✗ {e}[/erreur]")
