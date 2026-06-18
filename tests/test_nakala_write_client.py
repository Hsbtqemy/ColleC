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
        rep = c.creer_depot(
            metas=metas,
            files=files,
            status="pending",
            collections_ids=["10.34847/nkl.col1"],
        )
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
        rep = c.creer_collection(
            metas=metas, status="private", datas=["10.34847/nkl.d1"]
        )
    assert vus["path"] == "/collections"
    assert vus["body"]["status"] == "private"
    assert vus["body"]["metas"] == metas
    assert vus["body"]["datas"] == ["10.34847/nkl.d1"]
    assert rep["payload"]["id"] == "10.34847/nkl.colX"


def test_ajouter_fichier_post_sur_files_avec_sha1() -> None:
    """`ajouter_fichier` POST /datas/{id}/files avec un corps {sha1}
    (+ description/embargo optionnels), additif."""
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        vus["method"] = request.method
        vus["path"] = request.url.path
        vus["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 200, "message": "File added"})

    with _client(handler) as c:
        c.ajouter_fichier(
            "10.34847/nkl.d1",
            "abc123sha",
            description="scan recto",
        )
    assert vus["method"] == "POST"
    assert vus["path"] == "/datas/10.34847/nkl.d1/files"
    assert vus["body"] == {"sha1": "abc123sha", "description": "scan recto"}


def test_ajouter_fichier_corps_minimal_sha1_seul() -> None:
    """Sans description/embargo, le corps ne porte que sha1 (le name vient
    de l'upload côté Nakala)."""
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        vus["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": "File added"})

    with _client(handler) as c:
        c.ajouter_fichier("10.34847/nkl.d1", "deadbeef")
    assert vus["body"] == {"sha1": "deadbeef"}


def test_ajouter_fichier_500_leve_erreur() -> None:
    """sha1 fantôme / déjà présent → 500 côté Nakala → ErreurNakala
    (l'appelant valide en amont ; la méthode ne masque pas l'échec)."""
    with _client(
        lambda r: httpx.Response(
            500, json={"code": 500, "message": "File not found on server"}
        )
    ) as c:
        with pytest.raises(ErreurNakala):
            c.ajouter_fichier("10.34847/nkl.d1", "fantome")


def test_supprimer_fichier_donnee_delete_par_sha1() -> None:
    """`supprimer_fichier_donnee` DELETE /datas/{id}/files/{sha1} (le
    fileIdentifier de l'API EST le sha1)."""
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vus["method"] = request.method
        vus["path"] = request.url.path
        return httpx.Response(204)

    with _client(handler) as c:
        c.supprimer_fichier_donnee("10.34847/nkl.d1", "abc123sha")
    assert vus["method"] == "DELETE"
    assert vus["path"] == "/datas/10.34847/nkl.d1/files/abc123sha"


def test_supprimer_fichier_donnee_403_dernier_fichier() -> None:
    """Retirer le dernier fichier → 403 → NakalaAccesInterdit (un dépôt ne
    peut pas être vidé de tous ses fichiers)."""
    with _client(lambda r: httpx.Response(403, json={"message": "forbidden"})) as c:
        with pytest.raises(NakalaAccesInterdit):
            c.supprimer_fichier_donnee("10.34847/nkl.d1", "dernier")


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


def test_modifier_depot_put_metas() -> None:
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        vus["method"] = request.method
        vus["path"] = request.url.path
        vus["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    metas = [{"propertyUri": "http://nakala.fr/terms#title", "value": "Nouveau"}]
    with _client(handler) as c:
        c.modifier_depot("10.34847/nkl.d1", metas=metas)
    assert vus["method"] == "PUT"
    assert vus["path"] == "/datas/10.34847/nkl.d1"
    assert vus["body"] == {"metas": metas}


def test_modifier_depot_avec_status_publie() -> None:
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        vus["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"")  # corps vide toléré

    metas = [{"propertyUri": "http://nakala.fr/terms#title", "value": "T"}]
    with _client(handler) as c:
        rep = c.modifier_depot("10.34847/nkl.d1", metas=metas, status="published")
    assert vus["body"]["status"] == "published"
    assert rep == {}  # corps vide → dict vide


def test_modifier_depot_422_leve() -> None:
    with _client(lambda r: httpx.Response(422, json={"message": "bad"})) as c:
        with pytest.raises(NakalaSoumissionInvalide):
            c.modifier_depot("10.34847/nkl.d1", metas=[])


def test_rattacher_a_collection() -> None:
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        vus["method"] = request.method
        vus["path"] = request.url.path
        vus["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    with _client(handler) as c:
        c.rattacher_a_collection("10.34847/nkl.d1", "10.34847/nkl.col1")
    assert vus["method"] == "POST"
    assert vus["path"] == "/datas/10.34847/nkl.d1/collections"
    assert vus["body"] == ["10.34847/nkl.col1"]


def test_modifier_collection_put() -> None:
    vus: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        vus["method"] = request.method
        vus["path"] = request.url.path
        vus["body"] = json.loads(request.content)
        return httpx.Response(204, content=b"")  # Nakala renvoie 204 vide

    metas = [
        {"propertyUri": "http://nakala.fr/terms#title", "value": "Collection révisée"}
    ]
    with _client(handler) as c:
        rep = c.modifier_collection("10.34847/nkl.col1", metas=metas, status="public")
    assert vus["method"] == "PUT"
    assert vus["path"] == "/collections/10.34847/nkl.col1"
    assert vus["body"] == {"metas": metas, "status": "public"}
    assert rep == {}


# ---------------------------------------------------------------------------
# T3 — surfaçage de payload.validationErrors dans les messages d'erreur
# ---------------------------------------------------------------------------


def test_422_annexe_les_validation_errors_au_message() -> None:
    """Un 422 Nakala porte le détail par champ dans
    `payload.validationErrors` — le message de NakalaSoumissionInvalide
    doit le contenir (sinon l'utilisateur ne voit que « invalid data »)."""
    corps = {
        "code": 422,
        "message": "Data could not be submitted because of invalid data",
        "payload": {
            "validationErrors": [
                "The metadata http://nakala.fr/terms#title is required.",
                "The metadata http://nakala.fr/terms#type is required.",
            ]
        },
    }
    with _client(lambda r: httpx.Response(422, json=corps)) as c:
        with pytest.raises(NakalaSoumissionInvalide) as exc:
            c.creer_depot(metas=[], files=[])
    msg = str(exc.value)
    assert "http://nakala.fr/terms#title is required" in msg
    assert "http://nakala.fr/terms#type is required" in msg


def test_4xx_sans_validation_errors_message_generique_inchange() -> None:
    """4xx sans `payload.validationErrors` → message générique conservé
    (robustesse, pas de régression)."""
    with _client(lambda r: httpx.Response(400, json={"message": "Bad request"})) as c:
        with pytest.raises(NakalaSoumissionInvalide) as exc:
            c.creer_depot(metas=[], files=[])
    msg = str(exc.value)
    assert "Bad request" in msg
    assert "champs en cause" not in msg


@pytest.mark.parametrize(
    "corps",
    [
        {"message": "x", "payload": "pas un dict"},  # payload non-dict
        {"message": "x", "payload": {}},  # pas de validationErrors
        {"message": "x", "payload": {"validationErrors": []}},  # liste vide
        {"message": "x"},  # pas de payload
    ],
)
def test_detail_erreur_defensif_sans_validation_errors(corps) -> None:
    """detail_erreur_nakala reste défensif : payload absent / non-dict /
    validationErrors vide → message générique seul, sans crash."""
    from archives_tool.external.nakala.client import detail_erreur_nakala

    rep = httpx.Response(422, json=corps)
    detail = detail_erreur_nakala(rep)
    assert detail == "x"
    assert "champs en cause" not in detail


def test_detail_erreur_corps_non_json() -> None:
    """Corps non-JSON → texte brut, pas de crash."""
    from archives_tool.external.nakala.client import detail_erreur_nakala

    rep = httpx.Response(500, text="Internal Server Error (plain text)")
    assert detail_erreur_nakala(rep) == "Internal Server Error (plain text)"
