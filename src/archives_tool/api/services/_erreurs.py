"""Exceptions métier partagées entre services Fonds / Collection / Item.

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


class EntiteIntrouvable(LookupError):
    """L'identifiant ou la cote d'une entité métier n'existe pas."""


class FormulaireInvalide(ValueError):
    """Données de saisie invalides : porte un dict `erreurs` champ→message."""

    def __init__(self, erreurs: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))
        self.erreurs = erreurs


class OperationInterdite(Exception):
    """Opération refusée par invariant métier (modifier une miroir,
    supprimer une miroir indépendamment du fonds, etc.)."""


def message_cote_existe(cote: str) -> dict[str, str]:
    """Message standardisé pour un conflit d'unicité de cote."""
    return {"cote": f"La cote {cote!r} existe déjà."}
