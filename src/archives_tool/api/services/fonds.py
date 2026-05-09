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

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.models import Collection, Fonds, TypeCollection


class FondsIntrouvable(LookupError):
    """L'identifiant ou la cote du fonds n'existe pas."""


class FondsInvalide(ValueError):
    """Données de formulaire invalides : cote vide, doublon, etc."""

    def __init__(self, erreurs: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))
        self.erreurs = erreurs


@dataclass
class FormulaireFonds:
    """État de saisie pour création / modification d'un fonds."""

    cote: str = ""
    titre: str = ""
    description: str = ""
    description_publique: str = ""
    description_interne: str = ""
    personnalite_associee: str = ""
    responsable_archives: str = ""
    editeur: str = ""
    lieu_edition: str = ""
    periodicite: str = ""
    issn: str = ""
    date_debut: str = ""
    date_fin: str = ""


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


_OPTIONNELS_CHAINES: tuple[str, ...] = (
    "description",
    "description_publique",
    "description_interne",
    "personnalite_associee",
    "responsable_archives",
    "editeur",
    "lieu_edition",
    "periodicite",
    "issn",
    "date_debut",
    "date_fin",
)


def _valider_formulaire(formulaire: FormulaireFonds) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    if not formulaire.cote.strip():
        erreurs["cote"] = "La cote est obligatoire."
    if not formulaire.titre.strip():
        erreurs["titre"] = "Le titre est obligatoire."
    return erreurs


def _appliquer_formulaire(fonds: Fonds, formulaire: FormulaireFonds) -> None:
    fonds.cote = formulaire.cote.strip()
    fonds.titre = formulaire.titre.strip()
    for nom in _OPTIONNELS_CHAINES:
        valeur = getattr(formulaire, nom)
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
    """Liste tous les fonds avec leurs compteurs (items, collections)."""
    fonds_list = db.scalars(select(Fonds).order_by(Fonds.cote)).all()
    resumes: list[FondsResume] = []
    for f in fonds_list:
        miroir = f.collection_miroir
        resumes.append(
            FondsResume(
                id=f.id,
                cote=f.cote,
                titre=f.titre,
                description=f.description,
                nb_items=len(f.items),
                nb_collections=len(f.collections),
                miroir_id=miroir.id if miroir else None,
                miroir_cote=miroir.cote if miroir else None,
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
    Lève `FondsInvalide` si la cote / titre sont vides ou si la cote
    est déjà utilisée par un autre fonds.
    """
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise FondsInvalide(erreurs)

    cote = formulaire.cote.strip()
    if db.scalar(select(Fonds.id).where(Fonds.cote == cote)) is not None:
        raise FondsInvalide({"cote": f"La cote {cote!r} existe déjà."})

    fonds = Fonds(cree_par=cree_par)
    _appliquer_formulaire(fonds, formulaire)

    miroir = Collection(
        cote=cote,
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
        raise FondsInvalide({"cote": f"La cote {cote!r} existe déjà."}) from e
    db.refresh(fonds)
    return fonds


def modifier_fonds(
    db: Session,
    fonds_id: int,
    formulaire: FormulaireFonds,
    *,
    modifie_par: str | None = None,
) -> Fonds:
    """Met à jour un fonds. La cote peut changer ; si elle entre en
    conflit avec un autre fonds, lève `FondsInvalide`.

    Note : la cote de la collection miroir n'est PAS automatiquement
    réalignée. Le brief V0.9.0-alpha laisse cette décision aux
    sessions de polish ; pour l'instant, le rattachement reste
    cohérent (même `fonds_id`) mais la miroir peut diverger.
    """
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise FondsInvalide(erreurs)

    fonds = lire_fonds(db, fonds_id)
    nouvelle_cote = formulaire.cote.strip()
    if nouvelle_cote != fonds.cote:
        conflit = db.scalar(select(Fonds.id).where(Fonds.cote == nouvelle_cote))
        if conflit is not None:
            raise FondsInvalide({"cote": f"La cote {nouvelle_cote!r} existe déjà."})

    _appliquer_formulaire(fonds, formulaire)
    fonds.modifie_par = modifie_par
    fonds.modifie_le = datetime.now()

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise FondsInvalide(
            {"cote": f"La cote {nouvelle_cote!r} existe déjà."}
        ) from e
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

    Lève `FondsIntrouvable` si l'id n'existe pas.
    """
    fonds = lire_fonds(db, fonds_id)
    miroir = fonds.collection_miroir
    if miroir is not None:
        db.delete(miroir)
        db.flush()
    db.delete(fonds)
    db.commit()
