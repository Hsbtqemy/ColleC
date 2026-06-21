"""Tests du runner + registre d'import ShareDocs en tâche de fond.

``executer_import_sharedocs`` est **synchrone** (testable sans thread) :
on l'appelle directement avec un ``ClientShareDocs`` patché sur un httpx
``MockTransport`` (aucun réseau). Couvre : déroulement nominal (job termine,
progression, Fichier créés), garde anti-concurrent, échec → statut echec +
libération de la garde.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

import archives_tool.api.services.sharedocs_jobs as sj
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.sharedocs import ClientShareDocs
from archives_tool.models import Base, Fichier

_BASE = "https://sharedocs.huma-num.fr/dav/colleC"


def _dl_handler(req: httpx.Request) -> httpx.Response:
    if req.method == "PROPFIND":
        return httpx.Response(
            207, text="<d:multistatus xmlns:d='DAV:'></d:multistatus>"
        )
    return httpx.Response(200, content=b"BYTES")


def _fabrique(handler):
    def f(base_url, user, password, **kw):
        kw.pop("transport", None)
        return ClientShareDocs(
            base_url, user, password, transport=httpx.MockTransport(handler), **kw
        )

    return f


def _amorcer(tmp_path: Path) -> tuple[Path, int, Path]:
    """DB avec fonds AS / item AS-001 + racine 'import'. Renvoie
    (chemin_db, item_id, racine_dir)."""
    db = tmp_path / "t.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    with creer_session_factory(engine)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        it = creer_item(s, FormulaireItem(cote="AS-001", titre="x", fonds_id=f.id))
        s.commit()
        item_id = it.id
    engine.dispose()
    racine = tmp_path / "import"
    racine.mkdir()
    return db, item_id, racine


@pytest.fixture(autouse=True)
def _reset():
    sj._reset_pour_tests()
    yield
    sj._reset_pour_tests()


def test_runner_nominal_cree_fichiers_et_termine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, item_id, racine = _amorcer(tmp_path)
    monkeypatch.setattr(sj, "ClientShareDocs", _fabrique(_dl_handler))
    job_id = sj.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="d",
        chemins_distants=["d/a.jpg", "d/b.jpg"],
    )
    sj.executer_import_sharedocs(
        job_id,
        chemin_db=db,
        item_id=item_id,
        chemins_distants=["d/a.jpg", "d/b.jpg"],
        racine_cible="import",
        racines={"import": racine},
        base_url=_BASE,
        user="m",
        password="s",
        importe_par="t",
    )
    etat = sj.lire_etat_job(job_id)
    assert etat.statut == "termine"
    assert etat.faits == etat.total == 2
    assert etat.retenus == 2 and etat.sautes == 0
    assert sj.est_job_actif() is False  # garde libérée
    # Fichiers créés + binaires écrits.
    with creer_session_factory(creer_engine(db))() as s:
        chemins = {f.chemin_relatif for f in s.scalars(select(Fichier)).all()}
    assert chemins == {"AS-001/a.jpg", "AS-001/b.jpg"}
    assert (racine / "AS-001" / "a.jpg").read_bytes() == b"BYTES"


def test_reserver_job_concurrent_refuse(tmp_path: Path) -> None:
    sj.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/a.jpg"],
    )
    with pytest.raises(sj.JobConcurrent):
        sj.reserver_job(
            item_cote="AS-002",
            fonds_cote="AS",
            racine="import",
            chemin_retour="",
            chemins_distants=["d/b.jpg"],
        )


def test_runner_echec_marque_statut_et_libere_garde(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une exception réseau pendant le download → statut echec + garde libérée
    (un nouveau job peut repartir)."""
    db, item_id, racine = _amorcer(tmp_path)

    def boom(req: httpx.Request) -> httpx.Response:
        if req.method == "PROPFIND":
            return httpx.Response(207, text="<d:multistatus xmlns:d='DAV:'/>")
        raise httpx.ConnectError("réseau down")

    monkeypatch.setattr(sj, "ClientShareDocs", _fabrique(boom))
    job_id = sj.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="d",
        chemins_distants=["d/a.jpg"],
    )
    sj.executer_import_sharedocs(
        job_id,
        chemin_db=db,
        item_id=item_id,
        chemins_distants=["d/a.jpg"],
        racine_cible="import",
        racines={"import": racine},
        base_url=_BASE,
        user="m",
        password="s",
    )
    etat = sj.lire_etat_job(job_id)
    # Le download échoue par fichier (succès partiel) → l'import termine avec
    # 0 retenu, pas une exception globale. La garde est libérée dans tous les cas.
    assert etat.statut == "termine"
    assert etat.retenus == 0 and etat.sautes == 1
    assert sj.est_job_actif() is False


def test_runner_item_introuvable_echec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """item_id inexistant → exception interceptée → statut echec, garde libérée."""
    db, _item_id, racine = _amorcer(tmp_path)
    monkeypatch.setattr(sj, "ClientShareDocs", _fabrique(_dl_handler))
    job_id = sj.reserver_job(
        item_cote="ZZ",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/a.jpg"],
    )
    sj.executer_import_sharedocs(
        job_id,
        chemin_db=db,
        item_id=999999,
        chemins_distants=["d/a.jpg"],
        racine_cible="import",
        racines={"import": racine},
        base_url=_BASE,
        user="m",
        password="s",
    )
    etat = sj.lire_etat_job(job_id)
    assert etat.statut == "echec"
    assert "introuvable" in (etat.erreur_globale or "")
    assert sj.est_job_actif() is False


def test_demander_annulation_pose_le_drapeau() -> None:
    job_id = sj.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/a.jpg"],
    )
    assert sj.demander_annulation(job_id) is True
    assert sj.lire_etat_job(job_id).annule is True
    assert sj.demander_annulation("inconnu") is False  # job inconnu
    # Une fois terminé, on ne peut plus annuler.
    with sj._lock:
        sj._JOBS[job_id].statut = "termine"
    assert sj.demander_annulation(job_id) is False


def test_runner_annulation_conserve_le_partiel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Annulation après le 1er fichier : statut `annule`, le fichier déjà
    téléchargé est conservé, le reste n'est pas traité."""
    db, item_id, racine = _amorcer(tmp_path)
    job_id = sj.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/a.jpg", "d/b.jpg", "d/c.jpg"],
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "PROPFIND":
            return httpx.Response(207, text="<d:multistatus xmlns:d='DAV:'/>")
        sj.demander_annulation(job_id)  # annule pendant le 1er download
        return httpx.Response(200, content=b"BYTES")

    monkeypatch.setattr(sj, "ClientShareDocs", _fabrique(handler))
    sj.executer_import_sharedocs(
        job_id,
        chemin_db=db,
        item_id=item_id,
        chemins_distants=["d/a.jpg", "d/b.jpg", "d/c.jpg"],
        racine_cible="import",
        racines={"import": racine},
        base_url=_BASE,
        user="m",
        password="s",
    )
    etat = sj.lire_etat_job(job_id)
    assert etat.statut == "annule"
    assert etat.retenus == 1  # seul a.jpg (annulé avant b.jpg)
    assert sj.est_job_actif() is False  # garde libérée → un nouvel import possible
    with creer_session_factory(creer_engine(db))() as s:
        assert len(s.scalars(select(Fichier)).all()) == 1  # partiel conservé
