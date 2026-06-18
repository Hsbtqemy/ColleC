"""Tests de l'UI web ShareDocs (Chantier 1, tranche 3a) — page /sharedocs.

`ClientShareDocs` patché sur un httpx `MockTransport` (la vraie validation
base_url/HTTPS/hôte reste exercée), config + DB amorcées, session RAM
réinitialisée entre tests. Couvre : formulaire de connexion, connexion
validée → parcours, creds refusés, hôte interdit, déconnexion, fil d'Ariane,
parcours injoignable, lecture seule (formulaire masqué + POST bloqué 423).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

import archives_tool.api.routes.sharedocs_web as sharedocs_web
from archives_tool.api.main import app
from archives_tool.api.services import sharedocs_session
from archives_tool.db import assurer_tables_fts, creer_engine
from archives_tool.external.sharedocs import ClientShareDocs
from archives_tool.models import Base

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
    """La session ShareDocs est un module-global RAM → réinitialiser entre
    tests pour l'isolation."""
    sharedocs_session.deconnecter()
    yield
    sharedocs_session.deconnecter()


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
