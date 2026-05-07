"""Rendu Rich des rapports de renommage."""

from __future__ import annotations

from rich.table import Table

from archives_tool.affichage import console as cons
from archives_tool.affichage.formatters import panel_kv

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
    style_app = "succes" if rapport.applicable else "erreur"
    cons.console.print(
        panel_kv(
            "Plan de renommage",
            [
                ("Total opérations", str(len(rapport.operations))),
                ("À renommer", str(rapport.nb_renommages)),
                ("No-op", str(rapport.nb_no_op)),
                ("Bloqués", str(rapport.nb_bloques)),
                ("Conflits", str(len(rapport.conflits))),
                (
                    "Applicable",
                    f"[{style_app}]{rapport.applicable}[/{style_app}]",
                ),
            ],
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
    titre = f"Exécution {mode}"
    if rapport.batch_id:
        titre = f"{titre} — batch {rapport.batch_id}"
    cons.console.print(
        panel_kv(
            titre,
            [
                ("Réussies", str(rapport.operations_reussies)),
                ("Échouées", str(rapport.operations_echouees)),
                ("Compensées (rollback)", str(rapport.operations_compensees)),
                ("Durée", f"{rapport.duree_secondes:.2f}s"),
            ],
        )
    )
    for e in rapport.erreurs:
        cons.console.print(f"  [erreur]✗ {e}[/erreur]")


def afficher_annulation(rapport: RapportAnnulation) -> None:
    mode = "DRY-RUN" if rapport.dry_run else "RÉEL"
    titre = f"Annulation {mode} — batch {rapport.batch_id_original}"
    if rapport.batch_id_annulation:
        titre += f" → {rapport.batch_id_annulation}"
    cons.console.print(
        panel_kv(
            titre,
            [
                ("Inversées", str(rapport.operations_inversees)),
                ("Échouées", str(rapport.operations_echouees)),
                ("Durée", f"{rapport.duree_secondes:.2f}s"),
            ],
        )
    )
    for e in rapport.erreurs:
        cons.console.print(f"  [erreur]✗ {e}[/erreur]")
