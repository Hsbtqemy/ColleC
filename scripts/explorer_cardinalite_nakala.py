"""Sonde cardinalité / multi-valeur des propriétés Nakala (apitest).

Vérifie AVANT de bâtir le pont champ↔propriété
(cf. docs/developpeurs/champs-personnalises-nakala-future.md) :

  C1. Set FERMÉ des propriétés valides — `GET /vocabularies/properties`
      (lecture pure, aucune écriture).
  C2. Multi-valeur sur une propriété répétable (`dcterms:contributor`) :
      poser 2 valeurs distinctes survit-il au round-trip ? + l'idée de
      **préfixe de rôle** (« Dessinateur : X ») survit-elle verbatim ?
  C3. Scalaire (`nkl:title`) : poser une 2ᵉ valeur → doublon / dédup / refus ?

apitest + clé publique par défaut (`NAKALA_HOST`/`NAKALA_API_KEY`). Les
dépôts `pending` créés sont supprimés en fin (DELETE). **Aucune écriture
sur la production.**

Usage :
    uv run python -X utf8 scripts/explorer_cardinalite_nakala.py
"""

from __future__ import annotations

import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import deposer_item
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Base, Fichier

CLE = os.environ.get("NAKALA_API_KEY", "01234567-89ab-cdef-0123-456789abcdef")
HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
TYPE_LIVRE = "http://purl.org/coar/resource_type/c_2f33"
NKL = "http://nakala.fr/terms#"
DC = "http://purl.org/dc/terms/"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def _section(titre: str) -> None:
    print("\n" + "=" * 72 + f"\n{titre}\n" + "=" * 72)


def _amorcer_db(dossier: Path) -> Path:
    db = dossier / "sonde.db"
    eng = creer_engine(db)
    Base.metadata.create_all(eng)
    eng.dispose()
    return db


@contextmanager
def _session(db: Path):
    eng = creer_engine(db)
    fac = creer_session_factory(eng)
    s = fac()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def _ecrire_jpg(p: Path, n: int) -> None:
    p.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0]) + bytes([n % 256]) * 64)


def _deposer_base(ecriture: NakalaEcritureClient, parent: Path) -> str:
    """Dépôt pending minimal valide (titre/type/date/langue + 1 fichier)."""
    d = parent / f"c_{uuid.uuid4().hex[:8]}"
    scans = d / "scans"
    scans.mkdir(parents=True, exist_ok=True)
    db = _amorcer_db(d)
    with _session(db) as s:
        f = creer_fonds(
            s, FormulaireFonds(cote=f"SOND{uuid.uuid4().hex[:4]}", titre="Sonde")
        )
        item = creer_item(
            s,
            FormulaireItem(
                cote="IT-1",
                titre="Sonde cardinalité",
                fonds_id=f.id,
                date="2026",
                langue="fra",
                type_coar=TYPE_LIVRE,
                metadonnees={"createurs": ["Sonde, Test"]},  # preflight ColleC
            ),
        )
        nom = "f1.jpg"
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
            s, ecriture, item, racines={"scans": scans}, dry_run=False, cree_par="sonde"
        )
        assert rapport.doi
        return rapport.doi


def _metas(lecture: ClientLectureNakala, doi: str) -> list[dict[str, Any]]:
    return lecture.lire_depot(doi).get("metas") or []


def _valeurs(metas: list[dict[str, Any]], uri: str) -> list[Any]:
    return [m.get("value") for m in metas if m.get("propertyUri") == uri]


def _post_meta(ecriture: NakalaEcritureClient, doi: str, corps: dict[str, Any]) -> int:
    """POST /datas/{doi}/metadatas (additif) → code HTTP, sans lever."""
    reponse = ecriture._requete("POST", f"/datas/{doi}/metadatas", json=corps)
    return reponse.status_code


def main() -> int:
    print(f"Hôte : {HOTE} | clé {CLE[:8]}… (publique apitest par défaut)")

    # C1 — set fermé (lecture pure)
    _section("C1 - GET /vocabularies/properties : set fermé de propriétés")
    props = httpx.get(f"{HOTE}/vocabularies/properties", timeout=40).json()
    print(f"  {len(props)} propriétés Nakala valides (toute autre → rejet au push).")
    print(f"  exemples : {props[:3]}")

    with (
        NakalaEcritureClient(HOTE, api_key=CLE, timeout=60) as ecriture,
        tempfile.TemporaryDirectory() as tmp,
    ):
        lecture = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
        parent = Path(tmp)

        # C2 — multi-valeur + préfixe de rôle sur dcterms:contributor
        _section("C2 - dcterms:contributor : 2 valeurs + préfixe de rôle")
        roles = ["Dessinateur : Topor", "Directeur de collection : Reiser"]
        doi = _deposer_base(ecriture, parent)
        try:
            for v in roles:
                code = _post_meta(
                    ecriture,
                    doi,
                    {"propertyUri": DC + "contributor", "value": v, "typeUri": XSD_STRING},
                )
                print(f"  POST contributor={v!r} -> HTTP {code}")
            relu = _valeurs(_metas(lecture, doi), DC + "contributor")
            print(f"  relu {len(relu)} contributor(s) : {relu}")
            print(
                f"  → multi-valeur : {'OK (2)' if len(relu) == 2 else 'NON (%d)' % len(relu)}"
                f" ; préfixes : {'préservés' if set(relu) >= set(roles) else 'ALTÉRÉS'}"
            )
        finally:
            ecriture.supprimer_depot(doi)
            print(f"  (dépôt {doi} supprimé)")

        # C3 — scalaire nkl:title : 2ᵉ valeur → doublon / dédup / refus ?
        _section("C3 - nkl:title (scalaire) : POST d'une 2ᵉ valeur")
        doi = _deposer_base(ecriture, parent)
        try:
            avant = _valeurs(_metas(lecture, doi), NKL + "title")
            code = _post_meta(
                ecriture,
                doi,
                {
                    "propertyUri": NKL + "title",
                    "value": "Second titre",
                    "lang": "fr",
                    "typeUri": XSD_STRING,
                },
            )
            apres = _valeurs(_metas(lecture, doi), NKL + "title")
            print(f"  avant={avant} ; POST 2e titre -> HTTP {code} ; après={apres}")
            verdict = (
                "REFUSÉ" if code >= 400 else
                "DOUBLON créé" if len(apres) == 2 else
                "DÉDUPLIQUÉ/remplacé" if len(apres) == 1 else
                "?"
            )
            print(f"  → {verdict} (l'API n'impose pas la cardinalité scalaire au POST)")
        finally:
            ecriture.supprimer_depot(doi)
            print(f"  (dépôt {doi} supprimé)")

    _section("Conclusion")
    print(
        "  - Propriétés = set FERMÉ → le mapping UI doit s'y restreindre.\n"
        "  - Multi-valeur OK sur dcterms répétables ; les valeurs (préfixes de\n"
        "    rôle inclus) sont des chaînes libres préservées telles quelles.\n"
        "  - Scalaires (nkl:title/type/...) : à NE PAS multi-mapper (garde-fou UI),\n"
        "    l'API ne l'empêche pas → doublon silencieux possible."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
