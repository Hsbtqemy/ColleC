"""Export Excel (.xlsx) et CSV d'une sélection."""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, Literal

from openpyxl import Workbook
from sqlalchemy.orm import Session

from archives_tool.exporters.mapping_dc import extraire_valeur
from archives_tool.exporters.rapport import RapportExport
from archives_tool.exporters.selection import (
    CritereSelection,
    selectionner_fichiers,
    selectionner_items,
)
from archives_tool.models import Fichier, Item

COLONNES_DEFAUT_ITEM = [
    "cote",
    "titre",
    "date",
    "annee",
    "langue",
    "type_coar",
    "etat_catalogage",
    "doi_nakala",
]

COLONNES_DEFAUT_FICHIER = [
    "item.cote",
    "item.titre",
    "fichier.ordre",
    "fichier.nom_fichier",
    "fichier.racine",
    "fichier.chemin_relatif",
    "fichier.format",
]

LIBELLES = {
    "cote": "Cote",
    "titre": "Titre",
    "date": "Date",
    "annee": "Année",
    "langue": "Langue",
    "type_coar": "Type (COAR)",
    "etat_catalogage": "État",
    "doi_nakala": "DOI Nakala",
    "item.cote": "Cote item",
    "item.titre": "Titre item",
    "fichier.ordre": "Ordre",
    "fichier.nom_fichier": "Nom du fichier",
    "fichier.racine": "Racine",
    "fichier.chemin_relatif": "Chemin relatif",
    "fichier.format": "Format",
}


def _libelle(champ: str) -> str:
    return LIBELLES.get(champ, champ)


def _valeur_item(champ: str, item: Item) -> Any:
    val = extraire_valeur(item, champ)
    if isinstance(val, list):
        return " | ".join(str(v) for v in val)
    return val


def _valeur_couple(champ: str, item: Item, fichier: Fichier) -> Any:
    if champ.startswith("item."):
        return _valeur_item(champ[len("item.") :], item)
    if champ.startswith("fichier."):
        return getattr(fichier, champ[len("fichier.") :], None)
    return _valeur_item(champ, item)


def exporter_excel(
    session: Session,
    critere: CritereSelection,
    chemin_sortie: Path,
    format: Literal["xlsx", "csv"] = "xlsx",
    colonnes: list[str] | None = None,
    dry_run: bool = False,
) -> RapportExport:
    """Exporte une sélection vers `chemin_sortie` en xlsx ou csv.

    La granularité est prise dans `critere.granularite`. Les colonnes
    par défaut varient selon la granularité. En granularité fichier,
    les colonnes préfixées par `item.` ou `fichier.` désignent la
    source de la valeur.

    `dry_run=True` : calcule le rapport (nombre de lignes) sans
    écrire le fichier.
    """
    debut = time.monotonic()
    rapport = RapportExport(format=format, chemin_sortie=chemin_sortie)

    if colonnes is None:
        colonnes = (
            COLONNES_DEFAUT_FICHIER
            if critere.granularite == "fichier"
            else COLONNES_DEFAUT_ITEM
        )
    en_tetes = [_libelle(c) for c in colonnes]

    # Construction des lignes via streaming.
    if critere.granularite == "fichier":

        def _iter_lignes() -> list[list[Any]]:
            lignes = []
            items_vus: set[int] = set()
            for item, fichier in selectionner_fichiers(session, critere):
                lignes.append([_valeur_couple(c, item, fichier) for c in colonnes])
                items_vus.add(item.id)
                rapport.nb_fichiers_selectionnes += 1
            rapport.nb_items_selectionnes = len(items_vus)
            return lignes

        lignes = _iter_lignes()
    else:
        lignes = []
        for item in selectionner_items(session, critere):
            lignes.append([_valeur_item(c, item) for c in colonnes])
            rapport.nb_items_selectionnes += 1

    if dry_run:
        rapport.duree_secondes = time.monotonic() - debut
        return rapport

    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)

    if format == "xlsx":
        wb = Workbook(write_only=True)
        ws = wb.create_sheet(title="Export")
        ws.append(en_tetes)
        for ligne in lignes:
            ws.append(ligne)
        wb.save(chemin_sortie)
    elif format == "csv":
        # UTF-8 avec BOM pour ouverture directe dans Excel Windows.
        with chemin_sortie.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(en_tetes)
            for ligne in lignes:
                writer.writerow(["" if v is None else v for v in ligne])
    else:
        raise ValueError(f"Format inconnu : {format!r}")

    rapport.duree_secondes = time.monotonic() - debut
    return rapport
