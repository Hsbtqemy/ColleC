"""CRUD Item — création dans un fonds + auto-rattachement à la miroir.

Source de vérité pour les invariants 4 et 6 :
- Tout item a `fonds_id` non NULL (CHECK + service refuse).
- À la création, l'item est ajouté à la collection miroir du fonds
  (invariant 6) — dans la même transaction que la création.

Le `fonds_id` d'un item est immuable : déplacer un item d'un fonds
à un autre n'a pas de sens (sa cote serait incohérente). Pour
« déplacer », supprimer et recréer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
    OperationInterdite,
    message_cote_existe,
)
from archives_tool.api.services.tri import (
    Listage,
    Ordre,
    appliquer_tri,
)
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fonds,
    Item,
    ItemCollection,
    TypeCollection,
)


_PATTERN_COTE = re.compile(r"^[A-Za-z0-9_-]+$")
_ETATS_VALIDES: frozenset[str] = frozenset(e.value for e in EtatCatalogage)


class ItemIntrouvable(EntiteIntrouvable):
    """L'identifiant ou la cote de l'item n'existe pas."""


class ItemInvalide(FormulaireInvalide):
    """Données de formulaire invalides."""


class OperationItemInterdite(OperationInterdite):
    """Opération refusée : changer le fonds, fonds sans miroir, etc."""


def _erreur_cote_existe(cote: str) -> ItemInvalide:
    return ItemInvalide(message_cote_existe(cote))


class FormulaireItem(BaseModel):
    """Formulaire de création / modification d'un item.

    `fonds_id` est obligatoire à la création et immuable à la
    modification (le service `modifier_item` rejette tout changement).
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    cote: str = Field(default="")
    titre: str = Field(default="")
    fonds_id: int = Field(default=0)

    description: str = Field(default="")
    notes_internes: str = Field(default="")
    type_coar: str = Field(default="")
    langue: str = Field(default="")
    date: str = Field(default="")
    annee: int | None = None
    numero: str = Field(default="")
    numero_tri: int | None = None
    etat_catalogage: str = Field(default=EtatCatalogage.BROUILLON.value)
    metadonnees: dict[str, Any] = Field(default_factory=dict)
    doi_nakala: str = Field(default="")
    doi_collection_nakala: str = Field(default="")

    @field_validator("annee")
    @classmethod
    def _annee_borne(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 0 or v > 3000:
            raise ValueError(f"Année invraisemblable : {v}")
        return v

    @field_validator("etat_catalogage")
    @classmethod
    def _etat_valide(cls, v: str) -> str:
        if v and v not in _ETATS_VALIDES:
            raise ValueError(f"État inconnu : {v!r}")
        return v or EtatCatalogage.BROUILLON.value


@dataclass
class ItemResume:
    id: int
    cote: str
    titre: str | None
    fonds_id: int
    fonds_cote: str
    etat: str
    date: str | None = None
    annee: int | None = None
    type_coar: str | None = None
    nb_collections: int = 0
    modifie_le: datetime | None = None


def _valider_formulaire(formulaire: FormulaireItem) -> dict[str, str]:
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
    if formulaire.fonds_id <= 0:
        erreurs["fonds_id"] = "Le fonds est obligatoire."
    return erreurs


_OPTIONNELS_NULLABLES: tuple[str, ...] = (
    "description",
    "notes_internes",
    "type_coar",
    "langue",
    "date",
    "numero",
    "doi_nakala",
    "doi_collection_nakala",
)


def _appliquer_formulaire(item: Item, formulaire: FormulaireItem) -> None:
    """Copie le formulaire sur le modèle. `fonds_id` traité séparément
    par les appelants (immuable à la modification)."""
    item.cote = formulaire.cote.strip()
    item.titre = formulaire.titre.strip()
    item.etat_catalogage = (
        formulaire.etat_catalogage or EtatCatalogage.BROUILLON.value
    )
    item.annee = formulaire.annee
    item.numero_tri = formulaire.numero_tri
    item.metadonnees = formulaire.metadonnees or None
    for nom in _OPTIONNELS_NULLABLES:
        valeur = getattr(formulaire, nom)
        setattr(item, nom, valeur.strip() or None if isinstance(valeur, str) else valeur)


def lire_item(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise ItemIntrouvable(item_id)
    return item


def lire_item_par_cote(db: Session, cote: str, *, fonds_id: int) -> Item:
    """Lecture par cote dans un fonds donné. La cote n'étant unique que
    par fonds, `fonds_id` est obligatoire."""
    item = db.scalar(
        select(Item).where(Item.cote == cote, Item.fonds_id == fonds_id)
    )
    if item is None:
        raise ItemIntrouvable(f"cote={cote!r} dans le fonds {fonds_id}")
    return item


def collections_de_item(db: Session, item_id: int) -> list[Collection]:
    """Liste les collections (miroir + libres) où un item figure.

    Requête SQL fraîche plutôt que `item.collections` : la relation
    chargée peut être obsolète après des écritures directes sur la
    junction `item_collection`.
    """
    if db.get(Item, item_id) is None:
        raise ItemIntrouvable(item_id)
    return list(
        db.scalars(
            select(Collection)
            .join(ItemCollection, ItemCollection.collection_id == Collection.id)
            .where(ItemCollection.item_id == item_id)
            .order_by(Collection.titre)
        ).all()
    )


def lister_items_fonds(
    db: Session,
    fonds_id: int,
    *,
    etat: str | None = None,
    tri: str | None = None,
    ordre: Ordre = "asc",
    page: int = 1,
    par_page: int = 50,
) -> Listage[ItemResume]:
    """Liste paginée des items d'un fonds, filtrée optionnellement par état."""
    return _lister_items(
        db,
        scope_filtre=Item.fonds_id == fonds_id,
        etat=etat,
        tri=tri,
        ordre=ordre,
        page=page,
        par_page=par_page,
    )


def lister_items_collection(
    db: Session,
    collection_id: int,
    *,
    etat: str | None = None,
    tri: str | None = None,
    ordre: Ordre = "asc",
    page: int = 1,
    par_page: int = 50,
) -> Listage[ItemResume]:
    """Liste paginée des items d'une collection (via la junction N-N)."""
    return _lister_items(
        db,
        scope_filtre=Item.id.in_(
            select(ItemCollection.item_id).where(
                ItemCollection.collection_id == collection_id
            )
        ),
        etat=etat,
        tri=tri,
        ordre=ordre,
        page=page,
        par_page=par_page,
    )


def _lister_items(
    db: Session,
    *,
    scope_filtre,
    etat: str | None,
    tri: str | None,
    ordre: Ordre,
    page: int,
    par_page: int,
) -> Listage[ItemResume]:
    base_stmt = (
        select(Item, Fonds.cote.label("fonds_cote"))
        .join(Fonds, Item.fonds_id == Fonds.id)
        .where(scope_filtre)
    )
    filtres: dict[str, object] = {}
    if etat and etat in _ETATS_VALIDES:
        base_stmt = base_stmt.where(Item.etat_catalogage == etat)
        filtres["etat"] = etat

    mapping_tri = {
        "cote": Item.cote,
        "titre": Item.titre,
        "date": Item.date,
        "annee": Item.annee,
        "etat": Item.etat_catalogage,
        "modifie": Item.modifie_le,
    }
    stmt, tri_eff, ordre_eff = appliquer_tri(
        base_stmt, mapping_tri, tri, ordre, defaut=("cote", "asc")
    )

    count_stmt = select(func.count(Item.id)).where(scope_filtre)
    if "etat" in filtres:
        count_stmt = count_stmt.where(Item.etat_catalogage == etat)
    total = db.scalar(count_stmt) or 0

    page_eff = max(1, page)
    if par_page > 0:
        stmt = stmt.limit(par_page).offset((page_eff - 1) * par_page)

    rows = db.execute(stmt).all()
    nb_coll_par_item: dict[int, int] = {}
    if rows:
        ids = [r[0].id for r in rows]
        nb_coll_par_item = dict(
            db.execute(
                select(ItemCollection.item_id, func.count())
                .where(ItemCollection.item_id.in_(ids))
                .group_by(ItemCollection.item_id)
            ).all()
        )

    items = [
        ItemResume(
            id=item.id,
            cote=item.cote,
            titre=item.titre,
            fonds_id=item.fonds_id,
            fonds_cote=fonds_cote,
            etat=item.etat_catalogage,
            date=item.date,
            annee=item.annee,
            type_coar=item.type_coar,
            nb_collections=nb_coll_par_item.get(item.id, 0),
            modifie_le=item.modifie_le,
        )
        for item, fonds_cote in rows
    ]
    return Listage(
        items=items,
        tri=tri_eff,
        ordre=ordre_eff,
        page=page_eff,
        par_page=par_page,
        total=total,
        filtres=filtres,
    )


def creer_item(
    db: Session,
    formulaire: FormulaireItem,
    *,
    cree_par: str | None = None,
) -> Item:
    """Crée un item dans un fonds.

    L'item est automatiquement ajouté à la collection miroir du fonds
    (invariant 6). Si la miroir est introuvable (anomalie), lève
    `OperationItemInterdite`.

    Conflit de cote `(fonds_id, cote)` rattrapé via IntegrityError.
    """
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise ItemInvalide(erreurs)

    fonds = db.get(Fonds, formulaire.fonds_id)
    if fonds is None:
        raise ItemInvalide({"fonds_id": f"Le fonds {formulaire.fonds_id} n'existe pas."})

    item = Item(fonds_id=fonds.id, cree_par=cree_par)
    _appliquer_formulaire(item, formulaire)
    db.add(item)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _erreur_cote_existe(item.cote) from e

    miroir_id = db.scalar(
        select(Collection.id).where(
            Collection.fonds_id == fonds.id,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )
    if miroir_id is None:
        db.rollback()
        raise OperationItemInterdite(
            f"Le fonds {fonds.cote!r} (id={fonds.id}) n'a pas de "
            "collection miroir — anomalie d'intégrité."
        )

    db.add(ItemCollection(item_id=item.id, collection_id=miroir_id))
    db.commit()
    db.refresh(item)
    return item


def modifier_item(
    db: Session,
    item_id: int,
    formulaire: FormulaireItem,
    *,
    modifie_par: str | None = None,
) -> Item:
    """Met à jour un item. `fonds_id` est immuable : tout changement
    lève `OperationItemInterdite`. Conflit de cote rattrapé via
    IntegrityError.
    """
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise ItemInvalide(erreurs)

    item = lire_item(db, item_id)
    if formulaire.fonds_id != item.fonds_id:
        raise OperationItemInterdite(
            "Le fonds d'un item ne peut pas être modifié."
        )

    _appliquer_formulaire(item, formulaire)
    item.modifie_par = modifie_par
    item.modifie_le = datetime.now()

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise _erreur_cote_existe(item.cote) from e
    db.refresh(item)
    return item


def supprimer_item(db: Session, item_id: int) -> None:
    """Supprime un item ; ses fichiers et liaisons disparaissent en
    cascade. L'item est retiré de toutes ses collections (y compris
    la miroir)."""
    item = lire_item(db, item_id)
    db.delete(item)
    db.commit()
