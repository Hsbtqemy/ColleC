"""Sonde modération (clean-room) : cycle de vie + **prérequis de demande**.

Re-vérifie EN LIVE le §6 « Modération » de
`docs/developpeurs/nakala-savoir-api.md`. Écrite **en clean-room** à partir
des seuls *faits d'API* (endpoints, statuts, codes) — **PAS** dérivée du
script MSHB `moderation-lot-nakala` (Chloé Choquet, **CC BY-NC-SA 4.0**, cité
en source de référence). Les faits d'API ne sont pas couverts par le droit
d'auteur ; le code l'est → on ne le copie pas (principe maison « copie →
possession → divergence »).

CE QUE LA RE-PROBE A ÉTABLI (live apitest 2026-06-27, comptes test publics) —
corrige un §6 incomplet :

  * `ROLE_MODERATOR` est **nécessaire mais PAS suffisant**. Les comptes test
    apitest le portent tous et obtiennent quand même **403** sur
    `PUT /datas/{id}/status/moderated` (« You are not allowed to change the
    data status ») tant qu'il n'y a **pas de demande de modération**.
  * Le dépôt doit avoir une **demande / `Task` de modération** : visible via
    `POST /users/datas/moderable` (file) et `GET /users/resources/{id}/action`
    (tâches). Sans elle : file `totalRecords=0`, action `[]`, modérer → 403.
  * La **demande n'est PAS un endpoint API public** (`moderationRequester` /
    `lastModerationRequestDate` = champs en lecture seule). Elle se crée via
    l'UI test.nakala.fr / l'outil `depot-lot-nakala`. → un client pur-API ne
    peut pas l'initier ; cette sonde **ne peut donc pas atteindre le 204
    elle-même** sans qu'une demande ait été posée au préalable (via l'UI).
  * Inchangés (confirmés) : revert de statut interdit (`PUT status/published`
    → 403 pour tous), revert réel par **édition** du propriétaire ; re-poster
    les `files[]` au même `sha1` **ne crée pas de version** (idempotent).

Comportement de la sonde, selon l'état du dépôt :
  - **sans demande** (cas courant) → vérifie le 403 attendu + explique le
    prérequis (PASS) ; ne tente pas le reste.
  - **avec demande** (posée via l'UI au préalable) → modère (204), vérifie
    `lastModerator`/`lastModerationDate` + statut `moderated`, le 403 du
    revert-statut (×2), puis le revert par édition → `published`, et la
    persistance de la trace.

Auto-restaurante : finit toujours `published` (état de départ).

Prérequis (variables d'environnement) :
  NAKALA_HOST            défaut https://apitest.nakala.fr
  NAKALA_API_KEY         clé du DÉPOSANT (propriétaire du DOI de test)
  NAKALA_MODERATOR_KEY   clé d'un compte ROLE_MODERATOR (≠ déposant)
  NAKALA_MODERATION_DOI  DOI d'un dépôt PUBLIÉ appartenant au déposant

Sur apitest, les 4 comptes test (clés publiques sur test.nakala.fr) portent
tous ROLE_MODERATOR. En prod, ROLE_MODERATOR est rare (~1 par MSHS).

Lancer :
    uv run python -X utf8 scripts/explorer_moderation_nakala.py
"""

from __future__ import annotations

import os
import sys

import httpx

HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr").rstrip("/")
CLE_DEPOSANT = os.environ.get("NAKALA_API_KEY", "")
CLE_MODERATEUR = os.environ.get("NAKALA_MODERATOR_KEY", "")
DOI = os.environ.get("NAKALA_MODERATION_DOI", "")

#: Clés de fichier à renvoyer au PUT (anti-wipe : H1 files[] = remplacement
#: total ; H12 omettre `description` = la met à null).
_FILE_KEYS = ("sha1", "name", "description", "embargoed")


def _section(titre: str) -> None:
    print(f"\n{'=' * 70}\n  {titre}\n{'=' * 70}")


def _client(cle: str) -> httpx.Client:
    return httpx.Client(
        base_url=HOTE,
        headers={"Accept": "application/json", "X-API-KEY": cle},
        timeout=30,
        follow_redirects=False,  # un 3xx ne doit jamais passer pour un succès
    )


def _depot(c: httpx.Client) -> dict:
    r = c.get(f"/datas/{DOI}")
    r.raise_for_status()
    return r.json()


def _files_min(depot: dict) -> list[dict]:
    return [
        {k: f[k] for k in _FILE_KEYS if f.get(k) is not None}
        for f in depot.get("files") or []
    ]


def _revert_edition(dep: httpx.Client, metas: list, files: list) -> int:
    """Revert par édition propriétaire (seul chemin moderated→published)."""
    r = dep.put(
        f"/datas/{DOI}",
        json={"status": "published", "metas": metas, "files": files},
    )
    return r.status_code


def _exiger_prerequis() -> bool:
    manque = [
        n
        for n, v in (
            ("NAKALA_API_KEY", CLE_DEPOSANT),
            ("NAKALA_MODERATOR_KEY", CLE_MODERATEUR),
            ("NAKALA_MODERATION_DOI", DOI),
        )
        if not v
    ]
    if manque:
        print("!! Variables manquantes :", ", ".join(manque))
        print("   (voir la docstring du script)")
        return False
    return True


def _demande_existe(mod: httpx.Client) -> bool:
    """Le dépôt a-t-il une demande / tâche de modération ? (file + action)."""
    present = False
    rq = mod.post(
        "/users/datas/moderable",
        json={"page": 1, "limit": 100, "orders": [], "status": ["published"]},
    )
    if rq.status_code == 200:
        data = rq.json()
        total = data.get("totalRecords")
        present = any(d.get("identifier") == DOI for d in data.get("data") or [])
        print(f"  file moderable : HTTP 200 totalRecords={total} ; DOI présent={present}")
    else:
        print(f"  file moderable : HTTP {rq.status_code} {rq.text[:120]}")
    ra = mod.get(f"/users/resources/{DOI}/action")
    taches = ra.json() if ra.status_code == 200 else None
    print(f"  tâches sur la ressource : {taches!r}")
    return present or bool(taches)


def main() -> None:
    _section("Sonde modération — prérequis + cycle published ↔ moderated")
    print(f"hôte={HOTE}  doi={DOI or '(non défini)'}")
    if "apitest" not in HOTE:
        print("⚠️  HÔTE DE PROD : la trace lastModerator y sera INDÉLÉBILE.")
    if not _exiger_prerequis():
        sys.exit(2)

    dep = _client(CLE_DEPOSANT)
    mod = _client(CLE_MODERATEUR)
    try:
        # Rôle du modérateur (transparence : ROLE_MODERATOR nécessaire).
        me = mod.get("/users/me")
        if me.status_code == 200:
            j = me.json()
            print(f"modérateur : username={j.get('username')!r} roles={j.get('roles')!r}")
            if "ROLE_MODERATOR" not in (j.get("roles") or []):
                print("  ⚠️  ce compte n'a PAS ROLE_MODERATOR — modération impossible.")

        avant = _depot(dep)
        if avant.get("status") != "published":
            print(f"!! dépôt non 'published' (status={avant.get('status')!r}) — abandon.")
            sys.exit(2)
        metas0, files0 = avant.get("metas") or [], _files_min(avant)
        print(f"snapshot : status=published, {len(metas0)} metas, {len(files0)} fichier(s)")

        _section("1. Prérequis : demande/tâche de modération sur le dépôt ?")
        a_demande = _demande_existe(mod)
        print(f"  → demande de modération présente : {a_demande}")

        _section("2. Modérer  (PUT /datas/{id}/status/moderated)")
        rm = mod.put(f"/datas/{DOI}/status/moderated")
        print(f"HTTP {rm.status_code}: {rm.text[:160]}")

        if rm.status_code == 204:
            ap = _depot(dep)
            print(f"  status={ap.get('status')!r} lastModerator={ap.get('lastModerator')!r}")
            print(f"  lastModerationDate={ap.get('lastModerationDate')!r}")

            _section("3. Revert de statut interdit  (attendu 403 ×2)")
            print(f"  modérateur  → {mod.put(f'/datas/{DOI}/status/published').status_code}")
            print(f"  propriétaire→ {dep.put(f'/datas/{DOI}/status/published').status_code}")

            _section("4. Revert par ÉDITION (propriétaire)  attendu 204 → published")
            code = _revert_edition(dep, metas0, files0)
            fin = _depot(dep)
            print(f"HTTP {code} ; status={fin.get('status')!r}")
            _section("5. Persistance de la trace + intégrité fichiers")
            print(f"  lastModerator={fin.get('lastModerator')!r}  (persiste après revert)")
            print(f"  fichiers={len(fin.get('files') or [])}  version={fin.get('version')}")
        elif rm.status_code == 403:
            if a_demande:
                print("  ✗ INATTENDU : 403 alors qu'une demande existe — à investiguer.")
            else:
                print("  ✓ ATTENDU : ROLE_MODERATOR ne suffit PAS sans demande de")
                print("    modération. La demande se crée via l'UI test.nakala.fr /")
                print("    l'outil depot-lot-nakala (hors API publique). Pour exercer")
                print("    le cycle complet : poser une demande via l'UI puis relancer.")
        else:
            print(f"  ✗ code inattendu {rm.status_code}")

        _section("Restauration")
        final = _depot(dep)
        if final.get("status") != "published":
            print(f"  revert (status={final.get('status')!r}) …")
            _revert_edition(dep, metas0, files0)
            final = _depot(dep)
        ok = final.get("status") == "published"
        print("✓ dépôt à 'published'" if ok else f"✗ statut final {final.get('status')!r}")
    finally:
        dep.close()
        mod.close()


if __name__ == "__main__":
    main()
