"""Tests du client lecture Nakala (P1a) — httpx mocké, aucun réseau."""

from __future__ import annotations

import httpx
import pytest

from archives_tool.external.nakala.client import (
    ClientLectureNakala,
    NakalaAccesInterdit,
    NakalaAuthRefusee,
    NakalaInjoignable,
    NakalaIntrouvable,
    ErreurNakala,
)


def _client(handler) -> ClientLectureNakala:
    return ClientLectureNakala(
        "https://apitest.nakala.fr",
        api_key="cle-test",
        transport=httpx.MockTransport(handler),
    )


def test_lire_depot_succes_et_entetes() -> None:
    vus: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vus["path"] = request.url.path
        vus["apikey"] = request.headers.get("X-API-KEY", "")
        return httpx.Response(200, json={"identifier": "10.34847/nkl.abc", "metas": []})

    with _client(handler) as c:
        depot = c.lire_depot("10.34847/nkl.abc")
    assert depot["identifier"] == "10.34847/nkl.abc"
    assert vus["path"] == "/datas/10.34847/nkl.abc"
    assert vus["apikey"] == "cle-test"  # clé envoyée en en-tête


def test_redirection_non_suivie() -> None:
    """Anti-SSRF : un 3xx n'est PAS suivi (sinon la clé API partirait vers
    l'hôte de redirection) et est traité comme une erreur."""
    appels = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        appels["n"] += 1
        return httpx.Response(302, headers={"location": "https://evil.example.com/"})

    c = _client(handler)
    assert c._client.follow_redirects is False
    with c, pytest.raises(ErreurNakala):
        c.lire_depot("10.34847/nkl.abc")
    assert appels["n"] == 1  # handler appelé une seule fois (redirection non suivie)


def test_anonyme_sans_entete_cle() -> None:
    vus: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vus["apikey"] = request.headers.get("X-API-KEY", "ABSENT")
        return httpx.Response(200, json={"identifier": "x"})

    c = ClientLectureNakala(
        "https://api.nakala.fr", transport=httpx.MockTransport(handler)
    )
    with c:
        c.lire_depot("10.34847/nkl.pub")
    assert vus["apikey"] == "ABSENT"  # pas de clé → pas d'en-tête


@pytest.mark.parametrize(
    "code,exc",
    [
        (401, NakalaAuthRefusee),
        (403, NakalaAccesInterdit),
        (404, NakalaIntrouvable),
        (500, ErreurNakala),
    ],
)
def test_codes_http_vers_exceptions(code: int, exc: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"message": "boom"})

    with _client(handler) as c, pytest.raises(exc):
        c.lire_depot("10.34847/nkl.x")


def test_connexion_impossible_injoignable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with _client(handler) as c, pytest.raises(NakalaInjoignable):
        c.lire_depot("10.34847/nkl.x")


def test_validation_errors_surfacees_cote_lecture() -> None:
    """T3 : le client lecture annexe aussi `payload.validationErrors` au
    message d'erreur (helper partagé `detail_erreur_nakala`)."""
    corps = {
        "message": "invalid",
        "payload": {"validationErrors": ["The metadata X is required."]},
    }
    with _client(lambda r: httpx.Response(422, json=corps)) as c:
        with pytest.raises(ErreurNakala) as exc:
            c.lire_depot("10.34847/nkl.x")
    assert "The metadata X is required" in str(exc.value)


def test_citation_succes_chaine_json() -> None:
    """S4 : `GET /datas/{id}/citation` renvoie une chaîne JSON ; `citation()`
    la retourne et frappe le bon chemin."""
    vus: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vus["path"] = request.url.path
        return httpx.Response(
            200, json="Somers, A. (1984). Titre. Nakala. https://doi.org/10.34847/nkl.x"
        )

    with _client(handler) as c:
        cit = c.citation("10.34847/nkl.x")
    assert vus["path"] == "/datas/10.34847/nkl.x/citation"
    assert cit is not None and cit.startswith("Somers")


def test_citation_pending_non_citable() -> None:
    with _client(
        lambda r: httpx.Response(200, json="Test deposit, therefore not citable.")
    ) as c:
        assert c.citation("10.34847/nkl.x") == "Test deposit, therefore not citable."


def test_citation_corps_vide_retourne_none() -> None:
    with _client(lambda r: httpx.Response(200, text="")) as c:
        assert c.citation("10.34847/nkl.x") is None


def test_citation_404_leve() -> None:
    with _client(lambda r: httpx.Response(404, json={"message": "nope"})) as c:
        with pytest.raises(NakalaIntrouvable):
            c.citation("10.34847/nkl.x")


def test_lister_depots_scope_invalide() -> None:
    with _client(lambda r: httpx.Response(200, json={})) as c:
        with pytest.raises(ValueError):
            c.lister_depots("admin")


def test_lister_depots_poste_corps_vide() -> None:
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vus["method"] = request.method
        vus["path"] = request.url.path
        return httpx.Response(200, json={"totalRecords": 0, "data": []})

    with _client(handler) as c:
        c.lister_depots("readable")
    assert vus["method"] == "POST"  # lecture via POST (piège Nakala)
    assert vus["path"] == "/users/datas/readable"


# ---------------------------------------------------------------------------
# normaliser_identifiant_nakala (URL → DOI)
# ---------------------------------------------------------------------------


import pytest as _pytest  # noqa: E402

from archives_tool.external.nakala.client import (  # noqa: E402
    normaliser_identifiant_nakala,
)

_DOI = "10.34847/nkl.d8der2w4"


@_pytest.mark.parametrize(
    "entree",
    [
        _DOI,
        f"  {_DOI}  ",
        f"https://nakala.fr/collection/{_DOI}",
        f"https://nakala.fr/{_DOI}",
        f"https://api.nakala.fr/collections/{_DOI}",
        f"https://api.nakala.fr/datas/{_DOI}/abcdef0123",  # chemin fichier → DOI seul
        f"doi:{_DOI}",
        f"https://nakala.fr/collection/{_DOI}?page=2",
    ],
)
def test_normaliser_extrait_le_doi(entree: str) -> None:
    assert normaliser_identifiant_nakala(entree) == _DOI


def test_normaliser_conserve_la_version() -> None:
    assert normaliser_identifiant_nakala(f"https://nakala.fr/{_DOI}.v2") == f"{_DOI}.v2"


def test_normaliser_sans_doi_retourne_la_saisie() -> None:
    # Pas de motif DOI : on rend la saisie strippée (l'API fera un 404 propre).
    assert normaliser_identifiant_nakala("  pas-un-doi  ") == "pas-un-doi"
