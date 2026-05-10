"""Famille 1 — invariants du modèle Fonds / Collection / Item.

Vérifie que les invariants posés en V0.9.0-alpha (1, 2, 4, 6) tiennent
en runtime. La plupart sont garantis par contraintes DB ou par les
services métier ; ce module joue le rôle de filet de sécurité quand
on travaille avec une base manipulée hors API (ex. import SQL direct).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.models import (
    Collection,
    Fonds,
    Item,
    ItemCollection,
    TypeCollection,
)
from archives_tool.qa._commun import (
    Exemple,
    PerimetreControle,
    ResultatControle,
    Severite,
    borner_exemples,
)

FAMILLE = "invariants"


def _filtrer_fonds(stmt, perimetre: PerimetreControle):
    if perimetre.fonds_id is not None:
        return stmt.where(Fonds.id == perimetre.fonds_id)
    return stmt


def controler_inv1_miroir_unique(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """INV1 : tout fonds a exactement une collection miroir."""
    stmt = (
        select(
            Fonds.id,
            Fonds.cote,
            func.count(Collection.id).label("nb_miroirs"),
        )
        .outerjoin(
            Collection,
            (Collection.fonds_id == Fonds.id)
            & (Collection.type_collection == TypeCollection.MIROIR.value),
        )
        .group_by(Fonds.id, Fonds.cote)
        .order_by(Fonds.cote)
    )
    rows = db.execute(_filtrer_fonds(stmt, perimetre)).all()
    problemes: list[Exemple] = []
    for fonds_id, cote, nb in rows:
        if nb == 1:
            continue
        msg = (
            f"Fonds {cote} sans collection miroir"
            if nb == 0
            else f"Fonds {cote} a {nb} miroirs (devrait en avoir 1)"
        )
        problemes.append(
            Exemple(message=msg, references={"fonds_cote": cote, "fonds_id": fonds_id})
        )
    return ResultatControle(
        id="INV1",
        famille=FAMILLE,
        severite=Severite.ERREUR,
        libelle="Collection miroir unique par fonds",
        passe=not problemes,
        compte_total=len(rows),
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
    )


def controler_inv2_miroir_avec_fonds(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """INV2 : toute collection miroir a fonds_id non null."""
    stmt = (
        select(Collection.id, Collection.cote)
        .where(
            Collection.type_collection == TypeCollection.MIROIR.value,
            Collection.fonds_id.is_(None),
        )
        .order_by(Collection.cote)
    )
    nb_miroirs = (
        db.scalar(
            select(func.count(Collection.id)).where(
                Collection.type_collection == TypeCollection.MIROIR.value
            )
        )
        or 0
    )
    rows = db.execute(stmt).all()
    problemes = [
        Exemple(
            message=f"Collection miroir orpheline : {cote}",
            references={"collection_cote": cote, "collection_id": cid},
        )
        for cid, cote in rows
    ]
    return ResultatControle(
        id="INV2",
        famille=FAMILLE,
        severite=Severite.ERREUR,
        libelle="Collection miroir avec fonds parent",
        passe=not problemes,
        compte_total=nb_miroirs,
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
    )


def controler_inv4_item_avec_fonds(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """INV4 : tout item a fonds_id non null.

    `Item.fonds_id` est NOT NULL au niveau DB — ce contrôle est donc
    un filet de sécurité (impossible en théorie sans manipulation
    manuelle hors API)."""
    stmt = select(Item.id, Item.cote).where(Item.fonds_id.is_(None))
    rows = db.execute(stmt).all()
    problemes = [
        Exemple(
            message=f"Item {cote} sans fonds",
            references={"item_cote": cote, "item_id": iid},
        )
        for iid, cote in rows
    ]
    return ResultatControle(
        id="INV4",
        famille=FAMILLE,
        severite=Severite.ERREUR,
        libelle="Item rattaché à un fonds",
        passe=not problemes,
        compte_total=perimetre.items_count,
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
    )


def controler_inv6_item_dans_miroir(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """INV6 : tout item est dans la collection miroir de son fonds.

    Severité **avertissement** : retirer un item de sa miroir est
    explicitement permis par l'invariant 7 (l'item reste dans le fonds).
    Le contrôle remonte l'information pour que l'utilisateur sache
    où se trouve l'écart, sans bloquer.
    """
    miroirs_par_fonds = dict(
        db.execute(
            select(Collection.fonds_id, Collection.id).where(
                Collection.type_collection == TypeCollection.MIROIR.value
            )
        ).all()
    )

    items_stmt = select(Item.id, Item.cote, Item.fonds_id, Fonds.cote.label("fc")).join(
        Fonds, Fonds.id == Item.fonds_id
    )
    if perimetre.fonds_id is not None:
        items_stmt = items_stmt.where(Item.fonds_id == perimetre.fonds_id)
    items = db.execute(items_stmt).all()

    liaisons = set(
        db.execute(
            select(ItemCollection.item_id, ItemCollection.collection_id)
        ).all()
    )

    problemes: list[Exemple] = []
    for iid, item_cote, fonds_id, fc in items:
        miroir_id = miroirs_par_fonds.get(fonds_id)
        if miroir_id is None:
            continue  # INV1 le couvre
        if (iid, miroir_id) not in liaisons:
            problemes.append(
                Exemple(
                    message=(
                        f"Item {item_cote} retiré de la miroir du fonds {fc}"
                    ),
                    references={
                        "item_cote": item_cote,
                        "item_id": iid,
                        "fonds_cote": fc,
                    },
                )
            )

    return ResultatControle(
        id="INV6",
        famille=FAMILLE,
        severite=Severite.AVERTISSEMENT,
        libelle="Item dans la collection miroir de son fonds",
        passe=not problemes,
        compte_total=len(items),
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
    )
