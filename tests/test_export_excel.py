"""Tests de l'export Excel / CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from archives_tool.config import ConfigLocale
from archives_tool.exporters.excel import exporter_excel
from archives_tool.exporters.selection import CritereSelection
from archives_tool.importers.ecrivain import importer as importer_profil
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


@pytest.fixture
def base_avec_fixture(session: Session) -> Session:
    """Importe cas_item_simple dans la DB de test."""
    chemin = FIXTURES / "cas_item_simple" / "profil.yaml"
    profil = charger_profil(chemin)
    config = ConfigLocale(
        utilisateur="T",
        racines={"scans_revues": FIXTURES / "cas_item_simple" / "arbre"},
    )
    importer_profil(profil, chemin, session, config, dry_run=False, cree_par="T")
    return session


def test_export_xlsx_item(base_avec_fixture: Session, tmp_path: Path) -> None:
    sortie = tmp_path / "inventaire.xlsx"
    rapport = exporter_excel(
        base_avec_fixture,
        CritereSelection(collection_cote="HK"),
        sortie,
        format="xlsx",
    )
    assert rapport.nb_items_selectionnes == 5
    assert sortie.is_file()

    df = pd.read_excel(sortie)
    assert list(df["Cote"]) == [
        "HK-1960-01",
        "HK-1960-02",
        "HK-1961-01",
        "HK-1961-02",
        "HK-1961-03",
    ]
    assert df.loc[0, "Titre"] == "Premier numéro"


def test_export_csv_bom_et_sep(base_avec_fixture: Session, tmp_path: Path) -> None:
    sortie = tmp_path / "inventaire.csv"
    rapport = exporter_excel(
        base_avec_fixture,
        CritereSelection(collection_cote="HK"),
        sortie,
        format="csv",
    )
    assert rapport.nb_items_selectionnes == 5
    # BOM UTF-8 présent.
    raw = sortie.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    # Relecture pandas en ";".
    df = pd.read_csv(sortie, sep=";", encoding="utf-8-sig")
    assert len(df) == 5


def test_export_granularite_fichier(base_avec_fixture: Session, tmp_path: Path) -> None:
    sortie = tmp_path / "fichiers.xlsx"
    rapport = exporter_excel(
        base_avec_fixture,
        CritereSelection(collection_cote="HK", granularite="fichier"),
        sortie,
    )
    # 3 fichiers PNG matchent (numero 1, 2, 3) sur 5 items.
    assert rapport.nb_fichiers_selectionnes == 3
    assert rapport.nb_items_selectionnes == 3

    df = pd.read_excel(sortie)
    assert list(df.columns) == [
        "Cote item",
        "Titre item",
        "Ordre",
        "Nom du fichier",
        "Racine",
        "Chemin relatif",
        "Format",
    ]
    assert set(df["Nom du fichier"]) == {"01.png", "02.png", "03.png"}


def test_export_colonnes_personnalisees(
    base_avec_fixture: Session, tmp_path: Path
) -> None:
    sortie = tmp_path / "min.xlsx"
    exporter_excel(
        base_avec_fixture,
        CritereSelection(collection_cote="HK"),
        sortie,
        colonnes=["cote", "titre", "metadonnees.collaborateurs"],
    )
    df = pd.read_excel(sortie)
    # En-têtes transcrits via LIBELLES quand connus, nom technique
    # sinon (metadonnees.collaborateurs n'est pas dans LIBELLES).
    assert list(df.columns) == ["Cote", "Titre", "metadonnees.collaborateurs"]
    # Colonne liste : jointure par " | ".
    ligne1 = df[df["Cote"] == "HK-1960-01"].iloc[0]
    assert ligne1["metadonnees.collaborateurs"] == "Cavanna | Choron | Fournier"


def test_dry_run_ne_cree_pas_le_fichier(
    base_avec_fixture: Session, tmp_path: Path
) -> None:
    sortie = tmp_path / "n_existe_pas.xlsx"
    rapport = exporter_excel(
        base_avec_fixture,
        CritereSelection(collection_cote="HK"),
        sortie,
        dry_run=True,
    )
    assert rapport.nb_items_selectionnes == 5
    assert not sortie.exists()
