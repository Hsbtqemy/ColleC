"""Famille 3 — cohérence des métadonnées.

Vérifie cote, titre, date, année sur Fonds + Collection + Item. Les
contrôles utilisent les mêmes patterns que `services._erreurs` pour
rester cohérents avec la validation à l'entrée.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import PATTERN_COTE, chaine_ou_none
from archives_tool.models import Collection, Fonds, Item
from archives_tool.qa._commun import (
    Exemple,
    PerimetreControle,
    ResultatControle,
    Severite,
    construire_resultat,
    restreindre_aux_items,
)

FAMILLE = "metadonnees"

# EDTF tolérant : année (1930), année-mois (1969-09), interval
# (1930/1969), incertitude (1969?), approximation (~1930).
# Suffit à attraper les vraies typos sans rejeter les saisies
# archivistiques courantes (« vers 1924 » est laissé passer car
# l'utilisateur pourra l'avoir voulu en chaîne libre).
_RE_EDTF_TOLERANT = re.compile(
    r"^"
    r"(?:\?\?|s\.d\.|sans\s*date|"
    r"vers\s+\d{1,4}|c\.?\s*\d{1,4}|ca\.?\s*\d{1,4}|"
    r"~?\d{1,4}(?:-\d{2}(?:-\d{2})?)?(?:\?|~)?"
    r"(?:/\d{1,4}(?:-\d{2}(?:-\d{2})?)?)?"
    r")$",
    re.IGNORECASE,
)

ANNEE_MIN_DEFAUT = 1000
ANNEE_MAX_DEFAUT = 2100


def _items_filtres(perimetre: PerimetreControle):
    """Items du périmètre, projection commune (id, cote, titre, date, annee)."""
    return restreindre_aux_items(
        select(Item.id, Item.cote, Item.titre, Item.date, Item.annee), perimetre
    ).order_by(Item.cote)


def _collections_filtrees(perimetre: PerimetreControle):
    stmt = select(Collection.id, Collection.cote, Collection.titre)
    if perimetre.fonds_id is not None:
        stmt = stmt.where(Collection.fonds_id == perimetre.fonds_id)
    elif perimetre.collection_id is not None:
        stmt = stmt.where(Collection.id == perimetre.collection_id)
    return stmt


def _fonds_filtres(perimetre: PerimetreControle):
    """Fonds inclus dans le périmètre — vide si périmètre = collection
    (la collection peut être transversale, pas de fonds défini)."""
    if perimetre.collection_id is not None:
        return None
    stmt = select(Fonds.id, Fonds.cote, Fonds.titre)
    if perimetre.fonds_id is not None:
        stmt = stmt.where(Fonds.id == perimetre.fonds_id)
    return stmt


def controler_meta_cote_invalide(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """META-COTE-INVALIDE : cote hors du pattern alphanumérique."""
    problemes: list[Exemple] = []
    total = 0

    fonds_stmt = _fonds_filtres(perimetre)
    if fonds_stmt is not None:
        for fid, cote in db.execute(
            fonds_stmt.with_only_columns(Fonds.id, Fonds.cote)
        ).all():
            total += 1
            if not PATTERN_COTE.match(cote):
                problemes.append(
                    Exemple(
                        message=f"Cote de fonds invalide : {cote!r}",
                        references={"fonds_cote": cote, "fonds_id": fid},
                    )
                )

    for cid, cote, _ in db.execute(_collections_filtrees(perimetre)).all():
        total += 1
        if not PATTERN_COTE.match(cote):
            problemes.append(
                Exemple(
                    message=f"Cote de collection invalide : {cote!r}",
                    references={"collection_cote": cote, "collection_id": cid},
                )
            )

    for iid, cote, *_ in db.execute(_items_filtres(perimetre)).all():
        total += 1
        if not PATTERN_COTE.match(cote):
            problemes.append(
                Exemple(
                    message=f"Cote d'item invalide : {cote!r}",
                    references={"item_cote": cote, "item_id": iid},
                )
            )
    return construire_resultat(
        id="META-COTE-INVALIDE",
        famille=FAMILLE,
        severite=Severite.ERREUR,
        libelle="Cote conforme au pattern alphanumérique",
        total=total,
        problemes=problemes,
    )


def _est_vide(titre: str | None) -> bool:
    """Réutilise `chaine_ou_none` pour aligner la définition de « vide »
    avec la validation côté services."""
    return chaine_ou_none(titre) is None


def controler_meta_titre_vide(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """META-TITRE-VIDE : titre vide sur fonds, collection ou item.

    Sur fonds/collection le titre est NOT NULL en base ; ce contrôle
    capte le cas chaîne vide ou whitespace-only (manipulation manuelle).
    """
    problemes: list[Exemple] = []
    total = 0

    fonds_stmt = _fonds_filtres(perimetre)
    if fonds_stmt is not None:
        for fid, cote, titre in db.execute(fonds_stmt).all():
            total += 1
            if _est_vide(titre):
                problemes.append(
                    Exemple(
                        message=f"Fonds {cote} sans titre",
                        references={"fonds_cote": cote, "fonds_id": fid},
                    )
                )

    for cid, cote, titre in db.execute(_collections_filtrees(perimetre)).all():
        total += 1
        if _est_vide(titre):
            problemes.append(
                Exemple(
                    message=f"Collection {cote} sans titre",
                    references={"collection_cote": cote, "collection_id": cid},
                )
            )

    for iid, cote, titre, *_ in db.execute(_items_filtres(perimetre)).all():
        total += 1
        if _est_vide(titre):
            problemes.append(
                Exemple(
                    message=f"Item {cote} sans titre",
                    references={"item_cote": cote, "item_id": iid},
                )
            )

    return construire_resultat(
        id="META-TITRE-VIDE",
        famille=FAMILLE,
        severite=Severite.ERREUR,
        libelle="Titre non vide sur fonds, collection et item",
        total=total,
        problemes=problemes,
    )


def controler_meta_date_invalide(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """META-DATE-INVALIDE : Item.date renseignée mais syntaxe EDTF non
    reconnue (regex tolérante)."""
    rows = list(db.execute(_items_filtres(perimetre)).all())
    items_avec_date = [(iid, cote, date) for iid, cote, _, date, _ in rows if date]
    problemes = [
        Exemple(
            message=f"Item {cote} : date non reconnue {date!r}",
            references={"item_cote": cote, "item_id": iid, "date": date},
        )
        for iid, cote, date in items_avec_date
        if not _RE_EDTF_TOLERANT.match(date.strip())
    ]
    return construire_resultat(
        id="META-DATE-INVALIDE",
        famille=FAMILLE,
        severite=Severite.AVERTISSEMENT,
        libelle="Date Item respecte la syntaxe EDTF tolérante",
        total=len(items_avec_date),
        problemes=problemes,
    )


def controler_meta_annee_implausible(
    db: Session,
    perimetre: PerimetreControle,
    *,
    annee_min: int = ANNEE_MIN_DEFAUT,
    annee_max: int = ANNEE_MAX_DEFAUT,
) -> ResultatControle:
    """META-ANNEE-IMPLAUSIBLE : Item.annee hors d'une plage configurable
    (par défaut 1000..2100)."""
    rows = list(db.execute(_items_filtres(perimetre)).all())
    items_avec_annee = [(iid, cote, annee) for iid, cote, _, _, annee in rows if annee]
    problemes = [
        Exemple(
            message=f"Item {cote} : année implausible ({annee})",
            references={"item_cote": cote, "item_id": iid, "annee": annee},
        )
        for iid, cote, annee in items_avec_annee
        if annee < annee_min or annee > annee_max
    ]
    return construire_resultat(
        id="META-ANNEE-IMPLAUSIBLE",
        famille=FAMILLE,
        severite=Severite.AVERTISSEMENT,
        libelle=f"Item.annee dans la plage [{annee_min}, {annee_max}]",
        total=len(items_avec_annee),
        problemes=problemes,
    )
