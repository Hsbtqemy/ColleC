"""Sonde « piste #1 » (jumeau de T2) : endpoints granulaires de métadonnées
`POST /datas/{id}/metadatas` et `DELETE /datas/{id}/metadatas`, AVANT
d'envisager de réécrire le push de métadonnées (qui passe aujourd'hui par
le `PUT /datas` `metas[]` qui REMPLACE tout, d'où la danse `diff_push` +
canonicalisation des créateurs).

Enjeu ColleC. Si `POST /metadatas` est **additif** (ajoute une meta sans
toucher les autres) et `DELETE /metadatas` **granulaire à la valeur**, le
push de métadonnées pourrait devenir granulaire comme l'a été le push de
fichiers (T2) : ne toucher QUE les metas qui changent → plus de
remplacement total, et le faux-diff « créateur enrichi au stockage »
disparaît (on ne renvoie plus les créateurs inchangés). Si au contraire le
DELETE est par-propriété (efface toutes les valeurs d'un propertyUri) ou si
le contrat est introuvable, le gain s'effondre et le `PUT` reste la voie.

Questions de la sonde :
  M1. `POST /metadatas` est-il ADDITIF sur une propriété multi-valuée
      (`dcterms:subject`) ? Forme de réponse ? Les autres metas intactes ?
  M2. `POST` d'un propertyUri SCALAIRE déjà présent (`nkl:title`) :
      remplace / ajoute un doublon / refuse ?
  M3. `DELETE /metadatas` : quel CONTRAT d'identification (corps JSON ?
      propertyUri en chemin ?) et quelle GRANULARITÉ (une valeur précise
      vs toutes les valeurs d'un propertyUri) ?
  M4. `DELETE` d'un champ OBLIGATOIRE (`nkl:title`) : refusé (comme le
      retrait du dernier fichier → 403) ?
  M5. `POST` d'un propertyUri INCONNU / malformé : code d'erreur ?
  M_pub. Sur dépôt PUBLIÉ — GATÉ (NAKALA_ALLOW_PUBLISH=1) : une mutation
      granulaire de meta crée-t-elle une version ? (le `PUT metas` sur
      publié n'en crée pas — on vérifie que le granulaire est cohérent.)

Sondes M1-M5 amorcent des dépôts `pending` nettoyés en fin (DELETE
best-effort). Écriture uniquement sur des dépôts jetables créés ici.

Lancer :
    NAKALA_API_KEY=... uv run python -X utf8 \
        scripts/explorer_metadatas_granulaire_nakala.py
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import deposer_item
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Base, Fichier

CLE = os.environ.get("NAKALA_API_KEY", "01234567-89ab-cdef-0123-456789abcdef")
HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
AUTORISER_PUBLICATION = os.environ.get("NAKALA_ALLOW_PUBLISH") == "1"
TYPE_LIVRE = "http://purl.org/coar/resource_type/c_2f33"
NKL = "http://nakala.fr/terms#"
DC = "http://purl.org/dc/terms/"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


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
    # Sel uuid : contenu UNIQUE -> sha1 frais (upload Nakala à usage unique).
    sel = uuid.uuid4().hex.encode()
    chemin.write_bytes(
        b"\xff\xd8\xff METADATAS " + bytes([0x30 + marqueur]) + b" " + sel
    )


def _deposer_item_metas(
    ecriture: NakalaEcritureClient,
    parent: Path,
    *,
    cote: str,
    fonds_cote: str,
    sujets: list[str],
) -> str:
    """Dépôt pending à 1 fichier avec des metas connues (titre, type, date,
    langue, description, créateur + N sujets). Renvoie le DOI."""
    tmp_dir = parent / f"meta_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db = _amorcer_db(tmp_dir)
    scans = tmp_dir / "scans"
    scans.mkdir(exist_ok=True)
    racines = {"scans": scans}

    with _session(db) as s:
        f = creer_fonds(
            s, FormulaireFonds(cote=fonds_cote, titre=f"{fonds_cote} metas")
        )
        item = creer_item(
            s,
            FormulaireItem(
                cote=cote,
                titre="Titre sonde meta",
                fonds_id=f.id,
                date="2026",
                langue="fra",
                description="Description sonde meta",
                type_coar=TYPE_LIVRE,
                metadonnees={"createurs": ["Test, Hugo"], "sujets": list(sujets)},
            ),
        )
        nom = "fichier1.jpg"
        _ecrire_jpg(scans / nom, 1)
        s.add(
            Fichier(
                item_id=item.id,
                nom_fichier=nom,
                racine="scans",
                chemin_relatif=nom,
                ordre=1,
            )
        )
        s.commit()
        rapport = deposer_item(
            s, ecriture, item, racines=racines, dry_run=False, cree_par="sonde"
        )
        doi = rapport.doi
        assert doi
    return doi


def _metas(lecture: ClientLectureNakala, doi: str) -> list[dict[str, Any]]:
    return lecture.lire_depot(doi).get("metas") or []


def _court(uri: str) -> str:
    """Forme courte d'un propertyUri pour l'affichage (#title, dcterms/subject…)."""
    if uri.startswith(NKL):
        return "nkl:" + uri[len(NKL) :]
    if uri.startswith(DC):
        return "dcterms:" + uri[len(DC) :]
    return uri


def _valeurs(metas: list[dict[str, Any]], property_uri: str) -> list[Any]:
    return [m.get("value") for m in metas if m.get("propertyUri") == property_uri]


def _meta_par_valeur(
    metas: list[dict[str, Any]], property_uri: str, valeur: str
) -> dict[str, Any] | None:
    for m in metas:
        if m.get("propertyUri") == property_uri and m.get("value") == valeur:
            return m
    return None


def sonde_m1_post_additif(ecriture, lecture, tmp_dir: Path) -> None:
    """M1 — POST /metadatas ajoute-t-il une valeur sans toucher le reste ?"""
    _print_section("M1 - POST /metadatas : additif sur propriete multi-valuee ?")
    doi = _deposer_item_metas(
        ecriture, tmp_dir, cote="MA-001", fonds_cote="MA", sujets=["SujetA"]
    )
    avant = _metas(lecture, doi)
    print(f"Depot cree : {doi}")
    print(
        f"Avant POST : {len(avant)} metas, dont sujets={_valeurs(avant, DC + 'subject')}"
    )

    # Construit la meta à POSTer en miroir d'un sujet existant (mêmes
    # propertyUri / typeUri / lang) pour coller au format attendu.
    modele = _meta_par_valeur(avant, DC + "subject", "SujetA") or {
        "propertyUri": DC + "subject",
        "typeUri": XSD_STRING,
    }
    nouvelle = {
        k: modele.get(k) for k in ("propertyUri", "typeUri", "lang") if modele.get(k)
    }
    nouvelle["propertyUri"] = DC + "subject"
    nouvelle["value"] = "SujetAjoutePost"
    print(f"\nPOST /metadatas corps={json.dumps(nouvelle, ensure_ascii=False)}")
    code, charge = ecriture.ajouter_meta_explo(doi, nouvelle)
    print(
        f"  -> HTTP {code} ; reponse = {json.dumps(charge, ensure_ascii=False)[:300]}"
    )

    apres = _metas(lecture, doi)
    sujets_apres = _valeurs(apres, DC + "subject")
    titre_intact = _valeurs(apres, NKL + "title") == _valeurs(avant, NKL + "title")
    print(f"\nApres POST : sujets={sujets_apres} ; titre intact={titre_intact}")
    if "SujetA" in sujets_apres and "SujetAjoutePost" in sujets_apres and titre_intact:
        print("\n[OK] M1 ADDITIF : POST ajoute une valeur sans toucher le reste.")
        print("     -> push granulaire de metas envisageable (cf. synthese finale).")
    elif sujets_apres == ["SujetAjoutePost"]:
        print(
            "\n[!] M1 REMPLACE-PROPRIETE : le POST a ecrase les valeurs du propertyUri."
        )
    elif not titre_intact:
        print("\n[!] M1 REMPLACE-TOUT : d'autres metas ont bouge (inattendu).")
    else:
        print(f"\n[?] M1 AMBIGU : sujets={sujets_apres}")

    _cleanup(ecriture, doi)


def sonde_m2_post_scalaire(ecriture, lecture, tmp_dir: Path) -> None:
    """M2 — POST sur un propertyUri scalaire deja present (nkl:title)."""
    _print_section(
        "M2 - POST /metadatas sur scalaire (nkl:title) : remplace/doublon/refus ?"
    )
    doi = _deposer_item_metas(
        ecriture, tmp_dir, cote="MB-001", fonds_cote="MB", sujets=["SujetA"]
    )
    avant = _metas(lecture, doi)
    titres_avant = _valeurs(avant, NKL + "title")
    print(f"Depot cree : {doi} ; titre(s) avant = {titres_avant}")

    modele = _meta_par_valeur(
        avant, NKL + "title", titres_avant[0] if titres_avant else ""
    )
    corps = {"propertyUri": NKL + "title", "value": "Titre nouveau via POST"}
    if modele and modele.get("lang"):
        corps["lang"] = modele["lang"]
    if modele and modele.get("typeUri"):
        corps["typeUri"] = modele["typeUri"]
    print(f"\nPOST /metadatas {json.dumps(corps, ensure_ascii=False)}")
    code, charge = ecriture.ajouter_meta_explo(doi, corps)
    print(f"  -> HTTP {code} : {json.dumps(charge, ensure_ascii=False)[:240]}")

    apres = _metas(lecture, doi)
    titres_apres = _valeurs(apres, NKL + "title")
    print(f"\nApres : titre(s) = {titres_apres}")
    if titres_apres == ["Titre nouveau via POST"]:
        print(
            "\n[OK] M2 REMPLACE : POST sur scalaire ecrase la valeur (update direct)."
        )
    elif len(titres_apres) == 2:
        print("\n[!] M2 DOUBLON : POST a cree un 2e nkl:title (dépôt a 2 titres).")
        print("     -> un update de scalaire imposerait DELETE puis POST.")
    elif code >= 400:
        print(
            f"\n[!] M2 REFUS : POST refuse sur un scalaire deja present (HTTP {code})."
        )
    else:
        print(f"\n[?] M2 AMBIGU : HTTP {code}, titres={titres_apres}")

    _cleanup(ecriture, doi)


def sonde_m3_delete_contrat(ecriture, lecture, tmp_dir: Path) -> None:
    """M3 — contrat + granularite du DELETE /metadatas (le pivot)."""
    _print_section("M3 - DELETE /metadatas : contrat d'identification + granularite")
    doi = _deposer_item_metas(
        ecriture, tmp_dir, cote="MC-001", fonds_cote="MC", sujets=["SujetA", "SujetB"]
    )
    avant = _metas(lecture, doi)
    print(f"Depot cree : {doi} ; sujets = {_valeurs(avant, DC + 'subject')}")

    # Inspecte la projection granulaire (peut differer de lire_depot.metas :
    # un id propre par meta ?).
    code_get, metas_get = ecriture.lire_metas_explo(doi)
    print(f"\nGET /datas/{{id}}/metadatas -> HTTP {code_get}")
    if isinstance(metas_get, list) and metas_get:
        print(f"  cles d'une meta : {sorted(metas_get[0].keys())}")
        sujet_get = next(
            (
                m
                for m in metas_get
                if m.get("propertyUri") == DC + "subject" and m.get("value") == "SujetB"
            ),
            None,
        )
        print(
            f"  meta SujetB (forme distante) : {json.dumps(sujet_get, ensure_ascii=False)}"
        )
    else:
        print(f"  corps : {json.dumps(metas_get, ensure_ascii=False)[:300]}")

    cible = _meta_par_valeur(avant, DC + "subject", "SujetB") or {
        "propertyUri": DC + "subject",
        "value": "SujetB",
        "typeUri": XSD_STRING,
    }

    # Tentative (a) : DELETE avec corps JSON = la meta exacte.
    print(f"\n(a) DELETE /metadatas corps={json.dumps(cible, ensure_ascii=False)}")
    code_a, charge_a = ecriture.supprimer_meta_corps_explo(doi, cible)
    print(f"    -> HTTP {code_a} : {json.dumps(charge_a, ensure_ascii=False)[:200]}")
    apres_a = _metas(lecture, doi)
    sujets_a = _valeurs(apres_a, DC + "subject")
    print(f"    sujets apres (a) = {sujets_a}")

    contrat = None
    granularite = None
    if code_a in (200, 204):
        contrat = "corps JSON {propertyUri,value,lang,typeUri}"
        if sujets_a == ["SujetA"]:
            granularite = "valeur (SujetB retire, SujetA garde)"
        elif sujets_a == []:
            granularite = "propriete (TOUTES les valeurs du propertyUri retirees)"
        else:
            granularite = f"inattendue ({sujets_a})"
    else:
        # Tentative (b) : DELETE par propertyUri en chemin.
        chemin_uri = quote(DC + "subject", safe="")
        print(f"\n(b) DELETE /metadatas/{chemin_uri[:30]}...  (propertyUri en chemin)")
        code_b, charge_b = ecriture.supprimer_meta_chemin_explo(doi, DC + "subject")
        print(
            f"    -> HTTP {code_b} : {json.dumps(charge_b, ensure_ascii=False)[:200]}"
        )
        apres_b = _metas(lecture, doi)
        sujets_b = _valeurs(apres_b, DC + "subject")
        print(f"    sujets apres (b) = {sujets_b}")
        if code_b in (200, 204):
            contrat = "propertyUri en chemin"
            granularite = (
                "valeur"
                if sujets_b == ["SujetA"]
                else "propriete"
                if sujets_b == []
                else f"inattendue ({sujets_b})"
            )

    print("\n--- Diagnostic M3 ---")
    if contrat:
        print(f"  [OK] CONTRAT  : {contrat}")
        print(f"       GRANULARITE : {granularite}")
        if granularite and granularite.startswith("valeur"):
            print("       => DELETE granulaire A LA VALEUR : push de metas granulaire")
            print("          PLEINEMENT viable (toucher la seule valeur qui change).")
        elif granularite and granularite.startswith("propriete"):
            print("       => DELETE par PROPRIETE : pour une propriete multi-valuee,")
            print("          modifier une valeur = DELETE-all + re-POST-all. Gain")
            print("          partiel (OK pour les scalaires, pas pour les listes).")
    else:
        print("  [?] CONTRAT INTROUVABLE : ni corps JSON ni propertyUri en chemin.")
        print(
            "      Inspecter le schema DELETE dans GET /doc.json avant d'aller plus loin."
        )

    _cleanup(ecriture, doi)


def sonde_m4_delete_obligatoire(ecriture, lecture, tmp_dir: Path) -> None:
    """M4 — DELETE d'un champ obligatoire (nkl:title) : refuse ?"""
    _print_section("M4 - DELETE d'un champ obligatoire (nkl:title) : refuse ?")
    doi = _deposer_item_metas(
        ecriture, tmp_dir, cote="MD-001", fonds_cote="MD", sujets=["SujetA"]
    )
    avant = _metas(lecture, doi)
    titre = _meta_par_valeur(
        avant, NKL + "title", (_valeurs(avant, NKL + "title") or [""])[0]
    )
    print(f"Depot cree : {doi} ; titre = {_valeurs(avant, NKL + 'title')}")

    print("\nDELETE de nkl:title (corps JSON, puis chemin si echec)")
    code_a, charge_a = ecriture.supprimer_meta_corps_explo(
        doi, titre or {"propertyUri": NKL + "title"}
    )
    print(
        f"  (a corps) -> HTTP {code_a} : {json.dumps(charge_a, ensure_ascii=False)[:160]}"
    )
    if code_a not in (200, 204):
        # La variante par chemin n'existe pas (404) ; on la sonde pour
        # mémoire, mais le verdict garde le code du CORPS (l'endpoint réel).
        code_b, charge_b = ecriture.supprimer_meta_chemin_explo(doi, NKL + "title")
        print(
            f"  (b chemin) -> HTTP {code_b} : {json.dumps(charge_b, ensure_ascii=False)[:160]}"
        )

    apres = _metas(lecture, doi)
    titre_apres = _valeurs(apres, NKL + "title")
    if code_a >= 400 and titre_apres:
        print(f"\n[OK] M4 REFUS : nkl:title non supprimable (HTTP {code_a}) — comme le")
        print("     retrait du dernier fichier (403). Garde-fou cote Nakala.")
    elif not titre_apres:
        print(
            "\n[!] M4 ACCEPTE : nkl:title a ete SUPPRIME -> depot sans titre obligatoire (!)."
        )
    else:
        print(f"\n[?] M4 AMBIGU : HTTP {code_a}, titre={titre_apres}")

    _cleanup(ecriture, doi)


def sonde_m5_post_inconnu(ecriture, lecture, tmp_dir: Path) -> None:
    """M5 — POST d'un propertyUri inconnu / malforme."""
    _print_section("M5 - POST /metadatas propertyUri inconnu -> erreur ?")
    doi = _deposer_item_metas(
        ecriture, tmp_dir, cote="ME-001", fonds_cote="ME", sujets=["SujetA"]
    )
    print(f"Depot cree : {doi}")
    corps = {
        "propertyUri": "http://example.org/inconnu",
        "value": "x",
        "typeUri": XSD_STRING,
    }
    code, charge = ecriture.ajouter_meta_explo(doi, corps)
    print(
        f"POST propertyUri inconnu -> HTTP {code} : {json.dumps(charge, ensure_ascii=False)[:240]}"
    )
    if code >= 400:
        print("\n[OK] M5 : propertyUri inconnu refuse (validation cote Nakala).")
    else:
        print("\n[?] M5 : Nakala a ACCEPTE un propertyUri hors vocabulaire (laxe).")
    _cleanup(ecriture, doi)


def sonde_m_pub(ecriture, lecture, tmp_dir: Path) -> None:
    """M_pub — mutation granulaire de meta sur dépôt PUBLIÉ : versionne ? GATÉ."""
    _print_section("M_pub - meta granulaire sur depot PUBLIE (gate, irreversible)")
    if not AUTORISER_PUBLICATION:
        print("[SKIP] NAKALA_ALLOW_PUBLISH != 1 — sonde non lancee.")
        print("  Publier sur apitest est irreversible (DELETE reserve au pending).")
        return
    doi = _deposer_item_metas(
        ecriture, tmp_dir, cote="MP-001", fonds_cote="MP", sujets=["SujetA"]
    )
    print(f"Depot pending cree : {doi}")
    code_v0, v0 = ecriture.lire_versions_explo(doi)
    n0 = len(v0.get("data") or []) if isinstance(v0, dict) else 0
    ecriture.publier_via_status_explo(doi, "published")
    print(f"Publie. Versions avant mutation meta : {n0}")

    corps = {
        "propertyUri": DC + "subject",
        "value": "SujetPublie",
        "typeUri": XSD_STRING,
    }
    code_add, _ = ecriture.ajouter_meta_explo(doi, corps)
    print(f"POST meta sur publie -> HTTP {code_add}")
    code_v1, v1 = ecriture.lire_versions_explo(doi)
    n1 = len(v1.get("data") or []) if isinstance(v1, dict) else 0
    print(f"Versions apres mutation meta : {n1}")
    if n1 > n0:
        print(
            "\n[!] M_pub : la mutation de meta sur publie CREE une version (≠ PUT metas)."
        )
    else:
        print(
            "\n[OK] M_pub : meta sur publie = en place, PAS de version (coherent PUT metas)."
        )
    print(f"\n  (depot publie {doi} NON nettoye — indestructible sur apitest)")


def _cleanup(ecriture, doi: str) -> None:
    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def _synthese() -> None:
    _print_section("SYNTHESE - le push de metadonnees peut-il devenir granulaire ?")
    print(
        "Lire M1 (additif ?) + M3 (granularite du DELETE) ensemble :\n"
        "  - M1 ADDITIF + M3 granularite VALEUR  -> push granulaire PLEINEMENT\n"
        "    viable : on POSTe les metas ajoutees, on DELETE les retirees, on ne\n"
        "    touche pas les inchangees. Le faux-diff 'createur enrichi au\n"
        "    stockage' disparait (createurs inchanges jamais renvoyes).\n"
        "  - M1 ADDITIF + M3 granularite PROPRIETE -> gain PARTIEL : OK pour les\n"
        "    scalaires (titre, type, date, licence), mais une propriete\n"
        "    multi-valuee (sujets, createurs, contributeurs) impose DELETE-all +\n"
        "    re-POST-all de la propriete -> on retombe sur la canonicalisation.\n"
        "  - M1 NON ADDITIF ou M3 introuvable -> garder le PUT /datas metas[]\n"
        "    actuel ; la piste n'apporte rien.\n"
        "Decision a consigner dans backlog-nakala-api.md (nouveau ticket) +\n"
        "nakala-savoir-api.md (Partie I §2/§4 : comportement de l'endpoint)."
    )


def main() -> None:
    # Méthodes d'exploration greffées sur le client (renvoient le code HTTP
    # brut sans lever, pour observer 200/204/404/409/422).
    def ajouter_meta_explo(self, doi: str, corps: dict):
        reponse = self._requete("POST", f"/datas/{doi}/metadatas", json=corps)
        try:
            charge = reponse.json()
        except Exception:  # noqa: BLE001
            charge = reponse.text
        return reponse.status_code, charge

    def supprimer_meta_corps_explo(self, doi: str, corps: dict):
        # Contrat hypothèse (a) : corps JSON = la meta exacte à retirer.
        reponse = self._requete("DELETE", f"/datas/{doi}/metadatas", json=corps)
        try:
            charge = reponse.json()
        except Exception:  # noqa: BLE001
            charge = reponse.text
        return reponse.status_code, charge

    def supprimer_meta_chemin_explo(self, doi: str, property_uri: str):
        # Contrat hypothèse (b) : propertyUri (URL-encodé) en segment de chemin.
        reponse = self._requete(
            "DELETE", f"/datas/{doi}/metadatas/{quote(property_uri, safe='')}"
        )
        try:
            charge = reponse.json()
        except Exception:  # noqa: BLE001
            charge = reponse.text
        return reponse.status_code, charge

    def lire_metas_explo(self, doi: str):
        reponse = self._requete("GET", f"/datas/{doi}/metadatas")
        try:
            return reponse.status_code, reponse.json()
        except Exception:  # noqa: BLE001
            return reponse.status_code, reponse.text

    def publier_via_status_explo(self, doi: str, statut: str):
        reponse = self._requete("PUT", f"/datas/{doi}/status/{statut}")
        try:
            return reponse.status_code, reponse.json()
        except Exception:  # noqa: BLE001
            return reponse.status_code, reponse.text

    def lire_versions_explo(self, doi: str):
        reponse = self._requete("GET", f"/datas/{doi}/versions")
        try:
            return reponse.status_code, reponse.json()
        except Exception:  # noqa: BLE001
            return reponse.status_code, reponse.text

    NakalaEcritureClient.ajouter_meta_explo = ajouter_meta_explo
    NakalaEcritureClient.supprimer_meta_corps_explo = supprimer_meta_corps_explo
    NakalaEcritureClient.supprimer_meta_chemin_explo = supprimer_meta_chemin_explo
    NakalaEcritureClient.lire_metas_explo = lire_metas_explo
    NakalaEcritureClient.publier_via_status_explo = publier_via_status_explo
    NakalaEcritureClient.lire_versions_explo = lire_versions_explo

    print(f"Cible : {HOTE}")
    print(f"Cle   : {CLE[:13]}... (publique apitest par defaut)")
    print(f"Publication autorisee (sonde M_pub) : {AUTORISER_PUBLICATION}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        ecriture = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
        lecture = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
        try:
            sonde_m1_post_additif(ecriture, lecture, tmp_dir)
            sonde_m2_post_scalaire(ecriture, lecture, tmp_dir)
            sonde_m3_delete_contrat(ecriture, lecture, tmp_dir)
            sonde_m4_delete_obligatoire(ecriture, lecture, tmp_dir)
            sonde_m5_post_inconnu(ecriture, lecture, tmp_dir)
            sonde_m_pub(ecriture, lecture, tmp_dir)
            _synthese()
        finally:
            ecriture.fermer()
            lecture.fermer()


if __name__ == "__main__":
    main()
