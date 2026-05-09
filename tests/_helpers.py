"""Helpers utilitaires pour les tests V0.9.0+.

Constantes et factories d'instances ORM partagées par plusieurs
fichiers de tests. Les **fixtures** restent dans `conftest.py` (pour
auto-discovery pytest) ; ce module abrite seulement ce qui doit être
importé explicitement.
"""

from __future__ import annotations

from archives_tool.models import EtatCatalogage, Fonds, Item

BROUILLON: str = EtatCatalogage.BROUILLON.value


def make_item(fonds: Fonds, cote: str) -> Item:
    """Construit un Item minimal rattaché à `fonds` ; état par défaut
    `brouillon`. Non commit ; à `session.add()` puis `commit()`."""
    return Item(fonds_id=fonds.id, cote=cote, etat_catalogage=BROUILLON)
