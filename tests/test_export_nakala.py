"""Tests de l'export CSV Nakala."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from archives_tool.config import ConfigLocale
from archives_tool.exporters.nakala import (
    COLONNES_NAKALA,
    exporter_nakala_csv,
)
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
    importer_profil(profil, chemin, session, config, dry_run=False)
    return session


def test_export_nakala_structure(base_uri_dc: Session, tmp_path: Path) -> None:
    sortie = tmp_path / "depot.csv"
    rapport = exporter_nakala_csv(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        sortie,
    )
    assert rapport.nb_items_selectionnes == 2
    assert sortie.is_file()
    # BOM + relecture pandas.
    assert sortie.read_bytes().startswith(b"\xef\xbb\xbf")
    df = pd.read_csv(sortie, sep=";", encoding="utf-8-sig")
    assert list(df.columns) == COLONNES_NAKALA
    assert len(df) == 2


def test_licence_et_statut_par_defaut(base_uri_dc: Session, tmp_path: Path) -> None:
    sortie = tmp_path / "depot.csv"
    exporter_nakala_csv(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        sortie,
        licence_defaut="CC-BY-4.0",
        statut_defaut="published",
    )
    df = pd.read_csv(sortie, sep=";", encoding="utf-8-sig")
    assert (df["http://nakala.fr/terms#license"] == "CC-BY-4.0").all()
    assert (df["Status donnee"] == "published").all()


def test_createurs_concatenes(base_uri_dc: Session, tmp_path: Path) -> None:
    sortie = tmp_path / "depot.csv"
    exporter_nakala_csv(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        sortie,
    )
    df = pd.read_csv(sortie, sep=";", encoding="utf-8-sig")
    # Item NKLDC-001 : creator_1=Dupont, creator_2=Martin → agrégés
    # par " / " au mapping, puis triés et joints par " | " par
    # l'exporter pour la cellule Nakala.
    ligne = df[df["http://purl.org/dc/terms/identifier"] == "NKLDC-001"].iloc[0]
    # L'agrégation à l'import fait "Dupont / Martin" (1 chaîne),
    # l'exporter l'envoie tel quel.
    assert ligne["http://nakala.fr/terms#creator"] == "Dupont / Martin"


def test_items_incomplets_dry_run(base_uri_dc: Session, tmp_path: Path) -> None:
    # Ajout d'un item manquant titre+date+type+créateur.
    from sqlalchemy import select as sqla_select

    from archives_tool.models import Collection, Item

    col = base_uri_dc.scalar(
        sqla_select(Collection).where(Collection.cote_collection == "NKLDC")
    )
    base_uri_dc.add(Item(collection_id=col.id, cote="NKLDC-VIDE"))
    base_uri_dc.commit()

    sortie = tmp_path / "depot.csv"
    rapport = exporter_nakala_csv(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        sortie,
        dry_run=True,
    )
    manques = dict(rapport.items_incomplets)
    assert "NKLDC-VIDE" in manques
    assert set(manques["NKLDC-VIDE"]) >= {"titre", "date", "type_coar", "createur"}
    assert not sortie.exists()  # dry-run


def test_doi_nakala_et_collection_remontes(
    base_uri_dc: Session, tmp_path: Path
) -> None:
    sortie = tmp_path / "depot.csv"
    exporter_nakala_csv(
        base_uri_dc,
        CritereSelection(collection_cote="NKLDC"),
        sortie,
    )
    df = pd.read_csv(sortie, sep=";", encoding="utf-8-sig")
    # La collection fixture a doi_nakala="10.34847/nkl.fakedccoll" ;
    # les items n'ont pas de DOI Nakala individuel (non mappé).
    assert (df["Linked in collection"].fillna("").astype(str).str.strip() == "").all()
    assert (df["Linked in item"].fillna("").astype(str).str.strip() == "").all()
