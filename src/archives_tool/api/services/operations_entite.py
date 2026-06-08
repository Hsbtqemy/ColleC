"""Journal des suppressions d'entités (principe directeur n°4).

`OperationFichier` ne couvre que les fichiers, `ModificationItem` que
les métadonnées d'item — les **suppressions** de fonds / collection /
item n'étaient tracées nulle part. Ce module construit et insère une
ligne :class:`OperationEntite` **avant** la suppression effective,
dans la même transaction que le delete : le caller fait un commit
unique, donc journal et suppression sont atomiques (les deux, ou rien).

Phase 1 : audit + snapshot forensique. Pas d'undo — le snapshot
conserve les colonnes propres de l'entité + les ids/cotes des enfants
affectés (bornés), ce qui rend un restore futur possible sans perte
d'information (réversibilité asymétrique), mais l'exécution de l'undo
est reportée à un chantier dédié.

Listing : :func:`lister_suppressions`.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

from archives_tool.models import (
    AnnotationRegion,
    CollaborateurFonds,
    Collection,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
    OperationEntite,
    TypeCollection,
)

_PRIMITIFS = (str, int, float, bool, dict, list)


def _colonnes(obj: Any) -> dict[str, Any]:
    """Sérialise les colonnes propres d'un objet ORM en dict JSON-able.

    Les colonnes JSON (`metadonnees`) restent des dict/list ; les types
    non primitifs (datetime) sont convertis en str. N'inclut pas les
    relations — uniquement les colonnes mappées de la table de l'entité.
    """
    out: dict[str, Any] = {}
    for attr in sa_inspect(obj).mapper.column_attrs:
        valeur = getattr(obj, attr.key)
        out[attr.key] = valeur if valeur is None or isinstance(valeur, _PRIMITIFS) else str(valeur)
    return out


def _ajouter(
    db: Session,
    *,
    type_entite: str,
    entite: Any,
    cote: str | None,
    fonds_cote: str | None,
    titre: str | None,
    cascade: dict[str, Any],
    execute_par: str | None,
) -> None:
    """Ajoute la ligne de journal à la session (sans commit — le service
    de suppression committe une seule fois pour garantir l'atomicité)."""
    db.add(
        OperationEntite(
            type_entite=type_entite,
            entite_id=entite.id,
            cote=cote,
            fonds_cote=fonds_cote,
            titre=titre,
            snapshot_json=json.dumps(_colonnes(entite), ensure_ascii=False, default=str),
            cascade_resume=json.dumps(cascade, ensure_ascii=False, default=str),
            execute_par=execute_par,
        )
    )


def journaliser_suppression_item(
    db: Session, item: Item, *, execute_par: str | None = None
) -> None:
    """Journalise la suppression d'un item (fichiers + annotations +
    junctions disparaissent en cascade). À appeler avant `db.delete(item)`."""
    nb_fichiers = (
        db.scalar(select(func.count(Fichier.id)).where(Fichier.item_id == item.id)) or 0
    )
    nb_annotations = (
        db.scalar(
            select(func.count(AnnotationRegion.id))
            .join(Fichier, AnnotationRegion.fichier_id == Fichier.id)
            .where(Fichier.item_id == item.id)
        )
        or 0
    )
    fichier_ids = list(
        db.scalars(select(Fichier.id).where(Fichier.item_id == item.id)).all()
    )
    collection_ids = list(
        db.scalars(
            select(ItemCollection.collection_id).where(
                ItemCollection.item_id == item.id
            )
        ).all()
    )
    cascade = {
        "fichiers": nb_fichiers,
        "annotations": nb_annotations,
        "junctions": len(collection_ids),
        "fichier_ids": fichier_ids,
        "collection_ids": collection_ids,
    }
    _ajouter(
        db,
        type_entite="item",
        entite=item,
        cote=item.cote,
        fonds_cote=item.fonds.cote if item.fonds is not None else None,
        titre=item.titre,
        cascade=cascade,
        execute_par=execute_par,
    )


def journaliser_suppression_collection(
    db: Session, collection: Collection, *, execute_par: str | None = None
) -> None:
    """Journalise la suppression d'une collection libre (seules les
    junctions item_collection disparaissent ; les items survivent). À
    appeler avant `db.delete(collection)`."""
    item_ids = list(
        db.scalars(
            select(ItemCollection.item_id).where(
                ItemCollection.collection_id == collection.id
            )
        ).all()
    )
    cascade = {"junctions": len(item_ids), "item_ids": item_ids}
    _ajouter(
        db,
        type_entite="collection",
        entite=collection,
        cote=collection.cote,
        fonds_cote=collection.fonds.cote if collection.fonds is not None else None,
        titre=collection.titre,
        cascade=cascade,
        execute_par=execute_par,
    )


def journaliser_suppression_fonds(
    db: Session, fonds: Fonds, *, execute_par: str | None = None
) -> None:
    """Journalise la suppression d'un fonds (items + miroir +
    collaborateurs en cascade ; les libres rattachées deviennent
    transversales via FK SET NULL). À appeler avant `db.delete(...)`."""
    item_rows = db.execute(
        select(Item.id, Item.cote).where(Item.fonds_id == fonds.id)
    ).all()
    nb_fichiers = (
        db.scalar(
            select(func.count(Fichier.id))
            .join(Item, Fichier.item_id == Item.id)
            .where(Item.fonds_id == fonds.id)
        )
        or 0
    )
    nb_annotations = (
        db.scalar(
            select(func.count(AnnotationRegion.id))
            .join(Fichier, AnnotationRegion.fichier_id == Fichier.id)
            .join(Item, Fichier.item_id == Item.id)
            .where(Item.fonds_id == fonds.id)
        )
        or 0
    )
    nb_collaborateurs = (
        db.scalar(
            select(func.count(CollaborateurFonds.id)).where(
                CollaborateurFonds.fonds_id == fonds.id
            )
        )
        or 0
    )
    libres = db.execute(
        select(Collection.id, Collection.cote).where(
            Collection.fonds_id == fonds.id,
            Collection.type_collection != TypeCollection.MIROIR.value,
        )
    ).all()
    miroir = fonds.collection_miroir
    cascade = {
        "items": len(item_rows),
        "fichiers": nb_fichiers,
        "annotations": nb_annotations,
        "collaborateurs": nb_collaborateurs,
        "collections_detachees": len(libres),
        "miroir_supprimee": miroir is not None,
        "item_cotes": [cote for _, cote in item_rows],
        "collection_detachee_cotes": [cote for _, cote in libres],
        "miroir_cote": miroir.cote if miroir is not None else None,
    }
    _ajouter(
        db,
        type_entite="fonds",
        entite=fonds,
        cote=fonds.cote,
        fonds_cote=fonds.cote,
        titre=fonds.titre,
        cascade=cascade,
        execute_par=execute_par,
    )


def lister_suppressions(
    db: Session,
    *,
    type_entite: str | None = None,
    limite: int = 100,
) -> list[OperationEntite]:
    """Liste les suppressions journalisées, plus récentes d'abord.

    `type_entite` filtre sur `fonds` / `collection` / `item` si fourni.
    """
    requete = select(OperationEntite).order_by(OperationEntite.execute_le.desc())
    if type_entite is not None:
        requete = requete.where(OperationEntite.type_entite == type_entite)
    return list(db.scalars(requete.limit(limite)).all())
