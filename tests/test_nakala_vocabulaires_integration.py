"""Test de non-régression (opt-in) de la **parité des vocabulaires** ColleC
↔ Nakala live (sonde S1). Attrape les dérives : un type COAR ou une
`propertyUri` que ColleC ÉMET mais que Nakala n'accepte (plus) → rejet 422
au dépôt. Un audit antérieur avait trouvé 9 URIs COAR fausses sur 15 —
ce test fige la garantie « ce que ColleC émet ⊆ ce que Nakala accepte ».

Exclus par défaut (`-m "not integration"`, réseau). Lancer :

    uv run pytest -m integration tests/test_nakala_vocabulaires_integration.py

Provenance : `scripts/verifier_parite_vocabulaires_nakala.py` (même logique,
ici en assertions). Compte / hôte de test public apitest en défaut.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from archives_tool.api.services.vocabulaires import (
    TYPES_COAR_OPTIONS,
    type_coar_pour_nakala,
)
from archives_tool.external.nakala.depot_mapper import SLUG_TO_NAKALA
from archives_tool.reference.loaders import types_coar_nakala

pytestmark = pytest.mark.integration

HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
_CLES_URI = ("uri", "propertyUri", "id", "property")


def _extraire_uri(entree: Any) -> str | None:
    if isinstance(entree, str):
        return entree
    if isinstance(entree, dict):
        for cle in _CLES_URI:
            v = entree.get(cle)
            if isinstance(v, str) and v.strip():
                return v
    return None


def _set_uris(charge: Any) -> set[str]:
    """Extrait un set d'URIs d'une réponse vocab (liste plate, ou enveloppe)."""
    elements = charge
    if isinstance(charge, dict):
        for cle in ("data", "results", "items", "vocabulary"):
            if isinstance(charge.get(cle), list):
                elements = charge[cle]
                break
        else:
            elements = list(charge.values())
    if not isinstance(elements, list):
        return set()
    return {u for e in elements if (u := _extraire_uri(e))}


@pytest.fixture(scope="module")
def vocab_live() -> dict[str, set[str]]:
    """Récupère une fois les vocabulaires live (lecture publique, pas d'auth).

    ⚠️ `/properties` (liste plate d'URIs complètes) et **non**
    `/properties/details` (clé `uri` = namespace) — cf. sonde S1.
    """
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        types = _set_uris(c.get(f"{HOTE}/vocabularies/depositTypes").json())
        props = _set_uris(c.get(f"{HOTE}/vocabularies/properties").json())
    if not types or not props:
        pytest.skip(
            f"Vocabulaires Nakala live introuvables sur {HOTE} "
            "(réseau / forme de réponse inattendue)."
        )
    return {"types": types, "props": props}


def test_snapshot_coar_sous_ensemble_du_live(vocab_live: dict[str, set[str]]) -> None:
    """Le snapshot vendorisé `types_coar_nakala()` ne doit contenir aucun
    type que Nakala n'accepte pas (sinon dépôt rejeté 422)."""
    snapshot = set(types_coar_nakala())
    fantomes = snapshot - vocab_live["types"]
    assert not fantomes, (
        "Types COAR du snapshot ColleC absents de depositTypes Nakala "
        f"(rejet 422 au dépôt) : {sorted(fantomes)}"
    )


def test_projections_types_internes_tombent_dans_le_live(
    vocab_live: dict[str, set[str]],
) -> None:
    """Tout `nkl:type` que ColleC peut émettre (projection des 32 types
    internes via `type_coar_pour_nakala`) doit être accepté par Nakala."""
    hors_live = {
        cible
        for uri, _ in TYPES_COAR_OPTIONS
        if (cible := type_coar_pour_nakala(uri)) is not None
        and cible not in vocab_live["types"]
    }
    assert not hors_live, (
        f"Projections COAR internes→Nakala hors du set accepté : {sorted(hors_live)}"
    )


def test_property_uris_emises_connues_de_nakala(
    vocab_live: dict[str, set[str]],
) -> None:
    """Toute `propertyUri` que `SLUG_TO_NAKALA` émet doit être connue de
    Nakala (sinon meta silencieusement droppée ou rejetée)."""
    emises = {v["propertyUri"] for v in SLUG_TO_NAKALA.values()}
    inconnues = emises - vocab_live["props"]
    assert not inconnues, (
        f"propertyUri émises par ColleC inconnues de Nakala : {sorted(inconnues)}"
    )
