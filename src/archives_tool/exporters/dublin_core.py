"""Export Dublin Core XML d'une collection (V0.9.0-gamma.2).

Format : un fichier XML avec une racine `<collection>` qui contient :
- une `<notice>` de tête pour la collection elle-même (cote, titre,
  description, DOI, type, fonds parent ou fonds représentés) ;
- une `<notice>` par item, avec ses champs DC mappés via `MAPPING_DC`.

Le XML est produit via `xml.etree.ElementTree` (échappement géré),
encodage UTF-8 déclaré dans le prologue, indentation propre.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from pathlib import Path

from sqlalchemy.orm import Session

from archives_tool.exporters._commun import (
    CollectionPourExport,
    composer_export,
)
from archives_tool.exporters.mapping_dc import (
    DC,
    MAPPING_DC,
    extraire_valeur,
    valeur_en_liste,
)
from archives_tool.exporters.rapport import RapportExport, verifier_pre_export
from archives_tool.models import Collection, Item

CHAMPS_OBLIGATOIRES_DC = ["cote", "titre"]

NS_DC = "http://purl.org/dc/terms/"


def _tag_dc(uri: str) -> str:
    """URI DC complète → tag ElementTree ``{NS}local``."""
    if uri.startswith(DC):
        return f"{{{NS_DC}}}{uri[len(DC) :]}"
    return uri


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


def _notice_collection(export: CollectionPourExport) -> ET.Element:
    """Notice de tête pour la collection elle-même.

    Inclut un `dc:source` listant les fonds représentés (utile pour
    les transversales où les items viennent de plusieurs fonds).
    """
    col = export.collection
    notice = ET.Element("notice", attrib={"role": "collection"})

    ET.SubElement(notice, _tag_dc(f"{DC}identifier")).text = col.cote
    ET.SubElement(notice, _tag_dc(f"{DC}title")).text = col.titre
    if col.description:
        ET.SubElement(notice, _tag_dc(f"{DC}description")).text = col.description
    if col.description_publique:
        ET.SubElement(
            notice, _tag_dc(f"{DC}description")
        ).text = col.description_publique
    if col.doi_nakala:
        ET.SubElement(notice, _tag_dc(f"{DC}identifier")).text = (
            f"doi:{col.doi_nakala}"
        )

    fonds_a_lister = (
        [export.fonds_parent]
        if export.fonds_parent is not None
        else list(export.fonds_representes)
    )
    for fonds in fonds_a_lister:
        ET.SubElement(notice, _tag_dc(f"{DC}source")).text = (
            f"{fonds.titre} ({fonds.cote})"
        )

    return notice


def _serialiser(racine: ET.Element) -> bytes:
    """Sérialise avec indentation et prologue UTF-8."""
    ET.register_namespace("dc", NS_DC)
    ET.indent(racine, space="  ")
    return ET.tostring(racine, encoding="utf-8", xml_declaration=True)


def exporter_dublin_core(
    session: Session,
    collection: Collection,
    chemin_sortie: Path,
) -> RapportExport:
    """Exporte une collection en Dublin Core XML (fichier agrégé).

    `chemin_sortie` est un fichier (pas un dossier — le mode
    « un fichier par item » a été retiré en V0.9.0-gamma.2).
    """
    debut = time.monotonic()
    export = composer_export(session, collection)
    items = [ipe.item for ipe in export.items]

    rapport = verifier_pre_export(items, CHAMPS_OBLIGATOIRES_DC, format="dc_xml")
    rapport.chemin_sortie = chemin_sortie

    racine = ET.Element("collection", attrib={"cote": collection.cote})
    racine.append(_notice_collection(export))
    for item in items:
        racine.append(_notice_pour_item(item))

    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
    chemin_sortie.write_bytes(_serialiser(racine))

    rapport.duree_secondes = time.monotonic() - debut
    return rapport
