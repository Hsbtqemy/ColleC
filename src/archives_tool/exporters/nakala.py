"""Export CSV de dépôt Nakala d'une collection (V0.9.0-gamma.2).

Format CSV avec colonnes inspirées du format d'import Nakala
standard (DC + prédicats Nakala). Séparateur ``;``, UTF-8 avec BOM
pour ouverture directe dans Excel Windows.

Granularité : un item = une ligne = une « donnée » Nakala. La
collection elle-même est référencée via la première colonne
`Linked in collection` (DOI Nakala de la miroir si présent).
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from sqlalchemy.orm import Session

from archives_tool.exporters._commun import composer_export
from archives_tool.exporters.mapping_dc import (
    DC,
    extraire_valeur,
    valeur_en_liste,
)
from archives_tool.exporters.rapport import RapportExport, verifier_pre_export
from archives_tool.models import Collection, Item

CHAMPS_OBLIGATOIRES_NAKALA = ["titre", "date", "type_coar"]
# « créateur » est traité à part (3 sources alternatives possibles).

NS_NAKALA = "http://nakala.fr/terms#"

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
    "fonds_cote",  # Champ informatif, utile pour les transversales.
    "IsDescribedBy",
    "IsIdenticalTo",
    "IsDerivedFrom",
    "IsPublishedIn",
]


def _joindre(valeur: object) -> str:
    """Valeur → chaîne pour CSV. Listes concaténées par ' | '."""
    return " | ".join(valeur_en_liste(valeur))


def _ligne_nakala(
    item: Item,
    fonds_cote: str,
    doi_collection: str | None,
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
        "Linked in collection": item.doi_collection_nakala or doi_collection or "",
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
        "fonds_cote": fonds_cote,
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
        if createur:
            continue
        existant = next(
            (e for e in rapport.items_incomplets if e[0] == item.cote), None
        )
        if existant:
            existant[1].append("createur")
        else:
            rapport.items_incomplets.append((item.cote, ["createur"]))


def exporter_nakala_csv(
    session: Session,
    collection: Collection,
    chemin_sortie: Path,
    licence_defaut: str = "CC-BY-NC-ND-4.0",
    statut_defaut: str = "pending",
) -> RapportExport:
    """Exporte une collection au format CSV attendu par l'import Nakala.

    - Séparateur `;`, encodage UTF-8 avec BOM.
    - Licence et statut pris dans les métadonnées de l'item si présents,
      sinon valeurs par défaut.
    - Rapport.items_incomplets liste les items manquant titre, date,
      type_coar ou créateur.
    """
    debut = time.monotonic()
    export = composer_export(session, collection)
    items = [ipe.item for ipe in export.items]

    rapport = verifier_pre_export(
        items, CHAMPS_OBLIGATOIRES_NAKALA, format="nakala_csv"
    )
    rapport.chemin_sortie = chemin_sortie
    _verifier_createur(items, rapport)

    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
    with chemin_sortie.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=COLONNES_NAKALA, delimiter=";", extrasaction="raise"
        )
        writer.writeheader()
        for ipe in export.items:
            writer.writerow(
                _ligne_nakala(
                    ipe.item,
                    ipe.fonds_cote,
                    collection.doi_nakala,
                    licence_defaut,
                    statut_defaut,
                )
            )

    rapport.duree_secondes = time.monotonic() - debut
    return rapport
