"""Export Dublin Core XML.

Deux modes :
- ``agrege`` : un fichier XML avec une racine `<collection>` et une
  `<notice>` par item.
- ``un_fichier_par_item`` : un fichier par item dans le dossier de
  sortie, nommé `{cote-slug}.xml`.

Le XML est produit via `xml.etree.ElementTree` (échappement géré),
encodage UTF-8 déclaré dans le prologue, indentation propre.
"""

from __future__ import annotations

import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from sqlalchemy.orm import Session

from archives_tool.exporters.mapping_dc import (
    DC,
    MAPPING_DC,
    extraire_valeur,
    valeur_en_liste,
)
from archives_tool.exporters.rapport import RapportExport, verifier_pre_export
from archives_tool.exporters.selection import CritereSelection, selectionner_items
from archives_tool.models import Item

CHAMPS_OBLIGATOIRES_DC = ["cote", "titre"]

NS_DC = "http://purl.org/dc/terms/"


def _tag_dc(uri: str) -> str:
    """URI DC complète → tag ElementTree ``{NS}local``."""
    if uri.startswith(DC):
        return f"{{{NS_DC}}}{uri[len(DC) :]}"
    return uri


def _slug_nom_fichier(cote: str) -> str:
    """Convertit une cote en nom de fichier sûr cross-OS (/, \\, :, etc.
    remplacés par -)."""
    nfc = unicodedata.normalize("NFC", cote)
    slug = re.sub(r'[\\/:"*?<>|\s]+', "-", nfc).strip("-")
    return slug or "item"


def _notice_pour_item(item: Item) -> ET.Element:
    """Construit `<notice>` pour un item.

    Les champs absents ne génèrent aucun élément (pas de <dc:xxx/>
    vide). Les champs listes produisent plusieurs éléments homonymes.
    """
    notice = ET.Element("notice")

    for champ_interne, uri in MAPPING_DC.items():
        valeur = extraire_valeur(item, champ_interne)
        morceaux = valeur_en_liste(valeur)
        if not morceaux:
            continue
        tag = _tag_dc(uri)
        for m in morceaux:
            el = ET.SubElement(notice, tag)
            el.text = m

    return notice


def _serialiser(racine: ET.Element) -> bytes:
    """Sérialise avec indentation et prologue UTF-8.

    On force le préfixe `dc:` *au moment* de la sérialisation, pas au
    chargement du module : openpyxl/pandas (importés ailleurs dans le
    projet) réenregistrent `dcterms` plus tard et écraseraient un
    appel one-shot à l'import.
    """
    ET.register_namespace("dc", NS_DC)
    ET.indent(racine, space="  ")
    return ET.tostring(racine, encoding="utf-8", xml_declaration=True)


def exporter_dc_xml(
    session: Session,
    critere: CritereSelection,
    chemin_sortie: Path,
    mode: Literal["agrege", "un_fichier_par_item"] = "agrege",
    dry_run: bool = False,
) -> RapportExport:
    """Exporte en Dublin Core XML.

    Agrégé : `chemin_sortie` est un fichier.
    Un fichier par item : `chemin_sortie` est un dossier.
    """
    debut = time.monotonic()
    items = list(selectionner_items(session, critere))

    rapport = verifier_pre_export(items, CHAMPS_OBLIGATOIRES_DC, format="dc_xml")
    rapport.chemin_sortie = chemin_sortie

    # Slugification : logger les transformations.
    slugs: dict[str, str] = {}
    for item in items:
        s = _slug_nom_fichier(item.cote)
        if s != item.cote and mode == "un_fichier_par_item":
            rapport.avertissements.append(
                f"Cote {item.cote!r} → nom de fichier {s!r} (caractères non sûrs)"
            )
        slugs[item.cote] = s

    if dry_run:
        rapport.duree_secondes = time.monotonic() - debut
        return rapport

    if mode == "agrege":
        racine = ET.Element("collection")
        for item in items:
            racine.append(_notice_pour_item(item))
        chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
        chemin_sortie.write_bytes(_serialiser(racine))
    elif mode == "un_fichier_par_item":
        chemin_sortie.mkdir(parents=True, exist_ok=True)
        noms_utilises: dict[str, int] = {}
        for item in items:
            slug = slugs[item.cote]
            # Dé-doublonnage paranoïaque (au cas où le slug serait
            # identique pour deux cotes différentes).
            n = noms_utilises.get(slug, 0)
            nom = f"{slug}.xml" if n == 0 else f"{slug}_{n}.xml"
            noms_utilises[slug] = n + 1
            chemin = chemin_sortie / nom
            chemin.write_bytes(_serialiser(_notice_pour_item(item)))
    else:
        raise ValueError(f"Mode inconnu : {mode!r}")

    rapport.duree_secondes = time.monotonic() - debut
    return rapport
