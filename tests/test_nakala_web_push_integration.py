"""Smoke d'intégration **réel** de l'UI de push (apitest).

Pilote les **vraies** routes web `/nakala/pousser` et `/nakala/publier` via
`TestClient` avec les **vrais** clients Nakala (non mockés), pour valider la
couche web de bout en bout contre le bac à sable. Ferme le trou « UI validée
en mocké uniquement ». Exclus par défaut (`-m "not integration"`).

- `test_web_pousser_item_live` : dépose (pending) → modifie le titre →
  `POST /nakala/pousser` → re-pull → titre changé. **Cleanup** (pending
  supprimable).
- `test_web_publier_item_live` : `POST /nakala/publier` → `status=published`.
  **Irréversible** → gardé derrière `NAKALA_ALLOW_PUBLISH=1` pour qu'un
  `-m integration` de routine ne mint pas un DOI publié à chaque run.

Lancer : `uv run pytest -m integration` (push) ;
`NAKALA_ALLOW_PUBLISH=1 uv run pytest -m integration -k publier` (publication).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import deposer_item
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Base, Fichier, Item

pytestmark = pytest.mark.integration

CLE = os.environ.get("NAKALA_API_KEY", "01234567-89ab-cdef-0123-456789abcdef")
HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
_TYPE_LIVRE = "http://purl.org/coar/resource_type/c_2f33"
_NKL_TITLE = "http://nakala.fr/terms#title"


def _amorcer_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _ecrire_config(chemin: Path, scans: Path) -> None:
    data = {
        "utilisateur": "smoke",
        "racines": {"scans": str(scans)},
        "nakala": {"base_url": HOTE, "api_key": CLE, "timeout": 60},
    }
    chemin.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _seed_item(db: Path, tmp_path: Path, *, titre: str) -> None:
    scans = tmp_path / "scans"
    scans.mkdir(exist_ok=True)
    (scans / "as001.jpg").write_bytes(b"\xff\xd8\xff smoke")
    with _session(db) as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="Armonía Somers"))
        item = creer_item(
            s,
            FormulaireItem(
                cote="AS-001",
                titre=titre,
                fonds_id=f.id,
                date="1984",
                langue="spa",
                description="Roman",
                type_coar=_TYPE_LIVRE,
                metadonnees={
                    "createurs": ["Somers, Armonía"],
                    "sujets": ["Literatura"],
                },
            ),
        )
        s.add(
            Fichier(
                item_id=item.id,
                nom_fichier="as001.jpg",
                racine="scans",
                chemin_relatif="as001.jpg",
                ordre=1,
            )
        )
        s.commit()


def _deposer_pending(db: Path, tmp_path: Path) -> str:
    """Dépose AS-001 sur apitest en `pending`, renvoie le DOI."""
    cli = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
    try:
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            rapport = deposer_item(
                s,
                cli,
                item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
                cree_par="smoke",
            )
        assert rapport.doi
        return rapport.doi
    finally:
        cli.fermer()


def _modifier_titre(db: Path, titre: str) -> None:
    with _session(db) as s:
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        item.titre = titre
        s.commit()


def _titres_distants(doi: str) -> list[str]:
    cli = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
    try:
        metas = cli.lire_depot(doi)["metas"]
        return [m["value"] for m in metas if m.get("propertyUri") == _NKL_TITLE]
    finally:
        cli.fermer()


def _supprimer(doi: str) -> None:
    cli = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
    try:
        cli.supprimer_depot(doi)
    except Exception:  # noqa: BLE001
        pass
    finally:
        cli.fermer()


def test_web_pousser_item_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, tmp_path / "scans")
    db = _amorcer_db(tmp_path)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    _seed_item(db, tmp_path, titre="Titre initial smoke")
    doi = _deposer_pending(db, tmp_path)
    try:
        # Le titre déposé est bien le titre initial.
        assert any("initial" in t for t in _titres_distants(doi))

        # Modif locale puis push via la VRAIE route web (clients réels).
        _modifier_titre(db, "Titre RÉVISÉ via UI")
        r = TestClient(app).post(
            "/nakala/pousser",
            data={"cote": "AS-001", "fonds": "AS"},
            follow_redirects=False,
        )
        assert r.status_code == 303, r.text
        assert "nakala_pousse=" in r.headers["location"]

        # Le distant reflète le titre poussé.
        assert any("RÉVISÉ" in t for t in _titres_distants(doi)), _titres_distants(doi)
    finally:
        _supprimer(doi)  # pending → supprimable


@pytest.mark.skipif(
    not os.environ.get("NAKALA_ALLOW_PUBLISH"),
    reason="publication irréversible — opt-in via NAKALA_ALLOW_PUBLISH=1",
)
def test_web_publier_item_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, tmp_path / "scans")
    db = _amorcer_db(tmp_path)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    _seed_item(db, tmp_path, titre="ColleC — publication smoke UI")
    doi = _deposer_pending(
        db, tmp_path
    )  # NB : publié = NON supprimable (laissé sur le bac).

    r = TestClient(app).post(
        "/nakala/publier",
        data={"cote": "AS-001", "fonds": "AS"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert "nakala_publie=1" in r.headers["location"]

    cli = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
    try:
        assert cli.lire_depot(doi).get("status") == "published"
    finally:
        cli.fermer()
