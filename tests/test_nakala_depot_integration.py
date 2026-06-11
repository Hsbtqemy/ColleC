"""Tests d'intégration **réels** contre apitest.nakala.fr (P2/C1).

Touchent le vrai environnement de test Nakala : réseau + compte apitest
requis. **Exclus par défaut** (`addopts = -m "not integration"` dans
pyproject). Les lancer explicitement ::

    uv run pytest -m integration

La clé par défaut est le **compte de test public** publié par Huma-Num pour
apitest (PAS un secret). Surchargeable via `NAKALA_API_KEY` / `NAKALA_HOST`.

Objectifs :
  1. Valider l'auth (la clé atteint bien Nakala).
  2. **Verrouiller la forme de réponse** `POST /datas` + `POST /collections`
     (non documentée dans Swagger) → confirme `extraire_doi`.
  3. Round-trip : upload + dépôt + collection + lecture + nettoyage.

Chaque test nettoie ses créations. En cas d'échec mid-flow, un dépôt /
upload peut rester orphelin sur apitest (nettoyage manuel).
"""

from __future__ import annotations

import os

import pytest

from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.depot_mapper import slugs_vers_metas
from archives_tool.external.nakala.preflight import preflight_appliquer
from archives_tool.external.nakala.write_client import (
    NakalaEcritureClient,
    extraire_doi,
)

pytestmark = pytest.mark.integration

# Compte de test public Huma-Num (apitest) — non secret.
CLE_DEFAUT = "01234567-89ab-cdef-0123-456789abcdef"
HOTE_DEFAUT = "https://apitest.nakala.fr"

CLE = os.environ.get("NAKALA_API_KEY", CLE_DEFAUT)
HOTE = os.environ.get("NAKALA_HOST", HOTE_DEFAUT)

_TYPE_LIVRE = "http://purl.org/coar/resource_type/c_2f33"


@pytest.fixture
def client_ecriture():
    c = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
    yield c
    c.fermer()


@pytest.fixture
def client_lecture():
    c = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
    yield c
    c.fermer()


@pytest.fixture
def nettoyage(client_ecriture):
    """Traque les dépôts + collections créés, les supprime au teardown."""
    depots: list[str] = []
    collections: list[str] = []
    yield depots, collections
    for doi in depots:
        try:
            client_ecriture.supprimer_depot(doi)
        except Exception:  # noqa: BLE001
            pass
    for doi in collections:
        try:
            client_ecriture.supprimer_collection(doi)
        except Exception:  # noqa: BLE001
            pass


def _metas_minimal(titre: str) -> list[dict]:
    metas = slugs_vers_metas({
        "nkl_title": [{"value": titre, "lang": "fr"}],
        "nkl_creator": ["Test, ColleC"],
        "nkl_created": "2024",
        "nkl_type": _TYPE_LIVRE,
        "nkl_license": "CC-BY-4.0",
    })
    metas, _ = preflight_appliquer(metas)
    return metas


def test_round_trip_depot(client_ecriture, client_lecture, nettoyage, tmp_path) -> None:
    depots, _ = nettoyage
    fichier = tmp_path / "colle-c-integration.txt"
    fichier.write_text("ColleC integration test", encoding="utf-8")

    desc = client_ecriture.uploader_fichier(fichier)
    assert "sha1" in desc

    reponse = client_ecriture.creer_depot(
        metas=_metas_minimal("ColleC — test d'intégration dépôt"),
        files=[{"sha1": desc["sha1"], "name": desc.get("name") or fichier.name}],
        status="pending",
    )
    doi = extraire_doi(reponse)
    assert doi, f"DOI introuvable dans la réponse : {reponse!r}"
    depots.append(doi)

    # Vérifie via l'API de lecture que le dépôt existe et porte le titre.
    depot = client_lecture.lire_depot(doi)
    titres = [
        m["value"] for m in depot.get("metas", [])
        if m.get("propertyUri") == "http://nakala.fr/terms#title"
    ]
    assert any("test d'intégration" in t for t in titres)


def test_creer_collection(client_ecriture, nettoyage) -> None:
    _, collections = nettoyage
    reponse = client_ecriture.creer_collection(
        metas=slugs_vers_metas({"nkl_title": [{"value": "ColleC — collection test",
                                              "lang": "fr"}]}),
        status="private",
    )
    doi = extraire_doi(reponse)
    assert doi, f"DOI collection introuvable : {reponse!r}"
    collections.append(doi)
