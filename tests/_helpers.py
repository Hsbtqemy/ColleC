"""Helpers utilitaires pour les tests V0.9.0+.

Constantes et factories d'instances ORM partagées par plusieurs
fichiers de tests + utilitaires HTML pour les tests de routes web.
Les **fixtures** restent dans `conftest.py` (pour auto-discovery
pytest) ; ce module abrite seulement ce qui doit être importé
explicitement.
"""

from __future__ import annotations

import html
import re

from archives_tool.models import EtatCatalogage, Fonds, Item

BROUILLON: str = EtatCatalogage.BROUILLON.value


def make_item(fonds: Fonds, cote: str) -> Item:
    """Construit un Item minimal rattaché à `fonds` ; état par défaut
    `brouillon`. Non commit ; à `session.add()` puis `commit()`."""
    return Item(fonds_id=fonds.id, cote=cote, etat_catalogage=BROUILLON)


def texte_visible(markup: str) -> str:
    """Approximation du texte visible d'une page HTML : strippe les
    balises, décode les entités, compresse les blancs. Suffisant pour
    des assertions sémantiques `in` côté tests de routes web.
    """
    sans_balises = re.sub(r"<[^>]+>", " ", markup)
    decode = html.unescape(sans_balises)
    return re.sub(r"\s+", " ", decode).strip()
