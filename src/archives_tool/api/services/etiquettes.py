"""Étiquettes colorées de chantier — CRUD + étiquetage des items (Lot 4 UI⁺).

Concept distinct des vocabulaires contrôlés (cf. `models/etiquette.py`) :
marquage workflow interne, global, multi-tag, jamais exporté. Palette de
couleurs **fermée** (validée ici, pas en SQL — évolutive sans migration).
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
)
from archives_tool.models import Etiquette, Item, ItemEtiquette

#: Palette fermée (nom affiché, hex). Choisie pour contraster sur fond
#: blanc ; alignée sur les teintes d'état existantes + quelques ajouts.
PALETTE_ETIQUETTES: list[tuple[str, str]] = [
    ("Rouge", "#E24B4A"),
    ("Orange", "#BA7517"),
    ("Vert", "#639922"),
    ("Bleu", "#378ADD"),
    ("Violet", "#8B5CF6"),
    ("Rose", "#DB2777"),
    ("Sarcelle", "#0D9488"),
    ("Gris", "#888780"),
]
COULEUR_DEFAUT: str = "#378ADD"
_HEXES: frozenset[str] = frozenset(hex_ for _, hex_ in PALETTE_ETIQUETTES)


class EtiquetteIntrouvable(EntiteIntrouvable):
    """L'id d'étiquette n'existe pas."""


class EtiquetteInvalide(FormulaireInvalide):
    """Saisie d'étiquette invalide (libellé vide/doublon, couleur hors palette)."""


class FormulaireEtiquette(BaseModel):
    libelle: str = ""
    couleur: str = COULEUR_DEFAUT


def _valider(formulaire: FormulaireEtiquette) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    libelle = formulaire.libelle.strip()
    if not libelle:
        erreurs["libelle"] = "Le libellé est obligatoire."
    elif len(libelle) > 80:
        erreurs["libelle"] = "Le libellé est trop long (80 caractères max)."
    if formulaire.couleur not in _HEXES:
        erreurs["couleur"] = "Couleur hors palette."
    return erreurs


def lister_etiquettes(db: Session) -> list[Etiquette]:
    """Toutes les étiquettes, triées par libellé."""
    return list(db.scalars(select(Etiquette).order_by(Etiquette.libelle)).all())


def etiquette_par_id(db: Session, etiquette_id: int) -> Etiquette:
    et = db.get(Etiquette, etiquette_id)
    if et is None:
        raise EtiquetteIntrouvable(etiquette_id)
    return et


def _libelle_libre(db: Session, libelle: str, *, sauf_id: int | None = None) -> bool:
    """True si aucun autre étiquette ne porte ce libellé (insensible casse)."""
    stmt = select(Etiquette.id).where(func.lower(Etiquette.libelle) == libelle.lower())
    if sauf_id is not None:
        stmt = stmt.where(Etiquette.id != sauf_id)
    return db.scalar(stmt) is None


def creer_etiquette(
    db: Session, formulaire: FormulaireEtiquette, *, cree_par: str | None = None
) -> Etiquette:
    erreurs = _valider(formulaire)
    if erreurs:
        raise EtiquetteInvalide(erreurs)
    libelle = formulaire.libelle.strip()
    if not _libelle_libre(db, libelle):
        raise EtiquetteInvalide({"libelle": f"L'étiquette « {libelle} » existe déjà."})
    et = Etiquette(libelle=libelle, couleur=formulaire.couleur, cree_par=cree_par)
    db.add(et)
    try:
        db.commit()
    except IntegrityError as e:  # garde-fou course (UNIQUE libelle)
        db.rollback()
        raise EtiquetteInvalide(
            {"libelle": f"L'étiquette « {libelle} » existe déjà."}
        ) from e
    db.refresh(et)
    return et


def modifier_etiquette(
    db: Session, etiquette_id: int, formulaire: FormulaireEtiquette
) -> Etiquette:
    erreurs = _valider(formulaire)
    if erreurs:
        raise EtiquetteInvalide(erreurs)
    et = etiquette_par_id(db, etiquette_id)
    libelle = formulaire.libelle.strip()
    if not _libelle_libre(db, libelle, sauf_id=etiquette_id):
        raise EtiquetteInvalide({"libelle": f"L'étiquette « {libelle} » existe déjà."})
    et.libelle = libelle
    et.couleur = formulaire.couleur
    db.commit()
    db.refresh(et)
    return et


def supprimer_etiquette(db: Session, etiquette_id: int) -> None:
    """Supprime une étiquette ; ses étiquetages disparaissent en cascade
    (FK `item_etiquette.etiquette_id ON DELETE CASCADE`). Les items
    survivent."""
    et = etiquette_par_id(db, etiquette_id)
    db.delete(et)
    db.commit()


def etiquettes_de_item(db: Session, item_id: int) -> list[Etiquette]:
    """Étiquettes d'un item, triées par libellé."""
    return list(
        db.scalars(
            select(Etiquette)
            .join(ItemEtiquette, ItemEtiquette.etiquette_id == Etiquette.id)
            .where(ItemEtiquette.item_id == item_id)
            .order_by(Etiquette.libelle)
        ).all()
    )


def etiquettes_courantes_et_disponibles(
    db: Session, item_id: int
) -> tuple[list[Etiquette], list[Etiquette]]:
    """(`courantes`, `disponibles`) pour la section d'étiquetage d'un item :
    ses étiquettes, et celles encore assignables (toutes − courantes).

    Une seule requête : on charge toutes les étiquettes (triées) avec un
    booléen `EXISTS` indiquant l'appartenance à l'item, puis on partitionne
    en Python (l'ordre par libellé est préservé dans les deux listes)."""
    courante = (
        select(ItemEtiquette.etiquette_id)
        .where(
            ItemEtiquette.etiquette_id == Etiquette.id,
            ItemEtiquette.item_id == item_id,
        )
        .exists()
        .label("courante")
    )
    courantes: list[Etiquette] = []
    disponibles: list[Etiquette] = []
    for etiquette, est_courante in db.execute(
        select(Etiquette, courante).order_by(Etiquette.libelle)
    ):
        (courantes if est_courante else disponibles).append(etiquette)
    return courantes, disponibles


def etiqueter_item(
    db: Session,
    item_id: int,
    etiquette_id: int,
    *,
    ajoute_par: str | None = None,
) -> None:
    """Attache une étiquette à un item (idempotent : ne double pas un
    étiquetage existant)."""
    if db.get(Item, item_id) is None:
        raise EtiquetteIntrouvable(f"item {item_id}")
    etiquette_par_id(db, etiquette_id)  # 404 si étiquette inconnue
    existe = db.get(ItemEtiquette, {"item_id": item_id, "etiquette_id": etiquette_id})
    if existe is None:
        db.add(
            ItemEtiquette(
                item_id=item_id, etiquette_id=etiquette_id, ajoute_par=ajoute_par
            )
        )
        db.commit()


def retirer_etiquette_item(db: Session, item_id: int, etiquette_id: int) -> None:
    """Détache une étiquette d'un item (idempotent : no-op si absente)."""
    lien = db.get(ItemEtiquette, {"item_id": item_id, "etiquette_id": etiquette_id})
    if lien is not None:
        db.delete(lien)
        db.commit()
