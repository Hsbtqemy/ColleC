"""Tests des routes UI de dépôt collection (D3 du backlog dépôt UI).

Les routes lancent ``executer_depot_collection`` dans un Thread daemon —
pour des tests déterministes, on monkeypatche le runner par un stub qui
ne fait que marquer le job comme terminé sans toucher à Nakala. Cela
isole la logique de routing (réservation, redirect, garde concurrente,
422 absent api_key, statut HTMX) du runner lui-même (testé séparément
dans `test_nakala_depot_jobs.py`).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml
from fastapi.testclient import TestClient

import archives_tool.api.routes.nakala_web as nakala_web
from archives_tool.api.main import app
from archives_tool.api.services import nakala_depot_jobs
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.db import (
    assurer_tables_fts,
    creer_engine,
    creer_session_factory,
)
from archives_tool.models import Base, Collection, Fichier, TypeCollection
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registre() -> None:
    """Isole chaque test du registre global."""
    nakala_depot_jobs._reset_pour_tests()
    yield
    nakala_depot_jobs._reset_pour_tests()


def _ecrire_config(
    chemin: Path, *, avec_api_key: bool = True, lecture_seule: bool = False,
) -> None:
    data: dict = {"utilisateur": "testdepot", "lecture_seule": lecture_seule,
                  "racines": {"scans": str(chemin.parent / "scans")}}
    nak: dict = {"base_url": "https://apitest.nakala.fr"}
    if avec_api_key:
        nak["api_key"] = "01234567-89ab-cdef-0123-456789abcdef"
    data["nakala"] = nak
    chemin.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _amorcer_db(tmp_path: Path, *, doi_nakala: str | None = None) -> Path:
    """Base + fonds AS + miroir + 1 item AS-001 avec fichier local.

    `doi_nakala` (optionnel) : pose le DOI sur la miroir pour tester
    le cas « collection déjà déposée » (garde défensive sur GET / POST)."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    assurer_tables_fts(engine)
    factory = creer_session_factory(engine)
    (tmp_path / "scans").mkdir(exist_ok=True)
    (tmp_path / "scans" / "as001.jpg").write_bytes(b"\xff\xd8\xff img")
    with factory() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="Armonía Somers"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="La mujer desnuda", fonds_id=f.id,
            date="1984", langue="spa", description="Roman",
            type_coar="http://purl.org/coar/resource_type/c_2f33",
            metadonnees={"createurs": ["Somers, A."], "sujets": ["Lit"]},
        ))
        s.add(Fichier(
            item_id=item.id, nom_fichier="as001.jpg", racine="scans",
            chemin_relatif="as001.jpg", ordre=1,
        ))
        if doi_nakala is not None:
            miroir = s.scalar(
                select(Collection).where(
                    Collection.cote == "AS",
                    Collection.type_collection == TypeCollection.MIROIR.value,
                )
            )
            miroir.doi_nakala = doi_nakala
        s.commit()
    engine.dispose()
    return db


class _FakeWriteClient:
    """Stub minimal pour deposer_collection en mode dry_run (GET apercu).

    Le service appelle `creer_collection` seulement quand dry_run=False ;
    en GET on est dry_run=True donc ce client n'est pas réellement
    utilisé pour des appels distants. Mais l'instanciation par
    `_client_ecriture_ou_none` doit réussir → on patche
    `NakalaEcritureClient` au module nakala_web."""

    def __init__(self, base_url=None, api_key=None, **kwargs):
        pass

    def uploader_fichier(self, chemin, nom=None):
        return {"name": nom or Path(chemin).name, "sha1": "sha-1"}

    def creer_collection(self, *, metas, status="private", datas=None):
        return {"payload": {"id": "10.34847/nkl.colNEW"}}

    def creer_depot(self, *, metas, files, status="pending", collections_ids=None):
        return {"payload": {"id": "10.34847/nkl.depNEW"}}

    def supprimer_upload(self, sha1):
        pass

    def fermer(self) -> None:
        pass


def _client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
    avec_api_key: bool = True, lecture_seule: bool = False,
    doi_nakala: str | None = None,
) -> TestClient:
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, avec_api_key=avec_api_key, lecture_seule=lecture_seule)
    db = _amorcer_db(tmp_path, doi_nakala=doi_nakala)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    # Patch les clients pour éviter de toucher à api-test.nakala.fr.
    monkeypatch.setattr(nakala_web, "NakalaEcritureClient", _FakeWriteClient)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /nakala/deposer-collection — apercu dry-run
# ---------------------------------------------------------------------------


def test_get_apercu_renvoie_200_avec_rapport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET nominal : page 200 avec le rapport dry-run rendu."""
    client = _client(tmp_path, monkeypatch)
    r = client.get("/nakala/deposer-collection?cote=AS&fonds=AS")
    assert r.status_code == 200
    # Le template rend les stats (1 item à déposer + bouton confirmation)
    assert "à déposer" in r.text
    assert "AS-001" in r.text
    assert "/nakala/deposer-collection" in r.text  # form action


def test_get_apercu_sans_api_key_redirige_vers_erreur(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sans `nakala.api_key` configuré, on redirige vers le fonds avec
    un message d'erreur (le bouton ne devait pas s'afficher mais
    défense par URL directe)."""
    client = _client(tmp_path, monkeypatch, avec_api_key=False)
    r = client.get(
        "/nakala/deposer-collection?cote=AS&fonds=AS",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/fonds/AS" in r.headers["location"]
    assert "nakala_erreur" in r.headers["location"]


def test_get_apercu_collection_deja_deposee_redirige(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la miroir a déjà un DOI, on refuse (utiliser « Pousser » à la
    place). Garde défensive : le bouton ne devait pas s'afficher mais
    URL direct possible.

    DOI fixture neutre (`nkl.x1`) volontairement — un DOI qui
    contiendrait « deja » en sous-chaîne ferait passer le test par
    coïncidence même si la garde ne fonctionnait pas (passe revue D3).
    On parse l'URL pour vérifier le message décodé."""
    client = _client(tmp_path, monkeypatch, doi_nakala="10.34847/nkl.x1")
    r = client.get(
        "/nakala/deposer-collection?cote=AS&fonds=AS",
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    parsed = urlparse(location)
    assert parsed.path == "/fonds/AS"
    # parse_qs decode automatiquement l'URL encoding.
    message = parse_qs(parsed.query).get("nakala_erreur", [""])[0]
    assert "déjà déposée" in message
    # Le DOI est mentionne dans le message (pour debug)
    assert "10.34847/nkl.x1" in message


# ---------------------------------------------------------------------------
# POST /nakala/deposer-collection — lance le thread daemon
# ---------------------------------------------------------------------------


def test_post_lance_thread_et_redirige_vers_suivi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST nominal :
    - réserve un job_id ;
    - lance un thread daemon (stub mocké, retour immédiat) ;
    - redirige 303 vers /nakala/deposer-collection/suivi/<job_id>.
    """
    client = _client(tmp_path, monkeypatch)
    appels_runner: list[tuple] = []

    def stub_runner(job_id, **kwargs):
        appels_runner.append((job_id, kwargs))

    monkeypatch.setattr(nakala_web, "executer_depot_collection", stub_runner)
    r = client.post(
        "/nakala/deposer-collection",
        data={"cote": "AS", "fonds": "AS"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/nakala/deposer-collection/suivi/")
    # Le runner a été lancé (le thread daemon s'est déclenché)
    # Note : le thread peut prendre quelques ms à démarrer. On attend
    # un peu si nécessaire.
    import time
    for _ in range(20):
        if appels_runner:
            break
        time.sleep(0.05)
    assert len(appels_runner) == 1
    job_id, kwargs = appels_runner[0]
    # Le runner reçoit les bons kwargs
    assert kwargs["collection_id"] is not None
    assert kwargs["cree_par"] == "testdepot"
    assert kwargs["config_nakala"] is not None
    # Le job_id du redirect correspond au job_id passé au runner
    assert location.endswith(f"/{job_id}")


def test_post_garde_concurrente_renvoie_erreur(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si un autre job est déjà actif (`_id_actuel` posé), le POST
    redirige avec une erreur sans lancer de nouveau thread."""
    client = _client(tmp_path, monkeypatch)
    # Pose un job actif manuellement
    nakala_depot_jobs.reserver_job(
        fonds_cote="X", collection_cote="X", total=0,
    )
    # Stub le runner (au cas où — on s'attend à ce qu'il ne soit pas
    # appelé, mais évite de toucher la vraie config)
    appels = []
    monkeypatch.setattr(
        nakala_web, "executer_depot_collection",
        lambda *args, **kwargs: appels.append(args),
    )
    r = client.post(
        "/nakala/deposer-collection",
        data={"cote": "AS", "fonds": "AS"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/fonds/AS" in r.headers["location"]
    assert "nakala_erreur" in r.headers["location"]
    # Le runner n'a PAS été lancé pour le 2e job
    assert appels == []


def test_post_lecture_seule_bloque_423(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Middleware `est_lecture_seule` doit retourner 423 avant le
    handler — le job n'est pas réservé."""
    client = _client(tmp_path, monkeypatch, lecture_seule=True)
    appels = []
    monkeypatch.setattr(
        nakala_web, "executer_depot_collection",
        lambda *args, **kwargs: appels.append(args),
    )
    r = client.post(
        "/nakala/deposer-collection",
        data={"cote": "AS", "fonds": "AS"},
        follow_redirects=False,
    )
    assert r.status_code == 423
    # Aucun job lancé
    assert appels == []
    assert nakala_depot_jobs.est_job_actif() is False


def test_post_sans_api_key_redirige_avec_erreur(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sans config Nakala, on refuse au plus tôt — pas de réservation
    de job."""
    client = _client(tmp_path, monkeypatch, avec_api_key=False)
    monkeypatch.setattr(
        nakala_web, "executer_depot_collection",
        lambda *args, **kwargs: None,
    )
    r = client.post(
        "/nakala/deposer-collection",
        data={"cote": "AS", "fonds": "AS"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/fonds/AS" in r.headers["location"]
    assert nakala_depot_jobs.est_job_actif() is False


# ---------------------------------------------------------------------------
# GET /suivi/{job_id} + GET /statut/{job_id}
# ---------------------------------------------------------------------------


def test_get_suivi_rend_la_page_avec_etat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Page de suivi : rend l'état initial + le wrapper HTMX qui poll."""
    client = _client(tmp_path, monkeypatch)
    job_id = nakala_depot_jobs.reserver_job(
        fonds_cote="AS", collection_cote="AS", total=3,
    )
    r = client.get(f"/nakala/deposer-collection/suivi/{job_id}")
    assert r.status_code == 200
    # La page contient la cote de la collection + le wrapper HTMX
    assert "AS" in r.text
    assert "statut-job" in r.text
    assert f"/nakala/deposer-collection/statut/{job_id}" in r.text


def test_get_suivi_job_inconnu_redirige(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Job inexistant (uvicorn redémarré) → redirect avec message."""
    client = _client(tmp_path, monkeypatch)
    r = client.get(
        "/nakala/deposer-collection/suivi/abc123nonexistant",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/nakala" in r.headers["location"]


def test_get_statut_rend_fragment_pour_job_existant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fragment HTMX : rend le partial avec la barre + la cote courante."""
    client = _client(tmp_path, monkeypatch)
    job_id = nakala_depot_jobs.reserver_job(
        fonds_cote="AS", collection_cote="AS", total=5,
    )
    # Pose un peu de progression manuellement
    with nakala_depot_jobs._lock:
        etat = nakala_depot_jobs._JOBS[job_id]
        etat.faits = 2
        etat.cote_courante = "AS-002"

    r = client.get(f"/nakala/deposer-collection/statut/{job_id}")
    assert r.status_code == 200
    assert "2" in r.text and "5" in r.text  # 2/5
    assert "AS-002" in r.text


def test_get_statut_404_si_job_inconnu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fragment : 404 si le job n'existe pas (HTMX gère côté client)."""
    client = _client(tmp_path, monkeypatch)
    r = client.get("/nakala/deposer-collection/statut/inexistant42")
    assert r.status_code == 404


def test_bouton_deposer_present_sur_fonds_si_miroir_sans_doi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4 : sur `/fonds/AS`, le bouton « Déposer sur Nakala » apparaît
    quand la miroir n'a PAS encore de `doi_nakala`. URL pointe sur la
    route GET d'aperçu de D3."""
    client = _client(tmp_path, monkeypatch, doi_nakala=None)
    r = client.get("/fonds/AS")
    assert r.status_code == 200
    assert "Déposer sur Nakala" in r.text
    assert "/nakala/deposer-collection" in r.text


def test_bouton_deposer_absent_sur_fonds_si_miroir_a_deja_doi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le bouton est masqué si la miroir a déjà un DOI — la dichotomie
    avec Rafraîchir/Pousser/Publier qui apparaissent à la place est
    nette."""
    client = _client(tmp_path, monkeypatch, doi_nakala="10.34847/nkl.dejaPose")
    r = client.get("/fonds/AS")
    assert r.status_code == 200
    assert "Déposer sur Nakala" not in r.text
    # Les boutons de l'autre branche sont visibles
    assert "Rafraîchir depuis Nakala" in r.text
    assert "Pousser vers Nakala" in r.text


def test_bouton_deposer_absent_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """En lecture seule, le bouton n'est pas affiché — le POST serait
    bloqué 423 mais le bouton serait trompeur."""
    client = _client(
        tmp_path, monkeypatch, doi_nakala=None, lecture_seule=True,
    )
    r = client.get("/fonds/AS")
    assert r.status_code == 200
    assert "Déposer sur Nakala" not in r.text


def test_get_statut_arrete_polling_quand_termine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quand le job est terminé, le wrapper retiré le `hx-trigger` pour
    arrêter le polling HTMX every 2s — sinon le client garderait un
    cycle de requêtes pour rien."""
    client = _client(tmp_path, monkeypatch)
    job_id = nakala_depot_jobs.reserver_job(
        fonds_cote="AS", collection_cote="AS", total=1,
    )
    # Termine
    with nakala_depot_jobs._lock:
        etat = nakala_depot_jobs._JOBS[job_id]
        etat.statut = "termine"
        etat.faits = 1
        etat.deposes = ["AS-001"]
        etat.collection_doi = "10.34847/nkl.fini"

    r = client.get(f"/nakala/deposer-collection/statut/{job_id}")
    assert r.status_code == 200
    # Pas de hx-trigger (le polling s'arrête) — mais hx-get pourrait
    # rester si on a oublié le `{% if not arret %}`. Cherche absence
    # de "every 2s" comme proxy fiable.
    assert "every 2s" not in r.text
    # Et le bouton "Retour au fonds" est présent
    assert "/fonds/AS" in r.text
