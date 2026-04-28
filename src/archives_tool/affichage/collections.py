"""Affichage liste collections (mode plat ou arbre) et fiche collection."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.affichage import console as cons  # le sous-module
from archives_tool.affichage.formatters import (
    ABSENT,
    barre_progression,
    formater_date,
    tronquer,
)
from archives_tool.models import Collection, EtatCatalogage, Fichier, Item


def _stats_collection(session: Session, collection_id: int) -> dict:
    """Compte items, fichiers et ratio d'avancement pour une collection."""
    nb_items = (
        session.scalar(
            select(func.count(Item.id)).where(Item.collection_id == collection_id)
        )
        or 0
    )
    nb_fichiers = (
        session.scalar(
            select(func.count(Fichier.id))
            .join(Item, Fichier.item_id == Item.id)
            .where(Item.collection_id == collection_id)
        )
        or 0
    )
    valides = (
        session.scalar(
            select(func.count(Item.id)).where(
                Item.collection_id == collection_id,
                Item.etat_catalogage.in_(
                    [EtatCatalogage.VALIDE.value, EtatCatalogage.VERIFIE.value]
                ),
            )
        )
        or 0
    )
    ratio = (valides / nb_items) if nb_items else 0.0
    return {
        "nb_items": nb_items,
        "nb_fichiers": nb_fichiers,
        "ratio": ratio,
        "modifie_le": None,  # rempli plus loin si besoin
    }


def _avancement(stats: dict) -> str:
    if stats["nb_items"] == 0:
        return ABSENT
    pct = round(stats["ratio"] * 100)
    return f"{barre_progression(stats['ratio'])} {pct:>3}%"


def afficher_collections_plat(session: Session, vide: bool = True) -> int:
    """Tableau plat de toutes les collections triées par cote."""
    from rich.table import Table

    collections = list(
        session.scalars(select(Collection).order_by(Collection.cote_collection))
    )
    if not collections:
        cons.console.print(
            "[avertissement]Aucune collection en base. "
            "Importez un profil ou créez une collection.[/avertissement]"
        )
        return 0

    table = Table(title="[titre]Collections[/titre]", show_lines=False)
    table.add_column("Cote", style="cyan", no_wrap=True)
    table.add_column("Titre", overflow="fold")
    table.add_column("Items", justify="right")
    table.add_column("Fichiers", justify="right")
    table.add_column("Avancement", no_wrap=True)
    table.add_column("Modifié le", no_wrap=True)

    affichees = 0
    for col in collections:
        stats = _stats_collection(session, col.id)
        if not vide and stats["nb_items"] == 0:
            continue
        table.add_row(
            col.cote_collection,
            tronquer(col.titre, 60),
            str(stats["nb_items"]),
            str(stats["nb_fichiers"]),
            _avancement(stats),
            formater_date(col.modifie_le or col.cree_le),
        )
        affichees += 1

    cons.console.print(table)
    return affichees


def afficher_collections_arbre(session: Session) -> int:
    """Arbre des collections (parent → enfants)."""
    from rich.tree import Tree

    racines = list(
        session.scalars(
            select(Collection)
            .where(Collection.parent_id.is_(None))
            .order_by(Collection.cote_collection)
        )
    )
    if not racines:
        cons.console.print("[avertissement]Aucune collection en base.[/avertissement]")
        return 0

    arbre = Tree("[titre]Collections[/titre]")

    def _ajouter(noeud: Tree, col: Collection) -> int:
        stats = _stats_collection(session, col.id)
        etiquette = (
            f"[cyan]{col.cote_collection}[/cyan] — {tronquer(col.titre, 60)} "
            f"([dim]{stats['nb_items']} items, {stats['nb_fichiers']} fichiers, "
            f"{_avancement(stats)}[/dim])"
        )
        sous_noeud = noeud.add(etiquette)
        compte = 1
        for enfant in sorted(col.enfants, key=lambda c: c.cote_collection):
            compte += _ajouter(sous_noeud, enfant)
        return compte

    total = 0
    for racine in racines:
        total += _ajouter(arbre, racine)

    cons.console.print(arbre)
    return total
