"""Tests de `archives-tool montrer` (V0.9.0-gamma.4.1)."""

from __future__ import annotations

import json
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
from archives_tool.models import Base, Fichier, Item, ItemCollection
from sqlalchemy import select as sa_select

runner = CliRunner()


def _base_demo_petite(tmp_path: Path) -> Path:
    """Base avec 2 fonds + items + 1 libre + 1 transversale + 2 fichiers
    sur HK-001. Suffisant pour couvrir les 4 sous-commandes."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        creer_fonds(s, FormulaireFonds(cote="FA", titre="Fonds Aínsa"))
        fonds_hk = lire_fonds_par_cote(s, "HK")
        fonds_fa = lire_fonds_par_cote(s, "FA")
        item_hk1 = creer_item(
            s,
            FormulaireItem(
                cote="HK-001",
                titre="Numéro 1",
                fonds_id=fonds_hk.id,
                date="1969-09",
                annee=1969,
                metadonnees={"auteurs": ["Cavanna"], "thematiques": ["satire"]},
            ),
        )
        creer_item(
            s,
            FormulaireItem(cote="HK-002", titre="Numéro 2", fonds_id=fonds_hk.id),
        )
        creer_item(
            s,
            FormulaireItem(cote="FA-001", titre="Manuscrit 1", fonds_id=fonds_fa.id),
        )
        creer_collection_libre(
            s,
            FormulaireCollection(
                cote="FA-OEUVRES",
                titre="Œuvres",
                fonds_id=fonds_fa.id,
            ),
        )
        creer_collection_libre(
            s,
            FormulaireCollection(
                cote="TRANSV", titre="Transversale", fonds_id=None
            ),
        )
        s.add_all(
            [
                Fichier(
                    item_id=item_hk1.id,
                    racine="s",
                    chemin_relatif="HK-001/01.tif",
                    nom_fichier="01.tif",
                    ordre=1,
                    taille_octets=1_000_000,
                    largeur_px=3000,
                    hauteur_px=4000,
                    format="tif",
                ),
                Fichier(
                    item_id=item_hk1.id,
                    racine="s",
                    chemin_relatif="HK-001/02.tif",
                    nom_fichier="02.tif",
                    ordre=2,
                    format="tif",
                ),
            ]
        )
        # Lier HK-001 et FA-001 à la transversale.
        from archives_tool.api.services.collections import lire_collection_par_cote

        transv = lire_collection_par_cote(s, "TRANSV")
        item_fa1 = s.scalar(
            sa_select(Item).where(Item.cote == "FA-001", Item.fonds_id == fonds_fa.id)
        )
        s.add_all(
            [
                ItemCollection(item_id=item_hk1.id, collection_id=transv.id),
                ItemCollection(item_id=item_fa1.id, collection_id=transv.id),
            ]
        )
        s.commit()
    engine.dispose()
    return db


# ---------------------------------------------------------------------------
# montrer fonds
# ---------------------------------------------------------------------------


def test_montrer_fonds_liste(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(app, ["montrer", "fonds", "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    assert "HK" in result.output
    assert "FA" in result.output
    assert "Fonds (2)" in result.output


def test_montrer_fonds_liste_json(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app, ["montrer", "fonds", "--format", "json", "--db-path", str(db)]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["type"] == "fonds_liste"
    assert len(data["fonds"]) == 2


def test_montrer_fonds_detail(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app, ["montrer", "fonds", "--cote", "HK", "--db-path", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "Hara-Kiri" in result.output
    # Le détail mentionne la collection miroir + items récents.
    assert "miroir" in result.output.lower()


def test_montrer_fonds_detail_json(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "montrer", "fonds",
            "--cote", "HK",
            "--format", "json",
            "--db-path", str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["type"] == "fonds_detail"
    assert data["fonds"]["cote"] == "HK"
    assert data["fonds"]["nb_items"] == 2


def test_montrer_fonds_inexistant(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app, ["montrer", "fonds", "--cote", "INEXISTANT", "--db-path", str(db)]
    )
    assert result.exit_code == 1
    assert "introuvable" in result.output.lower()


# ---------------------------------------------------------------------------
# montrer collection
# ---------------------------------------------------------------------------


def test_montrer_collection_liste(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(app, ["montrer", "collection", "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    # 2 miroirs (HK, FA) + 1 libre (FA-OEUVRES) + 1 transversale = 4.
    assert "FA-OEUVRES" in result.output
    assert "TRANSV" in result.output
    assert "transversale" in result.output.lower()


def test_montrer_collection_liste_filtre_par_fonds(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app,
        ["montrer", "collection", "--fonds", "FA", "--db-path", str(db)],
    )
    assert result.exit_code == 0, result.output
    assert "FA-OEUVRES" in result.output
    assert "TRANSV" not in result.output  # transversale exclue


def test_montrer_collection_detail_libre(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "montrer", "collection",
            "--cote", "FA-OEUVRES",
            "--fonds", "FA",
            "--db-path", str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Œuvres" in result.output
    assert "Fonds Aínsa" in result.output  # fonds parent visible


def test_montrer_collection_detail_transversale(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app,
        ["montrer", "collection", "--cote", "TRANSV", "--db-path", str(db)],
    )
    assert result.exit_code == 0, result.output
    assert "transversale" in result.output.lower()
    # Les 2 fonds représentés sont listés.
    assert "HK" in result.output
    assert "FA" in result.output


def test_montrer_collection_detail_json_transversale(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "montrer", "collection",
            "--cote", "TRANSV",
            "--format", "json",
            "--db-path", str(db),
        ],
    )
    data = json.loads(result.output)
    assert data["type"] == "collection_detail"
    assert data["collection"]["est_transversale"] is True
    cotes_fonds = {f["cote"] for f in data["collection"]["fonds_representes"]}
    assert cotes_fonds == {"HK", "FA"}


# ---------------------------------------------------------------------------
# montrer item
# ---------------------------------------------------------------------------


def test_montrer_item_detail(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "montrer", "item",
            "HK-001",
            "--fonds", "HK",
            "--db-path", str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "HK-001" in result.output
    assert "Numéro 1" in result.output
    # Métadonnées custom affichées.
    assert "Cavanna" in result.output
    # Les 2 fichiers sont listés.
    assert "01.tif" in result.output
    assert "02.tif" in result.output


def test_montrer_item_sans_fonds_422(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app, ["montrer", "item", "HK-001", "--db-path", str(db)]
    )
    # `--fonds` requis (Typer renvoie 2 si argument requis manquant).
    assert result.exit_code == 2


def test_montrer_item_inexistant(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "montrer", "item",
            "INEXISTANT",
            "--fonds", "HK",
            "--db-path", str(db),
        ],
    )
    assert result.exit_code == 1
    assert "introuvable" in result.output.lower()


def test_montrer_item_format_json(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "montrer", "item",
            "HK-001",
            "--fonds", "HK",
            "--format", "json",
            "--db-path", str(db),
        ],
    )
    data = json.loads(result.output)
    assert data["type"] == "item_detail"
    assert data["item"]["cote"] == "HK-001"
    assert len(data["item"]["fichiers"]) == 2
    assert data["item"]["metadonnees"]["auteurs"] == ["Cavanna"]


# ---------------------------------------------------------------------------
# montrer fichier
# ---------------------------------------------------------------------------


def test_montrer_fichier_detail(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    # Récupère l'id du premier fichier en DB.
    factory = creer_session_factory(creer_engine(db))
    with factory() as s:
        fichier_id = s.scalar(sa_select(Fichier.id).order_by(Fichier.id).limit(1))

    result = runner.invoke(
        app,
        ["montrer", "fichier", str(fichier_id), "--db-path", str(db)],
    )
    assert result.exit_code == 0, result.output
    assert "01.tif" in result.output
    assert "HK-001" in result.output  # contexte item
    assert "Hara-Kiri" in result.output  # contexte fonds


def test_montrer_fichier_inexistant(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    result = runner.invoke(
        app, ["montrer", "fichier", "9999999", "--db-path", str(db)]
    )
    assert result.exit_code == 1
    assert "introuvable" in result.output.lower()


def test_montrer_fichier_format_json(tmp_path: Path) -> None:
    db = _base_demo_petite(tmp_path)
    factory = creer_session_factory(creer_engine(db))
    with factory() as s:
        fichier_id = s.scalar(sa_select(Fichier.id).order_by(Fichier.id).limit(1))

    result = runner.invoke(
        app,
        [
            "montrer", "fichier", str(fichier_id),
            "--format", "json",
            "--db-path", str(db),
        ],
    )
    data = json.loads(result.output)
    assert data["type"] == "fichier_detail"
    assert data["fichier"]["nom_fichier"] == "01.tif"
    assert data["fichier"]["item"]["cote"] == "HK-001"
