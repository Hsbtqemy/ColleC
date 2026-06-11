"""Tests du client d'écriture Nakala (P2/A1) — httpx mocké, aucun réseau."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from archives_tool.external.nakala.client import (
    ErreurNakala,
    NakalaAccesInterdit,
    NakalaAuthRefusee,
    NakalaInjoignable,
)
from archives_tool.external.nakala.write_client import (
    NakalaEcritureClient,
    NakalaSoumissionInvalide,
    extraire_doi,
)


def _client(handler, *, api_key: str = "cle") -> NakalaEcritureClient:
    return NakalaEcritureClient(
        "https://apitest.nakala.fr",
        api_key=api_key,
        transport=httpx.MockTransport(handler),
    )


def test_cle_api_obligatoire() -> None:
    with pytest.raises(ValueError):
        NakalaEcritureClient("https://apitest.nakala.fr", api_key="")


def test_uploader_fichier_renvoie_sha1(tmp_path: Path) -> None:
    f = tmp_path / "scan.jpg"
    f.write_bytes(b"\xff\xd8\xff data")
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vus["path"] = request.url.path
        vus["apikey"] = request.headers.get("X-API-KEY")
        vus["ctype"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"name": "scan.jpg", "sha1": "abc123"})

    with _client(handler) as c:
        desc = c.uploader_fichier(f)
    assert desc["sha1"] == "abc123"
    assert vus["path"] == "/datas/uploads"
    assert vus["apikey"] == "cle"
    assert "multipart/form-data" in vus["ctype"]


def test_uploader_fichier_absent_du_disque(tmp_path: Path) -> None:
    with _client(lambda r: httpx.Response(200, json={})) as c:
        with pytest.raises(NakalaSoumissionInvalide):
            c.uploader_fichier(tmp_path / "inexistant.jpg")


def test_uploader_reponse_sans_sha1(tmp_path: Path) -> None:
    f = tmp_path / "x.jpg"
    f.write_bytes(b"x")
    with _client(lambda r: httpx.Response(200, json={"name": "x.jpg"})) as c:
        with pytest.raises(NakalaSoumissionInvalide):
            c.uploader_fichier(f)


def test_creer_depot_envoie_le_corps_et_renvoie_doi() -> None:
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        vus["path"] = request.url.path
        vus["body"] = json.loads(request.content)
        return httpx.Response(201, json={"payload": {"id": "10.34847/nkl.new1"}})

    metas = [{"propertyUri": "http://nakala.fr/terms#title", "value": "T"}]
    files = [{"sha1": "abc123", "name": "scan.jpg"}]
    with _client(handler) as c:
        rep = c.creer_depot(metas=metas, files=files, status="pending",
                            collections_ids=["10.34847/nkl.col1"])
    assert vus["path"] == "/datas"
    body = vus["body"]
    assert body["status"] == "pending"
    assert body["files"] == files
    assert body["metas"] == metas
    assert body["collectionsIds"] == ["10.34847/nkl.col1"]
    assert rep["payload"]["id"] == "10.34847/nkl.new1"


def test_creer_collection_envoie_status_et_metas() -> None:
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        vus["path"] = request.url.path
        vus["body"] = json.loads(request.content)
        return httpx.Response(201, json={"payload": {"id": "10.34847/nkl.colX"}})

    metas = [{"propertyUri": "http://nakala.fr/terms#title", "value": "Ma collection"}]
    with _client(handler) as c:
        rep = c.creer_collection(metas=metas, status="private",
                                 datas=["10.34847/nkl.d1"])
    assert vus["path"] == "/collections"
    assert vus["body"]["status"] == "private"
    assert vus["body"]["metas"] == metas
    assert vus["body"]["datas"] == ["10.34847/nkl.d1"]
    assert rep["payload"]["id"] == "10.34847/nkl.colX"


@pytest.mark.parametrize(
    "code,exc",
    [
        (401, NakalaAuthRefusee),
        (403, NakalaAccesInterdit),
        (422, NakalaSoumissionInvalide),
        (400, NakalaSoumissionInvalide),
        (500, ErreurNakala),
    ],
)
def test_codes_http_vers_exceptions(code: int, exc: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"message": "boom"})

    with _client(handler) as c, pytest.raises(exc):
        c.creer_depot(metas=[], files=[])


def test_injoignable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with _client(handler) as c, pytest.raises(NakalaInjoignable):
        c.creer_depot(metas=[], files=[])


def test_supprimer_depot_et_upload() -> None:
    vus: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vus.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={})

    with _client(handler) as c:
        c.supprimer_depot("10.34847/nkl.d1")
        c.supprimer_upload("abc123")
        c.supprimer_collection("10.34847/nkl.col1")
    assert vus == [
        "DELETE /datas/10.34847/nkl.d1",
        "DELETE /datas/uploads/abc123",
        "DELETE /collections/10.34847/nkl.col1",
    ]


@pytest.mark.parametrize(
    "reponse,attendu",
    [
        ({"payload": {"id": "10.34847/nkl.a"}}, "10.34847/nkl.a"),
        ({"payload": {"identifier": "10.34847/nkl.b"}}, "10.34847/nkl.b"),
        ({"identifier": "10.34847/nkl.c"}, "10.34847/nkl.c"),
        ({"id": "10.34847/nkl.d"}, "10.34847/nkl.d"),
        ({"payload": {}}, None),
        ({}, None),
    ],
)
def test_extraire_doi_variantes(reponse: dict, attendu: str | None) -> None:
    assert extraire_doi(reponse) == attendu
