"""Gestion des collaborateurs d'un fonds.

Lecture (groupée par rôle pour l'affichage), ajout, modification,
suppression. Mêmes invariants et même vocabulaire fermé que
`services/collaborateurs.py` (qui gère `CollaborateurCollection`),
mais sur la table `collaborateur_fonds`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import CollaborateurFonds, RoleCollaborateur


class CollaborateurFondsIntrouvable(LookupError):
    """L'identifiant du collaborateur n'existe pas."""


class CollaborateurFondsInvalide(ValueError):
    """Données de formulaire invalides : nom vide, rôles vides ou hors
    vocabulaire. Porte un dict `erreurs` champ → message."""

    def __init__(self, erreurs: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))
        self.erreurs = erreurs


@dataclass
class CollaborateurFondsResume:
    id: int
    nom: str
    roles: list[RoleCollaborateur]
    periode: str | None
    notes: str | None


class FormulaireCollaborateurFonds(BaseModel):
    """Formulaire de saisie. Les rôles arrivent comme une liste de
    chaînes (checkboxes du même `name`)."""

    model_config = ConfigDict(str_strip_whitespace=False)

    nom: str = Field(default="")
    roles: list[str] = Field(default_factory=list)
    periode: str = Field(default="")
    notes: str = Field(default="")


_ROLES_VALIDES: frozenset[str] = frozenset(r.value for r in RoleCollaborateur)
_ORDRE_ROLES: list[RoleCollaborateur] = list(RoleCollaborateur)


def valider_formulaire(formulaire: FormulaireCollaborateurFonds) -> dict[str, str]:
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


def _depuis_modele(c: CollaborateurFonds) -> CollaborateurFondsResume:
    return CollaborateurFondsResume(
        id=c.id,
        nom=c.nom,
        roles=[RoleCollaborateur(r) for r in (c.roles or []) if r in _ROLES_VALIDES],
        periode=c.periode,
        notes=c.notes,
    )


def lister_collaborateurs_fonds(
    db: Session, fonds_id: int
) -> list[CollaborateurFondsResume]:
    """Tous les collaborateurs d'un fonds, ordre stable par cree_le."""
    rows = db.scalars(
        select(CollaborateurFonds)
        .where(CollaborateurFonds.fonds_id == fonds_id)
        .order_by(CollaborateurFonds.cree_le, CollaborateurFonds.id)
    ).all()
    return [_depuis_modele(c) for c in rows]


def lister_collaborateurs_fonds_par_role(
    db: Session, fonds_id: int
) -> dict[RoleCollaborateur, list[CollaborateurFondsResume]]:
    """Groupe par rôle. Une personne multi-rôles apparaît dans
    plusieurs groupes. Ordre des rôles fixé par l'enum ; les rôles
    sans collaborateur ne sont pas inclus."""
    tous = lister_collaborateurs_fonds(db, fonds_id)
    groupes: dict[RoleCollaborateur, list[CollaborateurFondsResume]] = {}
    for role in _ORDRE_ROLES:
        membres = [c for c in tous if role in c.roles]
        if membres:
            groupes[role] = membres
    return groupes


def _lire_modele(db: Session, collaborateur_id: int) -> CollaborateurFonds:
    """Retourne le modèle ou lève `CollaborateurFondsIntrouvable`."""
    c = db.get(CollaborateurFonds, collaborateur_id)
    if c is None:
        raise CollaborateurFondsIntrouvable(collaborateur_id)
    return c


def ajouter_collaborateur_fonds(
    db: Session,
    fonds_id: int,
    formulaire: FormulaireCollaborateurFonds,
) -> CollaborateurFondsResume:
    """Ajoute un collaborateur. Hypothèse : `fonds_id` pointe vers un
    Fonds existant (vérifié en amont par la route). Lève
    `CollaborateurFondsInvalide` sur données invalides."""
    erreurs = valider_formulaire(formulaire)
    if erreurs:
        raise CollaborateurFondsInvalide(erreurs)

    c = CollaborateurFonds(
        fonds_id=fonds_id,
        nom=formulaire.nom.strip(),
        roles=list(formulaire.roles),
        periode=formulaire.periode.strip() or None,
        notes=formulaire.notes.strip() or None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _depuis_modele(c)


def modifier_collaborateur_fonds(
    db: Session,
    collaborateur_id: int,
    formulaire: FormulaireCollaborateurFonds,
) -> CollaborateurFondsResume:
    """Remplace les champs. Lève `CollaborateurFondsInvalide` ou
    `CollaborateurFondsIntrouvable`."""
    erreurs = valider_formulaire(formulaire)
    if erreurs:
        raise CollaborateurFondsInvalide(erreurs)

    c = _lire_modele(db, collaborateur_id)
    c.nom = formulaire.nom.strip()
    c.roles = list(formulaire.roles)
    c.periode = formulaire.periode.strip() or None
    c.notes = formulaire.notes.strip() or None
    db.commit()
    db.refresh(c)
    return _depuis_modele(c)


def supprimer_collaborateur_fonds(db: Session, collaborateur_id: int) -> None:
    """Suppression dure. Lève si l'id n'existe pas."""
    c = _lire_modele(db, collaborateur_id)
    db.delete(c)
    db.commit()
