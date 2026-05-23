"""Re-import PF après fixes Bug A/B/C — validation manuelle.

1. Supprime le fonds PF existant.
2. Réinitialise session 2 (efface mappings pour forcer le re-build
   via les nouvelles heuristiques Bug B).
3. Reconstruit le mapping en mode simple (cote = "Nouvelle cote",
   granularité = fichier).
4. Lance importer en dry-run d'abord, puis en réel si OK.
5. Affiche un récap des items + fichiers + metadonnees post-import.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ARCHIVES_DB", "data/archives.db")

from sqlalchemy import select

from archives_tool.api.services.import_web import (
    construire_mapping_depuis_simple,
    composer_profil,
    _chemin_profil_notionnel,
)
from archives_tool.config import ConfigLocale
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.importers.ecrivain import importer
from archives_tool.models import (
    Fonds,
    Item,
    Fichier,
    SessionImport,
)


def main() -> None:
    engine = creer_engine(Path("data/archives.db"))
    SessionLocal = creer_session_factory(engine)

    with SessionLocal() as db:
        # 1. Cleanup fonds PF (déjà fait via SQL direct pour contourner
        # le CHECK ck_collection_miroir_a_fonds qui empêche la cascade ORM).
        pf = db.scalar(select(Fonds).where(Fonds.cote == "PF"))
        if pf is not None:
            print(f"Fonds PF présent (id={pf.id}, {len(pf.items)} items) — abandon.")
            print("Lancer d'abord le script de cleanup SQL direct.")
            return
        print("Fonds PF déjà nettoyé.")

        # 2. Réinitialiser session 2 (efface mappings pour rebuild)
        s2 = db.get(SessionImport, 2)
        if s2 is None:
            print("Session 2 introuvable.")
            return
        print(f"Réinitialisation session 2 (était à l'étape {s2.etape}, statut {s2.statut})…")
        s2.mappings = None
        s2.etape = "mapping"
        s2.statut = "en_cours"
        s2.fonds_id = None
        s2.collection_miroir_data = None
        s2.configuration_fichiers = None
        db.commit()
        print("  OK")

        # 3. Construire mapping via Bug B (heuristiques nominatives)
        print("\nConstruction mapping mode simple (cote='Nouvelle cote', granularite='fichier')…")
        s2.granularite = "fichier"
        s2.fonds_data = {"cote": "PF", "titre": "Por Favor"}
        mapping = construire_mapping_depuis_simple(
            s2,
            colonne_cote="Nouvelle cote",
            colonne_titre="title",
            colonne_date="Date de création",
        )
        s2.mappings = mapping
        s2.etape = "fichiers"
        db.commit()
        print(f"  {len(mapping)} entrees dans le mapping :")
        for cible, source in sorted(mapping.items()):
            niveau = "ITEM" if not cible.startswith("fichier") else "FICH"
            print(f"    [{niveau}] {cible:<45} <- {source}")

        # 4. Composer profil + dry-run
        print("\nDry-run…")
        config = ConfigLocale(utilisateur="Hugo", racines={})
        profil = composer_profil(s2, ignorer_lignes_sans_cote=True)
        rapport = importer(
            profil,
            _chemin_profil_notionnel(s2),
            db,
            config,
            dry_run=True,
        )
        print(f"  items_crees     : {rapport.items_crees}")
        print(f"  fichiers_ajoutes: {rapport.fichiers_ajoutes}")
        print(f"  erreurs         : {len(rapport.erreurs)}")
        print(f"  warnings        : {len(rapport.warnings)}")
        print(f"  divergences agg : {len(rapport.divergences_aggregees)}")
        if rapport.erreurs:
            print("  Premières erreurs :")
            for e in rapport.erreurs[:5]:
                print(f"    - {e}")
            return

        # 5. Import réel
        print("\nImport réel…")
        rapport = importer(
            profil,
            _chemin_profil_notionnel(s2),
            db,
            config,
            dry_run=False,
            cree_par="Hugo",
        )
        print(f"  items_crees     : {rapport.items_crees}")
        print(f"  fichiers_ajoutes: {rapport.fichiers_ajoutes}")
        print(f"  erreurs         : {len(rapport.erreurs)}")
        if rapport.erreurs:
            print("  Premières erreurs :")
            for e in rapport.erreurs[:5]:
                print(f"    - {e}")
            return

        # 6. Inspect
        print("\n=== État post-import ===")
        pf = db.scalar(select(Fonds).where(Fonds.cote == "PF"))
        nb_items = db.scalar(
            select(Item).where(Item.fonds_id == pf.id)
        )
        items = db.scalars(
            select(Item).where(Item.fonds_id == pf.id).order_by(Item.cote)
        ).all()
        print(f"Fonds PF : {len(items)} items")
        nb_fichiers_total = sum(len(it.fichiers) for it in items)
        print(f"Total fichiers : {nb_fichiers_total}")

        if items:
            i = items[0]
            print(f"\n--- Item {i.cote} ---")
            print(f"  titre       = {i.titre!r}")
            print(f"  date        = {i.date!r}")
            print(f"  langue      = {i.langue!r}")
            print(f"  type_coar   = {i.type_coar!r}")
            print(f"  description = {(i.description or '')[:80]!r}…")
            print(f"  doi_nakala  = {i.doi_nakala!r}")
            print(f"  doi_coll    = {i.doi_collection_nakala!r}")
            print(f"  numero      = {i.numero!r}")
            print(f"  metadonnees keys = {list((i.metadonnees or {}).keys())}")
            print(f"  nb fichiers = {len(i.fichiers)}")
            if i.fichiers:
                f = i.fichiers[0]
                print(f"  Fichier 1 :")
                print(f"    nom_fichier      = {f.nom_fichier!r}")
                print(f"    iiif_url_nakala  = {f.iiif_url_nakala!r}")
                print(f"    hash_sha256      = {f.hash_sha256!r}")
                print(f"    metadonnees keys = {list((f.metadonnees or {}).keys())}")


if __name__ == "__main__":
    main()
