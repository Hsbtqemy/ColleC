"""Affichage fiche item avec ses fichiers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.affichage import console as cons  # le sous-module
from archives_tool.affichage.formatters import (
    ABSENT,
    formater_date,
    formater_etat,
    formater_taille_octets,
    tronquer,
)
from archives_tool.models import Collection, Item


class ItemAmbigu(Exception):
    """Plusieurs items partagent la même cote — préciser la collection."""


def _trouver_item(
    session: Session, cote: str, collection_cote: str | None
) -> Item | None:
    stmt = select(Item).where(Item.cote == cote)
    if collection_cote is not None:
        stmt = stmt.join(Collection, Item.collection_id == Collection.id).where(
            Collection.cote_collection == collection_cote
        )
    items = list(session.scalars(stmt))
    if len(items) == 0:
        return None
    if len(items) > 1:
        raise ItemAmbigu(
            f"{len(items)} items portent la cote {cote!r} dans des collections "
            "différentes. Préciser avec --collection COTE_COLLECTION."
        )
    return items[0]


def afficher_fiche_item(
    session: Session,
    cote_item: str,
    collection_cote: str | None = None,
    metadonnees_completes: bool = False,
    fichiers: bool = True,
) -> bool:
    from rich.panel import Panel
    from rich.pretty import Pretty
    from rich.table import Table

    try:
        item = _trouver_item(session, cote_item, collection_cote)
    except ItemAmbigu as e:
        cons.console.print(f"[erreur]{e}[/erreur]")
        return False

    if item is None:
        cible = f"{collection_cote}/{cote_item}" if collection_cote else cote_item
        cons.console.print(f"[erreur]Item {cible!r} introuvable.[/erreur]")
        return False

    col = item.collection

    lignes = [
        ("Cote", item.cote),
        ("Collection", f"{col.cote_collection} — {col.titre}"),
        ("Numéro", item.numero or ABSENT),
        ("Date", formater_date(item.date)),
        ("Année", str(item.annee) if item.annee else ABSENT),
        ("Titre", item.titre or ABSENT),
        ("Type COAR", item.type_coar or ABSENT),
        ("Langue", item.langue or ABSENT),
        ("État", formater_etat(item.etat_catalogage)),
        ("DOI Nakala", item.doi_nakala or ABSENT),
        ("DOI collection Nakala", item.doi_collection_nakala or ABSENT),
    ]
    largeur_cle = max(len(c) for c, _ in lignes)
    corps = "\n".join(
        f"[cle]{cle.ljust(largeur_cle)}[/cle] : [valeur]{valeur}[/valeur]"
        for cle, valeur in lignes
    )
    if item.description:
        corps += f"\n\n[sous_titre]Description[/sous_titre]\n{item.description}"
    titre_panneau = f"[titre]Item {item.cote}[/titre] ({col.cote_collection})"
    cons.console.print(Panel(corps, title=titre_panneau, expand=False))

    # Métadonnées étendues
    meta = item.metadonnees or {}
    if meta:
        if metadonnees_completes:
            cons.console.print(
                Panel(
                    Pretty(meta, expand_all=True),
                    title="[sous_titre]Métadonnées étendues (complètes)[/sous_titre]",
                    expand=False,
                )
            )
        else:
            lignes_meta = []
            for cle, val in meta.items():
                if isinstance(val, dict):
                    val_aff = ", ".join(f"{k}={v}" for k, v in val.items())
                    val_aff = tronquer(val_aff, 80)
                elif isinstance(val, list):
                    val_aff = tronquer(", ".join(str(v) for v in val), 80)
                else:
                    val_aff = tronquer(str(val) if val is not None else ABSENT, 80)
                lignes_meta.append((cle, val_aff))
            largeur_meta = max(len(c) for c, _ in lignes_meta)
            corps_meta = "\n".join(
                f"[cle]{cle.ljust(largeur_meta)}[/cle] : [valeur]{val}[/valeur]"
                for cle, val in lignes_meta
            )
            cons.console.print(
                Panel(
                    corps_meta,
                    title="[sous_titre]Métadonnées étendues[/sous_titre]",
                    expand=False,
                )
            )

    # Fichiers rattachés
    if not fichiers:
        return True

    fichiers_tries = sorted(item.fichiers, key=lambda f: f.ordre)
    if not fichiers_tries:
        cons.console.print(
            Panel(
                "[dim]Aucun fichier rattaché.[/dim]",
                title="[sous_titre]Fichiers[/sous_titre]",
                expand=False,
            )
        )
        return True

    tableau = Table(
        title=f"[sous_titre]Fichiers ({len(fichiers_tries)})[/sous_titre]",
        show_lines=False,
    )
    tableau.add_column("#", justify="right")
    tableau.add_column("Type", no_wrap=True)
    tableau.add_column("Folio", no_wrap=True)
    tableau.add_column("Nom", overflow="fold")
    tableau.add_column("Taille", justify="right", no_wrap=True)
    tableau.add_column("État", no_wrap=True)
    for f in fichiers_tries:
        tableau.add_row(
            str(f.ordre),
            f.type_page,
            f.folio or ABSENT,
            f.nom_fichier,
            formater_taille_octets(f.taille_octets),
            formater_etat(f.etat),
        )
    cons.console.print(tableau)
    return True
