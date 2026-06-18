"""Smoke d'intégration **réel** de l'UI de dépôt collection (apitest).

Pilote la VRAIE route web ``/nakala/deposer-collection`` via ``TestClient``
avec les VRAIS clients Nakala (non mockés), pour valider la couche web
de bout en bout contre le bac à sable. Ferme le trou « UI de dépôt
validée en mocké uniquement ». Exclus par défaut (``-m "not integration"``).

Spécificité par rapport au push (cf. ``test_nakala_web_push_integration``) :
le dépôt est **asynchrone** — le POST réserve un job, démarre un thread
daemon et redirige vers la page de suivi. Le test :

1. POST /nakala/deposer-collection → 303 vers /suivi/{job_id} → extract job_id ;
2. POST le statut via la VRAIE route fragment HTMX ``/statut/{job_id}``
   (au moins une fois, pour valider la route) ;
3. polle ``lire_etat_job`` jusqu'à ``termine`` ou ``echec`` (timeout 120s) ;
4. assertions sur l'état final + le distant Nakala ;
5. cleanup : ``supprimer_depot`` pour chaque item déposé + ``supprimer_collection``
   (autorisés sur pending/private).

Petit lot (3 items) — sur apitest ça prend ~10-30s. ``NAKALA_ALLOW_PUBLISH``
n'a aucun effet ici : le dépôt reste ``status=pending``/``private``,
réversible.

Lancer : ``uv run pytest -m integration tests/test_nakala_web_deposer_integration.py``
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services import nakala_depot_jobs
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import (
    Base,
    Collection,
    Fichier,
    Item,
    TypeCollection,
)

pytestmark = pytest.mark.integration

CLE = os.environ.get("NAKALA_API_KEY", "01234567-89ab-cdef-0123-456789abcdef")
HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
_TYPE_LIVRE = "http://purl.org/coar/resource_type/c_2f33"

# Bornes du polling sur le job de fond. 3 items sur apitest = ~10-30s ;
# 120s laisse de la marge pour la latence réseau / les variations.
_TIMEOUT_POLL_S = 120
_INTERVALLE_POLL_S = 0.5


@pytest.fixture(autouse=True)
def reset_registre() -> None:
    """Isole chaque test du registre global des jobs."""
    nakala_depot_jobs._reset_pour_tests()
    yield
    nakala_depot_jobs._reset_pour_tests()


def _ecrire_config(chemin: Path, scans: Path) -> None:
    data = {
        "utilisateur": "smoke-depot",
        "racines": {"scans": str(scans)},
        "nakala": {"base_url": HOTE, "api_key": CLE, "timeout": 60},
    }
    chemin.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _amorcer_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _seed(db: Path, scans: Path, n_items: int = 3) -> None:
    """Fonds AS + miroir + N items, chacun avec 1 fichier local minimal."""
    scans.mkdir(exist_ok=True)
    with _session(db) as s:
        f = creer_fonds(
            s, FormulaireFonds(cote="AS", titre="Armonía Somers (smoke UI dépôt)")
        )
        for i in range(1, n_items + 1):
            nom = f"as{i:03d}.jpg"
            (scans / nom).write_bytes(b"\xff\xd8\xff smoke" + bytes([i]))
            item = creer_item(
                s,
                FormulaireItem(
                    cote=f"AS-{i:03d}",
                    titre=f"Smoke {i}",
                    fonds_id=f.id,
                    date="1984",
                    langue="spa",
                    description="Roman smoke UI",
                    type_coar=_TYPE_LIVRE,
                    metadonnees={"createurs": ["Somers, Armonía"], "sujets": ["Smoke"]},
                ),
            )
            s.add(
                Fichier(
                    item_id=item.id,
                    nom_fichier=nom,
                    racine="scans",
                    chemin_relatif=nom,
                    ordre=1,
                )
            )
        s.commit()


def _job_id_depuis_location(location: str) -> str:
    """Extrait le job_id de l'URL ``/nakala/deposer-collection/suivi/{job_id}``."""
    return location.rsplit("/", 1)[-1]


def _polling_jusqu_a_fin(job_id: str) -> nakala_depot_jobs.EtatJobDepot:
    """Attend que le job atteigne un statut terminal (``termine`` / ``echec``).

    Lit le registre via l'API publique ``lire_etat_job`` (qui renvoie une
    deepcopy thread-safe). Timeout dur à ``_TIMEOUT_POLL_S`` secondes.
    """
    debut = time.time()
    while time.time() - debut < _TIMEOUT_POLL_S:
        etat = nakala_depot_jobs.lire_etat_job(job_id)
        assert etat is not None, f"Job {job_id} disparu du registre."
        if etat.statut in ("termine", "echec"):
            return etat
        time.sleep(_INTERVALLE_POLL_S)
    pytest.fail(
        f"Job {job_id} n'a pas terminé en {_TIMEOUT_POLL_S}s "
        f"(statut={etat.statut if etat else '?'})."
    )


def _miroir_doi(db: Path) -> str | None:
    with _session(db) as s:
        miroir = s.scalar(
            select(Collection).where(
                Collection.cote == "AS",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        return miroir.doi_nakala if miroir else None


def _items_doi(db: Path) -> list[str]:
    with _session(db) as s:
        rows = s.scalars(
            select(Item.doi_nakala)
            .where(Item.doi_nakala.is_not(None))
            .order_by(Item.cote)
        )
        return list(rows)


def _supprimer_distants(doi_collection: str | None, doi_items: list[str]) -> None:
    """Cleanup best-effort des dépôts pending + collection privée.

    L'ordre est sans importance — DELETE /datas et DELETE /collections
    sont indépendants. On suit le pattern du push : avale les erreurs
    individuelles pour ne pas masquer une vraie assertion de test."""
    cli = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
    try:
        for doi in doi_items:
            try:
                cli.supprimer_depot(doi)
            except Exception:  # noqa: BLE001
                pass
        if doi_collection:
            try:
                cli.supprimer_collection(doi_collection)
            except Exception:  # noqa: BLE001
                pass
    finally:
        cli.fermer()


def test_web_deposer_collection_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke bout-en-bout : 3 items déposés via la route web, vérification
    sur apitest, cleanup."""
    cfg = tmp_path / "config.yaml"
    scans = tmp_path / "scans"
    _ecrire_config(cfg, scans)
    db = _amorcer_db(tmp_path)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    _seed(db, scans, n_items=3)

    client = TestClient(app)

    # 1. POST : réserve un job, démarre un thread daemon, redirige vers suivi.
    r = client.post(
        "/nakala/deposer-collection",
        data={"cote": "AS", "fonds": "AS"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    location = r.headers["location"]
    assert location.startswith("/nakala/deposer-collection/suivi/"), location
    job_id = _job_id_depuis_location(location)

    # 2. Au moins un appel à la route fragment HTMX pour la valider.
    #    (Le statut peut être encore "en_cours" ou déjà "termine" si très rapide.)
    r_statut = client.get(f"/nakala/deposer-collection/statut/{job_id}")
    assert r_statut.status_code == 200, r_statut.text

    doi_collection: str | None = None
    doi_items: list[str] = []
    try:
        # 3. Attend la fin du job.
        etat = _polling_jusqu_a_fin(job_id)

        # Capture les DOIs ASAP, AVANT toute assertion. Si une assertion
        # plus bas saute (statut=echec, mismatch de compteur, vérif
        # distante…), le cleanup `finally` doit pouvoir effacer ce qui a
        # déjà été créé sur apitest. Le runner peut très bien avoir
        # `collection_doi` et quelques `Item.doi_nakala` posés AVANT
        # qu'une étape ultérieure plante. Source de vérité = registre
        # mémoire (deepcopy thread-safe) + base locale.
        if etat.collection_doi:
            doi_collection = etat.collection_doi
        doi_items = _items_doi(db)

        # 4. Assertions état + base.
        assert etat.statut == "termine", (
            f"Job en {etat.statut} — erreurs : {etat.erreurs} / "
            f"erreur_globale : {etat.erreur_globale}"
        )
        assert etat.faits == 3
        assert etat.total == 3
        assert len(etat.deposes) == 3
        assert len(etat.erreurs) == 0
        assert etat.collection_creee is True
        assert etat.collection_doi is not None
        assert len(doi_items) == 3
        assert _miroir_doi(db) == doi_collection

        # 5. Vérification côté Nakala : la collection existe + liste 3 datas
        # rattachées. Deux endpoints distincts :
        # - `GET /collections/{id}` (= `lire_collection`) : métadonnées de
        #   la collection (titre, status) — PAS la liste des datas.
        # - `GET /collections/{id}/datas` (= `lister_depots_collection`) :
        #   page paginée des datas rattachées, clé `data` (sing.) pas
        #   `datas`. Avec 3 items la page 1 suffit (taille défaut = 25).
        cli = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
        try:
            assert (
                doi_collection is not None
            )  # rassure mypy après les asserts ci-dessus
            collec = cli.lire_collection(doi_collection)
            assert collec.get("status") == "private"
            page = cli.lister_depots_collection(doi_collection, page=1)
            datas = page.get("data") or []
            ids_distants = {d.get("identifier") for d in datas if d.get("identifier")}
            # Chaque DOI item posé en base doit être listé dans la collection.
            for doi_item in doi_items:
                assert doi_item in ids_distants, (
                    f"DOI {doi_item} absent de la collection {doi_collection} "
                    f"(distant : {ids_distants})"
                )
            # Chaque dépôt est bien en pending.
            for doi_item in doi_items:
                statut = cli.lire_depot(doi_item).get("status")
                assert statut == "pending", (
                    f"Dépôt {doi_item} en {statut}, attendu pending."
                )
        finally:
            cli.fermer()
    finally:
        # Filet defensif : si le polling a timeout (pytest.fail leve
        # AVANT la capture ligne ~218), `doi_collection` est encore
        # None et `doi_items` est vide — alors que le runner peut etre
        # en train de finir sur apitest. Lookup defensif :
        # - registre : `collection_doi` est pose dès que `POST /collections`
        #   réussit (cf. nakala_depot.py:346-349) ;
        # - base : chaque `Item.doi_nakala` est commité après son depot
        #   (nakala_depot.py:240) — visible même mid-run.
        # Garantit qu'on ne laisse pas de pending orphelins sur apitest
        # même en cas de timeout.
        if doi_collection is None:
            etat_final = nakala_depot_jobs.lire_etat_job(job_id)
            if etat_final is not None and etat_final.collection_doi:
                doi_collection = etat_final.collection_doi
        if not doi_items:
            doi_items = _items_doi(db)
        _supprimer_distants(doi_collection, doi_items)
