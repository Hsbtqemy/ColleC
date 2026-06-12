"""Tests d'intégration **réels** du round-trip métadonnées (P3/T4).

Touchent apitest.nakala.fr (réseau + compte test). **Exclus par défaut**
(`-m "not integration"`). Lancer : `uv run pytest -m integration`.

Le test clé est le **round-trip idempotent** : déposer des metas → re-lire →
`diff_push` doit être vide. Il valide la **fidélité (difficulté #3)** : ce
que Nakala stocke correspond à ce qu'on envoie via la carte 57 champs.
"""

from __future__ import annotations

import os

import pytest

from archives_tool.api.services.nakala_depot import diff_push
from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.depot_mapper import slugs_vers_metas
from archives_tool.external.nakala.preflight import preflight_appliquer
from archives_tool.external.nakala.write_client import (
    NakalaEcritureClient,
    extraire_doi,
)

pytestmark = pytest.mark.integration

CLE = os.environ.get("NAKALA_API_KEY", "01234567-89ab-cdef-0123-456789abcdef")
HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
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
    depots: list[str] = []
    yield depots
    for doi in depots:
        try:
            client_ecriture.supprimer_depot(doi)
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def nettoyage_collections(client_ecriture):
    cols: list[str] = []
    yield cols
    for doi in cols:
        try:
            client_ecriture.supprimer_collection(doi)
        except Exception:  # noqa: BLE001
            pass


def _metas(titre: str) -> list[dict]:
    metas, _ = preflight_appliquer(slugs_vers_metas({
        "nkl_title": [{"value": titre, "lang": "fr"}],
        "nkl_creator": ["Test, ColleC"],
        "nkl_created": "2024",
        "nkl_type": _TYPE_LIVRE,
        "nkl_license": "CC-BY-4.0",
        "dcterms_subject": [{"value": "Test round-trip", "lang": "fr"}],
    }))
    return metas


def test_round_trip_idempotent_et_modif(
    client_ecriture, client_lecture, nettoyage, tmp_path
) -> None:
    fichier = tmp_path / "rt.txt"
    fichier.write_text("round-trip", encoding="utf-8")
    desc = client_ecriture.uploader_fichier(fichier)

    metas = _metas("ColleC — round-trip P3")
    rep = client_ecriture.creer_depot(
        metas=metas,
        files=[{"sha1": desc["sha1"], "name": desc.get("name") or fichier.name}],
        status="pending",
    )
    doi = extraire_doi(rep)
    assert doi
    nettoyage.append(doi)

    # 1) Fidélité : re-lire → diff_push vide (ce qu'on a envoyé = ce qui est stocké).
    distant = client_lecture.lire_depot(doi)["metas"]
    assert diff_push(distant, metas) == [], (
        "round-trip non idempotent — Nakala a normalisé/ajouté des metas"
    )

    # 2) Update : PUT avec un titre modifié → re-lire → changé + toujours idempotent.
    metas2 = _metas("ColleC — round-trip P3 (RÉVISÉ)")
    client_ecriture.modifier_depot(doi, metas=metas2)
    distant2 = client_lecture.lire_depot(doi)["metas"]
    titres = [
        m["value"] for m in distant2
        if m.get("propertyUri") == "http://nakala.fr/terms#title"
    ]
    assert any("RÉVISÉ" in t for t in titres)
    assert diff_push(distant2, metas2) == []


def test_round_trip_collection_metadonnees(
    client_ecriture, client_lecture, nettoyage_collections
) -> None:
    """Round-trip métadonnées de collection (PUT /collections/{id})."""
    metas = slugs_vers_metas({
        "nkl_title": [{"value": "ColleC — collection round-trip", "lang": "fr"}],
        "dcterms_description": [{"value": "Description initiale", "lang": "fr"}],
    })
    rep = client_ecriture.creer_collection(metas=metas, status="private")
    doi = extraire_doi(rep)
    assert doi
    nettoyage_collections.append(doi)

    # Idempotent : ce qu'on a envoyé = ce qui est stocké (diff vide).
    distant = client_lecture.lire_collection(doi)["metas"]
    assert diff_push(distant, metas) == []

    # Update : PUT titre modifié → re-lire → changé + toujours idempotent.
    metas2 = slugs_vers_metas({
        "nkl_title": [{"value": "ColleC — collection round-trip (RÉVISÉ)", "lang": "fr"}],
        "dcterms_description": [{"value": "Description initiale", "lang": "fr"}],
    })
    client_ecriture.modifier_collection(doi, metas=metas2)
    distant2 = client_lecture.lire_collection(doi)["metas"]
    titres = [
        m["value"] for m in distant2
        if m.get("propertyUri") == "http://nakala.fr/terms#title"
    ]
    assert any("RÉVISÉ" in t for t in titres)
    assert diff_push(distant2, metas2) == []
