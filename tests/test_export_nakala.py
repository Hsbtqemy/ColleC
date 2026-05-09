"""Tests de l'export Nakala CSV (V0.9.0-gamma.2)."""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy.orm import Session

from archives_tool.api.services.collections import lire_collection_par_cote
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.exporters.nakala import COLONNES_NAKALA, exporter_nakala_csv

# Fixture `session_avec_export` partagée définie dans tests/conftest.py.


def test_export_nakala_csv_format(
    session_avec_export: Session, tmp_path: Path
) -> None:
    """Le CSV contient l'en-tête attendu + une ligne par item."""
    fonds = lire_fonds_par_cote(session_avec_export, "HK")
    miroir = lire_collection_par_cote(session_avec_export, "HK", fonds_id=fonds.id)

    sortie = tmp_path / "hk_nakala.csv"
    rapport = exporter_nakala_csv(session_avec_export, miroir, sortie)
    assert sortie.is_file()
    assert rapport.nb_items_selectionnes == 3

    with sortie.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[0] == COLONNES_NAKALA
    assert len(rows) == 4  # entête + 3 items
    assert "fonds_cote" in rows[0]


def test_export_nakala_transversale_fonds_par_ligne(
    session_avec_export: Session, tmp_path: Path
) -> None:
    """Pour une transversale, chaque ligne indique son fonds d'origine."""
    transv = lire_collection_par_cote(session_avec_export, "TRANSV")

    sortie = tmp_path / "transv_nakala.csv"
    exporter_nakala_csv(session_avec_export, transv, sortie)

    with sortie.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)
    fonds_cotes = {row["fonds_cote"] for row in rows}
    assert fonds_cotes == {"HK", "FA"}


def test_export_nakala_doi_collection_propage(
    session_avec_export: Session, tmp_path: Path
) -> None:
    """Si la collection a un DOI Nakala, il devient le `Linked in
    collection` par défaut pour les items qui n'en ont pas."""
    fonds = lire_fonds_par_cote(session_avec_export, "HK")
    favoris = lire_collection_par_cote(
        session_avec_export, "HK-FAVORIS", fonds_id=fonds.id
    )
    favoris.doi_nakala = "10.34847/nkl.fakecollab"
    session_avec_export.commit()

    sortie = tmp_path / "favoris_nakala.csv"
    exporter_nakala_csv(session_avec_export, favoris, sortie)

    with sortie.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)
    assert all(row["Linked in collection"] == "10.34847/nkl.fakecollab" for row in rows)


def test_export_nakala_items_incomplets_signales(
    session_avec_export: Session, tmp_path: Path
) -> None:
    """Les items sans date/type_coar/créateur sont listés dans
    `items_incomplets`."""
    fonds = lire_fonds_par_cote(session_avec_export, "HK")
    miroir = lire_collection_par_cote(session_avec_export, "HK", fonds_id=fonds.id)

    sortie = tmp_path / "hk_nakala.csv"
    rapport = exporter_nakala_csv(session_avec_export, miroir, sortie)

    # Les items du fixture n'ont ni date ni type_coar ni créateur.
    assert len(rapport.items_incomplets) == 3
    cotes_incompletes = {c for c, _ in rapport.items_incomplets}
    assert cotes_incompletes == {"HK-001", "HK-002", "HK-003"}
