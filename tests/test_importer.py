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


def test_fichier_metadonnees_par_ligne(session: Session) -> None:
    """`fichier.metadonnees.<cle>` : chaque ligne en granularité fichier
    pose sa propre métadonnée sur le Fichier (et non sur Item.metadonnees)
    — pas de warning de divergence quand plusieurs lignes partagent la
    même cote avec des valeurs différentes."""
    profil, chemin = _profil("cas_fichier_colonnes")
    # On détourne la colonne `hash` du mapping pour qu'elle aille sur
    # `fichier.metadonnees.empreinte` au lieu de `fichier.hash_sha256`.
    # Les 2 lignes de PFC-1 ont des hashes différents → on doit voir
    # les 2 valeurs persistées (1 par fichier), sans warning.
    from archives_tool.profils.schema import MappingSimple

    del profil.mapping.champs["fichier.hash_sha256"]
    profil.mapping.champs["fichier.metadonnees.empreinte"] = MappingSimple(
        source="hash"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    # Pas de warning de divergence sur l'empreinte (chaque fichier a la sienne).
    assert all("empreinte" not in w for w in rapport.warnings)

    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    par_cote = {it.cote: it for it in fonds.items}
    pfc1 = par_cote["PFC-1"]
    fichiers_tries = sorted(pfc1.fichiers, key=lambda f: f.nom_fichier)
    assert fichiers_tries[0].metadonnees == {"empreinte": "abc111"}
    assert fichiers_tries[1].metadonnees == {"empreinte": "def222"}
    # L'item lui-même ne doit pas porter ces empreintes.
    assert "empreinte" not in (pfc1.metadonnees or {})


def test_divergences_aggregees_par_champ(session: Session) -> None:
    """V0.9.2-import T6 — quand une colonne par-fichier (qui varie au
    sein d'une cote) est mappée en niveau item, l'import remonte une
    entrée par champ dans `rapport.divergences_aggregees` (et plus
    seulement N warnings individuels)."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    # Force `hash` sur `metadonnees.hash` (niveau item) — chaque cote
    # avec plusieurs fichiers verra une divergence. PFC-1 a 2 hashes
    # différents → 1 divergence sur 1 cote.
    del profil.mapping.champs["fichier.hash_sha256"]
    profil.mapping.champs["metadonnees.hash"] = MappingSimple(source="hash")
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=True, cree_par="Alice"
    )
    assert rapport.erreurs == []
    # La flat list de warnings reste remplie (rétro-compat).
    assert any("hash" in w for w in rapport.warnings)
    # Et l'agrégation est présente.
    assert len(rapport.divergences_aggregees) >= 1
    divs_hash = [
        d for d in rapport.divergences_aggregees if d.champ == "hash"
    ]
    assert len(divs_hash) == 1
    div = divs_hash[0]
    assert div.niveau == "metadonnees"
    assert div.nb_cotes_affectees == 1  # seule PFC-1 a des divergences
    assert div.nb_divergences == 1  # 1 valeur ignorée (def222 vs abc111)
    assert div.exemple_cote == "PFC-1"
    # Les 2 valeurs distinctes vues figurent en exemples.
    assert "abc111" in div.exemples_valeurs
    assert "def222" in div.exemples_valeurs


def test_divergences_aggregees_vide_si_pas_de_conflit(session: Session) -> None:
    """Pas de divergence : `rapport.divergences_aggregees` est vide
    (backward-compat — les tests existants qui ignorent ce champ
    continuent à passer)."""
    profil, chemin = _profil("cas_item_simple")
    rapport = importer(
        profil, chemin, session, _config({"scans_revues": FIXTURES / "cas_item_simple" / "arbre"}),
        dry_run=True,
    )
    assert rapport.divergences_aggregees == []


def test_ordre_depuis_nom_extrait_du_suffixe(session: Session) -> None:
    """`ordre_depuis_nom` : la regex extrait l'ordre depuis le nom de
    fichier au lieu du séquentiel d'apparition. Utile quand le tableur
    n'a pas de colonne « ordre » mais que les noms portent _001/_002."""
    profil, chemin = _profil("cas_fichier_colonnes")
    # Les fichiers s'appellent pfc1_p01.jpg, pfc1_p02.jpg → ordre = 1, 2.
    profil.ordre_depuis_nom = r"_p(\d+)\.[^.]+$"
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    par_cote = {it.cote: it for it in fonds.items}
    pfc1 = par_cote["PFC-1"]
    fichiers_tries = sorted(pfc1.fichiers, key=lambda f: f.ordre)
    assert [f.ordre for f in fichiers_tries] == [1, 2]
    assert fichiers_tries[0].nom_fichier == "pfc1_p01.jpg"
    assert fichiers_tries[1].nom_fichier == "pfc1_p02.jpg"


def test_ordre_depuis_nom_fallback_sequentiel_si_pas_match(
    session: Session,
) -> None:
    """Si la regex ne matche pas tous les noms, fallback sur séquentiel
    avec un warning explicatif. Pas d'échec — le caller est tolérant."""
    profil, chemin = _profil("cas_fichier_colonnes")
    profil.ordre_depuis_nom = r"_z(\d+)\.[^.]+$"  # ne matche aucun nom
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    assert any("ne matche pas" in w for w in rapport.warnings)
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    par_cote = {it.cote: it for it in fonds.items}
    # Fallback séquentiel pour PFC-1 (2 fichiers) → ordres 1 et 2.
    assert sorted(f.ordre for f in par_cote["PFC-1"].fichiers) == [1, 2]
