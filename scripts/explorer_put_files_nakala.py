"""Script d'exploration apitest : valider les hypotheses critiques sur
`PUT /datas/{id}` avec `files[]` AVANT de coder le palier P3+c.

Reutilise `deposer_item` (qui maitrise le format metas Nakala) pour
amorcer un depot a 2 fichiers, puis teste 2 hypotheses critiques.

Lancer :
    uv run python -X utf8 scripts/explorer_put_files_nakala.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

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


def _deposer_avec_n_fichiers(
    ecriture: NakalaEcritureClient, parent: Path,
    *, n: int, cote: str = "AS-001", fonds_cote: str = "AS",
) -> tuple[str, list[str]]:
    """Cree un depot pending avec n fichiers via le pipeline `deposer_item`.
    Renvoie (doi, sha1s_dans_l_ordre). Cree son propre sous-rep tmp_dir
    pour eviter les collisions entre hypotheses."""
    import uuid
    tmp_dir = parent / f"explo_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db = _amorcer_db(tmp_dir)
    scans = tmp_dir / "scans"
    scans.mkdir(exist_ok=True)
    racines = {"scans": scans}

    with _session(db) as s:
        f = creer_fonds(s, FormulaireFonds(cote=fonds_cote, titre=f"{fonds_cote} exploration"))
        item = creer_item(s, FormulaireItem(
            cote=cote, titre="Exploration P3+c", fonds_id=f.id,
            date="2026", langue="fra", description="Exploration H1/H2",
            type_coar=TYPE_LIVRE,
            metadonnees={"createurs": ["Test, Hugo"], "sujets": ["Expl"]},
        ))
        for i in range(1, n + 1):
            nom = f"fichier{i}.jpg"
            (scans / nom).write_bytes(
                b"\xff\xd8\xff EXPLORATION " + bytes([0x30 + i])
            )
            s.add(Fichier(
                item_id=item.id, nom_fichier=nom, racine="scans",
                chemin_relatif=nom, ordre=i,
            ))
        s.commit()
        rapport = deposer_item(s, ecriture, item, racines=racines,
                                dry_run=False, cree_par="explo")
        doi = rapport.doi
        assert doi
        # Recupere les sha1 capturés en base par P3+a.
        sha1s = [
            f.sha1_nakala for f in sorted(
                s.scalars(
                    select(Fichier).join(Item).where(Item.cote == cote)
                ).all(),
                key=lambda x: x.ordre,
            )
        ]
    return doi, sha1s


def hypothese_h1(ecriture, lecture, tmp_dir: Path) -> None:
    """H1 : PUT avec files: [un seul] retire-t-il l'autre ?"""
    _print_section("H1 - PUT {metas, files: [un seul]} -> retire les autres ?")
    doi, sha1s = _deposer_avec_n_fichiers(ecriture, tmp_dir, n=2)
    sha1_a, sha1_b = sha1s
    print(f"Depot cree : {doi}")
    print(f"  fichier1 sha1 : {sha1_a}")
    print(f"  fichier2 sha1 : {sha1_b}")

    avant = lecture.lire_depot(doi)
    files_avant = avant.get("files") or []
    sha1s_avant = [f.get("sha1") for f in files_avant]
    print(f"\nAvant PUT : {len(files_avant)} fichier(s) cote Nakala")
    print(f"  sha1s : {sha1s_avant}")
    assert sha1_a in sha1s_avant and sha1_b in sha1s_avant

    metas_distantes = avant.get("metas") or []
    print(f"\nPUT files=[fichier1 seul] + metas distantes ({len(metas_distantes)} metas)")
    ecriture.modifier_depot_files_exploration(
        doi,
        metas=metas_distantes,
        files=[{"sha1": sha1_a, "name": "fichier1.jpg"}],
    )

    apres = lecture.lire_depot(doi)
    files_apres = apres.get("files") or []
    sha1s_apres = [f.get("sha1") for f in files_apres]
    print(f"\nApres PUT : {len(files_apres)} fichier(s) cote Nakala")
    print(f"  sha1s : {sha1s_apres}")

    if len(files_apres) == 1 and sha1_a in sha1s_apres:
        print("\n[OK] H1 CONFIRMEE : Nakala REMPLACE files[] par la liste fournie.")
        print("     -> fichier2 retire cote distant. Pattern OK pour P3+c.")
    elif len(files_apres) == 2:
        print("\n[FAUX] H1 INFIRMEE : Nakala fait du delta/append.")
        print("       -> Autre endpoint ou format necessaire.")
    else:
        print(f"\n[?] H1 AMBIGU : {len(files_apres)} fichiers cote distant.")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur (best-effort) : {e}")


def hypothese_h2(ecriture, lecture, tmp_dir: Path) -> None:
    """H2 : PUT sans metas -> metas preservees ou wipe ?"""
    _print_section("H2 - PUT {files: [...]} SANS metas -> metas preservees ?")
    doi, sha1s = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=2, cote="BS-001", fonds_cote="BS",
    )
    sha1_a, sha1_b = sha1s
    print(f"Depot cree : {doi}")

    avant = lecture.lire_depot(doi)
    metas_avant = avant.get("metas") or []
    print(f"\nAvant PUT : {len(metas_avant)} metas distantes")
    titres_avant = [m.get("value") for m in metas_avant
                    if m.get("propertyUri") == f"{NKL}title"]
    print(f"  titre(s) : {titres_avant}")

    print("\nPUT corps = {files: [fichier1+fichier2]} SEUL (metas omis)")
    try:
        ecriture.modifier_depot_files_exploration(
            doi,
            metas=None,
            files=[
                {"sha1": sha1_a, "name": "fichier1.jpg"},
                {"sha1": sha1_b, "name": "fichier2.jpg"},
            ],
        )
        apres = lecture.lire_depot(doi)
        metas_apres = apres.get("metas") or []
        print(f"\nApres PUT : {len(metas_apres)} metas distantes")
        titres_apres = [m.get("value") for m in metas_apres
                        if m.get("propertyUri") == f"{NKL}title"]
        print(f"  titre(s) : {titres_apres}")

        if len(metas_apres) == len(metas_avant):
            print("\n[OK] H2A CONFIRMEE : Nakala PRESERVE les metas si non incluses.")
            print("     -> P3+c peut envoyer juste files[].")
        elif len(metas_apres) == 0:
            print("\n[!] H2B CONFIRMEE : Nakala WIPE les metas si non incluses.")
            print("     -> P3+c DOIT envoyer metas distantes intactes (defense).")
        else:
            print(f"\n[?] H2 PARTIEL : {len(metas_avant)} -> {len(metas_apres)} metas.")
    except Exception as e:  # noqa: BLE001
        print(f"\n[!] H2 PUT a echoue : {type(e).__name__}: {e}")
        print("     -> Nakala REFUSE le PUT sans metas. P3+c doit envoyer metas.")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur (best-effort) : {e}")


def hypothese_h3(ecriture, lecture, tmp_dir: Path) -> None:
    """H3 : PUT avec files=[] (liste vide) -> Nakala accepte ou rejette ?
    Critique pour le flag `--retirer-orphelins` quand TOUS les fichiers
    locaux sont orphelins."""
    _print_section("H3 - PUT files=[] (vide) -> Nakala accepte ?")
    doi, sha1s = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=2, cote="CS-001", fonds_cote="CS",
    )
    print(f"Depot cree : {doi} (2 fichiers)")

    print("\nPUT files=[] (liste vide)")
    try:
        ecriture.modifier_depot_files_exploration(
            doi, files=[],
        )
        apres = lecture.lire_depot(doi)
        files_apres = apres.get("files") or []
        print(f"\nApres PUT : {len(files_apres)} fichier(s) cote Nakala")
        if len(files_apres) == 0:
            print("\n[OK] H3 ACCEPTE : Nakala autorise un depot sans fichier.")
            print("     -> Cas --retirer-orphelins extreme viable.")
        else:
            print(f"\n[?] H3 PARTIEL : {len(files_apres)} fichiers restent.")
    except Exception as e:  # noqa: BLE001
        print(f"\n[REFUS] H3 : Nakala refuse PUT files=[] : "
              f"{type(e).__name__}: {e}")
        print("     -> Le flag --retirer-orphelins doit PRESERVER >=1 fichier,")
        print("        ou refuser explicitement le cas 'tout est orphelin'.")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def hypothese_h4(ecriture, lecture, tmp_dir: Path) -> None:
    """H4 : PUT avec un sha1 jamais uploade -> quel comportement ?
    Critique pour les cas d'erreur / cleanup en P3+c."""
    _print_section("H4 - PUT avec sha1 jamais uploade -> erreur ?")
    doi, sha1s = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote="DS-001", fonds_cote="DS",
    )
    sha1_existant = sha1s[0]
    sha1_fantome = "deadbeef" * 5  # 40 hex valides mais jamais uploade
    print(f"Depot cree : {doi}")
    print(f"  sha1 existant : {sha1_existant}")
    print(f"  sha1 fantome  : {sha1_fantome}")

    print(f"\nPUT files=[existant, fantome]")
    try:
        ecriture.modifier_depot_files_exploration(
            doi,
            files=[
                {"sha1": sha1_existant, "name": "fichier1.jpg"},
                {"sha1": sha1_fantome, "name": "phantom.jpg"},
            ],
        )
        apres = lecture.lire_depot(doi)
        files_apres = apres.get("files") or []
        sha1s_apres = [f.get("sha1") for f in files_apres]
        print(f"\nApres PUT : {len(files_apres)} fichier(s) cote Nakala")
        print(f"  sha1s : {sha1s_apres}")
        if sha1_fantome in sha1s_apres:
            print("\n[?] H4 ETONNANT : Nakala accepte un sha1 fantome.")
        elif len(files_apres) == 1 and sha1_existant in sha1s_apres:
            print("\n[OK] H4 SILENCE : Nakala ignore le sha1 fantome,")
            print("     garde l'existant. Pas d'erreur HTTP.")
    except Exception as e:  # noqa: BLE001
        print(f"\n[REFUS] H4 : Nakala refuse explicitement : "
              f"{type(e).__name__}: {e}")
        print("     -> P3+c doit valider que tous les sha1 viennent")
        print("        d'un upload reussi de la session courante.")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def hypothese_h10(ecriture, lecture, tmp_dir: Path) -> None:
    """H10 : Eventual consistency post-PUT.
    Si on lire_depot immediatement apres PUT, les changements sont-ils
    visibles ? Critique pour le smoke live qui chaine push -> re-comparer."""
    _print_section("H10 - Eventual consistency : lire_depot immediat apres PUT ?")
    doi, sha1s = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=2, cote="ES-001", fonds_cote="ES",
    )
    sha1_a, sha1_b = sha1s
    print(f"Depot cree : {doi} (2 fichiers)")

    print("\nPUT files=[fichier1 seul] (retire fichier2)")
    ecriture.modifier_depot_files_exploration(
        doi, files=[{"sha1": sha1_a, "name": "fichier1.jpg"}],
    )

    # Lecture immediate (pas de sleep)
    print("\nlire_depot() immediat sans sleep")
    immediat = lecture.lire_depot(doi)
    sha1s_immediat = [f.get("sha1") for f in immediat.get("files") or []]
    print(f"  {len(sha1s_immediat)} fichier(s) : {sha1s_immediat}")

    if len(sha1s_immediat) == 1 and sha1_a in sha1s_immediat:
        print("\n[OK] H10 CONSISTANT : changements visibles immediatement.")
        print("     -> Smoke live peut chainer PUT -> lire_depot sans sleep.")
    elif len(sha1s_immediat) == 2:
        print("\n[!] H10 EVENTUAL : changements pas encore visibles.")
        print("     -> Smoke live doit sleep ou re-essayer.")
        # Re-test avec sleep
        import time
        time.sleep(2)
        retard = lecture.lire_depot(doi)
        sha1s_retard = [f.get("sha1") for f in retard.get("files") or []]
        print(f"     Apres sleep(2) : {len(sha1s_retard)} fichier(s) : {sha1s_retard}")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def hypothese_h5(ecriture, lecture, tmp_dir: Path) -> None:
    """H5 : ordre des `files[]` preserve dans la reponse ?
    Cosmetique mais signal d'attention si ColleC veut afficher
    l'ordre cote distant."""
    _print_section("H5 - Ordre files[] preserve dans la reponse ?")
    doi, sha1s = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=3, cote="FS-001", fonds_cote="FS",
    )
    print(f"Depot cree : {doi} (3 fichiers, ordres 1/2/3)")

    # Lecture initiale - voir l'ordre du `creer_depot`
    avant = lecture.lire_depot(doi)
    files_avant = avant.get("files") or []
    sha1s_avant = [f.get("sha1") for f in files_avant]
    noms_avant = [f.get("name") for f in files_avant]
    print(f"\nApres creer_depot : ordre = {noms_avant}")
    print(f"  sha1s = {[s[:8] + '...' for s in sha1s_avant]}")
    print(f"  attendu = {['fichier1.jpg', 'fichier2.jpg', 'fichier3.jpg']}")

    # PUT avec ordre inverse 3/2/1
    print("\nPUT files=[fichier3, fichier2, fichier1] (ordre inverse)")
    sha1_1, sha1_2, sha1_3 = sha1s
    ecriture.modifier_depot_files_exploration(
        doi, files=[
            {"sha1": sha1_3, "name": "fichier3.jpg"},
            {"sha1": sha1_2, "name": "fichier2.jpg"},
            {"sha1": sha1_1, "name": "fichier1.jpg"},
        ],
    )
    apres = lecture.lire_depot(doi)
    files_apres = apres.get("files") or []
    noms_apres = [f.get("name") for f in files_apres]
    print(f"\nApres PUT : ordre = {noms_apres}")
    if noms_apres == ["fichier3.jpg", "fichier2.jpg", "fichier1.jpg"]:
        print("\n[OK] H5 PRESERVE : ordre envoye respecte cote distant.")
        print("     -> ColleC peut controler l'affichage cote Nakala.")
    elif noms_apres == ["fichier1.jpg", "fichier2.jpg", "fichier3.jpg"]:
        print("\n[!] H5 REORDONNE : Nakala trie alphabetiquement.")
        print("     -> ColleC ne peut PAS controler l'ordre distant.")
    else:
        print(f"\n[?] H5 INATTENDU : {noms_apres}")
        print("     -> Pas d'ordre fiable cote Nakala.")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def hypothese_h6(ecriture, lecture, tmp_dir: Path) -> None:
    """H6 : idempotence du PUT — re-PUT avec liste identique.
    Critique pour le re-push apres un crash : pas d'erreur 4xx, pas
    de duplication, juste un no-op silencieux."""
    _print_section("H6 - Idempotence : re-PUT avec liste identique ?")
    doi, sha1s = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=2, cote="GS-001", fonds_cote="GS",
    )
    print(f"Depot cree : {doi}")
    files_cible = [
        {"sha1": sha1s[0], "name": "fichier1.jpg"},
        {"sha1": sha1s[1], "name": "fichier2.jpg"},
    ]

    print(f"\n1er PUT files={[f['name'] for f in files_cible]} (identique au depot)")
    try:
        ecriture.modifier_depot_files_exploration(doi, files=files_cible)
        apres1 = lecture.lire_depot(doi)
        print(f"  Apres 1er PUT : {len(apres1.get('files') or [])} fichiers")

        print("\n2e PUT files=identique (re-push idempotent)")
        ecriture.modifier_depot_files_exploration(doi, files=files_cible)
        apres2 = lecture.lire_depot(doi)
        nb_apres2 = len(apres2.get("files") or [])
        print(f"  Apres 2e PUT : {nb_apres2} fichiers")
        if nb_apres2 == 2:
            print("\n[OK] H6 IDEMPOTENT : re-PUT identique = no-op silencieux.")
            print("     -> Reprise apres crash sans risque de duplication.")
        else:
            print(f"\n[?] H6 ANOMALIE : nb fichiers passe a {nb_apres2}.")
    except Exception as e:  # noqa: BLE001
        print(f"\n[REFUS] H6 : {type(e).__name__}: {e}")
        print("     -> Reprise apres crash PROBLEMATIQUE — il faut")
        print("        detecter avec lire_depot avant de re-PUT.")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def hypothese_h7(ecriture, lecture, tmp_dir: Path) -> None:
    """H7 : PUT avec sha1 inchange mais `name` different — Nakala
    met-il a jour le name ? Cas : ColleC fait un rename local sans
    changer le binaire."""
    _print_section("H7 - PUT sha1 inchange + name nouveau -> rename Nakala ?")
    doi, sha1s = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote="HS-001", fonds_cote="HS",
    )
    sha1_a = sha1s[0]
    print(f"Depot cree : {doi}")
    print(f"  fichier1.jpg sha1 : {sha1_a}")

    print(f"\nPUT files=[{{sha1: meme, name: 'RENOMME.jpg'}}]")
    try:
        ecriture.modifier_depot_files_exploration(
            doi, files=[{"sha1": sha1_a, "name": "RENOMME.jpg"}],
        )
        apres = lecture.lire_depot(doi)
        files_apres = apres.get("files") or []
        noms = [f.get("name") for f in files_apres]
        sha1s_apres = [f.get("sha1") for f in files_apres]
        print(f"\nApres PUT : {len(files_apres)} fichier(s)")
        print(f"  noms = {noms}")
        print(f"  sha1s = {sha1s_apres}")

        if noms == ["RENOMME.jpg"] and sha1_a in sha1s_apres:
            print("\n[OK] H7 RENOMME : Nakala met a jour le name au PUT.")
            print("     -> ColleC peut renommer sans re-uploader le binaire.")
        elif noms == ["fichier1.jpg"]:
            print("\n[!] H7 IGNORE : Nakala garde l'ancien name.")
            print("     -> Renommage sans re-upload non supporte.")
        else:
            print(f"\n[?] H7 INATTENDU : noms = {noms}")
    except Exception as e:  # noqa: BLE001
        print(f"\n[REFUS] H7 : {type(e).__name__}: {e}")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def hypothese_h11(ecriture, lecture, tmp_dir: Path) -> None:
    """H11 : Format `files[i]` au-dela de sha1+name (description,
    embargo) — accepte ? preserve ?"""
    _print_section("H11 - Champs additionnels files[i] (description, embargo)")
    doi, sha1s = _deposer_avec_n_fichiers(
        ecriture, tmp_dir, n=1, cote="IS-001", fonds_cote="IS",
    )
    sha1_a = sha1s[0]
    print(f"Depot cree : {doi}")

    print("\nPUT files=[{sha1, name, description, embargoed: false}]")
    try:
        ecriture.modifier_depot_files_exploration(
            doi, files=[{
                "sha1": sha1_a,
                "name": "fichier1.jpg",
                "description": "Description test par H11",
                "embargoed": False,
            }],
        )
        apres = lecture.lire_depot(doi)
        files_apres = apres.get("files") or []
        if files_apres:
            f = files_apres[0]
            print(f"\nApres PUT : champs presents = {sorted(f.keys())}")
            desc = f.get("description")
            print(f"  description = {desc!r}")
            if desc == "Description test par H11":
                print("\n[OK] H11 ACCEPTE : description preservee.")
                print("     -> ColleC peut envoyer description par fichier.")
            else:
                print("\n[!] H11 IGNORE : description perdue ou absente.")
    except Exception as e:  # noqa: BLE001
        print(f"\n[REFUS] H11 : {type(e).__name__}: {e}")

    try:
        ecriture.supprimer_depot(doi)
        print(f"\nCleanup : depot {doi} supprime.")
    except Exception as e:  # noqa: BLE001
        print(f"\nCleanup erreur : {e}")


def main() -> None:
    def modifier_depot_exploration(
        self, identifiant, *, metas=None, files=None, status=None,
    ):
        corps: dict = {}
        if metas is not None:
            corps["metas"] = metas
        if files is not None:
            corps["files"] = files
        if status is not None:
            corps["status"] = status
        print(f"  PUT corps cles : {sorted(corps.keys())}")
        reponse = self._requete("PUT", f"/datas/{identifiant}", json=corps)
        self._verifier_statut(reponse, contexte=f"PUT /datas/{identifiant} (explo)")
        return reponse

    NakalaEcritureClient.modifier_depot_files_exploration = (
        modifier_depot_exploration
    )

    print(f"Cible : {HOTE}")
    print(f"Cle    : {CLE[:13]}... (publique apitest)")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        ecriture = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
        lecture = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
        try:
            hypothese_h1(ecriture, lecture, tmp_dir)
            hypothese_h2(ecriture, lecture, tmp_dir)
            hypothese_h3(ecriture, lecture, tmp_dir)
            hypothese_h4(ecriture, lecture, tmp_dir)
            hypothese_h5(ecriture, lecture, tmp_dir)
            hypothese_h6(ecriture, lecture, tmp_dir)
            hypothese_h7(ecriture, lecture, tmp_dir)
            hypothese_h10(ecriture, lecture, tmp_dir)
            hypothese_h11(ecriture, lecture, tmp_dir)
        finally:
            ecriture.fermer()
            lecture.fermer()


if __name__ == "__main__":
    main()
