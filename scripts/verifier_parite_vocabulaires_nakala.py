"""Sonde S1 (backlog-nakala-api) : parité des vocabulaires ColleC ↔ Nakala.

Confronte, en **lecture seule**, les cartes vendorisées / hardcodées de
ColleC aux vocabulaires **live** de Nakala :

  - types COAR acceptés au dépôt : `types_coar_nakala()` (snapshot
    `reference/vocabulaires_nakala/coar_resource_types.json`) vs
    `GET /vocabularies/depositTypes` (29 types) ;
  - tout `nkl:type` que ColleC peut ÉMETTRE (projection `type_coar_pour_nakala`
    des 32 types internes) doit être ⊆ depositTypes live ;
  - tout `propertyUri` de `SLUG_TO_NAKALA` doit être ⊆
    `GET /vocabularies/properties` live.

Objet : attraper les dérives (un audit antérieur avait trouvé 9 URIs COAR
fausses sur 15). Aucune écriture. Code de sortie 1 si une dérive « ColleC
émet quelque chose que Nakala n'accepte pas » est détectée.

    uv run python -X utf8 scripts/verifier_parite_vocabulaires_nakala.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

from archives_tool.api.services.vocabulaires import (
    COAR_INTERNE_VERS_NAKALA,
    TYPES_COAR_OPTIONS,
    type_coar_pour_nakala,
)
from archives_tool.external.nakala.depot_mapper import SLUG_TO_NAKALA
from archives_tool.reference.loaders import types_coar_nakala

HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
_CLES_URI = ("uri", "propertyUri", "id", "property")


def _print_section(titre: str) -> None:
    print("\n" + "=" * 70 + f"\n  {titre}\n" + "=" * 70)


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
    """Extrait un set d'URIs d'une réponse vocab (liste, ou dict enveloppe)."""
    elements = charge
    if isinstance(charge, dict):
        # certaines réponses enveloppent dans data/results/...
        for cle in ("data", "results", "items", "vocabulary"):
            if isinstance(charge.get(cle), list):
                elements = charge[cle]
                break
        else:
            elements = list(charge.values())
    if not isinstance(elements, list):
        return set()
    return {u for e in elements if (u := _extraire_uri(e))}


def main() -> int:
    print(f"Cible : {HOTE} (lecture seule)")
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        dep = c.get(f"{HOTE}/vocabularies/depositTypes")
        dep.raise_for_status()
        props = c.get(f"{HOTE}/vocabularies/properties")
        props.raise_for_status()
        depot_charge = dep.json()
        props_charge = props.json()

    types_live = _set_uris(depot_charge)
    props_live = _set_uris(props_charge)
    print(f"depositTypes live : {len(types_live)} | properties live : {len(props_live)}")
    if not types_live or not props_live:
        # Aide au diagnostic si l'extraction a raté la forme.
        import json
        print("\n[!] Extraction vide — forme brute (1er element) :")
        print("  depositTypes:", json.dumps(depot_charge, ensure_ascii=False)[:400])
        print("  properties  :", json.dumps(props_charge, ensure_ascii=False)[:400])
        return 1

    anomalies = 0

    # --- 1. Snapshot COAR ColleC vs depositTypes live -------------------
    _print_section("1 - Snapshot types COAR Nakala (ColleC) vs live")
    snap = set(types_coar_nakala().keys())
    print(f"snapshot ColleC : {len(snap)} types | live : {len(types_live)}")
    faux = snap - types_live   # ColleC croit accepté, Nakala ne connait pas
    manques = types_live - snap  # Nakala accepte, snapshot ColleC l'ignore
    if faux:
        anomalies += 1
        print(f"\n[!] DÉRIVE — {len(faux)} type(s) du snapshot ColleC ABSENT(s) "
              f"du live (rejet 422 au dépôt) :")
        for u in sorted(faux):
            print(f"    {u}")
    else:
        print("\n[OK] snapshot ⊆ live : aucun type fantôme côté ColleC.")
    if manques:
        print(f"\n[i] {len(manques)} type(s) acceptés par Nakala mais hors snapshot "
              f"ColleC (couverture, pas un bug) :")
        for u in sorted(manques):
            label = _label(depot_charge, u)
            print(f"    {u}  {label}")

    # --- 2. Types ÉMIS par ColleC (projection) ⊆ live -------------------
    _print_section("2 - Types émis par ColleC (projection interne→Nakala) ⊆ live")
    sans_projection = []
    emis_hors_live = []
    for uri, label in TYPES_COAR_OPTIONS:
        cible = type_coar_pour_nakala(uri)
        if cible is None:
            sans_projection.append((uri, label))
        elif cible not in types_live:
            emis_hors_live.append((uri, label, cible))
    if emis_hors_live:
        anomalies += 1
        print(f"[!] DÉRIVE — {len(emis_hors_live)} type(s) interne(s) projeté(s) "
              f"vers une cible HORS live :")
        for uri, label, cible in emis_hors_live:
            print(f"    {label} ({uri}) → {cible}  [absent du live]")
    else:
        print("[OK] toutes les projections tombent dans depositTypes live.")
    if sans_projection:
        print(f"\n[i] {len(sans_projection)} type(s) interne(s) sans projection "
              f"(type_coar_pour_nakala→None ; à l'export = type omis) :")
        for uri, label in sans_projection:
            extra = " (extra connu)" if uri in COAR_INTERNE_VERS_NAKALA else ""
            print(f"    {label} ({uri}){extra}")

    # --- 3. propertyUri de SLUG_TO_NAKALA ⊆ live ------------------------
    _print_section("3 - propertyUri de SLUG_TO_NAKALA ⊆ properties live")
    props_emises = {v["propertyUri"] for v in SLUG_TO_NAKALA.values()}
    print(f"propriétés émises par ColleC : {len(props_emises)}")
    props_inconnues = props_emises - props_live
    if props_inconnues:
        anomalies += 1
        print(f"\n[!] DÉRIVE — {len(props_inconnues)} propertyUri émise(s) par "
              f"ColleC INCONNUE(s) de Nakala (risque drop/rejet) :")
        for u in sorted(props_inconnues):
            slugs = [s for s, v in SLUG_TO_NAKALA.items() if v["propertyUri"] == u]
            print(f"    {u}  (slugs: {', '.join(slugs)})")
    else:
        print("\n[OK] toutes les propertyUri émises sont connues de Nakala.")

    # --- Bilan ----------------------------------------------------------
    _print_section("Bilan")
    if anomalies == 0:
        print("[OK] Aucune dérive bloquante : tout ce que ColleC émet est accepté "
              "par Nakala (snapshot, types projetés, propriétés).")
    else:
        print(f"[!] {anomalies} catégorie(s) de dérive détectée(s) — voir ci-dessus.")
    return 1 if anomalies else 0


def _label(charge: Any, uri: str) -> str:
    elements = charge if isinstance(charge, list) else charge.get("data", [])
    for e in elements if isinstance(elements, list) else []:
        if isinstance(e, dict) and e.get("uri") == uri:
            return f"({e.get('fr') or e.get('en') or ''})"
    return ""


if __name__ == "__main__":
    sys.exit(main())
