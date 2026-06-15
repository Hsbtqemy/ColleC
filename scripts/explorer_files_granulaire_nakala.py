"""Sonde préalable T2 (backlog-nakala-api) : endpoints granulaires de
fichiers `POST /datas/{id}/files` et `DELETE /datas/{id}/files/{fileId}`,
AVANT de réécrire `pousser_fichiers_item` (qui passe aujourd'hui par le
`PUT /datas` `files[]` qui remplace tout).

Questions de la sonde (cf. ticket T2) :
  A. `POST …/files` est-il additif ? Quelle forme de réponse ? Le `name`
     est-il repris de l'upload (le schéma du corps ne porte que sha1) ?
  B. Que vaut `{fileIdentifier}` dans le DELETE — le sha1 ou un id propre ?
  C. L'ordre est-il contrôlable (append en fin ? tri ?) ?
  D. Comportement sur dépôt publié — GATÉ derrière NAKALA_ALLOW_PUBLISH=1
     (publier sur apitest est irréversible et laisse un dépôt indestructible).

Toutes les sondes A/B/C amorcent des dépôts `pending` nettoyés en fin
(DELETE best-effort). Lecture seule sur la spec, écriture uniquement sur
des dépôts jetables créés par la sonde.

Lancer :
    uv run python -X utf8 scripts/explorer_files_granulaire_nakala.py
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import deposer_item
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Base, Fichier, Item

CLE = os.environ.get("NAKALA_API_KEY", "01234567-89ab-cdef-0123-456789abcdef")
HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
AUTORISER_PUBLICATION = os.environ.get("NAKALA_ALLOW_PUBLISH") == "1"
TYPE_LIVRE = "http://purl.org/coar/resource_type/c_2f33"
NKL = "http://nakala.fr/terms#"


def _print_section(titre: str) -> None:
    print()
    print("=" * 70)
    print(f"  {titre}")
    print("=" * 70)


def _amorcer_db(tmp_dir: Path) -> Path:
    db = tmp_dir / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _ecrire_jpg(chemin: Path, marqueur: int) -> None:
    # Sel uuid : contenu UNIQUE a chaque ecriture -> sha1 frais. Sinon le
    # meme contenu rejoue entre deux runs reutilise un sha1 deja consomme
    # cote Nakala (upload a usage unique) -> 500/422 au POST /datas.
    sel = uuid.uuid4().hex.encode()
    chemin.write_bytes(b"\xff\xd8\xff GRANULAIRE " + bytes([0x30 + marqueur]) + b" " + sel)


def _deposer_avec_n_fichiers(
    ecriture: NakalaEcritureClient, parent: Path,
    *, n: int, cote: str, fonds_cote: str,
) -> tuple[str, list[str], Path]:
    """Dépôt pending à n fichiers via `deposer_item`. Renvoie
    (doi, sha1s_dans_l_ordre, dossier_scans) — le dossier scans est
    réutilisé pour uploader des fichiers additionnels dans la sonde."""
    tmp_dir = parent / f"granul_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db = _amorcer_db(tmp_dir)
    scans = tmp_dir / "scans"
    scans.mkdir(exist_ok=True)
    racines = {"scans": scans}

    with _session(db) as s:
        f = creer_fonds(s, FormulaireFonds(cote=fonds_cote, titre=f"{fonds_cote} granulaire"))
        item = creer_item(s, FormulaireItem(
            cote=cote, titre="Sonde granulaire T2", fonds_id=f.id,
            date="2026", langue="fra", description="Sonde POST/DELETE files",
            type_coar=TYPE_LIVRE,
            metadonnees={"createurs": ["Test, Hugo"], "sujets": ["Sonde"]},
        ))
        for i in range(1, n + 1):
            nom = f"fichier{i}.jpg"
            _ecrire_jpg(scans / nom, i)
            s.add(Fichier(
                item_id=item.id, nom_fichier=nom, racine="scans",
                chemin_relatif=nom, ordre=i,
            ))
        s.commit()
        rapport = deposer_item(s, ecriture, item, racines=racines,
                               dry_run=False, cree_par="sonde")
        doi = rapport.doi
        assert doi
        sha1s = [
            fic.sha1_nakala for fic in sorted(
                s.scalars(select(Fichier).join(Item).where(Item.cote == cote)).all(),
                key=lambda x: x.ordre,
            )
        ]
    return doi, sha1s, scans


def _noms_sha1(files: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(f.get("name"), (f.get("sha1") or "")[:8]) for f in files]


def sonde_a_post_additif(ecriture, lecture, tmp_dir: Path) -> None:
    """A — POST /datas/{id}/files ajoute-t-il sans toucher l'existant ?
    Le `name` est-il repris de l'upload (corps = sha1 seul) ?"""
    _print_section("A - POST /datas/{id}/files : additif ? forme reponse ? name ?")
    doi, sha1s, scans = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote="GA-001", fonds_cote="GA")
    print(f"Depot cree : {doi} (1 fichier)")

    avant = lecture.lire_depot(doi).get("files") or []
    print(f"Avant POST : {len(avant)} fichier(s) : {_noms_sha1(avant)}")

    # Upload d'un fichier additionnel (hors depot) -> sha1 frais.
    nouveau = scans / "ajoute_via_post.jpg"
    _ecrire_jpg(nouveau, 9)
    desc = ecriture.uploader_fichier(nouveau)
    sha1_b, nom_upload = desc["sha1"], desc.get("name")
    print(f"Upload additionnel : name={nom_upload!r} sha1={sha1_b[:8]}...")

    # POST corps = sha1 SEUL (le schema File ne porte pas 'name').
    print("\nPOST /datas/{id}/files corps={sha1} (sans name)")
    code, charge = ecriture.ajouter_fichier_explo(doi, {"sha1": sha1_b})
    print(f"  -> HTTP {code} ; corps reponse = {json.dumps(charge, ensure_ascii=False)[:300]}")

    apres = lecture.lire_depot(doi).get("files") or []
    print(f"\nApres POST : {len(apres)} fichier(s) : {_noms_sha1(apres)}")
    sha1s_apres = [f.get("sha1") for f in apres]
    if sha1s[0] in sha1s_apres and sha1_b in sha1s_apres and len(apres) == 2:
        print("\n[OK] A1 ADDITIF : POST ajoute sans retirer l'existant.")
    elif sha1_b in sha1s_apres and sha1s[0] not in sha1s_apres:
        print("\n[!] A1 REMPLACE : l'existant a disparu (inattendu).")
    else:
        print(f"\n[?] A1 AMBIGU : {sha1s_apres}")

    # Le name a-t-il ete repris de l'upload ?
    b = next((f for f in apres if f.get("sha1") == sha1_b), None)
    if b is not None:
        print(f"\nFichier ajoute cote Nakala : name={b.get('name')!r}")
        print(f"  cles disponibles : {sorted(b.keys())}")
        if b.get("name") == nom_upload:
            print("  [OK] A2 : le name est repris de l'upload.")
        else:
            print("  [!] A2 : le name differe de l'upload "
                  f"({b.get('name')!r} != {nom_upload!r}).")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def sonde_b_delete_identifier(ecriture, lecture, tmp_dir: Path) -> None:
    """B — DELETE /datas/{id}/files/{fileIdentifier} : sha1 ou id propre ?"""
    _print_section("B - DELETE files/{fileIdentifier} : sha1 ou id propre ?")
    doi, sha1s, scans = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=2, cote="GB-001", fonds_cote="GB")
    sha1_a, sha1_b = sha1s
    print(f"Depot cree : {doi} (2 fichiers)")

    # Inspecte la forme renvoyee par GET /datas/{id}/files (peut differer
    # de la projection 'files' de lire_depot).
    code_get, files_get = ecriture.lire_files_explo(doi)
    print(f"\nGET /datas/{{id}}/files -> HTTP {code_get}")
    if isinstance(files_get, list) and files_get:
        print(f"  cles d'un fichier : {sorted(files_get[0].keys())}")
        print("  exemple complet :")
        print(json.dumps(files_get[0], indent=4, ensure_ascii=False)[:600])
    else:
        print(f"  corps : {json.dumps(files_get, ensure_ascii=False)[:300]}")

    # Tentative 1 : DELETE avec le sha1 du 2e fichier.
    print(f"\nDELETE files/{sha1_b[:8]}... (sha1 du fichier2)")
    code = ecriture.supprimer_fichier_explo(doi, sha1_b)
    print(f"  -> HTTP {code}")
    apres = lecture.lire_depot(doi).get("files") or []
    sha1s_apres = [f.get("sha1") for f in apres]
    print(f"  Apres : {len(apres)} fichier(s) : {_noms_sha1(apres)}")

    if code in (200, 204) and sha1_b not in sha1s_apres and sha1_a in sha1s_apres:
        print("\n[OK] B CONFIRME : fileIdentifier == sha1. Suppression ciblee OK.")
    elif code == 404:
        print("\n[!] B : sha1 REFUSE (404) -> fileIdentifier n'est PAS le sha1.")
        # Cherche un autre id dans la reponse GET.
        if isinstance(files_get, list) and files_get:
            autres = {k: v for k, v in files_get[0].items()
                      if k != "sha1" and isinstance(v, (str, int))}
            print(f"     Candidats id alternatifs : {autres}")
            for cle in ("id", "identifier", "fileIdentifier", "uuid"):
                val = files_get[0].get(cle)
                if val:
                    print(f"     Reessai DELETE avec {cle}={val}")
                    code2 = ecriture.supprimer_fichier_explo(doi, str(val))
                    print(f"       -> HTTP {code2}")
                    if code2 in (200, 204):
                        print(f"\n[OK] B : fileIdentifier == '{cle}'.")
                        break
    else:
        print(f"\n[?] B AMBIGU : HTTP {code}, fichiers restants {sha1s_apres}")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def _poster_paire(ecriture, lecture, tmp_dir, *, cote, premier, second):
    """Depose un fichier de base puis POST deux fichiers dans l'ordre
    (premier, second). Renvoie (ordre_noms_relu, {nom: sha1})."""
    doi, _, scans = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote=cote, fonds_cote=cote.split("-")[0])
    sha1_par_nom = {}
    for marqueur, nom in ((7, premier), (8, second)):
        p = scans / nom
        _ecrire_jpg(p, marqueur)
        desc = ecriture.uploader_fichier(p)
        sha1_par_nom[nom] = desc["sha1"]
        ecriture.ajouter_fichier_explo(doi, {"sha1": desc["sha1"]})
    apres = lecture.lire_depot(doi).get("files") or []
    postes = [f for f in apres if f.get("name") in (premier, second)]
    ordre_noms = [f.get("name") for f in postes]
    try:
        ecriture.supprimer_depot(doi)
    except Exception:  # noqa: BLE001
        pass
    return ordre_noms, sha1_par_nom


def sonde_c_ordre(ecriture, lecture, tmp_dir: Path) -> None:
    """C — POST successifs : quelle regle d'ordre ? N essais pour SEPARER
    LIFO (ordre d'appel inverse) du TRI PAR SHA1, qui coincidaient sur 2
    essais. Un essai est *decisif* quand les deux hypotheses predisent un
    ordre different (le 1er POSTe a le plus grand sha1)."""
    _print_section("C - POST successifs : LIFO vs tri sha1 (N essais decisifs)")
    n_essais = 8
    premier, second = "fa_premier.jpg", "fb_second.jpg"  # POST premier puis second
    lifo_ok = sha1desc_ok = sha1asc_ok = fifo_ok = 0
    decisifs = 0
    for i in range(1, n_essais + 1):
        noms, m = _poster_paire(
            ecriture, lecture, tmp_dir, cote=f"GC-{i:03d}",
            premier=premier, second=second)
        s_premier, s_second = m[premier], m[second]
        pred_lifo = [second, premier]                       # dernier POSTe en tete
        pred_fifo = [premier, second]                        # ordre d'appel
        pred_sha1desc = ([premier, second] if s_premier > s_second
                         else [second, premier])
        pred_sha1asc = ([premier, second] if s_premier < s_second
                        else [second, premier])
        decisif = pred_lifo != pred_sha1desc  # premier a le plus grand sha1
        lifo_ok += noms == pred_lifo
        fifo_ok += noms == pred_fifo
        sha1desc_ok += noms == pred_sha1desc
        sha1asc_ok += noms == pred_sha1asc
        decisifs += decisif
        marque = " <== DECISIF (LIFO!=sha1desc)" if decisif else ""
        print(f"  essai {i}: relu={['…'+n[1:4] for n in noms]} "
              f"sha1(premier={s_premier[:6]} second={s_second[:6]}) "
              f"=> {'LIFO' if noms==pred_lifo else ''}"
              f"{'/sha1desc' if noms==pred_sha1desc else ''}"
              f"{'/sha1asc' if noms==pred_sha1asc else ''}"
              f"{'/FIFO' if noms==pred_fifo else ''}{marque}")

    print(f"\n--- Diagnostic ({n_essais} essais, dont {decisifs} decisifs) ---")
    print(f"  LIFO     : {lifo_ok}/{n_essais}")
    print(f"  sha1 desc: {sha1desc_ok}/{n_essais}")
    print(f"  sha1 asc : {sha1asc_ok}/{n_essais}")
    print(f"  FIFO     : {fifo_ok}/{n_essais}")
    if decisifs == 0:
        print("\n[?] Aucun essai decisif (sha1 jamais favorable au 1er POSTe) "
              "— relancer.")
    elif lifo_ok == n_essais and sha1desc_ok < n_essais:
        print("\n[OK] C = LIFO confirme : tient sur TOUS les essais, y compris")
        print("     les decisifs ou le tri sha1 predisait l'inverse. POST ne")
        print("     controle pas l'ordre -> PUT files[] final requis (H5).")
    elif sha1desc_ok == n_essais and lifo_ok < n_essais:
        print("\n[OK] C = TRI SHA1 DESCENDANT : tient sur tous les essais, LIFO non.")
        print("     Ordre non controlable (sha1 = hash) -> PUT files[] requis.")
    elif sha1asc_ok == n_essais and lifo_ok < n_essais:
        print("\n[OK] C = TRI SHA1 ASCENDANT.")
    else:
        print(f"\n[?] INDETERMINE : aucune hypothese unique a {n_essais}/{n_essais}.")


def sonde_e_delete_dernier(ecriture, lecture, tmp_dir: Path) -> None:
    """E — DELETE du dernier fichier : Nakala laisse-t-il un depot a 0
    fichier ? (le PUT files=[] est ignore, H3 ; le DELETE granulaire
    pourrait, lui, vider — determinant pour '--retirer-orphelins' quand
    TOUT est orphelin)."""
    _print_section("E - DELETE du dernier fichier -> depot a 0 fichier autorise ?")
    doi, sha1s, _ = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote="GE-001", fonds_cote="GE")
    print(f"Depot cree : {doi} (1 fichier)")
    code = ecriture.supprimer_fichier_explo(doi, sha1s[0])
    print(f"DELETE du seul fichier -> HTTP {code}")
    apres = lecture.lire_depot(doi).get("files") or []
    print(f"Apres : {len(apres)} fichier(s)")
    if code in (200, 204) and len(apres) == 0:
        print("\n[OK] E VIDE : Nakala autorise un depot a 0 fichier via DELETE")
        print("     granulaire (contrairement au PUT files=[] ignore, H3).")
        print("     -> cas '--retirer-orphelins, tout est orphelin' viable.")
    elif code >= 400:
        print(f"\n[!] E REFUS : Nakala refuse de retirer le dernier fichier "
              f"(HTTP {code}). -> preserver >=1 fichier, comme le garde-fou actuel.")
    else:
        print(f"\n[?] E AMBIGU : HTTP {code}, {len(apres)} fichier(s) restant(s).")
    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def sonde_f_post_fantome(ecriture, lecture, tmp_dir: Path) -> None:
    """F — POST /files avec un sha1 jamais uploade : 404 comme le PUT (H4) ?"""
    _print_section("F - POST /files avec sha1 fantome -> erreur (404 ?)")
    doi, sha1s, _ = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote="GF-001", fonds_cote="GF")
    fantome = "deadbeef" * 5  # 40 hex valides mais jamais uploades
    print(f"Depot cree : {doi} ; POST sha1 fantome {fantome[:8]}...")
    code, charge = ecriture.ajouter_fichier_explo(doi, {"sha1": fantome})
    print(f"  -> HTTP {code} : {json.dumps(charge, ensure_ascii=False)[:200]}")
    apres = lecture.lire_depot(doi).get("files") or []
    sha1s_apres = [f.get("sha1") for f in apres]
    if code == 404:
        print("\n[OK] F : sha1 fantome -> 404 (comme le PUT, H4). Valider en amont.")
    elif code >= 400 and fantome not in sha1s_apres:
        print(f"\n[OK] F : sha1 fantome refuse (HTTP {code}), depot inchange.")
    elif fantome in sha1s_apres:
        print("\n[?] F ETONNANT : Nakala a accepte un sha1 fantome.")
    else:
        print(f"\n[?] F : HTTP {code}, fantome absent ({len(apres)} fichier(s)).")
    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def sonde_g_doublon(ecriture, lecture, tmp_dir: Path) -> None:
    """G — re-POST d'un sha1 deja attache : 409 + fichier existant intact ?"""
    _print_section("G - re-POST sha1 deja attache -> 409 + fichier intact ?")
    doi, sha1s, _ = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote="GG-001", fonds_cote="GG")
    print(f"Depot cree : {doi} (1 fichier, sha1 {sha1s[0][:8]}...)")
    code, charge = ecriture.ajouter_fichier_explo(doi, {"sha1": sha1s[0]})
    print(f"  re-POST meme sha1 -> HTTP {code} : "
          f"{json.dumps(charge, ensure_ascii=False)[:160]}")
    apres = lecture.lire_depot(doi).get("files") or []
    intact = len(apres) == 1 and apres[0].get("sha1") == sha1s[0]
    if code == 409 and intact:
        print("\n[OK] G : 409 + fichier existant INTACT (pas de doublon) -> "
              "traiter le 409 en no-op idempotent.")
    elif intact:
        print(f"\n[OK] G : HTTP {code}, fichier intact (1 exemplaire).")
    else:
        print(f"\n[?] G : HTTP {code}, {len(apres)} fichier(s) (doublon cote distant ?).")
    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def sonde_d_publie(ecriture, lecture, tmp_dir: Path) -> None:
    """D — comportement sur depot PUBLIE. GATE : irreversible sur apitest."""
    _print_section("D - depot PUBLIE : POST/DELETE files acceptes ou refuses ?")
    if not AUTORISER_PUBLICATION:
        print("[SKIP] NAKALA_ALLOW_PUBLISH != 1 — sonde non lancee.")
        print("  Publier sur apitest est irreversible et laisse un depot")
        print("  indestructible (DELETE reserve au pending) -> pollution du")
        print("  serveur de test partage. Relancer avec NAKALA_ALLOW_PUBLISH=1")
        print("  UNIQUEMENT si ce cout est explicitement accepte.")
        return
    doi, sha1s, scans = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote="GD-001", fonds_cote="GD")
    print(f"Depot cree : {doi} ; publication (IRREVERSIBLE)...")
    ecriture.modifier_depot(doi, status="published")
    p = scans / "post_publie.jpg"
    _ecrire_jpg(p, 5)
    desc = ecriture.uploader_fichier(p)
    code, charge = ecriture.ajouter_fichier_explo(doi, {"sha1": desc["sha1"]})
    print(f"POST files sur publie -> HTTP {code} : "
          f"{json.dumps(charge, ensure_ascii=False)[:200]}")
    print("  (depot publie NON nettoye — indestructible)")


def main() -> None:
    # Methodes d'exploration greffees sur le client (renvoient le code HTTP
    # brut sans lever, pour observer 200/204/404/409).
    def ajouter_fichier_explo(self, doi: str, corps: dict):
        reponse = self._requete("POST", f"/datas/{doi}/files", json=corps)
        try:
            charge = reponse.json()
        except Exception:  # noqa: BLE001
            charge = reponse.text
        return reponse.status_code, charge

    def supprimer_fichier_explo(self, doi: str, file_id: str):
        reponse = self._requete("DELETE", f"/datas/{doi}/files/{file_id}")
        return reponse.status_code

    def lire_files_explo(self, doi: str):
        reponse = self._requete("GET", f"/datas/{doi}/files")
        try:
            return reponse.status_code, reponse.json()
        except Exception:  # noqa: BLE001
            return reponse.status_code, reponse.text

    NakalaEcritureClient.ajouter_fichier_explo = ajouter_fichier_explo
    NakalaEcritureClient.supprimer_fichier_explo = supprimer_fichier_explo
    NakalaEcritureClient.lire_files_explo = lire_files_explo

    print(f"Cible : {HOTE}")
    print(f"Cle   : {CLE[:13]}... (publique apitest)")
    print(f"Publication autorisee (sonde D) : {AUTORISER_PUBLICATION}")

    # ignore_cleanup_errors : sous Windows, les engines SQLite gardent un
    # handle ouvert sur test.db -> rmtree du temp echoue (cosmetique).
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        ecriture = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
        lecture = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
        try:
            sonde_a_post_additif(ecriture, lecture, tmp_dir)
            sonde_b_delete_identifier(ecriture, lecture, tmp_dir)
            sonde_c_ordre(ecriture, lecture, tmp_dir)
            sonde_e_delete_dernier(ecriture, lecture, tmp_dir)
            sonde_f_post_fantome(ecriture, lecture, tmp_dir)
            sonde_g_doublon(ecriture, lecture, tmp_dir)
            sonde_d_publie(ecriture, lecture, tmp_dir)
        finally:
            ecriture.fermer()
            lecture.fermer()


if __name__ == "__main__":
    main()
