"""Tests de `archives-tool exporter <format>` (V0.9.0-gamma.2)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from archives_tool.api.services.collections import (
    FormulaireCollection,
    creer_collection_libre,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base

runner = CliRunner()


def _base_avec_collection(tmp_path: Path) -> Path:
    """Petite base SQLite avec un fonds HK + 2 items + une libre rattachée."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        fonds = lire_fonds_par_cote(s, "HK")
        creer_item(
            s,
            FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id),
        )
        creer_item(
            s,
            FormulaireItem(cote="HK-002", titre="N°2", fonds_id=fonds.id),
        )
        creer_collection_libre(
            s,
            FormulaireCollection(
                cote="HK-FAVORIS", titre="Favoris", fonds_id=fonds.id
            ),
        )
    engine.dispose()
    return db


def test_cli_exporter_dublin_core(tmp_path: Path) -> None:
    db = _base_avec_collection(tmp_path)
    sortie = tmp_path / "out.xml"
    result = runner.invoke(
        app,
        [
            "exporter",
            "dublin-core",
            "HK",
            "--fonds",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.is_file()
    assert "2 items" in result.output


def test_cli_exporter_nakala(tmp_path: Path) -> None:
    db = _base_avec_collection(tmp_path)
    sortie = tmp_path / "out.csv"
    result = runner.invoke(
        app,
        [
            "exporter",
            "nakala",
            "HK-FAVORIS",
            "--fonds",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.is_file()


def test_cli_exporter_xlsx(tmp_path: Path) -> None:
    db = _base_avec_collection(tmp_path)
    sortie = tmp_path / "out.xlsx"
    result = runner.invoke(
        app,
        [
            "exporter",
            "xlsx",
            "HK",
            "--fonds",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.is_file()


def test_cli_exporter_sortie_par_defaut(tmp_path: Path, monkeypatch) -> None:
    """Sans --sortie, fichier créé dans le cwd avec un nom dérivé de la cote."""
    db = _base_avec_collection(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "exporter",
            "dublin-core",
            "HK",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "HK_dc.xml").is_file()


def test_cli_exporter_collection_inexistante(tmp_path: Path) -> None:
    db = _base_avec_collection(tmp_path)
    result = runner.invoke(
        app,
        [
            "exporter",
            "dublin-core",
            "INEXISTANTE",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1
    assert "introuvable" in result.output.lower()


def test_cli_exporter_db_inexistante(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "exporter",
            "dublin-core",
            "HK",
            "--db-path",
            str(tmp_path / "absente.db"),
        ],
    )
    assert result.exit_code == 2
    assert "introuvable" in result.output.lower()


# ---------------------------------------------------------------------------
# Exporter annotations (V0.9.7 δ)
# ---------------------------------------------------------------------------


def test_cli_exporter_annotations_succes(tmp_path: Path) -> None:
    """Export d'une collection sans annotation : produit un JSON
    AnnotationCollection W3C avec total=0."""
    import json
    db = _base_avec_collection(tmp_path)
    sortie = tmp_path / "annotations.json"
    result = runner.invoke(
        app,
        [
            "exporter",
            "annotations",
            "HK",
            "--db-path", str(db),
            "--sortie", str(sortie),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.exists()
    payload = json.loads(sortie.read_text(encoding="utf-8"))
    assert payload["type"] == "AnnotationCollection"
    assert payload["@context"] == "http://www.w3.org/ns/anno.jsonld"
    assert payload["total"] == 0
    assert "0 annotation(s) export" in result.output


def test_cli_exporter_annotations_avec_donnees(tmp_path: Path) -> None:
    """Export d'une collection avec annotations : items présents dans
    le AnnotationPage, format W3C complet préservé."""
    import json
    from archives_tool.api.services.annotations import (
        FormulaireAnnotation, creer_annotation,
    )
    from archives_tool.models import Fichier, Item
    from sqlalchemy import select

    db = _base_avec_collection(tmp_path)
    # Ajout d'un Fichier + 2 annotations
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        f = Fichier(
            item_id=item.id, racine="demo",
            chemin_relatif="p.jpg", nom_fichier="p.jpg", ordre=1,
        )
        s.add(f)
        s.commit()
        creer_annotation(s, f.id, FormulaireAnnotation(
            selecteur="xywh=0,0,10,10",
            corps=[
                {"type": "TextualBody", "purpose": "tagging", "value": "Copi"},
                {"type": "SpecificResource", "purpose": "tagging",
                 "source": {"id": "https://www.wikidata.org/entity/Q733678",
                            "label": "Copi"}},
            ],
        ))
        creer_annotation(s, f.id, FormulaireAnnotation(
            selecteur="xywh=20,20,10,10",
            corps=[{"type": "TextualBody", "purpose": "tagging",
                    "value": "Forges"}],
        ))
    engine.dispose()

    sortie = tmp_path / "ann.json"
    result = runner.invoke(
        app,
        ["exporter", "annotations", "HK",
         "--db-path", str(db), "--sortie", str(sortie)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(sortie.read_text(encoding="utf-8"))
    assert payload["total"] == 2
    items = payload["first"]["items"]
    # Le pivot URI doit être préservé dans le JSON exporté
    sources = []
    for it in items:
        for b in it.get("body", []):
            if isinstance(b.get("source"), dict):
                sources.append(b["source"].get("id"))
    assert "https://www.wikidata.org/entity/Q733678" in sources
