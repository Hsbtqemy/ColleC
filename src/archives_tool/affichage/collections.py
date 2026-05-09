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


def afficher_fiche_collection(
    session: Session,
    cote: str,
    items: bool = True,
    limite: int = 50,
    tri_par: str = "cote",
) -> bool:
    """Panneau Rich avec les métadonnées + tableau d'items.

    Retourne False si la collection n'existe pas (sortie déjà émise).
    """
    from rich.panel import Panel
    from rich.table import Table

    col = session.scalar(select(Collection).where(Collection.cote_collection == cote))
    if col is None:
        cons.console.print(f"[erreur]Collection {cote!r} introuvable en base.[/erreur]")
        return False

    stats = _stats_collection(session, col.id)
    nb_sous = (
        session.scalar(
            select(func.count(Collection.id)).where(Collection.parent_id == col.id)
        )
        or 0
    )

    dates = ABSENT
    if col.date_debut and col.date_fin:
        dates = f"{col.date_debut} — {col.date_fin}"
    elif col.date_debut:
        dates = f"{col.date_debut} —"

    lignes_meta = [
        ("Cote", col.cote_collection),
        ("Titre", col.titre),
        ("Éditeur", col.editeur or ABSENT),
        ("Lieu", col.lieu_edition or ABSENT),
        ("Périodicité", col.periodicite or ABSENT),
        ("Dates", dates),
        ("ISSN", col.issn or ABSENT),
        ("DOI Nakala", col.doi_nakala or ABSENT),
        ("Items", str(stats["nb_items"])),
        ("Fichiers", str(stats["nb_fichiers"])),
        ("Sous-collections", str(nb_sous)),
        ("Personnalité associée", col.personnalite_associee or ABSENT),
        ("Responsable Archives", col.responsable_archives or ABSENT),
    ]
    largeur_cle = max(len(c) for c, _ in lignes_meta)
    corps = "\n".join(
        f"[cle]{cle.ljust(largeur_cle)}[/cle] : [valeur]{valeur}[/valeur]"
        for cle, valeur in lignes_meta
    )
    if col.description:
        corps += f"\n\n[sous_titre]Description publique[/sous_titre]\n{col.description}"
    if col.description_interne:
        corps += (
            f"\n\n[sous_titre]Description interne[/sous_titre]\n"
            f"{col.description_interne}"
        )

    titre_panneau = f"[titre]{col.cote_collection}[/titre] — {col.titre}"
    cons.console.print(Panel(corps, title=titre_panneau, expand=False))

    if not items:
        return True

    # Tableau des items.
    cles_tri = {
        "cote": Item.cote,
        "date": Item.date,
        "etat": Item.etat_catalogage,
        "modifie": Item.modifie_le,
    }
    if tri_par not in cles_tri:
        tri_par = "cote"
    stmt = select(Item).where(Item.collection_id == col.id).order_by(cles_tri[tri_par])
    if limite > 0:
        stmt = stmt.limit(limite)
    liste = list(session.scalars(stmt))

    if not liste:
        cons.console.print("[dim]Aucun item rattaché à cette collection.[/dim]")
        return True

    tableau = Table(title=f"Items ({stats['nb_items']})", show_lines=False)
    tableau.add_column("Cote", style="cyan", no_wrap=True)
    tableau.add_column("Numéro", no_wrap=True)
    tableau.add_column("Date", no_wrap=True)
    tableau.add_column("Titre", overflow="fold")
    tableau.add_column("État", no_wrap=True)
    tableau.add_column("Fichiers", justify="right")

    for it in liste:
        nb_f = (
            session.scalar(
                select(func.count(Fichier.id)).where(Fichier.item_id == it.id)
            )
            or 0
        )
        from archives_tool.affichage.formatters import formater_etat

        tableau.add_row(
            it.cote,
            it.numero or ABSENT,
            formater_date(it.date),
            tronquer(it.titre, 60),
            formater_etat(it.etat_catalogage),
            str(nb_f),
        )
    cons.console.print(tableau)

    if limite > 0 and stats["nb_items"] > limite:
        cons.console.print(
            f"[dim]Affichage des {limite} premiers sur {stats['nb_items']}. "
            f"Utilisez --limite pour ajuster.[/dim]"
        )
    return True
