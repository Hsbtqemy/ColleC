"""Tests de l'UI web ShareDocs (Chantier 1, tranches 3a + 3b) — /sharedocs.

`ClientShareDocs` patché sur un httpx `MockTransport` (la vraie validation
base_url/HTTPS/hôte reste exercée), config + DB amorcées, session RAM
réinitialisée entre tests. Couvre 3a : connexion, parcours, creds refusés,
hôte interdit, déconnexion, fil d'Ariane (+ encodage), injoignable, lecture
seule, auto-déconnexion creds invalides, XSS échappé, contrat session.
Couvre 3b : formulaire d'import, aperçu dry-run, messages d'erreur
distinctifs (aucun fichier / item introuvable / racine inconnue / non
connecté), import réel (Fichier + binaires + ajoute_par), flash succès
rendu, ré-import idempotent (nb_retenus==0), import partiel, blocage 423.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

import archives_tool.api.routes.sharedocs_web as sharedocs_web
import archives_tool.api.services.sharedocs_jobs as sharedocs_jobs
from archives_tool.api.main import app
from archives_tool.api.services import sharedocs_session
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.db import assurer_tables_fts, creer_engine, creer_session_factory
from archives_tool.external.sharedocs import ClientShareDocs
from archives_tool.models import Base, Fichier
from sqlalchemy import select


class _ThreadSync:
    """Faux threading.Thread : exécute la cible **synchroniquement** au
    `.start()`. Rend les tests d'import (tâche de fond) déterministes —
    le download mocké se termine dans la requête POST."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self) -> None:
        self._target(*self._args, **self._kwargs)


_BASE = "https://sharedocs.huma-num.fr/dav/colleC"

# Multistatus : le dossier lui-même (écarté) + un sous-dossier + un fichier.
_MS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:multistatus xmlns:d="DAV:">'
    "<d:response><d:href>/dav/colleC/</d:href><d:propstat><d:prop>"
    "<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>"
    "<d:response><d:href>/dav/colleC/Revue/</d:href><d:propstat><d:prop>"
    "<d:resourcetype><d:collection/></d:resourcetype>"
    "<d:displayname>Revue</d:displayname></d:prop></d:propstat></d:response>"
    "<d:response><d:href>/dav/colleC/notice.pdf</d:href><d:propstat><d:prop>"
    "<d:resourcetype/><d:getcontentlength>9</d:getcontentlength>"
    "<d:displayname>notice.pdf</d:displayname></d:prop></d:propstat></d:response>"
    "</d:multistatus>"
)


def _ok_handler(req: httpx.Request) -> httpx.Response:
    return httpx.Response(207, text=_MS)


def _make_fabrique(handler):
    def fabrique(base_url, user, password, **kw):
        kw.pop("transport", None)
        return ClientShareDocs(
            base_url, user, password, transport=httpx.MockTransport(handler), **kw
        )

    return fabrique


def _patch(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setattr(sharedocs_web, "ClientShareDocs", _make_fabrique(handler))


def _amorcer_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    assurer_tables_fts(engine)
    engine.dispose()
    return db


def _config(tmp_path: Path, *, lecture_seule: bool = False) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "testweb",
                "lecture_seule": lecture_seule,
                "sharedocs": {"base_url": _BASE},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return cfg


@pytest.fixture(autouse=True)
def _reset_session():
    """La session ShareDocs et le registre de jobs sont des module-globaux
    RAM → réinitialiser entre tests pour l'isolation."""
    sharedocs_session.deconnecter()
    sharedocs_jobs._reset_pour_tests()
    yield
    sharedocs_session.deconnecter()
    sharedocs_jobs._reset_pour_tests()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ARCHIVES_CONFIG", str(_config(tmp_path)))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    _patch(monkeypatch, _ok_handler)
    return TestClient(app)


# ---------------------------------------------------------------------------


def test_page_non_connecte_montre_formulaire(client: TestClient) -> None:
    r = client.get("/sharedocs")
    assert r.status_code == 200
    assert "Se connecter" in r.text
    assert _BASE in r.text  # base_url pré-remplie depuis la config


def test_connexion_valide_puis_parcourt(client: TestClient) -> None:
    r = client.post(
        "/sharedocs/connexion",
        data={"base_url": _BASE, "user": "marie", "password": "secret"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/sharedocs"
    assert sharedocs_session.est_connecte() is True
    page = client.get("/sharedocs")
    assert "Revue" in page.text and "notice.pdf" in page.text  # parcours
    assert "marie" in page.text  # état connecté affiché


def test_connexion_creds_refuses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, lambda req: httpx.Response(403))
    r = client.post(
        "/sharedocs/connexion",
        data={"base_url": _BASE, "user": "x", "password": "y"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "erreur=" in r.headers["location"]
    assert sharedocs_session.est_connecte() is False


def test_connexion_hote_interdit(client: TestClient) -> None:
    r = client.post(
        "/sharedocs/connexion",
        data={"base_url": "https://evil.example.com/dav", "user": "x", "password": "y"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "erreur=" in r.headers["location"]
    assert sharedocs_session.est_connecte() is False


def test_deconnexion(client: TestClient) -> None:
    sharedocs_session.connecter(_BASE, "marie", "secret")
    r = client.post("/sharedocs/deconnexion", follow_redirects=False)
    assert r.status_code == 303
    assert sharedocs_session.est_connecte() is False


def test_fil_ariane_sur_sous_dossier(client: TestClient) -> None:
    sharedocs_session.connecter(_BASE, "marie", "secret")
    r = client.get("/sharedocs", params={"chemin": "Revue/1974"})
    assert r.status_code == 200
    assert "Racine" in r.text
    # Segment intermédiaire = lien <a> EXACT (pas un simple préfixe).
    assert 'href="/sharedocs?chemin=Revue"' in r.text


def test_fil_ariane_encode_les_segments(client: TestClient) -> None:
    """Un segment avec espace exerce réellement l'`| urlencode` du template."""
    sharedocs_session.connecter(_BASE, "marie", "secret")
    r = client.get("/sharedocs", params={"chemin": "Revue 1974/num"})
    assert r.status_code == 200
    assert (
        "chemin=Revue%201974" in r.text or "chemin=Revue+1974" in r.text
    )  # espace encodé (jamais brut dans l'href)
    assert "chemin=Revue 1974" not in r.text


def test_parcours_injoignable_affiche_erreur(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sharedocs_session.connecter(_BASE, "marie", "secret")

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("réseau down")

    _patch(monkeypatch, boom)
    r = client.get("/sharedocs")
    assert r.status_code == 200
    assert "injoignable" in r.text.lower()


def test_lecture_seule_masque_connexion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARCHIVES_CONFIG", str(_config(tmp_path, lecture_seule=True)))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    _patch(monkeypatch, _ok_handler)
    r = TestClient(app).get("/sharedocs")
    assert r.status_code == 200
    assert "lecture seule" in r.text.lower()
    assert "Se connecter" not in r.text


def test_connexion_bloquee_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARCHIVES_CONFIG", str(_config(tmp_path, lecture_seule=True)))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    _patch(monkeypatch, _ok_handler)
    r = TestClient(app).post(
        "/sharedocs/connexion",
        data={"base_url": _BASE, "user": "marie", "password": "secret"},
        follow_redirects=False,
    )
    assert r.status_code == 423  # middleware lecture seule
    assert sharedocs_session.est_connecte() is False


def test_identifiants_invalides_pendant_parcours_auto_deconnecte(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si les identifiants deviennent invalides pendant le parcours (403),
    la session est auto-déconnectée et le formulaire réapparaît — et le mot
    de passe n'est jamais réaffiché."""
    sharedocs_session.connecter(_BASE, "marie", "secret")
    _patch(monkeypatch, lambda req: httpx.Response(403))
    r = client.get("/sharedocs")
    assert r.status_code == 200
    assert sharedocs_session.est_connecte() is False  # auto-déconnecté
    assert "Se connecter" in r.text  # formulaire réaffiché
    assert "refus" in r.text.lower()
    assert "secret" not in r.text  # mot de passe jamais réaffiché


def test_connexion_sans_section_config_sharedocs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans section `sharedocs:` en config, la base_url pré-remplie est vide,
    mais la connexion fonctionne avec une base_url saisie au formulaire."""
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump({"utilisateur": "T"}), encoding="utf-8")
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db(tmp_path)))
    _patch(monkeypatch, _ok_handler)
    cli = TestClient(app)
    assert 'value=""' in cli.get("/sharedocs").text  # base_url défaut vide
    r = cli.post(
        "/sharedocs/connexion",
        data={"base_url": _BASE, "user": "marie", "password": "secret"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert sharedocs_session.est_connecte() is True


def test_nom_distant_est_echappe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un nom d'entrée distant hostile est rendu échappé (autoescape) — pas
    de balise HTML brute injectée."""
    ms = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:">'
        "<d:response><d:href>/dav/colleC/x.jpg</d:href><d:propstat><d:prop>"
        "<d:resourcetype/><d:getcontentlength>1</d:getcontentlength>"
        "<d:displayname>&lt;img src=x onerror=alert(1)&gt;</d:displayname>"
        "</d:prop></d:propstat></d:response></d:multistatus>"
    )
    sharedocs_session.connecter(_BASE, "marie", "secret")
    _patch(monkeypatch, lambda req: httpx.Response(207, text=ms))
    r = client.get("/sharedocs")
    assert r.status_code == 200
    assert "<img src=x onerror" not in r.text  # pas de balise brute
    assert "&lt;img src=x onerror" in r.text  # échappé


def test_dossier_vide_affiche_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ms_vide = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/colleC/</d:href>'
        "<d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>"
        "</d:prop></d:propstat></d:response></d:multistatus>"
    )
    sharedocs_session.connecter(_BASE, "marie", "secret")
    _patch(monkeypatch, lambda req: httpx.Response(207, text=ms_vide))
    r = client.get("/sharedocs")
    assert "(dossier vide)" in r.text


def test_deconnexion_idempotente(client: TestClient) -> None:
    """Déconnexion alors que déjà déconnecté → 303, pas d'erreur."""
    r = client.post("/sharedocs/deconnexion", follow_redirects=False)
    assert r.status_code == 303
    assert sharedocs_session.est_connecte() is False


def test_session_etat_public_n_expose_jamais_le_password() -> None:
    """Contrat de sécurité du module : `etat_public` ne contient jamais le
    mot de passe ; `identifiants` (interne) le porte ; None après déconnexion."""
    sharedocs_session.connecter("https://sharedocs.huma-num.fr/dav", "marie", "secret")
    etat = sharedocs_session.etat_public()
    assert "password" not in etat and "secret" not in etat.values()
    assert etat == {
        "connecte": True,
        "base_url": "https://sharedocs.huma-num.fr/dav",
        "user": "marie",
    }
    assert sharedocs_session.identifiants()[2] == "secret"  # interne
    sharedocs_session.deconnecter()
    assert sharedocs_session.identifiants() is None


# ---------------------------------------------------------------------------
# Tranche 3b — sélection + cible + aperçu + import
# ---------------------------------------------------------------------------


def _dl_handler(req: httpx.Request) -> httpx.Response:
    """PROPFIND → listing ; GET (download) → octets."""
    if req.method == "PROPFIND":
        return httpx.Response(207, text=_MS)
    return httpx.Response(200, content=b"BYTES")


def _amorcer_db_item(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    assurer_tables_fts(engine)
    with creer_session_factory(engine)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        creer_item(s, FormulaireItem(cote="AS-001", titre="x", fonds_id=f.id))
        s.commit()
    engine.dispose()
    return db


@pytest.fixture
def client_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Config avec racine `import` + DB fonds AS / item AS-001 + handler
    download. Session connectée d'avance."""
    racine = tmp_path / "import"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "testweb",
                "racines": {"import": str(racine)},
                "sharedocs": {"base_url": _BASE},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db_item(tmp_path)))
    _patch(monkeypatch, _dl_handler)
    # Import en tâche de fond : le runner construit son propre client →
    # patcher aussi `sharedocs_jobs.ClientShareDocs`. Et exécuter le thread
    # de façon synchrone pour que le POST soit déterministe en test.
    monkeypatch.setattr(sharedocs_jobs, "ClientShareDocs", _make_fabrique(_dl_handler))
    monkeypatch.setattr(sharedocs_web.threading, "Thread", _ThreadSync)
    sharedocs_session.connecter(_BASE, "marie", "secret")
    return TestClient(app)


def test_page_connectee_montre_formulaire_import(client_import: TestClient) -> None:
    r = client_import.get("/sharedocs")
    assert r.status_code == 200
    assert "Importer la sélection" in r.text
    assert 'name="fichiers"' in r.text  # cases à cocher
    assert '<option value="import"' in r.text  # racine configurée dans le select


def test_apercu_importer_dry_run(client_import: TestClient) -> None:
    r = client_import.get(
        "/sharedocs/importer",
        params={
            "fonds": "AS",
            "item": "AS-001",
            "racine": "import",
            "fichiers": ["d/a.jpg", "d/b.jpg"],
        },
    )
    assert r.status_code == 200
    assert "Aperçu de l'import" in r.text
    assert "Confirmer l'import" in r.text
    assert "AS-001/a.jpg" in r.text


def test_apercu_sans_fichier_redirige_erreur(client_import: TestClient) -> None:
    r = client_import.get(
        "/sharedocs/importer",
        params={"fonds": "AS", "item": "AS-001", "racine": "import"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Aucun" in r.headers["location"]  # « Aucun fichier sélectionné »


def test_apercu_item_introuvable_redirige(client_import: TestClient) -> None:
    r = client_import.get(
        "/sharedocs/importer",
        params={
            "fonds": "AS",
            "item": "AS-999",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "introuvable" in r.headers["location"]


def test_executer_importer_cree_fichiers(
    client_import: TestClient, tmp_path: Path
) -> None:
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "AS-001",
            "racine": "import",
            "fichiers": ["d/a.jpg", "d/b.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Désormais asynchrone : redirige vers la page de suivi (le thread, rendu
    # synchrone en test, a déjà fait l'import).
    assert "/sharedocs/importer/suivi/" in r.headers["location"]
    # Fichiers créés (chemins + identité) + binaires écrits sous la racine.
    with creer_session_factory(creer_engine(tmp_path / "test.db"))() as s:
        fichiers = s.scalars(select(Fichier)).all()
        chemins = {f.chemin_relatif for f in fichiers}
        assert {f.ajoute_par for f in fichiers} == {"testweb"}  # utilisateur courant
    assert chemins == {"AS-001/a.jpg", "AS-001/b.jpg"}
    assert (tmp_path / "import" / "AS-001" / "a.jpg").read_bytes() == b"BYTES"
    assert (tmp_path / "import" / "AS-001" / "b.jpg").read_bytes() == b"BYTES"


def test_executer_importer_racine_inconnue_exit_erreur(
    client_import: TestClient,
) -> None:
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "AS-001",
            "racine": "absente",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "inconnue" in r.headers["location"]  # « Racine cible … inconnue »


def test_apercu_non_connecte_redirige(
    client_import: TestClient,
) -> None:
    sharedocs_session.deconnecter()
    r = client_import.get(
        "/sharedocs/importer",
        params={
            "fonds": "AS",
            "item": "AS-001",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "connect" in r.headers["location"]  # « Non connecté à ShareDocs »


def test_executer_importer_bloque_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    racine = tmp_path / "import"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "t",
                "lecture_seule": True,
                "racines": {"import": str(racine)},
                "sharedocs": {"base_url": _BASE},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_db_item(tmp_path)))
    _patch(monkeypatch, _dl_handler)
    sharedocs_session.connecter(_BASE, "marie", "secret")
    r = TestClient(app).post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "AS-001",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 423
    with creer_session_factory(creer_engine(tmp_path / "test.db"))() as s:
        assert s.scalars(select(Fichier)).all() == []  # rien écrit


def test_executer_importer_flash_succes_rendu(client_import: TestClient) -> None:
    """Le PRG mène à la page de suivi qui montre l'import terminé."""
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "AS-001",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Import ShareDocs en cours" in r.text  # titre page suivi
    assert "Import terminé" in r.text  # thread synchrone → déjà fini
    assert "AS-001" in r.text  # item cible affiché


def test_reimport_idempotent_aucun_retenu(client_import: TestClient) -> None:
    """Ré-importer les mêmes fichiers : aperçu → deja_en_base, rien à
    importer, bouton de confirmation absent."""
    data = {
        "fonds": "AS",
        "item": "AS-001",
        "racine": "import",
        "fichiers": ["d/a.jpg"],
    }
    client_import.post("/sharedocs/importer", data=data, follow_redirects=False)
    apercu = client_import.get("/sharedocs/importer", params=data)
    assert apercu.status_code == 200
    assert "deja_en_base" in apercu.text
    assert "Rien à importer" in apercu.text
    assert "Confirmer l'import" not in apercu.text


def test_executer_importer_partiel(
    client_import: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fichier en échec de téléchargement → succès partiel : message
    reflète retenus + sautés, seul le fichier OK est en base."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "PROPFIND":
            return httpx.Response(207, text=_MS)
        if req.url.path.endswith("b.jpg"):
            return httpx.Response(500)  # échec download → echec_telechargement
        return httpx.Response(200, content=b"BYTES")

    _patch(monkeypatch, handler)
    # Le runner (tâche de fond) construit son propre client → re-patcher la
    # fabrique côté jobs avec le handler partiel pour ce test.
    monkeypatch.setattr(sharedocs_jobs, "ClientShareDocs", _make_fabrique(handler))
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "AS-001",
            "racine": "import",
            "fichiers": ["d/a.jpg", "d/b.jpg"],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    # Page de suivi : 1 importé, 1 sauté, détail du sauté.
    assert "importé(s)" in r.text and "sauté(s)" in r.text
    assert "b.jpg" in r.text  # fichier sauté listé dans le récap
    with creer_session_factory(creer_engine(tmp_path / "test.db"))() as s:
        chemins = {f.chemin_relatif for f in s.scalars(select(Fichier)).all()}
    assert chemins == {"AS-001/a.jpg"}  # b.jpg sauté


# ---------------------------------------------------------------------------
# Polish UX : tout-sélectionner (A), cibles assistées (B), création inline (C)
# ---------------------------------------------------------------------------


def test_case_maitre_et_script_presents(client_import: TestClient) -> None:
    """(A) La liste propose « Tout sélectionner » et la page charge sharedocs.js."""
    r = client_import.get("/sharedocs")
    assert r.status_code == 200
    assert "data-sd-tout" in r.text
    assert "Tout sélectionner" in r.text
    assert "js/sharedocs.js" in r.text


def test_selects_fonds_item_avec_sentinelle(client_import: TestClient) -> None:
    """(B) Fonds et item sont des <select> des entités existantes + une option
    sentinelle « créer » ; le select fonds recharge l'item en HTMX."""
    r = client_import.get("/sharedocs")
    assert '<select id="imp-fonds" name="fonds"' in r.text
    assert '<option value="AS"' in r.text  # fonds existant
    assert '<option value="AS-001"' in r.text  # item du 1er fonds (zone initiale)
    assert 'value="__nouveau__"' in r.text  # sentinelle de création
    assert 'hx-get="/sharedocs/cible-items"' in r.text  # rechargement HTMX


def test_cible_items_partial_fonds_existant(client_import: TestClient) -> None:
    """(B) Le fragment HTMX liste les items du fonds choisi + l'option créer."""
    r = client_import.get("/sharedocs/cible-items", params={"fonds": "AS"})
    assert r.status_code == 200
    assert '<option value="AS-001"' in r.text
    assert 'value="__nouveau__"' in r.text


def test_cible_items_partial_fonds_nouveau_que_creation(
    client_import: TestClient,
) -> None:
    """(C) Pour un fonds neuf (sentinelle), aucun item existant : seule la
    création est proposée, le champ cote du nouvel item est visible."""
    r = client_import.get("/sharedocs/cible-items", params={"fonds": "__nouveau__"})
    assert r.status_code == 200
    assert '<option value="AS-001"' not in r.text  # pas d'items d'un autre fonds
    assert 'name="nouveau_item_cote"' in r.text
    assert "selected" in r.text  # option « créer » présélectionnée


def test_apercu_nouvelle_cible_ne_cree_rien(
    client_import: TestClient, tmp_path: Path
) -> None:
    """(C) L'aperçu d'une cible neuve signale « sera créé » et n'écrit RIEN."""
    r = client_import.get(
        "/sharedocs/importer",
        params={
            "fonds": "__nouveau__",
            "nouveau_fonds_cote": "NF",
            "nouveau_fonds_titre": "Nouveau fonds",
            "item": "__nouveau__",
            "nouveau_item_cote": "NF-001",
            "nouveau_item_titre": "Premier",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
    )
    assert r.status_code == 200
    assert "sera créé" in r.text
    assert "NF-001/a.jpg" in r.text  # plan calculé sur la cote neuve
    # Aucune écriture : seul le fonds AS d'amorçage existe.
    from archives_tool.models import Fonds, Item

    with creer_session_factory(creer_engine(tmp_path / "test.db"))() as s:
        assert {f.cote for f in s.scalars(select(Fonds)).all()} == {"AS"}
        assert {i.cote for i in s.scalars(select(Item)).all()} == {"AS-001"}


def test_executer_cree_fonds_et_item_puis_importe(
    client_import: TestClient, tmp_path: Path
) -> None:
    """(C) La confirmation crée le fonds (+ miroir) et l'item neufs, puis
    importe les fichiers vers le nouvel item."""
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "__nouveau__",
            "nouveau_fonds_cote": "NF",
            "nouveau_fonds_titre": "Nouveau fonds",
            "item": "__nouveau__",
            "nouveau_item_cote": "NF-001",
            "nouveau_item_titre": "Premier",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    # Page de suivi : bannière de création + import terminé.
    assert "NF-001" in r.text and "créé" in r.text
    assert "Import terminé" in r.text
    from archives_tool.models import Fonds, Item

    with creer_session_factory(creer_engine(tmp_path / "test.db"))() as s:
        assert "NF" in {f.cote for f in s.scalars(select(Fonds)).all()}
        item = s.scalars(select(Item).where(Item.cote == "NF-001")).one()
        assert item.titre == "Premier"
    assert (tmp_path / "import" / "NF-001" / "a.jpg").read_bytes() == b"BYTES"


def test_executer_fonds_existant_nouvel_item(
    client_import: TestClient, tmp_path: Path
) -> None:
    """(C) Fonds existant + nouvel item : seul l'item est créé (dans le fonds)
    et l'import s'y rattache (pas de nouveau fonds)."""
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "__nouveau__",
            "nouveau_item_cote": "AS-002",
            "nouveau_item_titre": "Deux",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    # Page de suivi : item AS-002 créé, import terminé (pas de nouveau fonds).
    assert "AS-002" in r.text and "créé" in r.text
    assert "Import terminé" in r.text
    from archives_tool.models import Item

    with creer_session_factory(creer_engine(tmp_path / "test.db"))() as s:
        assert {i.cote for i in s.scalars(select(Item)).all()} == {"AS-001", "AS-002"}


def test_executer_nouvel_item_sans_titre_redirige(client_import: TestClient) -> None:
    """(C) La création d'item exige un titre : sans titre → erreur, pas d'import."""
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "__nouveau__",
            "nouveau_item_cote": "AS-003",
            "nouveau_item_titre": "",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "erreur=" in r.headers["location"]


def test_apercu_nouvel_item_cote_manquante_redirige(client_import: TestClient) -> None:
    """(C) Sentinelle « créer item » sans cote saisie → erreur explicite."""
    r = client_import.get(
        "/sharedocs/importer",
        params={
            "fonds": "AS",
            "item": "__nouveau__",
            "nouveau_item_cote": "",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "manquante" in r.headers["location"]


# ---------------------------------------------------------------------------
# Import en tâche de fond : suivi + statut + concurrence
# ---------------------------------------------------------------------------


def test_import_lance_redirige_vers_suivi(client_import: TestClient) -> None:
    """Le POST réserve un job et redirige vers la page de suivi."""
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "AS-001",
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/sharedocs/importer/suivi/")
    job_id = loc.rsplit("/", 1)[-1]
    assert sharedocs_jobs.lire_etat_job(job_id) is not None


def test_suivi_page_rend_pour_job(client_import: TestClient) -> None:
    job_id = sharedocs_jobs.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="d",
        chemins_distants=["d/a.jpg", "d/b.jpg"],
    )
    r = client_import.get(f"/sharedocs/importer/suivi/{job_id}")
    assert r.status_code == 200
    assert "Import ShareDocs en cours" in r.text
    assert "AS-001" in r.text
    assert "0 / 2" in r.text  # barre initiale


def test_suivi_job_inconnu_redirige(client_import: TestClient) -> None:
    r = client_import.get(
        "/sharedocs/importer/suivi/inexistant", follow_redirects=False
    )
    assert r.status_code == 303
    assert "introuvable" in r.headers["location"]


def test_statut_en_cours_a_le_polling(client_import: TestClient) -> None:
    job_id = sharedocs_jobs.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/a.jpg"],
    )
    r = client_import.get(f"/sharedocs/importer/statut/{job_id}")
    assert r.status_code == 200
    assert 'hx-trigger="every 2s"' in r.text  # polling actif
    assert "sd-barre-active" in r.text  # indicateur visuel « en cours »


def test_statut_termine_arrete_le_polling(client_import: TestClient) -> None:
    job_id = sharedocs_jobs.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/a.jpg"],
    )
    with sharedocs_jobs._lock:
        sharedocs_jobs._JOBS[job_id].statut = "termine"
    r = client_import.get(f"/sharedocs/importer/statut/{job_id}")
    assert r.status_code == 200
    assert "hx-trigger" not in r.text  # polling arrêté
    assert "sd-barre-active" not in r.text  # plus d'animation quand terminé
    assert "Import terminé" in r.text


def test_statut_job_inconnu_404(client_import: TestClient) -> None:
    r = client_import.get("/sharedocs/importer/statut/inexistant")
    assert r.status_code == 404


def test_statut_en_cours_montre_bouton_annuler(client_import: TestClient) -> None:
    job_id = sharedocs_jobs.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/a.jpg"],
    )
    r = client_import.get(f"/sharedocs/importer/statut/{job_id}")
    assert r.status_code == 200
    assert f"/sharedocs/importer/annuler/{job_id}" in r.text
    assert "Annuler l'import" in r.text


def test_annuler_pose_drapeau_et_redirige(client_import: TestClient) -> None:
    job_id = sharedocs_jobs.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="d",
        chemins_distants=["d/a.jpg"],
    )
    r = client_import.post(
        f"/sharedocs/importer/annuler/{job_id}", follow_redirects=False
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/sharedocs/importer/suivi/{job_id}"
    assert sharedocs_jobs.lire_etat_job(job_id).annule is True


def test_statut_annule_arrete_polling_et_affiche(client_import: TestClient) -> None:
    job_id = sharedocs_jobs.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/a.jpg"],
    )
    with sharedocs_jobs._lock:
        sharedocs_jobs._JOBS[job_id].statut = "annule"
    r = client_import.get(f"/sharedocs/importer/statut/{job_id}")
    assert r.status_code == 200
    assert "hx-trigger" not in r.text  # polling arrêté
    assert "sd-barre-active" not in r.text  # plus d'animation
    assert "Import annulé" in r.text
    assert "Reprendre" in r.text  # reprise possible


def test_annuler_job_inconnu_redirige_sans_erreur(client_import: TestClient) -> None:
    r = client_import.post(
        "/sharedocs/importer/annuler/inexistant", follow_redirects=False
    )
    assert r.status_code == 303  # idempotent : pas d'erreur si déjà fini/inconnu


def test_import_concurrent_refuse(client_import: TestClient) -> None:
    """Un 2ᵉ import alors qu'un job tourne déjà → refus (JobConcurrent)."""
    # Simule un job en cours (sans le lancer → la garde reste posée).
    sharedocs_jobs.reserver_job(
        item_cote="AS-001",
        fonds_cote="AS",
        racine="import",
        chemin_retour="",
        chemins_distants=["d/z.jpg"],
    )
    r = client_import.post(
        "/sharedocs/importer",
        data={
            "fonds": "AS",
            "item": "AS-001",  # item existant → pas de création parasite
            "racine": "import",
            "fichiers": ["d/a.jpg"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "en+cours" in r.headers["location"] or "en%20cours" in r.headers["location"]
