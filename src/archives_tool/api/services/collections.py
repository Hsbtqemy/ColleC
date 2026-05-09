"""CRUD Collection — gère uniquement les collections **libres**.

Les collections **miroirs** sont créées et supprimées par
`services/fonds.py` (pas d'API publique ici pour les muter).

Invariants de référence (cf. `models/collection.py` et CLAUDE.md) :
- Cote unique au sein d'un fonds (index `(fonds_id, cote)`).
- Une miroir doit toujours avoir un `fonds_id` (CHECK).
- Une libre peut être rattachée à un fonds ou transversale.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
    OperationInterdite,
    chaine_ou_none,
    garde_cote_unique,
    valider_cote_titre,
)
from archives_tool.api.services.tri import Listage
from archives_tool.models import (
    Collection,
    Fonds,
    Item,
    ItemCollection,
    PhaseChantier,
    TypeCollection,
)


class CollectionIntrouvable(EntiteIntrouvable):
    """L'identifiant ou la cote de la collection n'existe pas."""


class CollectionInvalide(FormulaireInvalide):
    """Données de formulaire invalides : cote conflit, fonds inexistant…"""


class OperationCollectionInterdite(OperationInterdite):
    """Opération refusée par invariant : modifier le fonds d'une miroir,
    supprimer une miroir indépendamment du fonds, etc."""


class FormulaireCollection(BaseModel):
    """Formulaire de création / modification d'une collection libre.

    La collection **miroir** est créée par `services/fonds.creer_fonds` ;
    aucun champ ici ne s'applique aux miroirs.
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    cote: str = Field(default="")
    titre: str = Field(default="")
    description: str = Field(default="")
    description_publique: str = Field(default="")
    description_interne: str = Field(default="")
    fonds_id: int | None = None
    phase: str = Field(default=PhaseChantier.CATALOGAGE.value)
    doi_nakala: str = Field(default="")
    doi_collection_nakala_parent: str = Field(default="")
    personnalite_associee: str = Field(default="")
    responsable_archives: str = Field(default="")

    @field_validator("phase")
    @classmethod
    def _phase_valide(cls, v: str) -> str:
        if v and v not in {p.value for p in PhaseChantier}:
            raise ValueError(f"Phase inconnue : {v!r}")
        return v or PhaseChantier.CATALOGAGE.value


_OPTIONNELS_NULLABLES: tuple[str, ...] = (
    "description",
    "description_publique",
    "description_interne",
    "doi_nakala",
    "doi_collection_nakala_parent",
    "personnalite_associee",
    "responsable_archives",
)


def formulaire_depuis_collection(col: Collection) -> FormulaireCollection:
    """Pré-remplit un `FormulaireCollection` depuis une Collection
    existante (pour la page d'édition)."""
    return FormulaireCollection(
        cote=col.cote,
        titre=col.titre,
        description=col.description or "",
        description_publique=col.description_publique or "",
        description_interne=col.description_interne or "",
        fonds_id=col.fonds_id,
        phase=col.phase or PhaseChantier.CATALOGAGE.value,
        doi_nakala=col.doi_nakala or "",
        doi_collection_nakala_parent=col.doi_collection_nakala_parent or "",
        personnalite_associee=col.personnalite_associee or "",
        responsable_archives=col.responsable_archives or "",
    )


def _appliquer_formulaire(
    col: Collection, formulaire: FormulaireCollection
) -> None:
    """Copie le formulaire sur le modèle ; chaînes vides → None pour
    les champs optionnels.

    Le `type_collection` n'est pas dans le formulaire : on ne change
    pas le type d'une collection (miroir reste miroir, libre reste
    libre).
    """
    col.cote = formulaire.cote.strip()
    col.titre = formulaire.titre.strip()
    col.fonds_id = formulaire.fonds_id
    col.phase = formulaire.phase or PhaseChantier.CATALOGAGE.value
    for nom in _OPTIONNELS_NULLABLES:
        setattr(col, nom, chaine_ou_none(getattr(formulaire, nom)))


def _verifier_fonds(db: Session, fonds_id: int | None) -> None:
    """Lève si le fonds référencé n'existe pas. None est accepté
    (collection transversale)."""
    if fonds_id is None:
        return
    if db.get(Fonds, fonds_id) is None:
        raise CollectionInvalide(
            {"fonds_id": f"Le fonds {fonds_id} n'existe pas."}
        )


def lire_collection(db: Session, collection_id: int) -> Collection:
    """Lit une collection par id ou lève `CollectionIntrouvable`."""
    col = db.get(Collection, collection_id)
    if col is None:
        raise CollectionIntrouvable(collection_id)
    return col


def lire_collection_par_cote(
    db: Session, cote: str, *, fonds_id: int | None = None
) -> Collection:
    """Lit une collection par cote.

    `fonds_id` permet de désambiguïser quand plusieurs collections de
    même cote existent (cas typique : la miroir d'un fonds + une
    transversale qui partage la cote). Si `fonds_id` est None et
    plusieurs collections matchent, lève `OperationCollectionInterdite`.
    """
    # LIMIT 2 : suffit pour détecter l'ambiguïté sans charger tous les
    # matches potentiels.
    stmt = select(Collection).where(Collection.cote == cote)
    if fonds_id is not None:
        stmt = stmt.where(Collection.fonds_id == fonds_id)
    resultats = list(db.scalars(stmt.limit(2)).all())

    if not resultats:
        contexte = f" dans le fonds {fonds_id}" if fonds_id is not None else ""
        raise CollectionIntrouvable(f"cote={cote!r}{contexte}")
    if len(resultats) > 1:
        raise OperationCollectionInterdite(
            f"Cote {cote!r} ambiguë : plusieurs collections trouvées. "
            "Précisez fonds_id."
        )
    return resultats[0]


def lister_collections(
    db: Session,
    *,
    fonds_id: int | None = None,
    type_collection: TypeCollection | str | None = None,
) -> list[Collection]:
    """Liste les collections, optionnellement filtrées par fonds et / ou
    type. Pas de pagination dans ce service ; l'UI dashboard construira
    sa propre vue paginée en V0.9.0-beta.
    """
    stmt = select(Collection)
    if fonds_id is not None:
        stmt = stmt.where(Collection.fonds_id == fonds_id)
    if type_collection is not None:
        valeur = (
            type_collection.value
            if isinstance(type_collection, TypeCollection)
            else type_collection
        )
        stmt = stmt.where(Collection.type_collection == valeur)
    return list(db.scalars(stmt.order_by(Collection.titre)).all())


def creer_collection_libre(
    db: Session,
    formulaire: FormulaireCollection,
    *,
    cree_par: str | None = None,
) -> Collection:
    """Crée une collection **libre**. Si `fonds_id` est fourni, vérifie
    que le fonds existe. L'unicité `(fonds_id, cote)` est garantie par
    l'index DB ; en cas de conflit, l'IntegrityError du commit est
    rattrapée.
    """
    erreurs = valider_cote_titre(formulaire.cote, formulaire.titre)
    if erreurs:
        raise CollectionInvalide(erreurs)
    _verifier_fonds(db, formulaire.fonds_id)

    col = Collection(
        type_collection=TypeCollection.LIBRE.value,
        cree_par=cree_par,
    )
    _appliquer_formulaire(col, formulaire)
    db.add(col)
    with garde_cote_unique(db, CollectionInvalide, col.cote):
        db.commit()
    db.refresh(col)
    return col


def modifier_collection(
    db: Session,
    collection_id: int,
    formulaire: FormulaireCollection,
    *,
    modifie_par: str | None = None,
) -> Collection:
    """Met à jour une collection.

    Refuse de changer `fonds_id` d'une miroir (rattachement immuable
    par invariant). Les autres champs sont libres. Conflit de cote
    rattrapé via IntegrityError.
    """
    erreurs = valider_cote_titre(formulaire.cote, formulaire.titre)
    if erreurs:
        raise CollectionInvalide(erreurs)

    col = lire_collection(db, collection_id)

    if (
        col.type_collection == TypeCollection.MIROIR.value
        and formulaire.fonds_id != col.fonds_id
    ):
        raise OperationCollectionInterdite(
            "Le fonds d'une collection miroir ne peut pas être modifié."
        )
    if formulaire.fonds_id != col.fonds_id:
        _verifier_fonds(db, formulaire.fonds_id)

    _appliquer_formulaire(col, formulaire)
    col.modifie_par = modifie_par
    col.modifie_le = datetime.now()

    with garde_cote_unique(db, CollectionInvalide, col.cote):
        db.commit()
    db.refresh(col)
    return col


def supprimer_collection_libre(db: Session, collection_id: int) -> None:
    """Supprime une collection libre. Refuse les miroirs (gérées par le
    service Fonds). Les liaisons `item_collection` sont supprimées en
    cascade ; les items eux-mêmes restent dans leur fonds et leurs
    autres collections.
    """
    col = lire_collection(db, collection_id)
    if col.type_collection == TypeCollection.MIROIR.value:
        raise OperationCollectionInterdite(
            "Une collection miroir ne peut pas être supprimée "
            "indépendamment du fonds."
        )
    db.delete(col)
    db.commit()


def ajouter_item_a_collection(
    db: Session,
    item_id: int,
    collection_id: int,
    *,
    ajoute_par: str | None = None,
) -> ItemCollection:
    """Lie un item à une collection (idempotent).

    Vérifie que l'item et la collection existent. Si la liaison existe
    déjà, retourne l'instance existante sans erreur ni doublon.
    """
    if db.get(Item, item_id) is None:
        raise EntiteIntrouvable(f"Item {item_id} introuvable.")
    lire_collection(db, collection_id)

    existante = db.get(ItemCollection, (item_id, collection_id))
    if existante is not None:
        return existante

    liaison = ItemCollection(
        item_id=item_id,
        collection_id=collection_id,
        ajoute_par=ajoute_par,
    )
    db.add(liaison)
    db.commit()
    return liaison


def ajouter_items_a_collection(
    db: Session,
    collection_id: int,
    item_ids: list[int],
    *,
    ajoute_par: str | None = None,
) -> int:
    """Ajoute plusieurs items à une collection en un commit. Idempotent
    (les items déjà présents sont ignorés). Retourne le nombre de
    liaisons effectivement créées.

    Vérifie l'existence de la collection (`CollectionIntrouvable` sinon).
    Les `item_id` inexistants sont silencieusement ignorés (l'IntegrityError
    sur INSERT échouerait sinon, mais on filtre avant).
    """
    lire_collection(db, collection_id)
    if not item_ids:
        return 0

    # Items qui existent réellement.
    ids_valides = set(
        db.scalars(select(Item.id).where(Item.id.in_(item_ids))).all()
    )
    # Items déjà liés à la collection.
    deja_lies = set(
        db.scalars(
            select(ItemCollection.item_id).where(
                ItemCollection.collection_id == collection_id,
                ItemCollection.item_id.in_(ids_valides),
            )
        ).all()
    )
    a_creer = ids_valides - deja_lies
    for iid in a_creer:
        db.add(
            ItemCollection(
                item_id=iid,
                collection_id=collection_id,
                ajoute_par=ajoute_par,
            )
        )
    db.commit()
    return len(a_creer)


def items_disponibles_pour_collection(
    db: Session,
    collection_id: int,
    *,
    fonds_id: int | None = None,
    recherche: str | None = None,
    page: int = 1,
    par_page: int = 50,
) -> Listage[Item]:
    """Page d'items qui ne sont PAS encore dans la collection.

    Filtres optionnels :
    - `fonds_id` : restreint aux items d'un fonds.
    - `recherche` : matche cote OU titre via `ILIKE %text%`.

    Retourne un `Listage[Item]` (cf. `services/tri.py`) — même contrat
    de pagination que `lister_items_collection`.
    """
    deja_dans = select(ItemCollection.item_id).where(
        ItemCollection.collection_id == collection_id
    )
    base_stmt = select(Item).where(Item.id.notin_(deja_dans))
    filtres: dict[str, object] = {}
    if fonds_id is not None:
        base_stmt = base_stmt.where(Item.fonds_id == fonds_id)
        filtres["fonds_id"] = fonds_id
    terme_recherche = (recherche or "").strip()
    if terme_recherche:
        motif = f"%{terme_recherche}%"
        base_stmt = base_stmt.where(
            Item.cote.ilike(motif) | Item.titre.ilike(motif)
        )
        filtres["recherche"] = terme_recherche

    total = db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
    page_eff = max(1, page)
    par_page_eff = max(1, par_page)
    items = list(
        db.scalars(
            base_stmt.order_by(Item.cote)
            .limit(par_page_eff)
            .offset((page_eff - 1) * par_page_eff)
        ).all()
    )
    return Listage(
        items=items,
        tri="cote",
        ordre="asc",
        page=page_eff,
        par_page=par_page_eff,
        total=total,
        filtres=filtres,
    )


def retirer_item_de_collection(
    db: Session, item_id: int, collection_id: int
) -> None:
    """Retire un item d'une collection (idempotent).

    Pas d'erreur si la liaison n'existe pas. Permis sur les miroirs
    aussi : un item retiré de sa miroir reste dans le fonds et ses
    autres collections (invariant 7).
    """
    liaison = db.get(ItemCollection, (item_id, collection_id))
    if liaison is None:
        return
    db.delete(liaison)
    db.commit()
