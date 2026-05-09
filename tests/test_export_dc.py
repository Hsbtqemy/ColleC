"""Tests de l'export Dublin Core XML (V0.9.0-gamma.2)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from sqlalchemy.orm import Session

from archives_tool.api.services.collections import lire_collection_par_cote
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.exporters.dublin_core import exporter_dublin_core

NS = {"dc": "http://purl.org/dc/terms/"}


def test_export_dc_miroir(session_avec_export: Session, tmp_path: Path) -> None:
    """Export d'une miroir : 1 notice collection + 3 notices items."""
    fonds = lire_fonds_par_cote(session_avec_export, "HK")
    miroir = lire_collection_par_cote(session_avec_export, "HK", fonds_id=fonds.id)

    sortie = tmp_path / "hk_dc.xml"
    rapport = exporter_dublin_core(session_avec_export, miroir, sortie)

    assert sortie.is_file()
    assert rapport.nb_items_selectionnes == 3
    assert rapport.format == "dc_xml"

    arbre = ET.parse(sortie)
    racine = arbre.getroot()
    assert racine.tag == "collection"
    assert racine.get("cote") == "HK"

    notices = racine.findall("notice")
    assert len(notices) == 4  # 1 collection + 3 items
    assert notices[0].get("role") == "collection"


def test_export_dc_libre_rattachee(
    session_avec_export: Session, tmp_path: Path
) -> None:
    """Une libre rattachée référence son fonds parent via dc:source."""
    fonds = lire_fonds_par_cote(session_avec_export, "HK")
    libre = lire_collection_par_cote(
        session_avec_export, "HK-FAVORIS", fonds_id=fonds.id
    )

    sortie = tmp_path / "hk_favoris_dc.xml"
    rapport = exporter_dublin_core(session_avec_export, libre, sortie)
    assert rapport.nb_items_selectionnes == 2

    arbre = ET.parse(sortie)
    notice_collection = arbre.getroot().find("notice[@role='collection']")
    sources = notice_collection.findall("dc:source", NS)
    assert len(sources) == 1
    assert "Hara-Kiri" in sources[0].text
    assert "(HK)" in sources[0].text


def test_export_dc_transversale_inclut_plusieurs_fonds(
    session_avec_export: Session, tmp_path: Path
) -> None:
    """Une transversale liste tous les fonds représentés en tête."""
    transv = lire_collection_par_cote(session_avec_export, "TRANSV")

    sortie = tmp_path / "transv_dc.xml"
    rapport = exporter_dublin_core(session_avec_export, transv, sortie)
    assert rapport.nb_items_selectionnes == 2

    arbre = ET.parse(sortie)
    notice_collection = arbre.getroot().find("notice[@role='collection']")
    sources = [s.text for s in notice_collection.findall("dc:source", NS)]
    assert any("(HK)" in s for s in sources)
    assert any("(FA)" in s for s in sources)


def test_export_dc_metadonnees_collection_presentes(
    session_avec_export: Session, tmp_path: Path
) -> None:
    """Cote, titre et description publique de la collection sont
    écrits dans la notice de tête."""
    fonds = lire_fonds_par_cote(session_avec_export, "HK")
    libre = lire_collection_par_cote(
        session_avec_export, "HK-FAVORIS", fonds_id=fonds.id
    )

    sortie = tmp_path / "hk_favoris_dc.xml"
    exporter_dublin_core(session_avec_export, libre, sortie)
    contenu = sortie.read_text(encoding="utf-8")
    assert "HK-FAVORIS" in contenu
    assert "Hara-Kiri favoris" in contenu
    assert "Sélection éditoriale" in contenu


def test_export_dc_titres_items_presents(
    session_avec_export: Session, tmp_path: Path
) -> None:
    """Le titre de chaque item est exporté en dc:title."""
    fonds = lire_fonds_par_cote(session_avec_export, "HK")
    miroir = lire_collection_par_cote(session_avec_export, "HK", fonds_id=fonds.id)

    sortie = tmp_path / "hk_dc.xml"
    exporter_dublin_core(session_avec_export, miroir, sortie)
    contenu = sortie.read_text(encoding="utf-8")
    assert "Numéro 1" in contenu
    assert "Numéro 2" in contenu
    assert "Numéro 3" in contenu
