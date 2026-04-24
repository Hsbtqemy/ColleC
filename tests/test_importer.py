"""Tests de l'écrivain d'import (bout en bout)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.config import ConfigLocale
from archives_tool.importers.ecrivain import importer
from archives_tool.models import Collection, Item, OperationImport
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


def _config(racines: dict[str, Path]) -> ConfigLocale:
    return ConfigLocale(utilisateur="Test", racines=racines)


def _profil(cas: str):
    chemin = FIXTURES / cas / "profil.yaml"
    return charger_profil(chemin), chemin


def test_dry_run_cas_item_simple(session: Session) -> None:
    profil, chemin = _profil("cas_item_simple")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=True)
    assert rapport.dry_run is True
    assert rapport.batch_id is None
    assert rapport.collection_creee is True
    assert rapport.items_crees == 5
    assert rapport.erreurs == []
    # Rien en base après dry-run.
    assert (
        session.scalar(select(Collection).where(Collection.cote_collection == "HK"))
        is None
    )
    assert session.scalar(select(OperationImport)) is None


def test_reel_cas_item_simple(session: Session) -> None:
    profil, chemin = _profil("cas_item_simple")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=False, cree_par="Alice")
    assert rapport.dry_run is False
    assert rapport.batch_id is not None
    assert rapport.items_crees == 5
    assert rapport.erreurs == []
    # Les fichiers PNG 01/02/03 correspondent aux trois premiers numeros.
    assert rapport.fichiers_ajoutes == 3

    col = session.scalar(select(Collection).where(Collection.cote_collection == "HK"))
    assert col is not None
    assert col.cree_par == "Alice"
    assert len(col.items) == 5

    journal = session.scalar(select(OperationImport))
    assert journal is not None
    assert journal.batch_id == rapport.batch_id
    assert journal.execute_par == "Alice"
    assert journal.items_crees == 5


def test_reimport_sans_changement(session: Session) -> None:
    profil, chemin = _profil("cas_item_simple")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    importer(profil, chemin, session, config, dry_run=False)
    rapport2 = importer(profil, chemin, session, config, dry_run=False)
    assert rapport2.items_crees == 0
    assert rapport2.items_mis_a_jour == 0
    assert rapport2.items_inchanges == 5
    # Fichiers déjà connus : ne sont pas ré-ajoutés.
    assert rapport2.fichiers_ajoutes == 0


def test_cas_fichier_groupe_dedoublonnage(session: Session) -> None:
    # Granularité fichier : 3 lignes, 2 cotes distinctes (PF-001 x2, PF-002 x1).
    # Attendu : 2 items créés, 3 fichiers.
    profil, chemin = _profil("cas_fichier_groupe")
    config = _config({"scans_revues": FIXTURES / "cas_fichier_groupe" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=False)
    assert rapport.erreurs == []
    assert rapport.items_crees == 2
    assert rapport.fichiers_ajoutes == 3

    items = session.scalars(select(Item).order_by(Item.cote)).all()
    assert [i.cote for i in items] == ["PF-001", "PF-002"]
    pf001 = next(i for i in items if i.cote == "PF-001")
    assert len(pf001.fichiers) == 2
    assert pf001.doi_nakala == "10.34847/nkl.fakepf001"


def test_cas_hierarchie_cote(session: Session) -> None:
    profil, chemin = _profil("cas_hierarchie_cote")
    config = _config({"scans_archives": FIXTURES / "cas_hierarchie_cote" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=False)
    assert rapport.erreurs == []
    assert rapport.items_crees == 4

    item = session.scalar(select(Item).where(Item.cote == "FA-AA-01-01"))
    assert item is not None
    # Décomposition cote rangée dans metadonnees.hierarchie.
    assert item.metadonnees["hierarchie"] == {
        "fonds": "FA",
        "sous_fonds": "AA",
        "serie": "01",
        "numero": "01",
    }
    assert item.metadonnees["typologie"]["categorie"] == "Correspondance"


def test_cas_uri_dc(session: Session) -> None:
    profil, chemin = _profil("cas_uri_dc")
    config = _config({"scans_nakala": FIXTURES / "cas_uri_dc" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=False)
    assert rapport.erreurs == []
    assert rapport.items_crees == 2

    item = session.scalar(select(Item).where(Item.cote == "NKLDC-001"))
    assert item.titre == "Étude café"
    assert item.metadonnees["sujets"] == "Histoire | Gastronomie"
    assert item.metadonnees["createurs"] == "Dupont / Martin"


def test_parent_cote_inexistant(session: Session, tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    tab = tmp_path / "t.csv"
    tab.write_text("Cote\nX1\n", encoding="utf-8")
    yml.write_text(
        """
version_profil: 1
collection:
  cote: "ORPHELIN"
  titre: "Sans parent existant"
  parent_cote: "N_EXISTE_PAS"
tableur:
  chemin: "t.csv"
  separateur_csv: ","
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    rapport = importer(profil, yml, session, _config({}), dry_run=False)
    assert any("parent" in e.lower() for e in rapport.erreurs)
    # Aucune collection créée (rollback).
    assert (
        session.scalar(
            select(Collection).where(Collection.cote_collection == "ORPHELIN")
        )
        is None
    )


def test_dry_run_collecte_les_erreurs(session: Session, tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    tab = tmp_path / "t.csv"
    tab.write_text("Cote,Titre\nOK,Un\n,Cote vide\nOK2,Deux\n", encoding="utf-8")
    yml.write_text(
        """
version_profil: 1
collection:
  cote: "TST"
  titre: "Test erreurs"
tableur:
  chemin: "t.csv"
  separateur_csv: ","
mapping:
  cote: "Cote"
  titre: "Titre"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    rapport = importer(profil, yml, session, _config({}), dry_run=True)
    # Une ligne en erreur (cote vide mais titre présent) doit être
    # remontée, les deux autres passer.
    assert len(rapport.erreurs) == 1
    assert "cote" in rapport.erreurs[0].lower()
    assert rapport.items_crees == 2  # simulé (dry-run)


def test_mode_reel_rollback_sur_erreur(session: Session, tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    tab = tmp_path / "t.csv"
    tab.write_text("Cote,Titre\nOK,Un\n,Vide\nOK2,Deux\n", encoding="utf-8")
    yml.write_text(
        """
version_profil: 1
collection:
  cote: "ROLL"
  titre: "Rollback"
tableur:
  chemin: "t.csv"
  separateur_csv: ","
mapping:
  cote: "Cote"
  titre: "Titre"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    rapport = importer(profil, yml, session, _config({}), dry_run=False)
    assert len(rapport.erreurs) >= 1
    assert rapport.batch_id is None
    # Aucune donnée en base après rollback.
    assert (
        session.scalar(select(Collection).where(Collection.cote_collection == "ROLL"))
        is None
    )
    assert session.scalar(select(OperationImport)) is None
