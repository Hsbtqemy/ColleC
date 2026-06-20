"""Sonde V1 (backlog-nakala-api § À vérifier) : **strictesse du `type`**
d'une relation donnée↔donnée sur `POST /datas/{id}/relations`.

Question (cf. nakala-savoir-api §6 « Relations entre données ») : le `type`
d'une relation (vocabulaire DataCite relationType, CamelCase) est-il
**strictement validé** ? sensible à la casse ? que vaut un doublon ?

CONCLUSIONS (validées live apitest 2026-06-20, clé publique apitest) :
  1. Vocabulaire FERMÉ et STRICT — un `type` inconnu → 422 « Unknown relation
     type. The available relations are : … » avec **la liste complète des 38
     types** (Cites, Collects, …, IsPartOf, …, Reviews). Cf. RELATION_TYPES.
  2. SENSIBLE À LA CASSE — `ispartof` (minuscule) vers une cible neuve → 422
     (rejeté), alors que `IsPartOf` → 200 « 1 relation added ».
  3. DÉDUP PAR CIBLE qui court-circuite la validation du `type` — re-poster
     une relation vers une cible **déjà reliée** → 200 « no relation added »
     **sans valider le `type`** (un `ispartof` vers une cible déjà reliée
     renvoie 200, pas 422 : c'est un leurre — la cible existe donc Nakala
     n'examine pas le type).
  4. `DELETE /datas/{id}/relations` **purge TOUTES** les relations (ignore le
     corps) — « N relations deleted ». Pas de suppression sélective.

Isole une seule variable — le `type` — en pointant des cibles Nakala
**publiées existantes** que la source ne relie pas encore :
  source publiée  : 10.34847/nkl.1eb87r1j  (status=published, déjà sacrifiée)
  cibles neuves   : voir CIBLE_NEUVE_* (publiées sur apitest, source non reliée)

La sonde **se restaure** : snapshot des relations d'origine en début, purge +
ré-ajout en fin → apitest retrouve son état (le `--no-restore` laisse l'état
pour inspection manuelle).

Lancer :
    uv run python -X utf8 scripts/explorer_relations_type_nakala.py
"""

from __future__ import annotations

import os
import sys

import httpx

CLE = os.environ.get("NAKALA_API_KEY", "01234567-89ab-cdef-0123-456789abcdef")
HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr").rstrip("/")

SOURCE = "10.34847/nkl.1eb87r1j"  # publiée, sacrifiée
CIBLE_DEJA_RELIEE = "10.34847/nkl.d5dduly8"  # la source a déjà IsPartOf -> ici
CIBLE_NEUVE_A = "10.34847/nkl.e6c2d65a"  # publiée, source non reliée
CIBLE_NEUVE_B = "10.34847/nkl.a6543621"  # publiée, source non reliée

# Vocabulaire fermé renvoyé par le 422 (38 types DataCite relationType).
RELATION_TYPES = (
    "Cites Collects Compiles Continues Describes Documents HasMetadata HasPart "
    "HasTranslation HasVersion IsCitedBy IsCollectedBy IsCompiledBy "
    "IsContinuedBy IsDerivedFrom IsDescribedBy IsDocumentedBy IsIdenticalTo "
    "IsMetadataFor IsNewVersionOf IsObsoletedBy IsOriginalFormOf IsPartOf "
    "IsPreviousVersionOf IsPublishedIn IsReferencedBy IsRequiredBy IsReviewedBy "
    "IsSourceOf IsSupplementedBy IsSupplementTo IsTranslationOf IsVariantFormOf "
    "IsVersionOf Obsoletes References Requires Reviews"
).split()


def _section(titre: str) -> None:
    print(f"\n{'=' * 70}\n  {titre}\n{'=' * 70}")


def _relations(c: httpx.Client) -> list[dict]:
    return c.get(f"/datas/{SOURCE}").json().get("relations") or []


def _poster(c: httpx.Client, type_rel: str, cible: str) -> tuple[int, str]:
    r = c.post(
        f"/datas/{SOURCE}/relations",
        json=[{"type": type_rel, "repository": "nakala", "target": cible}],
    )
    return r.status_code, r.text


def main() -> None:
    restaurer = "--no-restore" not in sys.argv
    _section("Sonde V1 — strictesse du `type` de relation (apitest)")
    print(f"hôte={HOTE}  source={SOURCE}  restaurer={restaurer}")

    with httpx.Client(
        base_url=HOTE,
        headers={"Accept": "application/json", "X-API-KEY": CLE},
        timeout=30,
        follow_redirects=True,
    ) as c:
        if c.get(f"/datas/{SOURCE}").status_code != 200:
            print("!! source injoignable — sonde abandonnée.")
            return

        # Snapshot pour restauration fidèle (type/repository/target/comment).
        snapshot = [
            {
                k: r.get(k)
                for k in ("type", "repository", "target", "comment")
                if r.get(k) is not None
            }
            for r in _relations(c)
        ]
        print(f"snapshot : {len(snapshot)} relation(s) d'origine")

        try:
            _section("T1 — type inventé, cible neuve  (attendu : 422 vocab)")
            st, txt = _poster(c, "NOTAREALTYPE", CIBLE_NEUVE_A)
            print(f"HTTP {st}: {txt[:400]}")

            _section("T2 — minuscule `ispartof`, cible neuve  (attendu : 422)")
            st, txt = _poster(c, "ispartof", CIBLE_NEUVE_A)
            print(f"HTTP {st}: {txt[:200]}")

            _section("T3 (contrôle) — `IsPartOf` correct, cible neuve  (added)")
            st, txt = _poster(c, "IsPartOf", CIBLE_NEUVE_B)
            print(f"HTTP {st}: {txt[:200]}")

            _section("T4 — minuscule vers cible DÉJÀ reliée  (leurre : 200 no-op)")
            st, txt = _poster(c, "ispartof", CIBLE_DEJA_RELIEE)
            print(f"HTTP {st}: {txt[:200]}")
            print("  -> dédup par cible : 200 sans validation du type.")

            _section("Bilan")
            etat = _relations(c)
            print(f"relations en fin de tests : {len(etat)}")
            for r in etat:
                print(f"   {r.get('type')!r:>12} -> {r.get('target')}")
        finally:
            if restaurer and snapshot is not None:
                _section("Restauration de l'état d'origine")
                c.request("DELETE", f"/datas/{SOURCE}/relations", json=snapshot)
                rr = c.post(f"/datas/{SOURCE}/relations", json=snapshot)
                print(f"ré-ajout {len(snapshot)} -> {rr.status_code} {rr.text[:120]}")
                fin = _relations(c)
                print(f"relations rétablies : {len(fin)}")
                for r in fin:
                    print(
                        f"   {r.get('type')!r:>12} -> {r.get('target')}"
                        f"  comment={r.get('comment')!r}"
                    )


if __name__ == "__main__":
    main()
