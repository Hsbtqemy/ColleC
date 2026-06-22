"""Suggestions de valeurs existantes pour l'autocomplete inline (Lot 3 UI⁺).

Propose, au fil de la frappe, les valeurs **déjà saisies** pour certains
champs libres récurrents (éditeur, lieu, périodicité, responsable…). But :
réduire la dérive orthographique entre fonds/collections (« Éd. du Square »
vs « Editions du Square ») sans imposer un vocabulaire contrôlé — cohérent
avec l'esprit « espace de travail ».

Distinct des vocabulaires contrôlés (`Vocabulaire`/`ValeurControlee`, rendus
en `<select>` strict à l'inline) : ici, simple aide à la saisie sur du texte
libre. Lecture seule. **Colonnes whitelistées** uniquement — pas d'accès
arbitraire à une colonne via la query string.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from archives_tool.models import Collection, Fonds

#: (type_entite, champ) → colonne ORM. Restreint aux champs **libres**
#: récurrents et inter-entités — pas les vocabulaires (select), pas les
#: identifiants uniques (ISSN, DOI), pas les dates.
_COLONNES_SUGGESTIBLES: dict[tuple[str, str], InstrumentedAttribute] = {
    ("fonds", "editeur"): Fonds.editeur,
    ("fonds", "lieu_edition"): Fonds.lieu_edition,
    ("fonds", "periodicite"): Fonds.periodicite,
    ("fonds", "responsable_archives"): Fonds.responsable_archives,
    ("fonds", "personnalite_associee"): Fonds.personnalite_associee,
    ("collection", "editeur"): Collection.editeur,
    ("collection", "lieu_edition"): Collection.lieu_edition,
    ("collection", "periodicite"): Collection.periodicite,
}


def champ_suggestible(type_entite: str, champ: str) -> bool:
    """True si (type, champ) est dans la whitelist des suggestions."""
    return (type_entite, champ) in _COLONNES_SUGGESTIBLES


def suggerer_valeurs(
    db: Session,
    *,
    type_entite: str,
    champ: str,
    prefixe: str = "",
    limite: int = 20,
) -> list[str]:
    """Valeurs distinctes non vides existantes pour (type, champ), triées,
    plafonnées à `limite`. `prefixe` filtre par début (insensible à la
    casse). Retourne `[]` si (type, champ) n'est pas whitelisté."""
    col = _COLONNES_SUGGESTIBLES.get((type_entite, champ))
    if col is None:
        return []
    stmt = select(col).where(col.is_not(None), col != "")
    prefixe = (prefixe or "").strip()
    if prefixe:
        stmt = stmt.where(col.ilike(f"{prefixe}%"))
    stmt = stmt.distinct().order_by(col).limit(limite)
    return list(db.scalars(stmt).all())
