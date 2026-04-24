"""Export CSV de dépôt Nakala.

Colonnes inspirées du format d'import standard Nakala. Séparateur ``;``
et UTF-8 avec BOM (ouverture directe sous Excel Windows).

Granularité : item uniquement (un item = une ligne = une « donnée »
Nakala).
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from sqlalchemy.orm import Session

from archives_tool.exporters.mapping_dc import (
    DC,
    extraire_valeur,
    valeur_en_liste,
)
from archives_tool.exporters.rapport import RapportExport, verifier_pre_export
from archives_tool.exporters.selection import CritereSelection, selectionner_items
from archives_tool.models import Item

# Champs obligatoires pour un dépôt Nakala valide.
CHAMPS_OBLIGATOIRES_NAKALA = [
    "titre",
    "date",
    "type_coar",
    # « créateur » : on accepte que l'un des trois champs soit présent.
]

NS_NAKALA = "http://nakala.fr/terms#"

# Colonnes du CSV Nakala, dans l'ordre.
COLONNES_NAKALA = [
    "Linked in collection",
    "Status collection",
    "collectionsIds",
    "Linked in item",
    "Status donnee",
    f"{NS_NAKALA}title",
    "langTitle",
    f"{NS_NAKALA}creator",
    f"{NS_NAKALA}created",
    f"{NS_NAKALA}type",
    f"{NS_NAKALA}license",
    "Embargoed",
    f"{DC}identifier",
    f"{DC}title",
    f"{DC}creator",
    f"{DC}date",
    f"{DC}description",
    f"{DC}subject",
    f"{DC}language",
    f"{DC}publisher",
    f"{DC}type",
    f"{DC}rights",
    "IsDescribedBy",
    "IsIdenticalTo",
    "IsDerivedFrom",
    "IsPublishedIn",
]


def _joindre(valeur: object) -> str:
    """Valeur → chaîne pour CSV. Listes concaténées par ' | '."""
    morceaux = valeur_en_liste(valeur)
    return " | ".join(morceaux)


def _ligne_nakala(
    item: Item,
    licence_defaut: str,
    statut_defaut: str,
) -> dict[str, str]:
    """Projette un Item vers un dict colonne → valeur pour le CSV Nakala."""
    meta = item.metadonnees or {}

    titre = item.titre or ""
    createur = _joindre(meta.get("createurs") or meta.get("auteurs"))
    date = item.date or ""
    type_coar = item.type_coar or ""
    licence = meta.get("licence") or meta.get("rights") or licence_defaut
    statut = meta.get("statut_nakala") or statut_defaut

    return {
        "Linked in collection": item.doi_collection_nakala or "",
        "Status collection": "",
        "collectionsIds": "",
        "Linked in item": item.doi_nakala or "",
        "Status donnee": statut,
        f"{NS_NAKALA}title": titre,
        "langTitle": item.langue or "",
        f"{NS_NAKALA}creator": createur,
        f"{NS_NAKALA}created": date,
        f"{NS_NAKALA}type": type_coar,
        f"{NS_NAKALA}license": licence,
        "Embargoed": "",
        f"{DC}identifier": item.cote,
        f"{DC}title": titre,
        f"{DC}creator": createur,
        f"{DC}date": date,
        f"{DC}description": item.description or "",
        f"{DC}subject": _joindre(meta.get("sujets") or meta.get("rubrique")),
        f"{DC}language": item.langue or "",
        f"{DC}publisher": _joindre(meta.get("editeur") or meta.get("publisher")),
        f"{DC}type": type_coar,
        f"{DC}rights": licence,
        "IsDescribedBy": "",
        "IsIdenticalTo": "",
        "IsDerivedFrom": "",
        "IsPublishedIn": "",
    }


def _verifier_createur(items: list[Item], rapport: RapportExport) -> None:
    """Complète items_incomplets avec les items sans aucun créateur."""
    for item in items:
        createur = extraire_valeur(item, "metadonnees.createurs") or extraire_valeur(
            item, "metadonnees.auteurs"
        )
        if not createur:
            existant = next(
                (e for e in rapport.items_incomplets if e[0] == item.cote), None
            )
            if existant:
                existant[1].append("createur")
            else:
                rapport.items_incomplets.append((item.cote, ["createur"]))


def exporter_nakala_csv(
    session: Session,
    critere: CritereSelection,
    chemin_sortie: Path,
    licence_defaut: str = "CC-BY-NC-ND-4.0",
    statut_defaut: str = "pending",
    dry_run: bool = False,
) -> RapportExport:
    """Exporte au format CSV attendu par l'import Nakala.

    - Séparateur `;`, encodage UTF-8 avec BOM.
    - Licence et statut pris dans les métadonnées de l'item si présents,
      sinon valeurs par défaut passées en paramètres.
    - Rapport.items_incomplets liste les items manquant de titre, date,
      type_coar ou créateur.
    """
    debut = time.monotonic()
    items = list(selectionner_items(session, critere))

    rapport = verifier_pre_export(
        items, CHAMPS_OBLIGATOIRES_NAKALA, format="nakala_csv"
    )
    rapport.chemin_sortie = chemin_sortie
    _verifier_createur(items, rapport)

    if dry_run:
        rapport.duree_secondes = time.monotonic() - debut
        return rapport

    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
    with chemin_sortie.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=COLONNES_NAKALA, delimiter=";", extrasaction="raise"
        )
        writer.writeheader()
        for item in items:
            writer.writerow(_ligne_nakala(item, licence_defaut, statut_defaut))

    rapport.duree_secondes = time.monotonic() - debut
    return rapport
