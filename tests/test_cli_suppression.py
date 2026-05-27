"""Tests des commandes `archives-tool fonds supprimer` et
`archives-tool items supprimer` (V0.9.7)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fichier, Fonds, Item

runner = CliRunner()


def _base_avec_hk_items(tmp_path: Path) -> Path:
    """DB avec un fonds HK contenant 2 items + 3 fichiers chacun."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        for i in range(1, 3):
            item = creer_item(
                s,
                FormulaireItem(
                    cote=f"HK-{i:03d}",
                    titre=f"Numéro {i}",
                    fonds_id=hk.id,
                ),
            )
            for j in range(1, 4):
                s.add(
                    Fichier(
                        item_id=item.id,
                        racine="scans",
                        chemin_relatif=f"hk/{item.cote}-{j:02d}.tif",
                        nom_fichier=f"{item.cote}-{j:02d}.tif",
                        ordre=j,
                    )
                )
        s.commit()
    engine.dispose()
    return db


# ---------------------------------------------------------------------------
# fonds supprimer
# ---------------------------------------------------------------------------


def test_fonds_supprimer_happy_path(tmp_path: Path) -> None:
    db = _base_avec_hk_items(tmp_path)
    result = runner.invoke(
        app, ["fonds", "supprimer", "HK", "--yes", "--db-path", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "supprimé" in result.output

    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        assert s.scalar(select(Fonds).where(Fonds.cote == "HK")) is None
        # Cascade : items + fichiers partis avec le fonds.
        assert s.scalars(select(Item)).all() == []
        assert s.scalars(select(Fichier)).all() == []


def test_fonds_supprimer_inconnu(tmp_path: Path) -> None:
    db = _base_avec_hk_items(tmp_path)
    result = runner.invoke(
        app, ["fonds", "supprimer", "INEXISTANT", "--yes", "--db-path", str(db)]
    )
    assert result.exit_code == 1
    assert "introuvable" in result.output.lower() or "Erreur" in result.output


def test_fonds_supprimer_refuse_sans_yes(tmp_path: Path) -> None:
    """Sans --yes, Typer demande confirmation ; on envoie « n »
    via stdin → l'opération doit abandonner."""
    db = _base_avec_hk_items(tmp_path)
    result = runner.invoke(
        app, ["fonds", "supprimer", "HK", "--db-path", str(db)], input="n\n"
    )
    assert result.exit_code != 0  # Abort
    # Fonds toujours là
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        assert s.scalar(select(Fonds).where(Fonds.cote == "HK")) is not None


# ---------------------------------------------------------------------------
# items supprimer
# ---------------------------------------------------------------------------


def test_items_supprimer_happy_path(tmp_path: Path) -> None:
    db = _base_avec_hk_items(tmp_path)
    result = runner.invoke(
        app,
        [
            "items",
            "supprimer",
            "HK-001",
            "--fonds",
            "HK",
            "--yes",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "supprimé" in result.output

    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        # Item HK-001 parti, ses 3 fichiers cascadés.
        assert (
            s.scalar(
                select(Item)
                .join(Fonds)
                .where(Fonds.cote == "HK", Item.cote == "HK-001")
            )
            is None
        )
        # HK-002 toujours là avec ses 3 fichiers.
        hk = lire_fonds_par_cote(s, "HK")
        autres = s.scalars(select(Item).where(Item.fonds_id == hk.id)).all()
        assert len(autres) == 1
        assert autres[0].cote == "HK-002"
        assert len(autres[0].fichiers) == 3


def test_items_supprimer_inconnu(tmp_path: Path) -> None:
    db = _base_avec_hk_items(tmp_path)
    result = runner.invoke(
        app,
        [
            "items",
            "supprimer",
            "HK-999",
            "--fonds",
            "HK",
            "--yes",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1


def test_items_supprimer_fonds_inconnu(tmp_path: Path) -> None:
    db = _base_avec_hk_items(tmp_path)
    result = runner.invoke(
        app,
        [
            "items",
            "supprimer",
            "HK-001",
            "--fonds",
            "ZZ",
            "--yes",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1
