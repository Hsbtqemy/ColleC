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
