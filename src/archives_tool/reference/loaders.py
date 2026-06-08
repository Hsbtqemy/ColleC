"""Chargeurs des vocabulaires Nakala snapshotés (lecture seule, cachés).

Données sous `vocabulaires_nakala/` (cf. PROVENANCE.md). Lues à la
demande via `Path` (le package tourne depuis les sources, comme
`web/static`), parsées une fois et mémoïsées.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent / "vocabulaires_nakala"


@lru_cache(maxsize=1)
def langues_iso639() -> dict[str, str]:
    """Mapping code ISO 639-3 → libellé (snapshot Nakala, ~8043 langues).

    Sert de table de résolution de libellé : afficher « Yiddish » pour
    un item stocké `yid`, même hors de la liste curée du dropdown.
    """
    data = json.loads((_DIR / "languages.json").read_text(encoding="utf-8"))
    return {e["id"]: e["label"] for e in data}


@lru_cache(maxsize=1)
def types_coar_nakala() -> dict[str, dict[str, str]]:
    """Mapping URI COAR → entrée `{uri, en, fr, es, definition}` pour le
    sous-ensemble **accepté par Nakala** au dépôt (~29 types).

    Autorité du chemin de dépôt (un type hors de cette table est rejeté
    par Nakala). Pas l'autorité du catalogage interne (cf. PROVENANCE.md).
    """
    data = json.loads((_DIR / "coar_resource_types.json").read_text(encoding="utf-8"))
    return {e["uri"]: e for e in data}


@lru_cache(maxsize=1)
def licences_spdx() -> dict[str, dict[str, str]]:
    """Mapping code → `{code, name, url}` (liste SPDX snapshotée, ~620).

    ⚠️ Liste SPDX complète, pas le sous-ensemble Nakala — à confirmer
    avant usage comme vocabulaire d'export (cf. PROVENANCE.md).
    """
    data = json.loads((_DIR / "licenses.json").read_text(encoding="utf-8"))
    return {e["code"]: e for e in data}
