"""Audit de parité apitest ↔ production Nakala — VOLET B (écriture, prod).

Valide le **chemin de code d'écriture de ColleC** contre la **production**
`api.nakala.fr`, sur UN SEUL dépôt **`pending`** (jamais publié), supprimé en
fin de run. But : confirmer que les constats d'écriture documentés (issus
d'apitest) tiennent en prod — surtout l'**idempotence du round-trip**, qui
repose sur la canonicalisation des créateurs (si prod enrichissait autrement,
`diff_push` ferait de faux diffs à l'infini).

GARDE-FOUS (irréversibilité prod) :
  - dépôt créé en **`pending`** (`deposer_item` statut par défaut) → Nakala
    **n'enregistre PAS le DOI chez DataCite** tant que pending → réversible ;
  - **AUCUN appel de publication** (pas de `publier_*`, pas de `status=published`) ;
  - **suppression `supprimer_depot` en `finally`** (autorisée sur pending) → on
    re-lit ensuite pour confirmer le 404 (zéro résidu) ;
  - **clé prod OBLIGATOIRE** (env `NAKALA_PROD_KEY` ou `secrets/nakala_prod.key`)
    — refus si absente ou si c'est la clé publique apitest (ce script écrit en
    prod, pas sur le bac à sable). La clé n'est jamais imprimée.

Sondes (toutes sur l'unique dépôt pending) :
  1. création `deposer_item` → DOI + statut == pending
  2. #2 enrichissement créateur + #422 langue (lecture du dépôt)
  3. round-trip idempotent : `pousser_item` dry-run juste après dépôt → 0 diff
  4. round-trip réel : modif titre → push → relecture ; re-push → 0 diff
  5. fichiers granulaires : `ajouter_fichier` (+ description + embargo) puis
     `supprimer_fichier_donnee` ; vérifie additif / description / normalisation
     embargo / retrait ciblé par sha1
  6. cleanup : `supprimer_depot` → relecture → 404

Lancer (confirmation obligatoire — écrit en prod) :
    NAKALA_VOLET_B_CONFIRM=1 uv run python -X utf8 scripts/audit_parite_prod_volet_b.py
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import deposer_item, pousser_item
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


def _ecrire_jpg(chemin: Path, marqueur: int) -> None:
    sel = uuid.uuid4().hex.encode()
    chemin.write_bytes(b"\xff\xd8\xff VOLETB " + bytes([0x30 + marqueur]) + b" " + sel)


def _meta_createur(metas: list[dict]) -> dict | None:
    for m in metas:
        if m.get("propertyUri") == f"{NKL}creator":
            v = m.get("value")
            return v if isinstance(v, dict) else {"_brut": v}
    return None


def _meta_valeur(metas: list[dict], property_uri: str):
    for m in metas:
        if m.get("propertyUri") == property_uri:
            return m.get("value")
    return None


def main() -> None:
    _section("Audit parité Nakala — VOLET B (écriture, prod, pending only)")
    # Garde-fou anti-exécution accidentelle : ce script ÉCRIT en production.
    # Confirmation explicite obligatoire (cf. pattern NAKALA_ALLOW_PUBLISH de
    # la sonde granulaire). Sans elle, on n'écrit RIEN.
    if os.environ.get("NAKALA_VOLET_B_CONFIRM") != "1":
        print("!! Écriture en PRODUCTION — confirmation requise. Relancer avec :")
        print("     NAKALA_VOLET_B_CONFIRM=1 uv run python -X utf8 "
              "scripts/audit_parite_prod_volet_b.py")
        print("   (crée 1 dépôt pending jamais publié, supprimé en fin de run.)")
        return
    cle = _charger_cle_prod()
    if not cle:
        print(
            "!! Clé prod absente (NAKALA_PROD_KEY / secrets/nakala_prod.key). Abandon."
        )
        return
    if cle == CLE_PUBLIQUE_APITEST or "apitest" in HOTE:
        print("!! Ce script écrit en PRODUCTION : refuse la clé/hôte apitest. Abandon.")
        return
    print(f"hôte : {HOTE}  | clé prod : chargée (jamais imprimée)")
    print("garde-fou : dépôt pending, JAMAIS publié, supprimé en fin de run.")

    ecriture = NakalaEcritureClient(HOTE, api_key=cle, timeout=90)
    lecture = ClientLectureNakala(HOTE, api_key=cle, timeout=90)
    doi: str | None = None

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
            # ---- 1) création (pending) ----
            _section("1) Création dépôt pending (deposer_item)")
            f = creer_fonds(
                session, FormulaireFonds(cote="ZZTEST", titre="TEST audit parité")
            )
            item = creer_item(
                session,
                FormulaireItem(
                    cote="ZZTEST-001",
                    titre="TEST ColleC — audit parité prod (À SUPPRIMER)",
                    fonds_id=f.id,
                    date="2026",
                    langue="spa",
                    description="Dépôt de test Volet B — supprimé automatiquement.",
                    type_coar=TYPE_LIVRE,
                    metadonnees={"createurs": ["Test, Hugo"], "sujets": ["Sonde"]},
                ),
            )
            _ecrire_jpg(scans / "page1.jpg", 1)
            session.add(
                Fichier(
                    item_id=item.id,
                    nom_fichier="page1.jpg",
                    racine="scans",
                    chemin_relatif="page1.jpg",
                    ordre=1,
                )
            )
            session.commit()
            rapport = deposer_item(
                session,
                ecriture,
                item,
                racines=racines,
                dry_run=False,
                cree_par="audit-volet-b",
            )
            doi = rapport.doi
            depot = lecture.lire_depot(doi)
            print(f"  DOI créé : {doi} | statut : {depot.get('status')!r}")
            assert depot.get("status") == "pending", (
                "statut inattendu (doit rester pending)"
            )

            # ---- 2) enrichissement créateur (#2) + langue RFC5646 (#422) ----
            _section("2) #2 créateur enrichi + #422 langue RFC5646")
            metas = depot.get("metas") or []
            createur = _meta_createur(metas)
            print(
                f"  créateur stocké : clés = {sorted(createur.keys()) if createur else None}"
            )
            enrichi = bool(createur and {"authorId", "fullName"} <= set(createur))
            print(
                f"    [{'OK' if enrichi else '!!'}] enrichissement authorId/fullName "
                f"{'présent (== apitest)' if enrichi else 'ABSENT (diffère d apitest)'}"
            )
            langue = _meta_valeur(metas, "http://purl.org/dc/terms/language")
            print(
                f"  langue stockée : {langue!r}  (ColleC a envoyé spa -> attendu 'es')"
            )
            print(
                f"    [{'OK' if langue == 'es' else '!!'}] conversion #422 "
                f"{'conforme' if langue == 'es' else 'NON conforme'}"
            )

            # ---- 3) round-trip idempotent juste après dépôt ----
            _section("3) Round-trip idempotent (pousser_item dry-run, 0 diff attendu)")
            r = pousser_item(session, lecture, ecriture, item, dry_run=True)
            print(
                f"  diffs = {len(r.diffs)}  (attendu 0 — canonicalisation créateurs OK sur prod)"
            )
            print(
                f"    [{'OK' if not r.diffs else '!!'}] "
                f"{'idempotent' if not r.diffs else 'FAUX DIFF : ' + json.dumps(r.diffs)[:300]}"
            )

            # ---- 4) round-trip réel : modif titre ----
            _section("4) Round-trip réel : modif titre -> PUT -> relecture -> re-push")
            item.titre = "TEST ColleC — titre modifié (À SUPPRIMER)"
            session.commit()
            r1 = pousser_item(
                session,
                lecture,
                ecriture,
                item,
                dry_run=False,
                modifie_par="audit-volet-b",
            )
            print(f"  push réel : {len(r1.diffs)} diff(s) appliqué(s)")
            titre_relu = _meta_valeur(
                lecture.lire_depot(doi).get("metas") or [],
                "http://nakala.fr/terms#title",
            )
            print(f"  titre relu côté Nakala : {titre_relu!r}")
            r2 = pousser_item(session, lecture, ecriture, item, dry_run=True)
            print(f"  re-push dry-run : {len(r2.diffs)} diff(s)")
            ok4 = bool(r1.diffs) and not r2.diffs
            print(
                f"    [{'OK' if ok4 else '!!'}] round-trip "
                f"{'appliqué puis idempotent' if ok4 else 'anomalie'}"
            )

            # ---- 5) fichiers granulaires + description + embargo ----
            _section("5) Granulaire : POST (desc+embargo) puis DELETE par sha1")
            _ecrire_jpg(scans / "page2.jpg", 2)
            up = ecriture.uploader_fichier(scans / "page2.jpg")
            sha1_b = up["sha1"]
            ecriture.ajouter_fichier(
                doi,
                sha1_b,
                description="Transcription de test (H11)",
                embargoed="2099-12-31",
            )
            files = lecture.lire_depot(doi).get("files") or []
            nb = len(files)
            ajoute = next((x for x in files if x.get("sha1") == sha1_b), None)
            print(f"  après POST : {nb} fichier(s) (additif si == 2)")
            if ajoute:
                print(f"    description : {ajoute.get('description')!r}")
                print(f"    embargoed   : {ajoute.get('embargoed')!r}")
                print(
                    f"    humanReadableEmbargoedDelay : {ajoute.get('humanReadableEmbargoedDelay')!r}"
                )
                print(f"    clés fichier : {sorted(ajoute.keys())}")
            ecriture.supprimer_fichier_donnee(doi, sha1_b)
            files2 = lecture.lire_depot(doi).get("files") or []
            print(
                f"  après DELETE(sha1) : {len(files2)} fichier(s) "
                f"({'retrait ciblé OK' if len(files2) == nb - 1 else 'anomalie'})"
            )

        finally:
            # ---- 6) cleanup (toujours, même en cas d'échec) ----
            _section("6) Cleanup : suppression du dépôt pending")
            if doi:
                try:
                    ecriture.supprimer_depot(doi)
                    # GET brut (ne lève pas) pour constater le 404 sans que
                    # _verifier_statut de lire_depot ne masque le résultat.
                    verif = ecriture._requete("GET", f"/datas/{doi}")
                    code = verif.status_code
                    print(f"  re-lecture après suppression : HTTP {code}")
                    print(
                        f"    [{'OK' if code == 404 else '!!'}] "
                        f"dépôt {'bien supprimé (zéro résidu)' if code == 404 else 'TOUJOURS présent — supprimer manuellement : ' + doi}"
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"  !! échec suppression {doi} : {e}")
                    print(f"     -> SUPPRIMER MANUELLEMENT le dépôt {doi}")
            else:
                print("  (aucun dépôt créé — rien à nettoyer)")
            session.close()
            ecriture.fermer()
            lecture.fermer()


if __name__ == "__main__":
    main()
