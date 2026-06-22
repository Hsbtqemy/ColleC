"""Tests de la page Journal (traçabilité lecture seule, Lot 1 UI⁺).

Deux niveaux :
- `composer_journal` (service) : agrégation + mise en forme des 3 journaux,
  testée sans HTTP via la fixture `session`.
- routes web : rendu de `/journal`, surfaçage d'une suppression réelle,
  fonctionnement en lecture seule, présence du lien header.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.journal_web import composer_journal
from archives_tool.api.services.operations_entite import (
    journaliser_suppression_item,
)
from archives_tool.api.services.operations_push_nakala import (
    journaliser_push_fichiers,
    nouveau_batch_id,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Fichier, OperationFichier, StatutOperation


# ---------------------------------------------------------------------------
# composer_journal (service, sans HTTP)
# ---------------------------------------------------------------------------


def test_composer_journal_vide(session: Session) -> None:
    vue = composer_journal(session)
    assert vue.vide
    assert vue.suppressions == []
    assert vue.push_nakala == []
    assert vue.renommages == []


def test_composer_journal_surface_une_suppression(session: Session) -> None:
    """Une suppression d'item journalisée apparaît avec son résumé de
    cascade (le producteur réel `journaliser_suppression_item` alimente
    le `cascade_resume` que `composer_journal` désérialise)."""
    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    fonds = lire_fonds_par_cote(session, "HK")
    item = creer_item(
        session, FormulaireItem(cote="HK-1", titre="Numéro 1", fonds_id=fonds.id)
    )
    session.add(
        Fichier(
            item_id=item.id,
            racine="scans",
            chemin_relatif="a.tif",
            nom_fichier="a.tif",
            ordre=1,
            type_page="page",
        )
    )
    session.commit()

    journaliser_suppression_item(session, item, execute_par="Marie")
    session.delete(item)
    session.commit()

    vue = composer_journal(session)
    assert not vue.vide
    assert len(vue.suppressions) == 1
    s = vue.suppressions[0]
    assert s.type_entite == "item"
    assert s.cote == "HK-1"
    assert s.execute_par == "Marie"
    # cascade : 1 fichier + 1 rattachement (l'item est auto-rattaché à la miroir)
    assert "fichier" in s.resume_cascade
    assert "rattachement" in s.resume_cascade


def test_composer_journal_surface_un_push_nakala(session: Session) -> None:
    journaliser_push_fichiers(
        session,
        batch_id=nouveau_batch_id(),
        cote_item="PF-001",
        fonds_cote="PF",
        doi="10.34847/nkl.test",
        snapshot_avant=[],
        snapshot_apres=[{"sha1": "aaa", "name": "a.jpg"}],
        sha1s_uploades=["aaa"],
        sha1s_retires=[],
        execute_par="Hugo",
    )
    session.commit()

    vue = composer_journal(session)
    assert len(vue.push_nakala) == 1
    p = vue.push_nakala[0]
    assert p.cote_item == "PF-001"
    assert p.doi == "10.34847/nkl.test"
    assert p.nb_uploades == 1
    assert p.nb_retires == 0
    assert p.execute_par == "Hugo"


def test_composer_journal_agrege_un_batch_de_renommage(session: Session) -> None:
    """Deux opérations d'un même batch s'agrègent en une entrée historique
    (et `execute_le_premier` reste un datetime exploitable par temps_relatif)."""
    batch_id = nouveau_batch_id()
    for type_op in ("rename", "move"):
        session.add(
            OperationFichier(
                batch_id=batch_id,
                type_operation=type_op,
                statut=StatutOperation.REUSSIE.value,
                execute_par="Marie",
            )
        )
    session.commit()

    vue = composer_journal(session)
    assert len(vue.renommages) == 1
    assert vue.renommages[0].nb_operations == 2
    assert not vue.vide


# ---------------------------------------------------------------------------
# Routes web
# ---------------------------------------------------------------------------


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


@pytest.fixture
def base_demo_lecture_seule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    cfg = tmp_path / "config.yaml"
    cfg.write_text("utilisateur: test\nlecture_seule: true\n", encoding="utf-8")
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    return db


def _session_demo(db_path: Path) -> Session:
    return creer_session_factory(creer_engine(db_path))()


def test_page_journal_rend_les_trois_sections(base_demo: Path) -> None:
    """Exerce les 3 branches de rendu du template — suppression (via une
    suppression UI réelle) + push + renommage (seedés en base). Verrouille
    notamment la section Renommages, dont la date vient d'un `func.min`
    agrégé (datetime, sinon `temps_relatif` planterait)."""
    batch_id = nouveau_batch_id()
    with _session_demo(base_demo) as db:
        journaliser_push_fichiers(
            db,
            batch_id=nouveau_batch_id(),
            cote_item="PF-001",
            fonds_cote="PF",
            doi="10.34847/nkl.zzz",
            snapshot_avant=[],
            snapshot_apres=[{"sha1": "aaa", "name": "a.jpg"}],
            sha1s_uploades=["aaa"],
            sha1s_retires=[],
            execute_par="Hugo",
        )
        db.add(
            OperationFichier(
                batch_id=batch_id,
                type_operation="rename",
                statut=StatutOperation.REUSSIE.value,
                execute_par="Marie",
            )
        )
        db.commit()

    client = TestClient(app, follow_redirects=False)
    assert (
        client.post("/fonds/HK/supprimer", data={"confirmer": "HK"}).status_code == 303
    )

    page = client.get("/journal")
    assert page.status_code == 200
    assert "Suppressions d'entités" in page.text
    assert "Push de fichiers Nakala" in page.text
    assert "Renommages" in page.text
    assert "10.34847/nkl.zzz" in page.text
    assert batch_id[:8] in page.text


def test_page_journal_repond_et_etat_vide(base_demo: Path) -> None:
    """Sur une base sans opération journalisée, la page répond 200 et
    affiche son état vide explicite."""
    client = TestClient(app)
    r = client.get("/journal")
    assert r.status_code == 200
    assert "Journal" in r.text
    assert "Aucune opération journalisée" in r.text


def test_page_journal_surface_une_suppression_reelle(base_demo: Path) -> None:
    """Une suppression effectuée via l'UI apparaît dans le journal."""
    client = TestClient(app, follow_redirects=False)
    r = client.post("/fonds/HK/supprimer", data={"confirmer": "HK"})
    assert r.status_code == 303

    page = client.get("/journal")
    assert page.status_code == 200
    assert "Suppressions d'entités" in page.text
    assert "HK" in page.text
    assert "fonds" in page.text


def test_page_journal_accessible_en_lecture_seule(base_demo_lecture_seule: Path) -> None:
    """La page est purement consultative : elle fonctionne en lecture seule."""
    client = TestClient(app)
    r = client.get("/journal")
    assert r.status_code == 200
    assert "Journal" in r.text


def test_lien_journal_dans_header(base_demo: Path) -> None:
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/journal"' in r.text
