"""CRUD Collection — gère uniquement les collections **libres**.

Les collections **miroirs** sont créées et supprimées par
`services/fonds.py` (pas d'API publique ici pour les muter).

Invariants de référence (cf. `models/collection.py` et CLAUDE.md) :
- Cote unique au sein d'un fonds (index `(fonds_id, cote)`).
- Une miroir doit toujours avoir un `fonds_id` (CHECK).
- Une libre peut être rattachée à un fonds ou transversale.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
    OperationInterdite,
    message_cote_existe,
)
from archives_tool.models import (
    Collection,
    Fonds,
    Item,
    ItemCollection,
    PhaseChantier,
    TypeCollection,
)


_PATTERN_COTE = re.compile(r"^[A-Za-z0-9_-]+$")


class CollectionIntrouvable(EntiteIntrouvable):
    """L'identifiant ou la cote de la collection n'existe pas."""


class CollectionInvalide(FormulaireInvalide):
    """Données de formulaire invalides : cote conflit, fonds inexistant…"""


class OperationCollectionInterdite(OperationInterdite):
    """Opération refusée par invariant : modifier le fonds d'une miroir,
    supprimer une miroir indépendamment du fonds, etc."""


def _erreur_cote_existe(cote: str) -> CollectionInvalide:
    return CollectionInvalide(message_cote_existe(cote))


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


def _valider_formulaire(formulaire: FormulaireCollection) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    cote = formulaire.cote.strip()
    if not cote:
        erreurs["cote"] = "La cote est obligatoire."
    elif not _PATTERN_COTE.match(cote):
        erreurs["cote"] = (
            "Caractères autorisés : lettres, chiffres, tiret, souligné."
        )
    if not formulaire.titre.strip():
        erreurs["titre"] = "Le titre est obligatoire."
    return erreurs


_OPTIONNELS_NULLABLES: tuple[str, ...] = (
    "description",
    "description_publique",
    "description_interne",
    "doi_nakala",
    "doi_collection_nakala_parent",
    "personnalite_associee",
    "responsable_archives",
)


def _appliquer_formulaire(
    col: Collection, formulaire: FormulaireCollection
) -> None:
    """Copie le formulaire sur le modèle ; chaînes vides → None pour
    les champs optionnels.

    Le `type_collection` n'est pas dans le formulaire — on ne change
    pas le type d'une collection (miroir reste miroir, libre reste
    libre).
    """
    col.cote = formulaire.cote.strip()
    col.titre = formulaire.titre.strip()
    col.fonds_id = formulaire.fonds_id
    col.phase = formulaire.phase or PhaseChantier.CATALOGAGE.value
    for nom in _OPTIONNELS_NULLABLES:
        valeur = getattr(formulaire, nom)
        setattr(col, nom, valeur.strip() or None if isinstance(valeur, str) else valeur)


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
    stmt = select(Collection).where(Collection.cote == cote)
    if fonds_id is not None:
        stmt = stmt.where(Collection.fonds_id == fonds_id)

    resultats = list(db.scalars(stmt).all())
    if not resultats:
        contexte = f" dans le fonds {fonds_id}" if fonds_id is not None else ""
        raise CollectionIntrouvable(f"cote={cote!r}{contexte}")
    if len(resultats) > 1:
        raise OperationCollectionInterdite(
            f"Cote {cote!r} ambiguë : {len(resultats)} collections trouvées. "
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
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise CollectionInvalide(erreurs)
    _verifier_fonds(db, formulaire.fonds_id)

    col = Collection(
        type_collection=TypeCollection.LIBRE.value,
        cree_par=cree_par,
    )
    _appliquer_formulaire(col, formulaire)
    db.add(col)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise _erreur_cote_existe(col.cote) from e
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
    erreurs = _valider_formulaire(formulaire)
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

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise _erreur_cote_existe(col.cote) from e
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
