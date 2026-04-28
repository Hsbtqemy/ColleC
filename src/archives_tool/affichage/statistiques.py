"""Statistiques globales ou par collection."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.affichage import console as cons  # le sous-module
from archives_tool.affichage.formatters import (
    LIBELLES_ETAT,
    barre_progression,
    formater_taille_octets,
)
from archives_tool.models import Collection, EtatCatalogage, Fichier, Item


def _ids_dans_arbre(session: Session, racine: Collection) -> list[int]:
    ids = [racine.id]
    a_visiter = list(racine.enfants)
    while a_visiter:
        n = a_visiter.pop(0)
        ids.append(n.id)
        a_visiter.extend(n.enfants)
    return ids


def afficher_statistiques(session: Session, collection_cote: str | None = None) -> bool:
    from rich.panel import Panel

    # Périmètre.
    if collection_cote is not None:
        col = session.scalar(
            select(Collection).where(Collection.cote_collection == collection_cote)
        )
        if col is None:
            cons.console.print(
                f"[erreur]Collection {collection_cote!r} introuvable.[/erreur]"
            )
            return False
        ids = _ids_dans_arbre(session, col)
        nb_racines = 0
        nb_sous_collections = len(ids) - 1
        clause_item = Item.collection_id.in_(ids)
        clause_fichier = Item.collection_id.in_(ids)
        portee = f"Collection [cyan]{col.cote_collection}[/cyan] — {col.titre}"
    else:
        nb_racines = (
            session.scalar(
                select(func.count(Collection.id)).where(Collection.parent_id.is_(None))
            )
            or 0
        )
        nb_total = session.scalar(select(func.count(Collection.id))) or 0
        nb_sous_collections = nb_total - nb_racines
        clause_item = None
        clause_fichier = None
        portee = "Globales"

    # Items.
    stmt_items = select(func.count(Item.id))
    if clause_item is not None:
        stmt_items = stmt_items.where(clause_item)
    nb_items = session.scalar(stmt_items) or 0

    if nb_items == 0:
        cons.console.print(
            f"[avertissement]Aucune donnée à analyser pour la portée : "
            f"{portee}[/avertissement]"
        )
        return True

    # Fichiers + volume.
    stmt_fichiers = select(
        func.count(Fichier.id), func.coalesce(func.sum(Fichier.taille_octets), 0)
    ).join(Item, Fichier.item_id == Item.id)
    if clause_fichier is not None:
        stmt_fichiers = stmt_fichiers.where(clause_fichier)
    nb_fichiers, volume_octets = session.execute(stmt_fichiers).one()

    # Items par état.
    stmt_etats = select(Item.etat_catalogage, func.count(Item.id)).group_by(
        Item.etat_catalogage
    )
    if clause_item is not None:
        stmt_etats = stmt_etats.where(clause_item)
    repartition = dict(session.execute(stmt_etats).all())

    # Composition.
    lignes = [f"[cle]Portée[/cle]                       : [valeur]{portee}[/valeur]"]
    if collection_cote is None:
        lignes.append(
            f"[cle]Collections (racines)[/cle]        : [valeur]{nb_racines}[/valeur]"
        )
    lignes.append(
        f"[cle]Sous-collections[/cle]             : [valeur]{nb_sous_collections}[/valeur]"
    )
    lignes.append(
        f"[cle]Items[/cle]                        : [valeur]{nb_items}[/valeur]"
    )
    lignes.append(
        f"[cle]Fichiers[/cle]                     : [valeur]{nb_fichiers}[/valeur]"
    )
    lignes.append(
        f"[cle]Volume disque référencé[/cle]      : "
        f"[valeur]{formater_taille_octets(int(volume_octets))}[/valeur]"
    )
    lignes.append("")
    lignes.append("[sous_titre]Items par état[/sous_titre]")
    ordre_etats = [
        EtatCatalogage.BROUILLON.value,
        EtatCatalogage.A_VERIFIER.value,
        EtatCatalogage.VERIFIE.value,
        EtatCatalogage.VALIDE.value,
        EtatCatalogage.A_CORRIGER.value,
    ]
    for etat in ordre_etats:
        nb = repartition.get(etat, 0)
        ratio = nb / nb_items if nb_items else 0
        pct = round(ratio * 100)
        libelle = LIBELLES_ETAT.get(etat, etat)
        lignes.append(
            f"  [etat.{etat}]{libelle:<12}[/etat.{etat}] : "
            f"{nb:>4} ({pct:>3}%) {barre_progression(ratio)}"
        )

    # Top 5 collections par items (vue globale uniquement).
    if collection_cote is None:
        top = session.execute(
            select(Collection.cote_collection, Collection.titre, func.count(Item.id))
            .join(Item, Item.collection_id == Collection.id)
            .group_by(Collection.id)
            .order_by(func.count(Item.id).desc())
            .limit(5)
        ).all()
        if top:
            lignes.append("")
            lignes.append("[sous_titre]Top 5 collections par items[/sous_titre]")
            for cote, titre, nb in top:
                lignes.append(f"  [cyan]{cote:<8}[/cyan] {titre[:28]:<30} : {nb:>4}")

    cons.console.print(
        Panel(
            "\n".join(lignes),
            title=f"[titre]Statistiques — {portee}[/titre]",
            expand=False,
        )
    )
    return True
