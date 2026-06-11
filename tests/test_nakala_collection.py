"""Tests de l'itérateur de collection Nakala (Lot 1, T1.1) — httpx mocké."""

from __future__ import annotations

import httpx
import pytest

from archives_tool.external.nakala.client import (
    ClientLectureNakala,
    NakalaIntrouvable,
)
from archives_tool.external.nakala.collection import iterer_donnees_collection

_DOI = "10.34847/nkl.collec01"


def _client(handler) -> ClientLectureNakala:
    return ClientLectureNakala(
        "https://apitest.nakala.fr",
        api_key="cle-test",
        transport=httpx.MockTransport(handler),
    )


def _page(donnees: list[dict], *, current: int, last: int) -> dict:
    return {
        "data": donnees,
        "currentPage": current,
        "lastPage": last,
        "limit": 50,
    }


def test_itere_toutes_les_pages_sans_doublon() -> None:
    # 3 pages : ids 0..4 (2 + 2 + 1).
    pages = {
        1: _page([{"identifier": "d0"}, {"identifier": "d1"}], current=1, last=3),
        2: _page([{"identifier": "d2"}, {"identifier": "d3"}], current=2, last=3),
        3: _page([{"identifier": "d4"}], current=3, last=3),
    }
    appels: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        appels.append(page)
        return httpx.Response(200, json=pages[page])

    with _client(handler) as c:
        ids = [d["identifier"] for d in iterer_donnees_collection(c, _DOI)]

    assert ids == ["d0", "d1", "d2", "d3", "d4"]
    assert appels == [1, 2, 3]  # arrêt correct après lastPage


def test_collection_vide() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_page([], current=1, last=1))

    with _client(handler) as c:
        assert list(iterer_donnees_collection(c, _DOI)) == []


def test_404_propage_introuvable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "absente"})

    with _client(handler) as c, pytest.raises(NakalaIntrouvable):
        list(iterer_donnees_collection(c, _DOI))


def test_borne_anti_boucle_sur_lastpage_initial() -> None:
    """Si l'API renvoyait un lastPage incohérent (toujours > current),
    l'itérateur s'arrête sur le lastPage observé en 1re page."""
    appels: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        appels.append(page)
        # lastPage figé à 2, données non vides à chaque page.
        return httpx.Response(200, json=_page([{"identifier": f"d{page}"}], current=page, last=2))

    with _client(handler) as c:
        ids = [d["identifier"] for d in iterer_donnees_collection(c, _DOI)]

    assert ids == ["d1", "d2"]
    assert appels == [1, 2]  # pas de page 3
