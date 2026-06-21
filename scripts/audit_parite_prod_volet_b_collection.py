"""Audit de parité prod Nakala — VOLET B (écriture) — niveau COLLECTION.

Complète `audit_parite_prod_volet_b.py` (qui couvre le niveau donnée/item) en
éprouvant le **chemin d'écriture COLLECTION de ColleC** contre la production
`api.nakala.fr` : création de la collection (`deposer_collection`), round-trip
de ses métadonnées (`pousser_metadonnees_collection`, qui réutilise `diff_push`
avec **fusion** — ColleC ne gère que titre/description et préserve les metas
Nakala non modélisées). Point critique, comme pour l'item : l'**idempotence**
du round-trip sur prod.

Tout est réversible : la collection est créée **`private`** et son item
**`pending`** (aucun DOI DataCite minté), tous deux **supprimés en fin de run**
(`supprimer_collection` + `supprimer_depot`), avec vérification 404.

GARDE-FOUS identiques au Volet B item :
  - confirmation obligatoire `NAKALA_VOLET_B_CONFIRM=1` (écrit en prod) ;
  - clé prod (env `NAKALA_PROD_KEY` / `secrets/nakala_prod.key`), jamais
    imprimée, refus de la clé/hôte apitest ;
  - AUCUNE publication ; suppression en `finally`.

Lancer (confirmation obligatoire — écrit en prod) :
    NAKALA_VOLET_B_CONFIRM=1 uv run python -X utf8 scripts/audit_parite_prod_volet_b_collection.py
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import (
    deposer_collection,
    pousser_metadonnees_collection,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Base, Fichier

HOTE = os.environ.get("NAKALA_HOST", "https://api.nakala.fr").rstrip("/")
CLE_PUBLIQUE_APITEST = "01234567-89ab-cdef-0123-456789abcdef"
TYPE_LIVRE = "http://purl.org/coar/resource_type/c_2f33"
NKL = "http://nakala.fr/terms#"


def _section(t: str) -> None:
    print(f"\n{'=' * 72}\n  {t}\n{'=' * 72}")


def _nettoyer_cle(brut: str | None) -> str | None:
    if not brut:
        return None
    cle = brut.lstrip(chr(0xFEFF)).strip()
    return cle or None


def _charger_cle_prod() -> str | None:
    cle = _nettoyer_cle(os.environ.get("NAKALA_PROD_KEY"))
    if cle:
        return cle
    f = Path("secrets/nakala_prod.key")
    return _nettoyer_cle(f.read_text(encoding="utf-8-sig")) if f.is_file() else None


def _ecrire_jpg(chemin: Path) -> None:
    chemin.write_bytes(b"\xff\xd8\xff VOLETB-COL " + uuid.uuid4().hex.encode())


def _meta_valeur(metas: list[dict], property_uri: str):
    for m in metas:
        if m.get("propertyUri") == property_uri:
            return m.get("value")
    return None


def _supprimer_verifie(ecriture, base: str, doi: str, fn) -> bool:
    """Supprime puis VÉRIFIE par GET, avec retry — prod a une cohérence
    éventuelle : un DELETE peut renvoyer 404 alors que la ressource est
    encore là (cf. run échoué). On boucle jusqu'à GET 404 confirmé."""
    for essai in range(5):
        try:
            fn(doi)
        except Exception as e:  # noqa: BLE001 — 404/5xx transitoire toléré
            print(f"    (delete {doi} essai {essai + 1}: {type(e).__name__})")
        try:
            code = ecriture._requete("GET", f"{base}/{doi}").status_code
        except Exception:  # noqa: BLE001 — blip réseau pendant la vérif
            code = None
        if code == 404:
            return True
        time.sleep(2)
    return False


def main() -> None:
    _section("Audit parité — VOLET B niveau COLLECTION (écriture, prod)")
    if os.environ.get("NAKALA_VOLET_B_CONFIRM") != "1":
        print("!! Écriture en PRODUCTION — confirmation requise. Relancer avec :")
        print(
            "     NAKALA_VOLET_B_CONFIRM=1 uv run python -X utf8 "
            "scripts/audit_parite_prod_volet_b_collection.py"
        )
        print("   (crée 1 collection private + 1 item pending, supprimés en fin.)")
        return
    cle = _charger_cle_prod()
    if not cle:
        print("!! Clé prod absente. Abandon.")
        return
    if cle == CLE_PUBLIQUE_APITEST or "apitest" in HOTE:
        print("!! Écrit en PRODUCTION : refuse la clé/hôte apitest. Abandon.")
        return
    print(f"hôte : {HOTE}  | clé prod : chargée (jamais imprimée)")
    print(
        "garde-fou : collection private + item pending, JAMAIS publiés, supprimés en fin."
    )

    ecriture = NakalaEcritureClient(HOTE, api_key=cle, timeout=90)
    lecture = ClientLectureNakala(HOTE, api_key=cle, timeout=90)
    coll_doi: str | None = None
    item_doi: str | None = None

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        db = tmp_dir / "test.db"
        engine = creer_engine(db)
        Base.metadata.create_all(engine)
        engine.dispose()
        scans = tmp_dir / "scans"
        scans.mkdir()
        racines = {"scans": scans}
        session = creer_session_factory(creer_engine(db))()

        try:
            # ---- 1) deposer_collection (collection private + item pending) ----
            _section("1) deposer_collection : collection private + item pending")
            fonds = creer_fonds(
                session,
                FormulaireFonds(cote="ZZTESTC", titre="TEST collection — audit parité"),
            )
            miroir = fonds.collection_miroir
            item = creer_item(
                session,
                FormulaireItem(
                    cote="ZZTESTC-001",
                    titre="Item de test collection (À SUPPRIMER)",
                    fonds_id=fonds.id,
                    date="2026",
                    langue="spa",
                    type_coar=TYPE_LIVRE,
                    metadonnees={"createurs": ["Test, Hugo"]},
                ),
            )
            _ecrire_jpg(scans / "p1.jpg")
            session.add(
                Fichier(
                    item_id=item.id,
                    nom_fichier="p1.jpg",
                    racine="scans",
                    chemin_relatif="p1.jpg",
                    ordre=1,
                )
            )
            session.commit()
            deposer_collection(
                session,
                ecriture,
                miroir,
                racines=racines,
                dry_run=False,
                cree_par="audit-volet-b-col",
            )
            session.refresh(miroir)
            session.refresh(item)
            coll_doi = miroir.doi_nakala
            item_doi = item.doi_nakala
            print(f"  collection créée : {coll_doi} | item : {item_doi}")

            # ---- 2) lecture de la collection ----
            _section("2) Lecture collection (forme + statut + titre)")
            coll = lecture.lire_collection(coll_doi)
            print(f"  statut : {coll.get('status')!r} | clés : {sorted(coll.keys())}")
            titre = _meta_valeur(coll.get("metas") or [], f"{NKL}title")
            print(f"  titre stocké : {titre!r}")
            assert coll.get("status") == "private", "collection devrait être private"

            # ---- 3) round-trip idempotent (fusion + diff_push) ----
            _section("3) pousser_metadonnees_collection dry-run → 0 diff attendu")
            r = pousser_metadonnees_collection(
                session, lecture, ecriture, miroir, dry_run=True
            )
            print(
                f"  diffs = {len(r.diffs)}  (attendu 0 — fusion idempotente sur prod)"
            )
            print(
                f"    [{'OK' if not r.diffs else '!!'}] "
                f"{'idempotent' if not r.diffs else 'FAUX DIFF : ' + str(r.diffs)[:300]}"
            )

            # ---- 4) round-trip réel : modif titre ----
            # Non bloquant : prod peut renvoyer un 500 transitoire — on le
            # rapporte sans avorter le run (le cleanup doit toujours tourner).
            _section("4) Modif titre collection → PUT → relecture → re-push")
            try:
                miroir.titre = "TEST collection — titre modifié (À SUPPRIMER)"
                session.commit()
                r1 = pousser_metadonnees_collection(
                    session, lecture, ecriture, miroir, dry_run=False
                )
                titre2 = _meta_valeur(
                    lecture.lire_collection(coll_doi).get("metas") or [], f"{NKL}title"
                )
                r2 = pousser_metadonnees_collection(
                    session, lecture, ecriture, miroir, dry_run=True
                )
                print(
                    f"  push réel : {len(r1.diffs)} diff(s) | titre relu : {titre2!r} | "
                    f"re-push : {len(r2.diffs)} diff(s)"
                )
                ok4 = bool(r1.diffs) and not r2.diffs
                print(
                    f"    [{'OK' if ok4 else '!!'}] round-trip "
                    f"{'appliqué puis idempotent' if ok4 else 'anomalie'}"
                )
            except Exception as e:  # noqa: BLE001
                print(f"    [!!] PUT collection a échoué : {type(e).__name__}: {e}")
                print(
                    "       (probablement transitoire — cf. PUT /collections "
                    "validé 204 par ailleurs ; relancer pour confirmer)"
                )

        finally:
            # ---- 5) cleanup : collection + item, vérif 404 avec retry ----
            _section("5) Cleanup : suppression collection + item (retry vérifié)")
            if coll_doi:
                ok = _supprimer_verifie(
                    ecriture, "/collections", coll_doi, ecriture.supprimer_collection
                )
                print(
                    f"  collection {coll_doi} -> {'OK supprimée ✅' if ok else '!! TOUJOURS LÀ ⚠️'}"
                )
            if item_doi:
                ok = _supprimer_verifie(
                    ecriture, "/datas", item_doi, ecriture.supprimer_depot
                )
                print(
                    f"  item {item_doi} -> {'OK supprimé ✅' if ok else '!! TOUJOURS LÀ ⚠️'}"
                )
            session.close()
            ecriture.fermer()
            lecture.fermer()


if __name__ == "__main__":
    main()
