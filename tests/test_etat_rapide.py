"""Tests de la quick-action « changement d'état » au survol du tableau d'items.

Trois temps HTMX : GET ouvre l'éditeur (<select>, version fraîche), POST
applique l'état (journalisé + verrou optimiste), GET ?annuler reswap le
badge. Le tableau de collection expose le déclencheur ▾ hors lecture seule.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Item, ModificationItem


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


@pytest.fixture
def base_demo_lecture_seule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Base peuplée + config `lecture_seule: true` — pour vérifier que le
    POST est bloqué (423) et que le déclencheur ▾ disparaît du tableau."""
    db = tmp_path / "demo.db"
    peupler_base(db)
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "test",
                "racines": {"miniatures": str(racine)},
                "lecture_seule": True,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _lire_item(db_path: Path, cote: str) -> tuple[str, int, int]:
    """(etat_catalogage, version, id) d'un item par cote."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        it = s.scalar(select(Item).where(Item.cote == cote))
        triplet = (it.etat_catalogage, it.version, it.id)
    engine.dispose()
    return triplet


def _autre_etat(courant: str) -> str:
    """Un état valide différent du courant (pour forcer un vrai changement)."""
    return "valide" if courant != "valide" else "a_corriger"


# ---------------------------------------------------------------------------
# GET — ouverture de l'éditeur
# ---------------------------------------------------------------------------


def test_ouvrir_editeur_retourne_select_des_5_etats(base_demo: Path) -> None:
    etat, version, item_id = _lire_item(base_demo, "HK-001")
    client = TestClient(app)
    resp = client.get("/item/HK-001/etat?fonds=HK")
    assert resp.status_code == 200
    assert "<select" in resp.text
    assert 'name="valeur"' in resp.text
    # Les 5 états du workflow sont proposés.
    for code in ("brouillon", "a_verifier", "verifie", "valide", "a_corriger"):
        assert f'value="{code}"' in resp.text
    # L'état courant est pré-sélectionné.
    assert f'value="{etat}" selected' in resp.text
    # La version fraîche est embarquée pour le POST + cible de swap stable.
    assert f'"version": {version}' in resp.text
    assert f'id="etat-cell-{item_id}"' in resp.text
    assert 'hx-post="/item/HK-001/etat?fonds=HK"' in resp.text


def test_editeur_a_autofocus_et_fragment_sans_whitespace(base_demo: Path) -> None:
    """A11y : le <select> porte `autofocus` (HTMX le focalise au swap, sinon
    le focus retombe sur <body>). Et le fragment commence directement par
    `<td` — pas de nœud texte en tête (swap outerHTML d'un <td> en table)."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/etat?fonds=HK")
    assert resp.status_code == 200
    assert "autofocus" in resp.text
    assert resp.text.startswith("<td")
    assert resp.text.rstrip().endswith("</td>")


def test_annuler_retourne_le_badge_sans_select(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/item/HK-001/etat?fonds=HK&annuler=1")
    assert resp.status_code == 200
    assert "<select" not in resp.text
    # Le badge + son déclencheur ▾ (mode édition rapide toujours dispo).
    assert "data-badge-etat" in resp.text
    assert "Changer l'état" in resp.text


def test_cote_inconnue_404(base_demo: Path) -> None:
    client = TestClient(app)
    assert client.get("/item/ZZZ-999/etat?fonds=HK").status_code == 404


def test_fonds_inconnu_404(base_demo: Path) -> None:
    client = TestClient(app)
    assert client.get("/item/HK-001/etat?fonds=NOPE").status_code == 404


# ---------------------------------------------------------------------------
# POST — application de l'état
# ---------------------------------------------------------------------------


def test_changer_etat_succes_swappe_le_badge_et_persiste(base_demo: Path) -> None:
    etat, version, item_id = _lire_item(base_demo, "HK-001")
    cible = _autre_etat(etat)
    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/etat?fonds=HK",
        data={"version": str(version), "valeur": cible},
    )
    assert resp.status_code == 200
    # Réponse = la cellule badge re-rendue (pas de <select>).
    assert f'id="etat-cell-{item_id}"' in resp.text
    assert "<select" not in resp.text
    assert "data-badge-etat" in resp.text
    # Persisté + version incrémentée.
    etat_apres, version_apres, _ = _lire_item(base_demo, "HK-001")
    assert etat_apres == cible
    assert version_apres == version + 1


def test_changer_etat_journalise_modification(base_demo: Path) -> None:
    etat, version, item_id = _lire_item(base_demo, "HK-001")
    cible = _autre_etat(etat)
    client = TestClient(app)
    client.post(
        "/item/HK-001/etat?fonds=HK",
        data={"version": str(version), "valeur": cible},
    )
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        lignes = list(
            s.scalars(
                select(ModificationItem).where(
                    ModificationItem.item_id == item_id,
                    ModificationItem.champ == "etat_catalogage",
                )
            ).all()
        )
    engine.dispose()
    assert len(lignes) == 1
    assert lignes[0].valeur_avant == etat
    assert lignes[0].valeur_apres == cible


@pytest.mark.parametrize(
    "cible", ["brouillon", "a_verifier", "verifie", "valide", "a_corriger"]
)
def test_changer_vers_chaque_etat(base_demo: Path, cible: str) -> None:
    _, version, _ = _lire_item(base_demo, "HK-001")
    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/etat?fonds=HK",
        data={"version": str(version), "valeur": cible},
    )
    assert resp.status_code == 200
    etat_apres, _, _ = _lire_item(base_demo, "HK-001")
    assert etat_apres == cible


def test_etat_invalide_rejete_400_sans_persister(base_demo: Path) -> None:
    etat, version, _ = _lire_item(base_demo, "HK-001")
    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/etat?fonds=HK",
        data={"version": str(version), "valeur": "etat_bidon"},
    )
    assert resp.status_code == 400
    etat_apres, _, _ = _lire_item(base_demo, "HK-001")
    assert etat_apres == etat  # inchangé


def test_version_perimee_recharge_le_badge_sans_ecraser(base_demo: Path) -> None:
    etat, version, _ = _lire_item(base_demo, "HK-001")
    premier = _autre_etat(etat)
    second = _autre_etat(premier)
    assert premier != second
    client = TestClient(app)
    # 1er POST avec la bonne version : applique `premier`, bump version.
    r1 = client.post(
        "/item/HK-001/etat?fonds=HK",
        data={"version": str(version), "valeur": premier},
    )
    assert r1.status_code == 200
    # 2e POST avec la version PÉRIMÉE → conflit : badge rechargé, pas 409.
    r2 = client.post(
        "/item/HK-001/etat?fonds=HK",
        data={"version": str(version), "valeur": second},
    )
    assert r2.status_code == 200
    assert "rechargé" in r2.text  # note de conflit
    assert "<select" not in r2.text
    # `second` n'a PAS écrasé `premier`.
    etat_apres, _, _ = _lire_item(base_demo, "HK-001")
    assert etat_apres == premier


# ---------------------------------------------------------------------------
# Tableau de collection — présence / absence du déclencheur
# ---------------------------------------------------------------------------


def test_tableau_collection_expose_le_declencheur(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    assert "/etat?fonds=HK" in resp.text
    assert "Changer l'état" in resp.text


def test_tableau_collection_sans_declencheur_en_lecture_seule(
    base_demo_lecture_seule: Path,
) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    assert "Changer l'état" not in resp.text


def test_post_bloque_en_lecture_seule_423(base_demo_lecture_seule: Path) -> None:
    _, version, _ = _lire_item(base_demo_lecture_seule, "HK-001")
    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/etat?fonds=HK",
        data={"version": str(version), "valeur": "valide"},
    )
    assert resp.status_code == 423
