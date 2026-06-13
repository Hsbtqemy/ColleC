"""Tests du runner + registre mémoire pour le dépôt collection (D2).

Voir backlog `docs/developpeurs/backlog-nakala-collection.md`.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot_jobs import (
    EtatJobDepot,
    JobConcurrent,
    _make_progress,
    _reset_pour_tests,
    est_job_actif,
    executer_depot_collection,
    lire_etat_job,
    reserver_job,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Collection, Fichier, Item, TypeCollection


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registre() -> None:
    """Isole chaque test du registre global. ``autouse=True`` pour que
    toute défaillance d'un test n'embarque pas l'`_id_actuel` dans le
    test suivant — sinon `JobConcurrent` bidons en chaîne."""
    _reset_pour_tests()
    yield
    _reset_pour_tests()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


class _ConfigNakalaStub:
    """Stub minimal de ConfigNakala — duck-typed (le runner n'utilise
    que ces 4 attributs pour construire NakalaEcritureClient)."""

    def __init__(self, *, base_url: str = "https://apitest.nakala.fr",
                 api_key: str = "test-key") -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = 30.0
        self.verify_ssl = False


class _ClientEcritureStub:
    """Stub de NakalaEcritureClient enregistré comme cible des
    patches `_client_ecriture` du runner. Mimique la collection + dépôt
    reussi pour un parcours nominal du runner."""

    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.collections_creees: list[dict] = []
        self.depots_crees: list[dict] = []
        self.supprimes: list[str] = []
        self.ferme = False

    def uploader_fichier(self, chemin, nom=None):
        self.uploads.append(nom or Path(chemin).name)
        return {"name": nom or Path(chemin).name, "sha1": f"sha-{len(self.uploads)}"}

    def creer_collection(self, *, metas, status="private", datas=None):
        self.collections_creees.append({"metas": metas, "status": status})
        return {"payload": {"id": "10.34847/nkl.colNEW"}}

    def creer_depot(self, *, metas, files, status="pending", collections_ids=None):
        self.depots_crees.append({
            "metas": metas, "files": files, "status": status,
            "collectionsIds": collections_ids,
        })
        return {"payload": {"id": f"10.34847/nkl.dep{len(self.depots_crees)}"}}

    def supprimer_upload(self, sha1):
        self.supprimes.append(sha1)

    def fermer(self) -> None:
        self.ferme = True


def _amorcer_collection_avec_item(db_path: Path, tmp_path: Path) -> int:
    """Crée fonds + miroir + 1 item avec fichier local. Retourne
    collection.id (miroir) pour passer au runner."""
    factory = creer_session_factory(creer_engine(db_path))
    with factory() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="Armonía Somers"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="La mujer desnuda", fonds_id=f.id,
            date="1984", langue="spa", description="Roman",
            type_coar="http://purl.org/coar/resource_type/c_2f33",
            metadonnees={"createurs": ["Somers, Armonía"], "sujets": ["Lit"]},
        ))
        (tmp_path / "scans").mkdir(exist_ok=True)
        (tmp_path / "scans" / "as001.jpg").write_bytes(b"\xff\xd8\xff img")
        s.add(Fichier(
            item_id=item.id, nom_fichier="as001.jpg", racine="scans",
            chemin_relatif="as001.jpg", ordre=1,
        ))
        s.commit()
        miroir = s.scalar(
            select(Collection).where(
                Collection.cote == "AS",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        return miroir.id


# ---------------------------------------------------------------------------
# reserver_job — garde anti-concurrent
# ---------------------------------------------------------------------------


def test_reserver_job_premier_appel_renvoie_uuid_hex() -> None:
    job_id = reserver_job(fonds_cote="AS", collection_cote="AS", total=3)
    assert isinstance(job_id, str)
    assert len(job_id) == 32  # uuid4().hex = 32 chars
    assert est_job_actif() is True
    etat = lire_etat_job(job_id)
    assert etat is not None
    assert etat.fonds_cote == "AS"
    assert etat.collection_cote == "AS"
    assert etat.total == 3
    assert etat.faits == 0
    assert etat.statut == "en_cours"
    assert etat.cote_courante is None
    assert etat.fin is None


def test_reserver_job_2e_appel_concurrent_leve_JobConcurrent() -> None:
    reserver_job(fonds_cote="AS", collection_cote="AS", total=1)
    with pytest.raises(JobConcurrent) as exc:
        reserver_job(fonds_cote="HK", collection_cote="HK", total=5)
    # Le message mentionne le job actif pour faciliter le debug.
    assert "en cours" in str(exc.value).lower()


def test_reserver_job_libere_apres_succes_via_executer() -> None:
    """Après une exécution complète, le verrou est libéré : on peut
    réserver un nouveau job. Couvre le cycle réservation → exécution
    → libération automatique du `finally`."""
    job1 = reserver_job(fonds_cote="A", collection_cote="A", total=0)
    # Exécution synchrone factice : on n'a pas de vraie collection,
    # mais on peut juste manipuler le registre pour simuler la fin.
    # En production, c'est `executer_depot_collection` qui passe par le
    # finally — testé séparément.
    from archives_tool.api.services import nakala_depot_jobs

    with nakala_depot_jobs._lock:
        nakala_depot_jobs._JOBS[job1].statut = "termine"
        nakala_depot_jobs._id_actuel = None  # simule fin runner

    job2 = reserver_job(fonds_cote="B", collection_cote="B", total=1)
    assert job2 != job1


# ---------------------------------------------------------------------------
# _make_progress — hook qui alimente le registre
# ---------------------------------------------------------------------------


def test_make_progress_met_a_jour_cote_courante_et_faits() -> None:
    job_id = reserver_job(fonds_cote="AS", collection_cote="AS", total=3)
    progress = _make_progress(job_id)

    progress("AS-001", 1, 3)
    etat = lire_etat_job(job_id)
    assert etat.cote_courante == "AS-001"
    assert etat.faits == 1
    assert etat.total == 3

    progress("AS-002", 2, 3)
    etat = lire_etat_job(job_id)
    assert etat.cote_courante == "AS-002"
    assert etat.faits == 2


def test_make_progress_silencieux_si_job_inconnu() -> None:
    """Si le registre est nettoyé entre-temps (cas marginal théorique),
    le callback ne crashe pas — il ignore silencieusement."""
    progress = _make_progress("inexistant")
    progress("X", 1, 1)  # doit pas lever


# ---------------------------------------------------------------------------
# executer_depot_collection — fonction synchrone (testable directement)
# ---------------------------------------------------------------------------


def test_executer_depot_succes_marque_termine_et_libere_id_actuel(
    db_path: Path, tmp_path: Path,
) -> None:
    """Parcours nominal : 1 item, dépôt réussi.
    - statut passe à `termine`.
    - `collection_doi` et `collection_creee` sont posés.
    - `deposes` contient la cote.
    - `_id_actuel` est libéré (un nouveau job peut être réservé).
    """
    col_id = _amorcer_collection_avec_item(db_path, tmp_path)
    racines = {"scans": tmp_path / "scans"}
    job_id = reserver_job(fonds_cote="AS", collection_cote="AS", total=1)
    client = _ClientEcritureStub()

    with patch(
        "archives_tool.api.services.nakala_depot_jobs._client_ecriture",
        return_value=client,
    ):
        executer_depot_collection(
            job_id, chemin_db=db_path, collection_id=col_id,
            config_nakala=_ConfigNakalaStub(), racines=racines,
        )

    etat = lire_etat_job(job_id)
    assert etat.statut == "termine"
    assert etat.fin is not None
    assert etat.collection_creee is True
    assert etat.collection_doi == "10.34847/nkl.colNEW"
    assert etat.deposes == ["AS-001"]
    assert etat.faits == 1
    assert etat.erreur_globale is None
    # Verrou libéré : on peut réserver un nouveau job.
    assert est_job_actif() is False
    nouveau = reserver_job(fonds_cote="B", collection_cote="B", total=0)
    assert nouveau != job_id


def test_executer_depot_collection_inexistante_marque_echec(
    db_path: Path, tmp_path: Path,
) -> None:
    """Collection introuvable → statut=echec, erreur_globale posée,
    verrou libéré. Garde-fou contre une race où la collection serait
    supprimée entre la réservation et le démarrage du thread."""
    job_id = reserver_job(fonds_cote="X", collection_cote="X", total=0)

    with patch(
        "archives_tool.api.services.nakala_depot_jobs._client_ecriture",
        return_value=_ClientEcritureStub(),
    ):
        executer_depot_collection(
            job_id, chemin_db=db_path, collection_id=99999,
            config_nakala=_ConfigNakalaStub(),
            racines={"scans": tmp_path / "scans"},
        )

    etat = lire_etat_job(job_id)
    assert etat.statut == "echec"
    assert "99999" in (etat.erreur_globale or "")
    assert est_job_actif() is False


def test_executer_depot_reprise_idempotente_via_doi_pre_existant(
    db_path: Path, tmp_path: Path,
) -> None:
    """Reprise après un job tué : on pré-pose `Collection.doi_nakala`
    et `Item.doi_nakala` pour simuler le résultat partiel. Le 2e run
    via `executer_depot_collection` ne refait aucun appel client (le
    stub n'enregistre rien) mais marque l'item en `sautes`, et le
    statut passe à `termine`.

    C'est la garantie qui permet à la « Reprendre » de D4 d'être un
    simple re-launch sans état spécial."""
    col_id = _amorcer_collection_avec_item(db_path, tmp_path)
    # Pose les DOI a posteriori : simule un run précédent interrompu
    factory = creer_session_factory(creer_engine(db_path))
    with factory() as s:
        col = s.get(Collection, col_id)
        col.doi_nakala = "10.34847/nkl.colDEJA"
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        item.doi_nakala = "10.34847/nkl.itemDEJA"
        s.commit()

    job_id = reserver_job(fonds_cote="AS", collection_cote="AS", total=1)
    client = _ClientEcritureStub()
    with patch(
        "archives_tool.api.services.nakala_depot_jobs._client_ecriture",
        return_value=client,
    ):
        executer_depot_collection(
            job_id, chemin_db=db_path, collection_id=col_id,
            config_nakala=_ConfigNakalaStub(),
            racines={"scans": tmp_path / "scans"},
        )

    etat = lire_etat_job(job_id)
    assert etat.statut == "termine"
    # Aucune écriture client (reprise idempotente)
    assert client.collections_creees == []
    assert client.depots_crees == []
    assert client.uploads == []
    # L'item est en `sautes`
    assert etat.sautes == ["AS-001"]
    assert etat.deposes == []
    # collection_doi reflète celui qui existait déjà
    assert etat.collection_doi == "10.34847/nkl.colDEJA"
    assert etat.collection_creee is False
    # Hook progress a quand même tracé la progression
    assert etat.faits == 1
    assert etat.cote_courante == "AS-001"


# ---------------------------------------------------------------------------
# Lock thread-safety (smoke test)
# ---------------------------------------------------------------------------


def test_lire_etat_job_retourne_snapshot_isole_des_mutations() -> None:
    """`lire_etat_job` doit retourner un snapshot deepcopy, pas l'objet
    vivant. Sinon le caller (route HTMX every 2s qui rend un template
    avec plusieurs accès aux champs après cette lecture) pourrait voir
    un état muté entre deux accès — bug subtil de torn reads que le GIL
    ne couvre PAS (`Lock` ne protège que les blocs `with _lock:`
    explicites)."""
    from archives_tool.api.services import nakala_depot_jobs

    job_id = reserver_job(fonds_cote="AS", collection_cote="AS", total=2)
    # Capture un snapshot AVANT de muter le registre.
    snap_avant = lire_etat_job(job_id)
    assert snap_avant is not None
    assert snap_avant.statut == "en_cours"
    assert snap_avant.deposes == []
    assert snap_avant.collection_doi is None

    # Mutation directe du registre (simule un finaliseur du runner).
    with nakala_depot_jobs._lock:
        live = nakala_depot_jobs._JOBS[job_id]
        live.statut = "termine"
        live.deposes = ["AS-001", "AS-002"]
        live.collection_doi = "10.34847/nkl.fin"

    # Le snapshot capturé avant la mutation N'A PAS bouge — preuve de
    # l'isolation deepcopy. Sans le deepcopy, snap_avant et live seraient
    # le meme objet → toutes les assertions ci-dessous tomberaient.
    assert snap_avant.statut == "en_cours"
    assert snap_avant.deposes == []  # liste pas mutee non plus
    assert snap_avant.collection_doi is None

    # Un nouveau snapshot reflete maintenant le nouvel etat
    snap_apres = lire_etat_job(job_id)
    assert snap_apres.statut == "termine"
    assert snap_apres.deposes == ["AS-001", "AS-002"]
    assert snap_apres.collection_doi == "10.34847/nkl.fin"


def test_lire_etat_job_isolation_listes_avec_runner_concurrent() -> None:
    """Smoke test concurrent : un thread mute en boucle, l'autre lit en
    boucle. Sans isolation des listes (deepcopy), le reader pourrait
    voir une liste en train d'etre re-assignee par le writer →
    `len(snap.deposes)` puis `snap.deposes[i]` pourraient observer des
    longueurs differentes. Avec deepcopy, chaque snapshot est un objet
    isole."""
    from archives_tool.api.services import nakala_depot_jobs

    job_id = reserver_job(fonds_cote="AS", collection_cote="AS", total=5)
    erreurs_detectees: list[str] = []
    arret = threading.Event()

    def lire_en_boucle():
        for _ in range(200):
            if arret.is_set():
                return
            snap = lire_etat_job(job_id)
            if snap is None:
                continue
            # Test d'isolation : la longueur lue 1 fois et iteree doit
            # rester coherente meme si le writer mute live entre-temps.
            n = len(snap.deposes)
            try:
                items = list(snap.deposes)  # iteration sur le snapshot
            except Exception as exc:
                erreurs_detectees.append(f"iter: {exc}")
                continue
            if len(items) != n:
                erreurs_detectees.append(
                    f"longueur incoherente : len={n} mais list a {len(items)}"
                )

    lecteur = threading.Thread(target=lire_en_boucle)
    lecteur.start()

    # Cycle de mutations rapides du writer
    for i in range(50):
        with nakala_depot_jobs._lock:
            live = nakala_depot_jobs._JOBS[job_id]
            live.deposes = [f"AS-{j:03d}" for j in range(i % 10)]

    arret.set()
    lecteur.join(timeout=2)
    assert erreurs_detectees == [], (
        f"snapshot non isole : {erreurs_detectees[:3]}"
    )
