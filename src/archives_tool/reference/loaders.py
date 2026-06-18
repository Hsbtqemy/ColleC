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


#: Licences acceptées par Nakala mais **absentes de SPDX** (sondées en live
#: contre apitest le 2026-06-15, cf. backlog-nakala-api S6). Le vocabulaire
#: Nakala = SPDX ∪ ces additions. Set volontairement minimal et extensible :
#: il ne sert qu'à **éviter un faux positif** (ne pas signaler une licence
#: pourtant valide). Une licence inconnue ici n'est jamais bloquée — seulement
#: signalée comme « à vérifier » (cf. `licence_reconnue`).
LICENCES_NAKALA_EXTRAS = frozenset({"etalab-2.0"})


def licence_reconnue(code: str) -> bool:
    """True si `code` est une licence plausible pour Nakala : code SPDX
    vendorisé OU addition Nakala connue (`etalab-2.0`).

    Correspondance **exacte** (les codes SPDX sont sensibles à la casse :
    `CC-BY-4.0`, pas `cc-by-4.0`). Sert à signaler tôt une licence
    probablement erronée (faute de frappe) avant un 422 distant — jamais à
    bloquer (le set Nakala non-SPDX peut être incomplet, cf.
    `LICENCES_NAKALA_EXTRAS`).
    """
    return code in licences_spdx() or code in LICENCES_NAKALA_EXTRAS
