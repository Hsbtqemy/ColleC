"""Audit de parité **apitest ↔ production** Nakala — VOLET A (lecture seule).

But (cf. backlog-nakala-api § *Audit de parité*) : tous les constats de
`nakala-savoir-api.md` ont été validés contre `apitest.nakala.fr`. Ce script
les reconfronte à la **production** `api.nakala.fr` et **diffe les deux**, pour
documenter fidèlement où prod et apitest divergent.

GARANTIE DE SÛRETÉ — ce script ne crée, ne modifie et ne supprime **rien** :
  - le helper `g()` ne fait que des GET ;
  - la SEULE exception est `lister_readable()` : un `POST /users/datas/{scope}`
    à **corps vide `{}`** — c'est l'idiome Nakala pour *lister/chercher* des
    dépôts lisibles (lecture pure, aucune mutation, aucun DOI minté) ;
  - aucun PUT/DELETE, aucune écriture base ni disque → **zéro pollution** prod.

CLÉ API PROD — jamais en clair dans le code ni le dépôt. Lue au runtime :
  1. variable d'environnement `NAKALA_PROD_KEY`, sinon
  2. fichier gitignoré `secrets/nakala_prod.key` (contenu = la clé seule).
La clé n'est **jamais imprimée** (seul un accusé « clé chargée : oui/non »).
apitest utilise la clé publique de test connue.

NB : `/search` renvoie des identifiants qui ne sont **pas** lisibles en direct
via `GET /datas/{id}` (index ≠ store) → on échantillonne via la liste
« readable » qui, elle, donne des DOI réellement GETtables.

Lancer :
    uv run python -X utf8 scripts/audit_parite_prod_nakala.py
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

PROD = "https://api.nakala.fr"
APITEST = "https://apitest.nakala.fr"
CLE_PUBLIQUE_APITEST = "01234567-89ab-cdef-0123-456789abcdef"

# Vocabulaires candidats (chemins probables — le script garde ceux qui → 200).
VOCAB_CANDIDATS = (
    "/vocabularies/licenses",
    "/vocabularies/datatypes",
    "/vocabularies/languages",
    "/vocabularies/countries",
)

# Champs de modération attendus dans la réponse `GET /datas/{id}`.
CHAMPS_MODERATION = (
    "lastModerator",
    "lastModerationDate",
    "lastModerationRequestDate",
    "moderationRequester",
)

TIMEOUT = httpx.Timeout(60.0, connect=60.0)


def _nettoyer_cle(brut: str | None) -> str | None:
    """Retire BOM (ajouté par PowerShell `Set-Content -Encoding utf8`) et
    espaces — un en-tête HTTP n'accepte que de l'ASCII."""
    if not brut:
        return None
    cle = brut.lstrip(chr(0xFEFF)).strip()
    return cle or None


def _charger_cle_prod() -> str | None:
    cle = _nettoyer_cle(os.environ.get("NAKALA_PROD_KEY"))
    if cle:
        return cle
    fichier = Path("secrets/nakala_prod.key")
    if fichier.is_file():
        return _nettoyer_cle(fichier.read_text(encoding="utf-8-sig"))
    return None


def _section(titre: str) -> None:
    print(f"\n{'=' * 72}\n  {titre}\n{'=' * 72}")


def g(client: httpx.Client, chemin: str, **kw) -> httpx.Response | None:
    """Accès réseau LECTURE — GET only, avec 3 essais (prod parfois lente)."""
    for essai in range(3):
        try:
            return client.get(chemin, **kw)
        except httpx.HTTPError as exc:
            if essai == 2:
                print(f"    [réseau] GET {chemin}: {type(exc).__name__} (abandon)")
    return None


def lister_readable(client: httpx.Client, scope: str = "readable") -> list[dict]:
    """LECTURE via `POST /users/datas/{scope}` à corps vide (idiome Nakala de
    listing — aucune mutation). Renvoie la liste de dépôts lisibles."""
    for essai in range(3):
        try:
            rep = client.post(
                f"/users/datas/{scope}", params={"page": 1, "limit": 25}, json={}
            )
            if rep.status_code == 200:
                d = rep.json()
                return d.get("data") or d.get("datas") or []
            return []
        except httpx.HTTPError:
            if essai == 2:
                return []
    return []


def _json(rep: httpx.Response | None):
    if rep is None:
        return None
    try:
        return rep.json()
    except Exception:  # noqa: BLE001
        return rep.text


def _client(host: str, cle: str | None) -> httpx.Client:
    headers = {"Accept": "application/json"}
    if cle:
        headers["X-API-KEY"] = cle
    return httpx.Client(
        base_url=host, headers=headers, timeout=TIMEOUT, follow_redirects=True
    )


def _choisir_echantillons(
    client: httpx.Client,
) -> tuple[str | None, tuple[str, str] | None]:
    """Renvoie (DOI publié lisible, (DOI, sha1) d'une image) parmi les dépôts
    readable — en lisant chaque candidat pour garantir un GET 200."""
    publie: str | None = None
    image: tuple[str, str] | None = None
    for it in lister_readable(client):
        ident = it.get("identifier")
        if not ident:
            continue
        d = _json(g(client, f"/datas/{ident}"))
        if not isinstance(d, dict) or "files" not in d:
            continue
        if publie is None and d.get("status") == "published":
            publie = ident
        if image is None:
            for f in d.get("files") or []:
                nom = (f.get("name") or "").lower()
                if nom.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2")):
                    if f.get("sha1"):
                        image = (ident, f["sha1"])
                        break
        if publie and image:
            break
    return publie, image


def auditer(host: str, cle: str | None, etiquette: str) -> dict:
    """Batterie de sondes lecture sur un hôte. Renvoie un résumé comparable."""
    _section(f"{etiquette} — {host}")
    r: dict = {"host": host}
    with _client(host, cle) as c:
        # 1) whoami
        rep = g(c, "/users/me")
        me = _json(rep)
        r["whoami_status"] = rep.status_code if rep else None
        if rep is not None and rep.status_code == 200 and isinstance(me, dict):
            r["roles"] = me.get("roles")
            print(
                f"  /users/me -> 200  username={me.get('username')!r} roles={me.get('roles')}"
            )
        else:
            print(f"  /users/me -> {rep.status_code if rep else 'n/a'}")

        # 2) vocabulaires (tailles)
        vocab: dict[str, int | str] = {}
        for chemin in VOCAB_CANDIDATS:
            rep = g(c, chemin)
            if rep is None:
                vocab[chemin] = "timeout"
            elif rep.status_code == 200:
                corps = _json(rep)
                vocab[chemin] = len(corps) if isinstance(corps, list) else "?"
            else:
                vocab[chemin] = f"HTTP {rep.status_code}"
        r["vocab"] = vocab
        print(f"  vocabulaires : {vocab}")

        # 3) échantillons réellement lisibles
        publie, image = _choisir_echantillons(c)
        print(
            f"  échantillon publié : {publie} | image : {image[0] if image else None}"
        )

        if publie:
            d = _json(g(c, f"/datas/{publie}"))
            if isinstance(d, dict):
                r["data_keys"] = sorted(d.keys())
                r["moderation_keys"] = [k for k in CHAMPS_MODERATION if k in d]
                print(
                    f"    data clés ({len(d)}) ; modération présente : {r['moderation_keys']}"
                )
            rv = g(c, f"/datas/{publie}/versions")
            r["versions_status"] = rv.status_code if rv else None
            print(f"    versions -> {rv.status_code if rv else 'n/a'}")
            rc = g(c, f"/datas/{publie}/citation")
            r["citation_status"] = rc.status_code if rc else None
            txt = (rc.text if rc else "") or ""
            r["citation_reelle"] = bool(
                rc and rc.status_code == 200 and "doi.org" in txt
            )
            print(
                f"    citation -> {rc.status_code if rc else 'n/a'} | réelle : {r.get('citation_reelle')}"
            )
            if r.get("citation_reelle"):
                print(f"      « {txt[:160]}… »")

        if image:
            doi, sha1 = image
            ri = g(c, f"/iiif/{doi}/{sha1}/info.json")
            r["iiif_status"] = ri.status_code if ri else None
            print(f"    IIIF info.json -> {ri.status_code if ri else 'n/a'}")

        # 4) corps d'erreur 404
        r404 = g(c, "/datas/10.34847/nkl.zzzzzzzz")
        r["err404_status"] = r404.status_code if r404 else None
        body = _json(r404)
        r["err404_keys"] = sorted(body.keys()) if isinstance(body, dict) else None
        print(f"  404 inexistant -> {r['err404_status']}  clés={r['err404_keys']}")

        # 5) OAI-PMH Identify (bon chemin : /oai2)
        roai = g(c, "/oai2", params={"verb": "Identify"})
        r["oai_status"] = roai.status_code if roai else None
        r["oai_ct"] = roai.headers.get("content-type") if roai else None
        print(f"  OAI /oai2 Identify -> {r['oai_status']} ({r['oai_ct']})")

    return r


def _diff(prod: dict, test: dict) -> None:
    _section("DIFF prod ↔ apitest")

    def cmp(label: str, a, b) -> None:
        verdict = "IDENTIQUE" if a == b else "DIFFÈRE  "
        print(f"  [{verdict}] {label}")
        if a != b:
            print(f"        prod    : {a}")
            print(f"        apitest : {b}")

    cmp("data : clés de réponse", prod.get("data_keys"), test.get("data_keys"))
    cmp(
        "data : champs modération présents",
        prod.get("moderation_keys"),
        test.get("moderation_keys"),
    )
    cmp(
        "citation : statut HTTP",
        prod.get("citation_status"),
        test.get("citation_status"),
    )
    cmp(
        "citation : réelle (doi.org)",
        prod.get("citation_reelle"),
        test.get("citation_reelle"),
    )
    cmp("versions : statut", prod.get("versions_status"), test.get("versions_status"))
    cmp("IIIF info.json : statut", prod.get("iiif_status"), test.get("iiif_status"))
    cmp("404 : clés du corps", prod.get("err404_keys"), test.get("err404_keys"))
    cmp("404 : statut", prod.get("err404_status"), test.get("err404_status"))
    cmp("OAI /oai2 : statut", prod.get("oai_status"), test.get("oai_status"))
    cmp("vocabulaires (tailles)", prod.get("vocab"), test.get("vocab"))
    cmp("roles du compte", prod.get("roles"), test.get("roles"))


def main() -> None:
    _section("Audit parité Nakala — VOLET A (lecture seule, zéro pollution)")
    cle_prod = _charger_cle_prod()
    print(f"clé prod chargée : {'oui' if cle_prod else 'NON'}")
    if not cle_prod:
        print("  -> sans clé : /users/me et la liste readable seront vides/401.")

    prod = auditer(PROD, cle_prod, "PRODUCTION")
    test = auditer(APITEST, CLE_PUBLIQUE_APITEST, "APITEST (référence)")
    _diff(prod, test)
    print("\nFin de l'audit Volet A. Aucune écriture effectuée.")


if __name__ == "__main__":
    main()
