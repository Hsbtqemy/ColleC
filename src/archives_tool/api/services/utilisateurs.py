"""Service des comptes utilisateur (Phase 1 — couche identité).

CRUD du référentiel `Utilisateur` (roster de connexion du mode serveur,
cf. `models/utilisateur.py`). Logique métier pure, réutilisée par la CLI
`archives-tool utilisateurs` et, en Phase 2, par le login/session du
mode serveur (le login appellera `lire_utilisateur_par_nom` +
`lister_utilisateurs(inclure_inactifs=False)`).

Suppression : **soft delete** (`desactiver_utilisateur`) — un compte
ayant agi reste référencé pour la traçabilité. Pas de hard delete.
"""

from __future__ import annotations

import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import Utilisateur


class UtilisateurIntrouvable(Exception):
    """Aucun compte ne porte ce nom."""


class NomDejaUtilise(Exception):
    """Un compte porte déjà ce nom (unicité du roster)."""


def _normaliser_nom(nom: str) -> str:
    """NFC + strip — un nom n'est pas un chemin, mais on garde la
    normalisation Unicode du projet pour éviter les doublons visuels
    (« José » NFC vs NFD)."""
    return unicodedata.normalize("NFC", (nom or "").strip())


def creer_utilisateur(
    session: Session, nom: str, *, peut_editer: bool = True
) -> Utilisateur:
    """Crée un compte actif. Lève `ValueError` si nom vide,
    `NomDejaUtilise` si le nom est déjà pris."""
    nom = _normaliser_nom(nom)
    if not nom:
        raise ValueError("Le nom d'utilisateur ne peut pas être vide.")
    if session.scalar(select(Utilisateur).where(Utilisateur.nom == nom)) is not None:
        raise NomDejaUtilise(nom)
    utilisateur = Utilisateur(nom=nom, actif=True, peut_editer=peut_editer)
    session.add(utilisateur)
    session.commit()
    session.refresh(utilisateur)
    return utilisateur


def lire_utilisateur_par_nom(session: Session, nom: str) -> Utilisateur:
    """Renvoie le compte exact (NFC). Lève `UtilisateurIntrouvable`."""
    nom = _normaliser_nom(nom)
    utilisateur = session.scalar(select(Utilisateur).where(Utilisateur.nom == nom))
    if utilisateur is None:
        raise UtilisateurIntrouvable(nom)
    return utilisateur


def lister_utilisateurs(
    session: Session, *, inclure_inactifs: bool = True
) -> list[Utilisateur]:
    """Comptes triés par nom. `inclure_inactifs=False` pour le login."""
    stmt = select(Utilisateur).order_by(Utilisateur.nom)
    if not inclure_inactifs:
        stmt = stmt.where(Utilisateur.actif.is_(True))
    return list(session.scalars(stmt))


def modifier_utilisateur(
    session: Session,
    nom: str,
    *,
    nouveau_nom: str | None = None,
    peut_editer: bool | None = None,
    actif: bool | None = None,
) -> Utilisateur:
    """Modifie un compte. Les paramètres à `None` sont laissés inchangés
    (tri-state). Lève `UtilisateurIntrouvable`, `NomDejaUtilise`,
    `ValueError`."""
    utilisateur = lire_utilisateur_par_nom(session, nom)
    if nouveau_nom is not None:
        nn = _normaliser_nom(nouveau_nom)
        if not nn:
            raise ValueError("Le nouveau nom ne peut pas être vide.")
        if nn != utilisateur.nom and (
            session.scalar(select(Utilisateur).where(Utilisateur.nom == nn)) is not None
        ):
            raise NomDejaUtilise(nn)
        utilisateur.nom = nn
    if peut_editer is not None:
        utilisateur.peut_editer = peut_editer
    if actif is not None:
        utilisateur.actif = actif
    session.commit()
    session.refresh(utilisateur)
    return utilisateur


def desactiver_utilisateur(session: Session, nom: str) -> Utilisateur:
    """Soft delete : `actif=False`. Réversible via `modifier(..., actif=True)`."""
    return modifier_utilisateur(session, nom, actif=False)
