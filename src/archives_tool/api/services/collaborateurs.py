"""Gestion des collaborateurs d'une collection (V0.8.0).

Lecture (groupée par rôle pour l'affichage), ajout, modification,
suppression. Toutes les opérations valident le vocabulaire des rôles
contre l'enum `RoleCollaborateur`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import (
    CollaborateurCollection,
    Collection,
    RoleCollaborateur,
)


class CollaborateurIntrouvable(LookupError):
    """L'identifiant du collaborateur n'existe pas."""


class CollaborateurInvalide(ValueError):
    """Données de formulaire invalides (nom vide, rôles vides ou hors
    vocabulaire). Les routes mappent ça en 400 + erreurs de champ."""

    def __init__(self, erreurs: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))
        self.erreurs = erreurs


@dataclass
class CollaborateurResume:
    id: int
    nom: str
    roles: list[RoleCollaborateur]
    periode: str | None
    notes: str | None


@dataclass
class FormulaireCollaborateur:
    """Formulaire de saisie. Les rôles arrivent depuis HTML comme une
    liste de chaînes (checkboxes du même `name`)."""

    nom: str = ""
    roles: list[str] = field(default_factory=list)
    periode: str = ""
    notes: str = ""


_ROLES_VALIDES: frozenset[str] = frozenset(r.value for r in RoleCollaborateur)
_ORDRE_ROLES: list[RoleCollaborateur] = list(RoleCollaborateur)


def valider_formulaire(formulaire: FormulaireCollaborateur) -> dict[str, str]:
    """Retourne un dict d'erreurs par champ (vide si valide)."""
    erreurs: dict[str, str] = {}
    if not formulaire.nom.strip():
        erreurs["nom"] = "Le nom est obligatoire."
    if not formulaire.roles:
        erreurs["roles"] = "Au moins un rôle est requis."
    else:
        invalides = [r for r in formulaire.roles if r not in _ROLES_VALIDES]
        if invalides:
            erreurs["roles"] = f"Rôle(s) inconnu(s) : {', '.join(invalides)}."
    return erreurs


def _depuis_modele(c: CollaborateurCollection) -> CollaborateurResume:
    return CollaborateurResume(
        id=c.id,
        nom=c.nom,
        roles=[RoleCollaborateur(r) for r in (c.roles or []) if r in _ROLES_VALIDES],
        periode=c.periode,
        notes=c.notes,
    )


def lister_collaborateurs(db: Session, collection_id: int) -> list[CollaborateurResume]:
    """Tous les collaborateurs d'une collection, ordre stable cree_le."""
    rows = db.scalars(
        select(CollaborateurCollection)
        .where(CollaborateurCollection.collection_id == collection_id)
        .order_by(CollaborateurCollection.cree_le, CollaborateurCollection.id)
    ).all()
    return [_depuis_modele(c) for c in rows]


def lister_collaborateurs_par_role(
    db: Session, collection_id: int
) -> dict[RoleCollaborateur, list[CollaborateurResume]]:
    """Groupe par rôle. Une personne avec plusieurs rôles apparaît
    dans plusieurs groupes. Ordre des rôles fixé par l'enum.

    Les rôles sans collaborateur ne sont pas inclus (l'UI itère sur
    le dict, pas sur l'enum, pour ne pas afficher de groupes vides).
    """
    tous = lister_collaborateurs(db, collection_id)
    groupes: dict[RoleCollaborateur, list[CollaborateurResume]] = {}
    for role in _ORDRE_ROLES:
        membres = [c for c in tous if role in c.roles]
        if membres:
            groupes[role] = membres
    return groupes


def lire_collaborateur(db: Session, collaborateur_id: int) -> CollaborateurCollection:
    """Retourne le modèle ou lève `CollaborateurIntrouvable`."""
    c = db.get(CollaborateurCollection, collaborateur_id)
    if c is None:
        raise CollaborateurIntrouvable(collaborateur_id)
    return c


def ajouter_collaborateur(
    db: Session,
    collection_id: int,
    formulaire: FormulaireCollaborateur,
) -> CollaborateurResume:
    """Ajoute un collaborateur après validation. Lève
    `CollaborateurInvalide` si les données ne sont pas conformes."""
    erreurs = valider_formulaire(formulaire)
    if erreurs:
        raise CollaborateurInvalide(erreurs)

    if db.get(Collection, collection_id) is None:
        raise LookupError(f"Collection id={collection_id} introuvable.")

    c = CollaborateurCollection(
        collection_id=collection_id,
        nom=formulaire.nom.strip(),
        roles=list(formulaire.roles),
        periode=formulaire.periode.strip() or None,
        notes=formulaire.notes.strip() or None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _depuis_modele(c)


def modifier_collaborateur(
    db: Session,
    collaborateur_id: int,
    formulaire: FormulaireCollaborateur,
) -> CollaborateurResume:
    """Remplace les champs du collaborateur. Lève
    `CollaborateurInvalide` ou `CollaborateurIntrouvable`."""
    erreurs = valider_formulaire(formulaire)
    if erreurs:
        raise CollaborateurInvalide(erreurs)

    c = lire_collaborateur(db, collaborateur_id)
    c.nom = formulaire.nom.strip()
    c.roles = list(formulaire.roles)
    c.periode = formulaire.periode.strip() or None
    c.notes = formulaire.notes.strip() or None
    db.commit()
    db.refresh(c)
    return _depuis_modele(c)


def supprimer_collaborateur(db: Session, collaborateur_id: int) -> None:
    """Suppression dure. Lève `CollaborateurIntrouvable` si l'id n'existe pas."""
    c = lire_collaborateur(db, collaborateur_id)
    db.delete(c)
    db.commit()
