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

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.affichage.formatters import (
    date_incertaine as _date_incertaine,
    temps_relatif,
)
from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
    OperationInterdite,
    chaine_ou_none,
    garde_cote_unique,
    valider_cote_titre,
)
from archives_tool.api.services.tri import (
    Listage,
    Ordre,
    appliquer_tri,
)
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
    TypeCollection,
)


_ETATS_VALIDES: frozenset[str] = frozenset(e.value for e in EtatCatalogage)


class ItemIntrouvable(EntiteIntrouvable):
    """L'identifiant ou la cote de l'item n'existe pas."""


class ItemInvalide(FormulaireInvalide):
    """Données de formulaire invalides."""


class OperationItemInterdite(OperationInterdite):
    """Opération refusée : changer le fonds, fonds sans miroir, etc."""


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
    nb_fichiers: int = 0
    modifie_le: datetime | None = None
    modifie_par: str | None = None
    description: str | None = None
    langue: str | None = None
    doi_nakala: str | None = None
    doi_collection_nakala: str | None = None
    metadonnees: dict[str, Any] | None = None

    # ---- Aliases attendus par la macro `tableau_items` (cf.
    # `web/templates/components/tableau_items.html`) -----
    # La macro accède : cote, href, titre, type_chaine, type_label,
    # date, date_incertaine, etat, nb_fichiers, modifie_par,
    # modifie_depuis, meta. Les passerelles ci-dessous évitent une
    # dataclass jumelle.

    @property
    def href(self) -> str:
        return f"/item/{self.cote}?fonds={self.fonds_cote}"

    @property
    def date_incertaine(self) -> bool:
        # Délègue au helper canonique de `affichage/formatters` qui
        # reconnaît `?`, `vers`, `c.`/`ca.`, `s.d.` (insensible à la casse).
        return _date_incertaine(self.date)

    @property
    def type_chaine(self) -> str | None:
        # V0.9.0 : pas de hiérarchie de type chaînée (modèle plat).
        return None

    @property
    def type_label(self) -> str | None:
        # Le label COAR n'est pas résolu ici (pas de table de
        # libellés en V0.9.0). On expose l'URI brut, le template
        # rend `type_label or type_coar or '—'`.
        return None

    @property
    def modifie_depuis(self) -> str:
        return temps_relatif(self.modifie_le)

    @property
    def meta(self) -> dict[str, Any]:
        return self.metadonnees or {}


def _valider_formulaire(formulaire: FormulaireItem) -> dict[str, str]:
    erreurs = valider_cote_titre(formulaire.cote, formulaire.titre)
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
        setattr(item, nom, chaine_ou_none(getattr(formulaire, nom)))


def formulaire_depuis_item(item: Item) -> FormulaireItem:
    """Pré-remplit un formulaire d'édition depuis un item ORM.

    `metadonnees` est défaut-é à dict vide pour ne jamais avoir None
    (le modèle accepte None mais le formulaire attend un dict)."""
    return FormulaireItem(
        cote=item.cote,
        titre=item.titre or "",
        fonds_id=item.fonds_id,
        description=item.description or "",
        notes_internes=item.notes_internes or "",
        type_coar=item.type_coar or "",
        langue=item.langue or "",
        date=item.date or "",
        annee=item.annee,
        numero=item.numero or "",
        numero_tri=item.numero_tri,
        etat_catalogage=item.etat_catalogage,
        metadonnees=dict(item.metadonnees) if item.metadonnees else {},
        doi_nakala=item.doi_nakala or "",
        doi_collection_nakala=item.doi_collection_nakala or "",
    )


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
    nb_fich_par_item: dict[int, int] = {}
    if rows:
        ids = [r[0].id for r in rows]
        nb_coll_par_item = dict(
            db.execute(
                select(ItemCollection.item_id, func.count())
                .where(ItemCollection.item_id.in_(ids))
                .group_by(ItemCollection.item_id)
            ).all()
        )
        nb_fich_par_item = dict(
            db.execute(
                select(Fichier.item_id, func.count(Fichier.id))
                .where(Fichier.item_id.in_(ids))
                .group_by(Fichier.item_id)
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
            nb_fichiers=nb_fich_par_item.get(item.id, 0),
            modifie_le=item.modifie_le,
            modifie_par=item.modifie_par,
            description=item.description,
            langue=item.langue,
            doi_nakala=item.doi_nakala,
            doi_collection_nakala=item.doi_collection_nakala,
            metadonnees=item.metadonnees,
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

    # Fail fast : si le fonds n'a pas de miroir (anomalie), pas la peine
    # de tenter l'insert.
    miroir_id = db.scalar(
        select(Collection.id).where(
            Collection.fonds_id == fonds.id,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )
    if miroir_id is None:
        raise OperationItemInterdite(
            f"Le fonds {fonds.cote!r} (id={fonds.id}) n'a pas de "
            "collection miroir — anomalie d'intégrité."
        )

    item = Item(fonds_id=fonds.id, cree_par=cree_par)
    _appliquer_formulaire(item, formulaire)
    db.add(item)
    with garde_cote_unique(db, ItemInvalide, item.cote):
        db.flush()
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

    with garde_cote_unique(db, ItemInvalide, item.cote):
        db.commit()
    db.refresh(item)
    return item


def supprimer_item(db: Session, item_id: int) -> None:
    """Supprime un item ; ses fichiers et liaisons disparaissent en
    cascade. L'item est retiré de toutes ses collections (y compris
    la miroir)."""
    item = lire_item(db, item_id)
    db.delete(item)
    db.commit()
