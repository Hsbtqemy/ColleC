"""Tests de l'écrivain d'import V0.9.0-gamma.1 (profil v2)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.config import ConfigLocale
from archives_tool.importers.ecrivain import importer
from archives_tool.models import (
    Collection,
    Fonds,
    Item,
    ItemCollection,
    OperationImport,
    TypeCollection,
)
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


def _config(racines: dict[str, Path]) -> ConfigLocale:
    return ConfigLocale(utilisateur="Test", racines=racines)


def _profil(cas: str):
    chemin = FIXTURES / cas / "profil.yaml"
    return charger_profil(chemin), chemin


# ---------------------------------------------------------------------------
# Cas item simple — granularité item, un fichier par item
# ---------------------------------------------------------------------------


def test_dry_run_cas_item_simple(session: Session) -> None:
    """Dry-run : rapport complet, aucune écriture."""
    profil, chemin = _profil("cas_item_simple")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=True)
    assert rapport.dry_run is True
    assert rapport.batch_id is None
    assert rapport.fonds_cote == "HK"
    assert rapport.fonds_cree is True
    assert rapport.items_crees == 5
    assert rapport.erreurs == []
    # Rien en base après dry-run.
    assert session.scalar(select(Fonds).where(Fonds.cote == "HK")) is None
    assert session.scalar(select(OperationImport)) is None


def test_reel_cas_item_simple(session: Session) -> None:
    """Mode réel : fonds + miroir + items + fichiers + journal."""
    profil, chemin = _profil("cas_item_simple")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    rapport = importer(
        profil, chemin, session, config, dry_run=False, cree_par="Alice"
    )
    assert rapport.dry_run is False
    assert rapport.batch_id is not None
    assert rapport.fonds_cree is True
    assert rapport.items_crees == 5
    assert rapport.erreurs == []
    # 3 fichiers PNG correspondants aux 3 premiers numéros.
    assert rapport.fichiers_ajoutes == 3

    fonds = session.scalar(select(Fonds).where(Fonds.cote == "HK"))
    assert fonds is not None
    assert fonds.cree_par == "Alice"
    assert len(fonds.items) == 5

    # La miroir est créée auto avec le fonds (invariant 1).
    miroir = session.scalar(
        select(Collection).where(
            Collection.fonds_id == fonds.id,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )
    assert miroir is not None
    assert miroir.cote == "HK"  # hérite du fonds
    assert miroir.titre == fonds.titre

    # Journal de l'opération.
    journal = session.scalar(select(OperationImport))
    assert journal is not None
    assert journal.batch_id == rapport.batch_id
    assert journal.execute_par == "Alice"
    assert journal.items_crees == 5
    assert journal.collection_id == miroir.id


def test_invariant_6_items_dans_miroir(session: Session) -> None:
    """Tous les items créés sont dans la miroir du fonds (invariant 6).
    Vérification via la table de jonction `item_collection`."""
    profil, chemin = _profil("cas_item_simple")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    importer(profil, chemin, session, config, dry_run=False)

    fonds = session.scalar(select(Fonds).where(Fonds.cote == "HK"))
    miroir = next(
        c
        for c in fonds.collections
        if c.type_collection == TypeCollection.MIROIR.value
    )
    for item in fonds.items:
        liaison = session.get(ItemCollection, (item.id, miroir.id))
        assert liaison is not None, f"Item {item.cote} pas dans la miroir"


# ---------------------------------------------------------------------------
# Réimport / contraintes d'unicité
# ---------------------------------------------------------------------------


def test_reimport_meme_cote_echoue(session: Session) -> None:
    """Importer un profil avec une cote déjà utilisée échoue.

    `creer_fonds` rejette via `IntegrityError` rattrapée en
    `FondsInvalide`. Le rapport doit signaler l'erreur."""
    profil, chemin = _profil("cas_item_simple")
    config = _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"})
    importer(profil, chemin, session, config, dry_run=False)

    rapport2 = importer(profil, chemin, session, config, dry_run=False)
    assert rapport2.erreurs, "second import devrait échouer (cote en doublon)"
    assert rapport2.items_crees == 0


# ---------------------------------------------------------------------------
# Cas fichier groupé — granularité fichier
# ---------------------------------------------------------------------------


def test_cas_fichier_groupe_regroupe_par_cote(session: Session) -> None:
    """3 lignes du tableur → 2 items (PF-001 x2 lignes, PF-002 x1)."""
    profil, chemin = _profil("cas_fichier_groupe")
    config = _config({"scans_revues": FIXTURES / "cas_fichier_groupe" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=False)
    assert rapport.erreurs == []
    assert rapport.items_crees == 2

    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PF"))
    cotes = sorted(i.cote for i in fonds.items)
    assert cotes == ["PF-001", "PF-002"]


def test_cas_fichier_groupe_miroir_personnalisee(session: Session) -> None:
    """Le profil personnalise la miroir avec un DOI Nakala."""
    profil, chemin = _profil("cas_fichier_groupe")
    config = _config({"scans_revues": FIXTURES / "cas_fichier_groupe" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=False)
    assert rapport.miroir_personnalisee is True

    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PF"))
    miroir = next(
        c
        for c in fonds.collections
        if c.type_collection == TypeCollection.MIROIR.value
    )
    assert miroir.doi_nakala == "10.34847/nkl.fakepfcoll"


# ---------------------------------------------------------------------------
# Cas hiérarchie cote — décomposition par regex
# ---------------------------------------------------------------------------


def test_cas_hierarchie_cote_decomposition(session: Session) -> None:
    """La regex de décomposition stocke les groupes nommés dans
    metadonnees.hierarchie sur chaque item."""
    profil, chemin = _profil("cas_hierarchie_cote")
    config = _config({"scans_archives": FIXTURES / "cas_hierarchie_cote" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=False)
    assert rapport.erreurs == []
    assert rapport.items_crees == 4

    # Item FA-AA-01-01 : hiérarchie {fonds: FA, sous_fonds: AA, serie: 01, numero: 01}
    item = session.scalar(
        select(Item).join(Fonds).where(Item.cote == "FA-AA-01-01")
    )
    assert item is not None
    assert item.metadonnees is not None
    h = item.metadonnees.get("hierarchie")
    assert h == {"fonds": "FA", "sous_fonds": "AA", "serie": "01", "numero": "01"}


# ---------------------------------------------------------------------------
# Cas URI Dublin Core — agrégation multi-colonnes
# ---------------------------------------------------------------------------


def test_cas_uri_dc_agregations(session: Session) -> None:
    """Les colonnes nommées par URI DC sont mappées correctement,
    les agrégations multi-colonnes produisent une chaîne séparée."""
    profil, chemin = _profil("cas_uri_dc")
    config = _config({"scans_nakala": FIXTURES / "cas_uri_dc" / "arbre"})
    rapport = importer(profil, chemin, session, config, dry_run=False)
    assert rapport.erreurs == []
    assert rapport.items_crees == 2

    fonds = session.scalar(select(Fonds).where(Fonds.cote == "NKLDC"))
    items = sorted(fonds.items, key=lambda i: i.cote)
    assert items[0].metadonnees is not None
    sujets = items[0].metadonnees.get("sujets")
    assert sujets is not None
    # 3 colonnes sources, séparateur " | "
    assert "|" in sujets


# ---------------------------------------------------------------------------
# Cas fichier colonnes — granularité fichier, fichiers décrits par les
# colonnes du tableur (export Nakala : nom + hash + URL IIIF par ligne)
# ---------------------------------------------------------------------------


def test_dry_run_cas_fichier_colonnes(session: Session) -> None:
    """Dry-run : 3 lignes / 2 cotes → 2 items, 3 fichiers comptés."""
    profil, chemin = _profil("cas_fichier_colonnes")
    rapport = importer(profil, chemin, session, _config({}), dry_run=True)
    assert rapport.erreurs == []
    assert rapport.items_crees == 2
    assert rapport.fichiers_ajoutes == 3
    assert session.scalar(select(Fonds).where(Fonds.cote == "PFC")) is None


def test_reel_cas_fichier_colonnes(session: Session) -> None:
    """Mode réel : chaque ligne devient un Fichier Nakala-only rattaché
    à l'item de sa cote — pas de résolution disque."""
    profil, chemin = _profil("cas_fichier_colonnes")
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    assert rapport.items_crees == 2
    assert rapport.fichiers_ajoutes == 3

    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    assert fonds is not None

    par_cote = {it.cote: it for it in fonds.items}
    assert set(par_cote) == {"PFC-1", "PFC-2"}
    # PFC-1 : 2 lignes fusionnées → 2 fichiers.
    pfc1 = par_cote["PFC-1"]
    assert len(pfc1.fichiers) == 2
    f0 = sorted(pfc1.fichiers, key=lambda f: f.ordre)[0]
    assert f0.nom_fichier == "pfc1_p01.jpg"
    assert f0.hash_sha256 == "abc111"
    assert f0.iiif_url_nakala.endswith("abc111/full/full/0/default.jpg")
    # Fichier Nakala-only : aucune source disque.
    assert f0.racine is None
    assert f0.chemin_relatif is None
    # PFC-2 : 1 ligne → 1 fichier.
    assert len(par_cote["PFC-2"].fichiers) == 1
