"""Tests du journal des suppressions d'entités (OperationEntite, V0.9.9).

Couvre : journalisation à la suppression (item / collection / fonds),
atomicité (journal + delete en une transaction), compteurs de cascade,
snapshot, et le listing `lister_suppressions`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from archives_tool.api.main import app as api_app
from archives_tool.api.services.collaborateurs_fonds import (
    FormulaireCollaborateurFonds,
    ajouter_collaborateur_fonds,
)
from archives_tool.api.services.collections import (
    FormulaireCollection,
    ajouter_item_a_collection,
    creer_collection_libre,
    supprimer_collection_libre,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    supprimer_fonds,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    creer_item,
    supprimer_item,
)
from archives_tool.api.services.operations_entite import lister_suppressions
from archives_tool.cli import app as cli_app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import (
    AnnotationRegion,
    Fichier,
    Fonds,
    Item,
    OperationEntite,
)


def _item_avec_fichier_annote(session: Session, fonds: Fonds, cote: str) -> Item:
    """Crée un item + 1 fichier + 1 annotation (pour tester la cascade)."""
    item = creer_item(session, FormulaireItem(cote=cote, titre="X", fonds_id=fonds.id))
    fichier = Fichier(
        item_id=item.id,
        racine="scans",
        chemin_relatif=f"HK/{cote}-001.tif",
        nom_fichier=f"{cote}-001.tif",
        ordre=1,
    )
    session.add(fichier)
    session.flush()
    session.add(
        AnnotationRegion(
            fichier_id=fichier.id,
            selecteur="xywh=0,0,10,10",
            selecteur_type="fragment",
            corps=[{"type": "TextualBody", "value": "Copi"}],
            motivation="tagging",
        )
    )
    session.commit()
    return item


def _derniere(session: Session) -> OperationEntite:
    return lister_suppressions(session, limite=1)[0]


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------


def test_supprimer_item_journalise(session: Session, fonds_hk: Fonds) -> None:
    item = _item_avec_fichier_annote(session, fonds_hk, "HK-001")
    supprimer_item(session, item.id, execute_par="Marie")

    op = _derniere(session)
    assert op.type_entite == "item"
    assert op.cote == "HK-001"
    assert op.fonds_cote == "HK"
    assert op.execute_par == "Marie"
    cascade = json.loads(op.cascade_resume)
    assert cascade["fichiers"] == 1
    assert cascade["annotations"] == 1
    assert cascade["junctions"] == 1  # la miroir


def test_supprimer_item_atomique(session: Session, fonds_hk: Fonds) -> None:
    """Le journal et la suppression committent ensemble : après l'appel,
    l'item est parti ET la ligne de journal existe."""
    item = creer_item(
        session, FormulaireItem(cote="HK-002", titre="Y", fonds_id=fonds_hk.id)
    )
    iid = item.id
    supprimer_item(session, iid)
    assert session.get(Item, iid) is None
    assert session.scalar(select(func.count(OperationEntite.id))) == 1


def test_supprimer_item_snapshot_contient_colonnes(
    session: Session, fonds_hk: Fonds
) -> None:
    item = creer_item(
        session,
        FormulaireItem(cote="HK-003", titre="Titre Z", fonds_id=fonds_hk.id),
    )
    supprimer_item(session, item.id)
    snap = json.loads(_derniere(session).snapshot_json)
    assert snap["cote"] == "HK-003"
    assert snap["titre"] == "Titre Z"
    assert "fonds_id" in snap


# ---------------------------------------------------------------------------
# Collection libre
# ---------------------------------------------------------------------------


def test_supprimer_collection_libre_journalise(
    session: Session, fonds_hk: Fonds
) -> None:
    item = creer_item(
        session, FormulaireItem(cote="HK-001", titre="X", fonds_id=fonds_hk.id)
    )
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œuvres", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)

    supprimer_collection_libre(session, libre.id, execute_par="Jean")

    op = _derniere(session)
    assert op.type_entite == "collection"
    assert op.cote == "OEUV"
    assert op.execute_par == "Jean"
    cascade = json.loads(op.cascade_resume)
    assert cascade["junctions"] == 1
    # L'item survit dans son fonds.
    assert session.get(Item, item.id) is not None


# ---------------------------------------------------------------------------
# Fonds
# ---------------------------------------------------------------------------


def test_supprimer_fonds_journalise_cascade(session: Session) -> None:
    fonds = creer_fonds(session, FormulaireFonds(cote="FA", titre="Fonds A"))
    _item_avec_fichier_annote(session, fonds, "FA-001")
    creer_item(session, FormulaireItem(cote="FA-002", titre="B", fonds_id=fonds.id))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="THEME", titre="Thème", fonds_id=fonds.id),
    )
    ajouter_collaborateur_fonds(
        session,
        fonds.id,
        FormulaireCollaborateurFonds(nom="Dupont", roles=["numerisation"]),
    )
    libre_cote = libre.cote

    supprimer_fonds(session, fonds.id, execute_par="Admin")

    op = _derniere(session)
    assert op.type_entite == "fonds"
    assert op.cote == "FA"
    assert op.execute_par == "Admin"
    cascade = json.loads(op.cascade_resume)
    assert cascade["items"] == 2
    assert cascade["fichiers"] == 1
    assert cascade["annotations"] == 1
    assert cascade["collaborateurs"] == 1
    assert cascade["collections_detachees"] == 1
    assert cascade["miroir_supprimee"] is True
    assert libre_cote in cascade["collection_detachee_cotes"]


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_lister_suppressions_filtre_et_ordre(
    session: Session, fonds_hk: Fonds
) -> None:
    i1 = creer_item(
        session, FormulaireItem(cote="HK-001", titre="A", fonds_id=fonds_hk.id)
    )
    i2 = creer_item(
        session, FormulaireItem(cote="HK-002", titre="B", fonds_id=fonds_hk.id)
    )
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds_hk.id),
    )
    supprimer_item(session, i1.id)
    supprimer_collection_libre(session, libre.id)
    supprimer_item(session, i2.id)

    toutes = lister_suppressions(session)
    assert len(toutes) == 3
    # Plus récente d'abord : le dernier delete (i2) est en tête.
    assert toutes[0].cote == "HK-002"

    items_seuls = lister_suppressions(session, type_entite="item")
    assert {o.cote for o in items_seuls} == {"HK-001", "HK-002"}
    assert all(o.type_entite == "item" for o in items_seuls)

    assert len(lister_suppressions(session, limite=1)) == 1


# ---------------------------------------------------------------------------
# Intégration route web + CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_route_web_suppression_journalise_execute_par(base_demo: Path) -> None:
    """La suppression via l'UI journalise avec l'utilisateur courant
    (renseigné depuis `get_utilisateur_courant`, jamais vide)."""
    client = TestClient(api_app)
    r = client.post(
        "/item/HK-001/supprimer?fonds=HK",
        data={"confirmer": "HK-001"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with creer_session_factory(creer_engine(base_demo))() as s:
        op = s.scalars(
            select(OperationEntite).where(OperationEntite.type_entite == "item")
        ).first()
        assert op is not None
        assert op.cote == "HK-001"
        # L'utilisateur courant est journalisé (valeur exacte dépend de
        # la config du poste ; ce qui compte est qu'elle soit captée).
        assert op.execute_par


def test_cli_supprimer_puis_montrer_suppressions(base_demo: Path) -> None:
    """CLI delete journalise avec --utilisateur, et `montrer suppressions
    --format json` le retrouve."""
    runner = CliRunner()
    r1 = runner.invoke(
        cli_app,
        [
            "items", "supprimer", "HK-001", "--fonds", "HK",
            "--yes", "--utilisateur", "CLI-User", "--db-path", str(base_demo),
        ],
    )
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(
        cli_app,
        ["montrer", "suppressions", "--db-path", str(base_demo), "--format", "json"],
    )
    assert r2.exit_code == 0, r2.output
    charge = json.loads(r2.output)
    assert any(
        o["cote"] == "HK-001" and o["execute_par"] == "CLI-User" for o in charge
    )
