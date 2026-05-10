"""Famille 3 — cohérence des métadonnées.

Vérifie cote, titre, date, année sur Fonds + Collection + Item. Les
contrôles utilisent les mêmes patterns que `services._erreurs` pour
rester cohérents avec la validation à l'entrée.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services._erreurs import PATTERN_COTE
from archives_tool.models import Collection, Fonds, Item, ItemCollection
from archives_tool.qa._commun import (
    Exemple,
    PerimetreControle,
    ResultatControle,
    Severite,
    borner_exemples,
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
    stmt = select(Item.id, Item.cote, Item.titre, Item.date, Item.annee)
    if perimetre.fonds_id is not None:
        stmt = stmt.where(Item.fonds_id == perimetre.fonds_id)
    elif perimetre.collection_id is not None:
        stmt = stmt.where(
            Item.id.in_(
                select(ItemCollection.item_id).where(
                    ItemCollection.collection_id == perimetre.collection_id
                )
            )
        )
    return stmt.order_by(Item.cote)


def controler_meta_cote_invalide(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """META-COTE-INVALIDE : fonds/collection/item dont la cote ne
    respecte pas le pattern alphanumérique + tirets/underscores."""
    fonds_rows: list = []
    if perimetre.fonds_id is None and perimetre.collection_id is None:
        fonds_rows = list(db.execute(select(Fonds.id, Fonds.cote)).all())
    elif perimetre.fonds_id is not None:
        fonds_rows = list(
            db.execute(
                select(Fonds.id, Fonds.cote).where(Fonds.id == perimetre.fonds_id)
            ).all()
        )

    collections_stmt = select(Collection.id, Collection.cote)
    if perimetre.fonds_id is not None:
        collections_stmt = collections_stmt.where(
            Collection.fonds_id == perimetre.fonds_id
        )
    elif perimetre.collection_id is not None:
        collections_stmt = collections_stmt.where(
            Collection.id == perimetre.collection_id
        )
    collections_rows = list(db.execute(collections_stmt).all())

    items_rows = list(db.execute(_items_filtres(perimetre)).all())

    problemes: list[Exemple] = []
    for fid, cote in fonds_rows:
        if not PATTERN_COTE.match(cote):
            problemes.append(
                Exemple(
                    message=f"Cote de fonds invalide : {cote!r}",
                    references={"fonds_cote": cote, "fonds_id": fid},
                )
            )
    for cid, cote in collections_rows:
        if not PATTERN_COTE.match(cote):
            problemes.append(
                Exemple(
                    message=f"Cote de collection invalide : {cote!r}",
                    references={"collection_cote": cote, "collection_id": cid},
                )
            )
    for iid, cote, *_ in items_rows:
        if not PATTERN_COTE.match(cote):
            problemes.append(
                Exemple(
                    message=f"Cote d'item invalide : {cote!r}",
                    references={"item_cote": cote, "item_id": iid},
                )
            )
    total = len(fonds_rows) + len(collections_rows) + len(items_rows)
    return ResultatControle(
        id="META-COTE-INVALIDE",
        famille=FAMILLE,
        severite=Severite.ERREUR,
        libelle="Cote conforme au pattern alphanumérique",
        passe=not problemes,
        compte_total=total,
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
    )


def _titre_vide(titre: str | None) -> bool:
    return not titre or not titre.strip()


def controler_meta_titre_vide(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """META-TITRE-VIDE : titre vide sur fonds, collection ou item.

    Sur fonds/collection le titre est NOT NULL en base ; ce contrôle
    capte le cas chaîne vide ou whitespace-only (manipulation manuelle).
    """
    problemes: list[Exemple] = []
    total = 0

    if perimetre.fonds_id is None and perimetre.collection_id is None:
        for fid, cote, titre in db.execute(
            select(Fonds.id, Fonds.cote, Fonds.titre)
        ).all():
            total += 1
            if _titre_vide(titre):
                problemes.append(
                    Exemple(
                        message=f"Fonds {cote} sans titre",
                        references={"fonds_cote": cote, "fonds_id": fid},
                    )
                )

    cstmt = select(Collection.id, Collection.cote, Collection.titre)
    if perimetre.fonds_id is not None:
        cstmt = cstmt.where(Collection.fonds_id == perimetre.fonds_id)
    elif perimetre.collection_id is not None:
        cstmt = cstmt.where(Collection.id == perimetre.collection_id)
    for cid, cote, titre in db.execute(cstmt).all():
        total += 1
        if _titre_vide(titre):
            problemes.append(
                Exemple(
                    message=f"Collection {cote} sans titre",
                    references={"collection_cote": cote, "collection_id": cid},
                )
            )

    for iid, cote, titre, *_ in db.execute(_items_filtres(perimetre)).all():
        total += 1
        if _titre_vide(titre):
            problemes.append(
                Exemple(
                    message=f"Item {cote} sans titre",
                    references={"item_cote": cote, "item_id": iid},
                )
            )

    return ResultatControle(
        id="META-TITRE-VIDE",
        famille=FAMILLE,
        severite=Severite.ERREUR,
        libelle="Titre non vide sur fonds, collection et item",
        passe=not problemes,
        compte_total=total,
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
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
    return ResultatControle(
        id="META-DATE-INVALIDE",
        famille=FAMILLE,
        severite=Severite.AVERTISSEMENT,
        libelle="Date Item respecte la syntaxe EDTF tolérante",
        passe=not problemes,
        compte_total=len(items_avec_date),
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
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
    return ResultatControle(
        id="META-ANNEE-IMPLAUSIBLE",
        famille=FAMILLE,
        severite=Severite.AVERTISSEMENT,
        libelle=f"Item.annee dans la plage [{annee_min}, {annee_max}]",
        passe=not problemes,
        compte_total=len(items_avec_annee),
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
    )
