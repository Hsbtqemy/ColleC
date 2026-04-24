"""Tests de l'export Dublin Core XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from archives_tool.config import ConfigLocale
from archives_tool.exporters.dublin_core import NS_DC, exporter_dc_xml
from archives_tool.exporters.selection import CritereSelection
from archives_tool.importers.ecrivain import importer as importer_profil
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


@pytest.fixture
def base_uri_dc(session: Session) -> Session:
    chemin = FIXTURES / "cas_uri_dc" / "profil.yaml"
    profil = charger_profil(chemin)
    config = ConfigLocale(
        utilisateur="T",
        racines={"scans_nakala": FIXTURES / "cas_uri_dc" / "arbre"},
    )
    importer_profil(profil, chemin, session, config, dry_run=False, cree_par="T")
    return session


def test_export_agrege(base_uri_dc: Session, tmp_path: Path) -> None:
    sortie = tmp_path / "dc.xml"
    rapport = exporter_dc_xml(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        sortie,
        mode="agrege",
    )
    assert rapport.nb_items_selectionnes == 2
    assert sortie.is_file()

    tree = ET.parse(sortie)
    racine = tree.getroot()
    assert racine.tag == "collection"
    notices = racine.findall("notice")
    assert len(notices) == 2

    # Premier item : Étude café
    titres = notices[0].findall(f"{{{NS_DC}}}title")
    assert [e.text for e in titres] == ["Étude café"]
    ids = notices[0].findall(f"{{{NS_DC}}}identifier")
    assert [e.text for e in ids] == ["NKLDC-001"]


def test_export_un_fichier_par_item(base_uri_dc: Session, tmp_path: Path) -> None:
    dossier = tmp_path / "par_item"
    rapport = exporter_dc_xml(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        dossier,
        mode="un_fichier_par_item",
    )
    assert rapport.nb_items_selectionnes == 2
    fichiers = sorted(dossier.glob("*.xml"))
    assert len(fichiers) == 2
    noms = {f.name for f in fichiers}
    assert noms == {"NKLDC-001.xml", "NKLDC-002.xml"}


def test_champs_absents_pas_d_elements_vides(
    base_uri_dc: Session, tmp_path: Path
) -> None:
    sortie = tmp_path / "dc.xml"
    exporter_dc_xml(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        sortie,
        mode="agrege",
    )
    xml = sortie.read_text(encoding="utf-8")
    # NKLDC-002 n'a pas de date (s.d. → valeur nulle) : pas d'élément
    # dc:date vide.
    assert "<dc:date></dc:date>" not in xml
    assert "<dc:date />" not in xml


def test_slugification_cote_avec_slash(session: Session, tmp_path: Path) -> None:
    # On attache directement des items avec une cote contenant des
    # caractères sûrs (le transformateur rejette / et \n, donc on
    # teste ici la slugification sur des espaces ou deux-points).
    from archives_tool.models import Collection, Item

    col = Collection(cote_collection="SLUG", titre="Slug")
    session.add(col)
    session.flush()
    session.add(Item(collection_id=col.id, cote="COTE: avec espaces", titre="T"))
    session.commit()

    dossier = tmp_path / "par_item"
    rapport = exporter_dc_xml(
        session,
        CritereSelection(collection_cote="SLUG"),
        dossier,
        mode="un_fichier_par_item",
    )
    fichiers = list(dossier.glob("*.xml"))
    assert len(fichiers) == 1
    # Espaces et : remplacés par -, pas de chemin échappé.
    assert fichiers[0].name == "COTE-avec-espaces.xml"
    assert any("slug" in a.lower() or "non sûr" in a for a in rapport.avertissements)


def test_items_incomplets_signales(base_uri_dc: Session, tmp_path: Path) -> None:
    # Ajout d'un item sans titre dans la collection NKLDC.
    from sqlalchemy import select as sqla_select

    from archives_tool.models import Collection, Item

    col = base_uri_dc.scalar(
        sqla_select(Collection).where(Collection.cote_collection == "NKLDC")
    )
    base_uri_dc.add(Item(collection_id=col.id, cote="NKLDC-SANSTITRE"))
    base_uri_dc.commit()

    sortie = tmp_path / "dc.xml"
    rapport = exporter_dc_xml(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        sortie,
        mode="agrege",
        dry_run=True,
    )
    assert ("NKLDC-SANSTITRE", ["titre"]) in rapport.items_incomplets
