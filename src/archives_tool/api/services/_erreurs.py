"""Exceptions et helpers de validation partagés entre services
Fonds / Collection / Item.

Convention V0.9.0-alpha :
- `EntiteIntrouvable` : par id ou par cote (mappé HTTP 404 côté route).
- `FormulaireInvalide` : données de saisie invalides (mappé HTTP 400
  + erreurs de champ).
- `OperationInterdite` : opération refusée par invariant métier
  (mappé HTTP 409 ou 422 côté route).

Chaque service spécialise via une sous-classe (FondsIntrouvable,
CollectionInvalide, etc.) — pour le tri / catch côté appelant et
des messages contextualisés.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# Cote : alphanumérique + tiret + souligné. Pas d'espaces, pas
# d'accents (pour la portabilité fichier et URL — voir CLAUDE.md).
PATTERN_COTE = re.compile(r"^[A-Za-z0-9_-]+$")

_MSG_COTE_CARACTERES = (
    "Caractères autorisés : lettres, chiffres, tiret, souligné."
)


class EntiteIntrouvable(LookupError):
    """L'identifiant ou la cote d'une entité métier n'existe pas."""


class FormulaireInvalide(ValueError):
    """Données de saisie invalides : porte un dict `erreurs` champ→message."""

    def __init__(self, erreurs: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))
        self.erreurs = erreurs

    @classmethod
    def cote_existe(cls, cote: str) -> "FormulaireInvalide":
        """Construit une erreur « cote en doublon » avec le message
        standard. Les sous-classes héritent du constructeur ; appeler
        `FondsInvalide.cote_existe(cote)` pour un type spécifique."""
        return cls({"cote": f"La cote {cote!r} existe déjà."})


class OperationInterdite(Exception):
    """Opération refusée par invariant métier (modifier une miroir,
    supprimer une miroir indépendamment du fonds, etc.)."""


def valider_cote_titre(
    cote: str, titre: str, *, exiger_pattern: bool = True
) -> dict[str, str]:
    """Validation partagée par tous les formulaires : cote non vide,
    cote conforme au pattern, titre non vide. Retourne un dict
    d'erreurs (vide si valide)."""
    erreurs: dict[str, str] = {}
    cote_strip = cote.strip()
    if not cote_strip:
        erreurs["cote"] = "La cote est obligatoire."
    elif exiger_pattern and not PATTERN_COTE.match(cote_strip):
        erreurs["cote"] = _MSG_COTE_CARACTERES
    if not titre.strip():
        erreurs["titre"] = "Le titre est obligatoire."
    return erreurs


def chaine_ou_none(valeur: object) -> object:
    """Pour un champ optionnel : si `valeur` est une chaîne, la strippe
    et la convertit à `None` si vide. Sinon (int, bool, list, dict),
    la retourne telle quelle.
    """
    if isinstance(valeur, str):
        return valeur.strip() or None
    return valeur


@contextmanager
def garde_cote_unique(
    db: "Session",
    exception_cls: type[FormulaireInvalide],
    cote: str,
) -> Iterator[None]:
    """Context manager qui transforme `IntegrityError` en
    `exception_cls.cote_existe(cote)` après rollback.

    Usage typique :

        with garde_cote_unique(db, FondsInvalide, fonds.cote):
            db.commit()
    """
    try:
        yield
    except IntegrityError as e:
        db.rollback()
        raise exception_cls.cote_existe(cote) from e
