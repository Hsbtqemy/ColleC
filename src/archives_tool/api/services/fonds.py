"""CRUD Fonds — corpus brut + invariant de la collection miroir.

Source de vérité pour les invariants 1, 2, 5, 8 du modèle V0.9.0 :
- Tout fonds est créé avec sa collection miroir (même cote / même
  titre, type=MIROIR, fonds_id rattaché).
- Une collection miroir n'existe qu'à travers un fonds : pas
  d'API publique pour créer / modifier / supprimer une miroir
  isolément.
- Suppression d'un fonds : items + miroir disparaissent en cascade
  (ON DELETE CASCADE côté FK + cascade ORM côté `items`) ; les
  collections libres rattachées au fonds passent à transversales
  (`fonds_id = NULL`) au lieu de disparaître — ne pas perdre le
  travail manuel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
    message_cote_existe,
)
from archives_tool.models import Collection, Fonds, Item, TypeCollection


class FondsIntrouvable(EntiteIntrouvable):
    """L'identifiant ou la cote du fonds n'existe pas."""


class FondsInvalide(FormulaireInvalide):
    """Données de formulaire invalides : cote vide, doublon, etc."""


def _erreur_cote_existe(cote: str) -> FondsInvalide:
    return FondsInvalide(message_cote_existe(cote))


class FormulaireFonds(BaseModel):
    """État de saisie pour création / modification d'un fonds.

    Pydantic pour la cohérence avec `FormulaireCollection` /
    `FormulaireCollaborateur` ; lié plus tard aux Form fields HTML
    via `Annotated[..., Form()]`.
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    cote: str = Field(default="")
    titre: str = Field(default="")
    description: str = Field(default="")
    description_publique: str = Field(default="")
    description_interne: str = Field(default="")
    personnalite_associee: str = Field(default="")
    responsable_archives: str = Field(default="")
    editeur: str = Field(default="")
    lieu_edition: str = Field(default="")
    periodicite: str = Field(default="")
    issn: str = Field(default="")
    date_debut: str = Field(default="")
    date_fin: str = Field(default="")


@dataclass
class FondsResume:
    id: int
    cote: str
    titre: str
    description: str | None
    nb_items: int = 0
    nb_collections: int = 0
    miroir_id: int | None = None
    miroir_cote: str | None = None
    cree_le: datetime | None = None


def _valider_formulaire(formulaire: FormulaireFonds) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    if not formulaire.cote.strip():
        erreurs["cote"] = "La cote est obligatoire."
    if not formulaire.titre.strip():
        erreurs["titre"] = "Le titre est obligatoire."
    return erreurs


def _appliquer_formulaire(fonds: Fonds, formulaire: FormulaireFonds) -> None:
    """Copie le formulaire sur le modèle ; chaînes vides → None
    pour les champs optionnels (cote/titre obligatoires sont strippés).

    Tous les champs de `FormulaireFonds` sont des `str` aujourd'hui ;
    le `isinstance(valeur, str)` protège l'ajout futur d'un champ
    non-string (bool / list / etc.) — le service applicatif devra
    alors traiter ce champ explicitement.
    """
    fonds.cote = formulaire.cote.strip()
    fonds.titre = formulaire.titre.strip()
    for nom, valeur in formulaire.model_dump().items():
        if nom in ("cote", "titre"):
            continue
        if isinstance(valeur, str):
            setattr(fonds, nom, valeur.strip() or None)


def lire_fonds(db: Session, fonds_id: int) -> Fonds:
    fonds = db.get(Fonds, fonds_id)
    if fonds is None:
        raise FondsIntrouvable(fonds_id)
    return fonds


def lire_fonds_par_cote(db: Session, cote: str) -> Fonds:
    fonds = db.scalar(select(Fonds).where(Fonds.cote == cote))
    if fonds is None:
        raise FondsIntrouvable(cote)
    return fonds


def lister_fonds(db: Session) -> list[FondsResume]:
    """Liste tous les fonds avec leurs compteurs.

    Les compteurs `nb_items`, `nb_collections` et la résolution de la
    miroir sont obtenus en agrégations SQL (3 requêtes total, pas N+1).
    """
    fonds_list = db.scalars(select(Fonds).order_by(Fonds.cote)).all()
    if not fonds_list:
        return []

    ids = [f.id for f in fonds_list]
    nb_items_par_fonds: dict[int, int] = dict(
        db.execute(
            select(Item.fonds_id, func.count(Item.id))
            .where(Item.fonds_id.in_(ids))
            .group_by(Item.fonds_id)
        ).all()
    )
    nb_coll_par_fonds: dict[int, int] = dict(
        db.execute(
            select(Collection.fonds_id, func.count(Collection.id))
            .where(Collection.fonds_id.in_(ids))
            .group_by(Collection.fonds_id)
        ).all()
    )
    miroirs_par_fonds: dict[int, tuple[int, str]] = {
        fonds_id: (mid, cote)
        for fonds_id, mid, cote in db.execute(
            select(Collection.fonds_id, Collection.id, Collection.cote).where(
                Collection.fonds_id.in_(ids),
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        ).all()
    }

    resumes: list[FondsResume] = []
    for f in fonds_list:
        miroir_id, miroir_cote = miroirs_par_fonds.get(f.id, (None, None))
        resumes.append(
            FondsResume(
                id=f.id,
                cote=f.cote,
                titre=f.titre,
                description=f.description,
                nb_items=nb_items_par_fonds.get(f.id, 0),
                nb_collections=nb_coll_par_fonds.get(f.id, 0),
                miroir_id=miroir_id,
                miroir_cote=miroir_cote,
                cree_le=f.cree_le,
            )
        )
    return resumes


def creer_fonds(
    db: Session,
    formulaire: FormulaireFonds,
    *,
    cree_par: str | None = None,
) -> Fonds:
    """Crée un fonds + sa collection miroir dans la même transaction.

    Le titre et la cote sont copiés sur la miroir (invariant 5).
    L'unicité de la cote est garantie par l'index UNIQUE en base : si
    une autre transaction l'a créée entretemps, l'IntegrityError du
    commit la rattrape.
    """
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise FondsInvalide(erreurs)

    fonds = Fonds(cree_par=cree_par)
    _appliquer_formulaire(fonds, formulaire)

    miroir = Collection(
        cote=fonds.cote,
        titre=fonds.titre,
        type_collection=TypeCollection.MIROIR.value,
        fonds=fonds,
        cree_par=cree_par,
    )
    db.add(fonds)
    db.add(miroir)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise _erreur_cote_existe(fonds.cote) from e
    db.refresh(fonds)
    return fonds


def modifier_fonds(
    db: Session,
    fonds_id: int,
    formulaire: FormulaireFonds,
    *,
    modifie_par: str | None = None,
) -> Fonds:
    """Met à jour un fonds. La cote peut changer ; un conflit avec un
    autre fonds est rattrapé par l'IntegrityError du commit.

    Note : la cote de la collection miroir n'est PAS automatiquement
    réalignée. Décision laissée aux sessions de polish ; pour
    l'instant, le rattachement reste cohérent (même `fonds_id`) mais
    la miroir peut diverger.
    """
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise FondsInvalide(erreurs)

    fonds = lire_fonds(db, fonds_id)
    _appliquer_formulaire(fonds, formulaire)
    fonds.modifie_par = modifie_par
    fonds.modifie_le = datetime.now()

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise _erreur_cote_existe(fonds.cote) from e
    db.refresh(fonds)
    return fonds


def supprimer_fonds(db: Session, fonds_id: int) -> None:
    """Supprime un fonds et toute sa descendance (items + miroir +
    collaborateurs).

    Les collections **libres** rattachées à ce fonds passent à
    transversales (`fonds_id = NULL`) — préserve le travail de
    classement manuel. C'est le FK `ON DELETE SET NULL` qui le fait
    automatiquement.

    La miroir, en revanche, ne peut pas avoir fonds_id NULL (CHECK
    constraint). Le service la supprime explicitement avant le fonds.

    Les items du fonds disparaissent en cascade (FK CASCADE +
    relation ORM avec `delete-orphan`).
    """
    fonds = lire_fonds(db, fonds_id)
    miroir = fonds.collection_miroir
    if miroir is not None:
        db.delete(miroir)
        db.flush()
    db.delete(fonds)
    db.commit()
