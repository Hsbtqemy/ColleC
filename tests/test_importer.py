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


# ---------------------------------------------------------------------------
# Promotion d'URL depuis fichier.metadonnees → fichier.iiif_url_nakala
# (V0.9.2-import bug A : mode simple sur un export Nakala promeut data_url/
# embed_url/preview_url/thumb en fichier.metadonnees.<slug> sans qu'aucune
# ne devienne source primaire — sans cette promotion, le CHECK SQL
# rejette les Fichier et l'utilisateur perd silencieusement ses scans).
# ---------------------------------------------------------------------------


def test_promotion_url_metadonnees_si_iiif_absent(session: Session) -> None:
    """Si `fichier.iiif_url_nakala` n'est pas mappé mais que les colonnes
    `fichier.metadonnees.<X>` contiennent une URL plausible (embed_url,
    data_url, …), la première trouvée selon l'ordre de préférence est
    promue en `iiif_url_nakala` pour satisfaire le CHECK source primaire.
    L'URL reste aussi dans `metadonnees` (pas de perte d'information)."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    # Retire la cible dédiée et bascule la colonne `iiif` en
    # fichier.metadonnees.embed_url — simule un mode simple où l'URL a
    # été slug-promue plutôt qu'élue comme source primaire.
    del profil.mapping.champs["fichier.iiif_url_nakala"]
    profil.mapping.champs["fichier.metadonnees.embed_url"] = MappingSimple(
        source="iiif"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    # Tous les Fichier sont créés (pas de silent drop).
    assert rapport.fichiers_ajoutes == 3

    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    par_cote = {it.cote: it for it in fonds.items}
    pfc1 = par_cote["PFC-1"]
    fichiers_tries = sorted(pfc1.fichiers, key=lambda f: f.nom_fichier)
    f0 = fichiers_tries[0]
    # L'URL embed_url a été promue en iiif_url_nakala (la fichier est
    # visible dans la viewer + CHECK satisfait). La normalisation
    # Nakala-aware transforme l'URL `full/full/0/default.jpg` en
    # URL IIIF info.json (le viewer OSD pourra l'ouvrir en streaming
    # progressif).
    assert f0.iiif_url_nakala is not None
    assert f0.iiif_url_nakala.endswith("abc111/info.json")
    # Et l'URL originale (avant normalisation) reste dans metadonnees
    # (l'utilisateur peut basculer en mode avancé pour la remapper
    # proprement sans perte de donnée).
    assert f0.metadonnees == {
        "embed_url": (
            "https://api.nakala.fr/iiif/10.34847/nkl.x/"
            "abc111/full/full/0/default.jpg"
        )
    }


def test_promotion_url_ne_ecrase_pas_iiif_explicite(session: Session) -> None:
    """Si `fichier.iiif_url_nakala` est mappé explicitement, la promotion
    automatique depuis `fichier.metadonnees.*` ne s'enclenche pas — le
    mapping utilisateur prime sur l'heuristique."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    # `fichier.iiif_url_nakala` reste mappé sur la colonne `iiif`.
    # On ajoute en parallèle `fichier.metadonnees.embed_url` sur la même
    # colonne (cas absurde mais isole la garde).
    profil.mapping.champs["fichier.metadonnees.embed_url"] = MappingSimple(
        source="iiif"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    par_cote = {it.cote: it for it in fonds.items}
    f0 = sorted(par_cote["PFC-1"].fichiers, key=lambda f: f.nom_fichier)[0]
    # Vient bien du mapping explicite (la promotion aurait choisi la
    # même valeur ici, mais on vérifie qu'aucun comportement ambigu
    # n'apparaît si l'utilisateur a explicitement mappé iiif_url_nakala).
    assert f0.iiif_url_nakala.endswith("abc111/full/full/0/default.jpg")


def test_promotion_url_choisit_iiif_avant_data_url(session: Session) -> None:
    """L'ordre de préférence privilégie les slugs IIIF-compatibles
    (iiif, embed_url) avant les URLs de download (data_url) ou les
    aperçus (preview_url, thumb). Cas typique : export Nakala où les
    4 URLs sont présentes simultanément."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    del profil.mapping.champs["fichier.iiif_url_nakala"]
    # Plusieurs URLs simultanées sur la même colonne (la fixture n'a
    # qu'une seule colonne URL — on simule les 4 slugs en pointant
    # tous vers `iiif`, la promotion doit retenir le premier dans
    # l'ordre de préférence : `iiif`).
    profil.mapping.champs["fichier.metadonnees.data_url"] = MappingSimple(
        source="iiif"
    )
    profil.mapping.champs["fichier.metadonnees.thumb"] = MappingSimple(
        source="iiif"
    )
    profil.mapping.champs["fichier.metadonnees.iiif"] = MappingSimple(
        source="iiif"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    par_cote = {it.cote: it for it in fonds.items}
    f0 = sorted(par_cote["PFC-1"].fichiers, key=lambda f: f.nom_fichier)[0]
    assert f0.iiif_url_nakala is not None
    # `iiif` est en tête de _SLUGS_URL_PROMUS_SOURCE → choisi en
    # priorité quel que soit l'ordre d'apparition dans le mapping.
    assert "iiif" in f0.metadonnees
    # L'URL Nakala est normalisée vers info.json — l'URL originale
    # reste intacte dans metadonnees, mais iiif_url_nakala est la
    # version IIIF Image API que le viewer OSD comprend.
    assert f0.iiif_url_nakala.endswith("/info.json")
    assert "abc111" in f0.iiif_url_nakala
    assert "abc111" in f0.metadonnees["iiif"]


def test_pas_de_promotion_si_aucune_url_plausible(session: Session) -> None:
    """Si `fichier.metadonnees.*` ne contient aucun slug d'URL connu,
    pas de promotion : le Fichier sans source est rejeté avec warning
    (comportement existant inchangé)."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    del profil.mapping.champs["fichier.iiif_url_nakala"]
    # `hash` slugifié — pas un nom d'URL.
    profil.mapping.champs["fichier.metadonnees.empreinte_libre"] = MappingSimple(
        source="hash"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    # Pas d'erreur fatale — juste des warnings + 0 fichiers ajoutés.
    assert rapport.erreurs == []
    assert rapport.fichiers_ajoutes == 0
    assert any(
        "ni chemin disque ni URL Nakala" in w for w in rapport.warnings
    )


def test_pas_de_promotion_si_slug_liste_mais_valeur_non_url(
    session: Session,
) -> None:
    """Garde sur la forme : un slug listé (`thumb`, `data_url`, …) qui
    porte une valeur non-URL (chaîne libre, hash, nombre stringifié)
    ne déclenche PAS la promotion. Évite qu'un mapping bizarre
    (`fichier.metadonnees.thumb` pointé sur une colonne « commentaire »)
    se traduise par un Fichier avec une source absurde dans
    `iiif_url_nakala`.

    Sans cette garde, le `hash` slugifié sous une cible `thumb`
    aurait été promu en iiif_url_nakala = "abc111", contredisant le
    contrat du champ et faisant planter la visionneuse de manière
    incompréhensible."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    del profil.mapping.champs["fichier.iiif_url_nakala"]
    # Le slug `thumb` est dans _SLUGS_URL_PROMUS_SOURCE — mais la
    # valeur en provenance de la colonne `hash` (abc111, def222, …)
    # n'est pas une URL.
    profil.mapping.champs["fichier.metadonnees.thumb"] = MappingSimple(
        source="hash"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    # Aucun Fichier ajouté — la garde a empêché la promotion d'un hash
    # vers iiif_url_nakala.
    assert rapport.fichiers_ajoutes == 0
    assert any(
        "ni chemin disque ni URL Nakala" in w for w in rapport.warnings
    )


def test_promotion_url_emet_warning_agrege(session: Session) -> None:
    """Trou #1 V0.9.2-import : quand Bug A promeut des URLs depuis
    `fichier.metadonnees.<slug>` vers `iiif_url_nakala` faute de
    mapping explicite, un warning agrégé par slug source apparaît
    dans le rapport. UNE seule ligne par slug — pas N warnings par
    fichier (sinon sur un export Nakala 7k scans on inonderait)."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    del profil.mapping.champs["fichier.iiif_url_nakala"]
    profil.mapping.champs["fichier.metadonnees.embed_url"] = MappingSimple(
        source="iiif"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=True
    )
    assert rapport.erreurs == []
    promotion_warnings = [
        w for w in rapport.warnings if "URL promue depuis" in w
    ]
    # Une seule ligne pour les 3 fichiers (groupés par slug source).
    assert len(promotion_warnings) == 1
    msg = promotion_warnings[0]
    assert "3 fichier(s)" in msg
    assert "embed_url" in msg
    assert "iiif_url_nakala" in msg
    assert "mode avancé" in msg


def test_promotion_url_pas_de_warning_si_mapping_explicite(
    session: Session,
) -> None:
    """Trou #1 V0.9.2-import : si `fichier.iiif_url_nakala` est mappé
    explicitement, pas de promotion → pas de warning. Confirme que le
    warning Bug A est bien strictement informatif sur l'auto-promotion,
    pas un signal général sur les fichiers Nakala-only."""
    profil, chemin = _profil("cas_fichier_colonnes")
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=True
    )
    assert rapport.erreurs == []
    assert not any("URL promue depuis" in w for w in rapport.warnings)


def test_normaliser_url_nakala_data_vers_iiif_info_json() -> None:
    """Une URL Nakala `data` (binaire download) est transformée en URL
    IIIF info.json — sinon la visionneuse OSD échoue systématiquement
    en chargeant le JPEG comme s'il était info.json."""
    from archives_tool.importers.ecrivain import (
        _normaliser_url_nakala_vers_iiif,
    )

    src = "https://api.nakala.fr/data/10.34847/nkl.76a43qkk/93b499b2cfa3c71e3492a520e5e532f735fdcccf"
    cible = _normaliser_url_nakala_vers_iiif(src)
    assert cible == (
        "https://api.nakala.fr/iiif/10.34847/nkl.76a43qkk/"
        "93b499b2cfa3c71e3492a520e5e532f735fdcccf/info.json"
    )


def test_normaliser_url_nakala_embed_vers_iiif() -> None:
    """`embed_url` Nakala (iframe HTML) idem : on extrait la base
    (doi, sha hex SHA-1) et on construit l'URL IIIF info.json."""
    from archives_tool.importers.ecrivain import (
        _normaliser_url_nakala_vers_iiif,
    )

    sha = "abcdef0123456789abcdef0123456789abcdef01"
    src = f"https://api.nakala.fr/embed/10.34847/nkl.abc/{sha}"
    cible = _normaliser_url_nakala_vers_iiif(src)
    assert cible == f"https://api.nakala.fr/iiif/10.34847/nkl.abc/{sha}/info.json"


def test_normaliser_url_nakala_thumb_vers_info_json() -> None:
    """`thumb` Nakala contient déjà la base IIIF — on extrait
    (doi, sha) et reconstruit info.json (sans le suffixe full/...)."""
    from archives_tool.importers.ecrivain import (
        _normaliser_url_nakala_vers_iiif,
    )

    src = (
        "https://api.nakala.fr/iiif/10.34847/nkl.x/abc111/"
        "full/!200,200/0/default.jpg"
    )
    cible = _normaliser_url_nakala_vers_iiif(src)
    assert cible == "https://api.nakala.fr/iiif/10.34847/nkl.x/abc111/info.json"


def test_normaliser_url_non_nakala_inchangee() -> None:
    """URL hors Nakala : retournée telle quelle. Le viewer OSD
    fera son propre fallback open-failed si ce n'est pas IIIF."""
    from archives_tool.importers.ecrivain import (
        _normaliser_url_nakala_vers_iiif,
    )

    for url in (
        "https://example.com/image.jpg",
        "https://api.huma-num.fr/data/abc/def",  # similaire mais pas nakala.fr
        "https://api.nakala.fr/collections/abc",  # endpoint nakala mais pas data/embed/iiif
    ):
        assert _normaliser_url_nakala_vers_iiif(url) == url


def test_normaliser_url_faux_positif_domaine_pirate() -> None:
    """Garde sur le hostname : `evil-nakala.fr` ou `nakala.fr.attacker.com`
    ne doivent PAS être transformés en URL `api.nakala.fr/iiif/...`.
    Sans ce test, le regex `\\bnakala\\.fr` matchait `evil-nakala.fr/`
    (le `-` est word boundary) et redirigeait les données vers le
    mauvais service. Exige maintenant `<sub>.nakala.fr` strict."""
    from archives_tool.importers.ecrivain import (
        _normaliser_url_nakala_vers_iiif,
    )

    sha = "abcdef0123456789abcdef0123456789abcdef01"
    for url in (
        f"https://evil-nakala.fr/data/10.1/x/{sha}",  # pas un sous-domaine
        f"https://nakala.fr.attacker.com/data/10.1/x/{sha}",
        f"https://fake.nakala-mirror.fr/data/10.1/x/{sha}",
    ):
        assert _normaliser_url_nakala_vers_iiif(url) == url


def test_est_extension_image_iiif() -> None:
    """`_est_extension_image_iiif` filtre les noms de fichier dont
    l'extension n'est pas une image servie en IIIF par Nakala. PDF,
    vidéo, archive → False (la normalisation ne servirait à rien).
    Images → True. Pas d'extension → True (bénéfice du doute)."""
    from archives_tool.importers.ecrivain import _est_extension_image_iiif

    # Images IIIF-servies
    for nom in ("scan.jpg", "page.PNG", "fichier.tiff", "image.jp2"):
        assert _est_extension_image_iiif(nom) is True
    # Non-images : pas d'utilité de normaliser
    for nom in ("document.pdf", "video.mp4", "archive.zip", "metadata.json"):
        assert _est_extension_image_iiif(nom) is False
    # Bénéfice du doute
    assert _est_extension_image_iiif(None) is True
    assert _est_extension_image_iiif("") is True
    assert _est_extension_image_iiif("sans_extension") is True


def test_promotion_url_pas_de_normalisation_iiif_si_pdf(session: Session) -> None:
    """Trou « non-image » V0.9.2-import : si le nom de fichier
    indique un PDF, la normalisation IIIF n'est PAS appliquée — on
    garde l'URL data brute. Sinon `iiif_url_nakala` pointerait sur
    `/iiif/.../info.json` qui retournerait 404 (IIIF Nakala n'est
    disponible que pour les images)."""
    from archives_tool.importers.ecrivain import _fichier_depuis_colonnes
    from archives_tool.importers.transformateur import ItemPrepare

    prep_pdf = ItemPrepare(
        cote="X-001",
        champs_fichier={"nom_fichier": "document.pdf"},
        champs_fichier_metadonnees={
            "data_url": "https://api.nakala.fr/data/10.1/x/abcdef0123",
        },
    )
    f = _fichier_depuis_colonnes(prep_pdf, ordre=1)
    # Pas de normalisation IIIF — on garde data_url brut.
    assert f.iiif_url_nakala == "https://api.nakala.fr/data/10.1/x/abcdef0123"
    assert "/iiif/" not in f.iiif_url_nakala
    assert "/info.json" not in f.iiif_url_nakala
    # Mais la promotion a quand même eu lieu (signalée pour le warning).
    assert f.url_promue_depuis == "data_url"


def test_promotion_url_normalisation_iiif_si_image(session: Session) -> None:
    """Pendant du précédent : si le nom de fichier est un .jpg, la
    normalisation IIIF s'applique — viewer OSD peut afficher en
    streaming progressif."""
    from archives_tool.importers.ecrivain import _fichier_depuis_colonnes
    from archives_tool.importers.transformateur import ItemPrepare

    prep_img = ItemPrepare(
        cote="X-001",
        champs_fichier={"nom_fichier": "scan_page_01.jpg"},
        champs_fichier_metadonnees={
            "data_url": "https://api.nakala.fr/data/10.1/x/abcdef0123",
        },
    )
    f = _fichier_depuis_colonnes(prep_img, ordre=1)
    assert f.iiif_url_nakala == "https://api.nakala.fr/iiif/10.1/x/abcdef0123/info.json"


def test_normaliser_url_nakala_preserve_hostname() -> None:
    """`api-test.nakala.fr` (env de test) ou autre sous-domaine garde
    son hostname dans la cible IIIF — la transformation ne hardcode
    pas `api.nakala.fr`. Indispensable pour ne pas casser un import
    depuis un environnement de test."""
    from archives_tool.importers.ecrivain import (
        _normaliser_url_nakala_vers_iiif,
    )

    sha = "abcdef0123456789abcdef0123456789abcdef01"
    src = f"https://api-test.nakala.fr/data/10.1/x/{sha}"
    cible = _normaliser_url_nakala_vers_iiif(src)
    assert cible == f"https://api-test.nakala.fr/iiif/10.1/x/{sha}/info.json"


def test_promotion_url_promeut_iiif_info_json_si_nakala(session: Session) -> None:
    """Intégration : sur un tableur Nakala dont les URLs sont des
    download binaires (`data_url`), la promotion finale stockée
    dans `Fichier.iiif_url_nakala` est l'URL IIIF info.json — pas
    le binaire. Le viewer OSD peut charger en streaming progressif."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    del profil.mapping.champs["fichier.iiif_url_nakala"]
    # La fixture cas_fichier_colonnes a une colonne `iiif` qui pointe
    # déjà sur une URL `api.nakala.fr/iiif/.../full/.../default.jpg`.
    # On la mappe en `fichier.metadonnees.data_url` pour simuler le
    # cas PF (export Nakala où la colonne s'appelle data_url et
    # contient une URL data binaire).
    profil.mapping.champs["fichier.metadonnees.data_url"] = MappingSimple(
        source="iiif"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    par_cote = {it.cote: it for it in fonds.items}
    f0 = sorted(par_cote["PFC-1"].fichiers, key=lambda f: f.nom_fichier)[0]
    # L'URL Nakala est normalisée en info.json IIIF v3.
    assert f0.iiif_url_nakala.endswith("/info.json")
    assert "/iiif/" in f0.iiif_url_nakala
    assert "/full/" not in f0.iiif_url_nakala  # plus le suffixe image


def test_propagation_doi_collection_sur_miroir(session: Session) -> None:
    """#3 V0.9.2-import : si tous les items partagent le même
    `doi_collection_nakala`, on propage cette valeur sur
    `Collection.miroir.doi_nakala`. Cas typique : tous les items
    d'un fonds Nakala pointent sur la même collection Nakala."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    # Pose un DOI collection commun à tous les items via valeurs_par_defaut.
    profil.valeurs_par_defaut = {"doi_collection_nakala": "10.34847/nkl.commun"}
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    miroir = next(
        c for c in fonds.collections
        if c.type_collection == TypeCollection.MIROIR.value
    )
    # Propagation sur la miroir.
    assert miroir.doi_nakala == "10.34847/nkl.commun"
    # Mais aussi conservé sur chaque item (autonomie).
    for item in fonds.items:
        assert item.doi_collection_nakala == "10.34847/nkl.commun"


def test_propagation_doi_collection_aucune_si_valeurs_multiples(
    session: Session,
) -> None:
    """#3 V0.9.2-import : si les items ont des valeurs différentes de
    `doi_collection_nakala`, on ne propage pas sur la miroir (ambigu —
    quel DOI choisir ?)."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    # PFC-1 reçoit doi A, PFC-2 reçoit doi B via une colonne du
    # tableur. La fixture a une colonne `hash` distincte par fichier
    # → on bricole en pose direct dans le mapping.
    profil.mapping.champs["doi_collection_nakala"] = MappingSimple(
        source="hash"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    miroir = next(
        c for c in fonds.collections
        if c.type_collection == TypeCollection.MIROIR.value
    )
    # Pas de propagation — chaque item a sa propre valeur.
    assert miroir.doi_nakala is None


def test_propagation_doi_collection_respecte_choix_utilisateur(
    session: Session,
) -> None:
    """#3 V0.9.2-import : si la miroir a déjà un `doi_nakala` (posé
    via `collection_miroir.doi_nakala` du profil ou autre), on ne
    l'écrase pas — le choix utilisateur prime sur la propagation auto."""
    profil, chemin = _profil("cas_fichier_colonnes")
    profil.valeurs_par_defaut = {"doi_collection_nakala": "10.34847/nkl.auto"}
    # Pose un DOI miroir explicite via le profil — devrait primer.
    from archives_tool.profils.schema import CollectionMiroirProfil

    profil.collection_miroir = CollectionMiroirProfil(
        doi_nakala="10.34847/nkl.explicite"
    )
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    miroir = next(
        c for c in fonds.collections
        if c.type_collection == TypeCollection.MIROIR.value
    )
    # Le DOI explicite du profil prime sur la propagation auto.
    assert miroir.doi_nakala == "10.34847/nkl.explicite"


def test_type_coar_auto_normalise_libelle_textuel(session: Session) -> None:
    """Trou #2 V0.9.2-import : la colonne `Type` détectée par
    heuristique va en `type_coar` (Item dédié), et la valeur textuelle
    (`journal`, `périodique`, …) est convertie en URI COAR canonique
    via `vocabulaires.normaliser_type_coar`. Sans cette normalisation,
    `item.type_coar = "journal"` brut — non-exportable proprement et
    non reconnu par le sélecteur d'édition inline."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    # Ajoute un mapping `type_coar` ← une colonne du tableur. Comme la
    # fixture n'a pas de colonne « Type » directement, on détourne
    # `titre` (qui contient "Numero 1" / "Numero 2") — pas une valeur
    # COAR reconnue → l'assertion testera le cas « non reconnu, garde
    # la valeur brute ». Puis on bascule sur valeurs reconnues via
    # `valeurs_par_defaut`.
    profil.valeurs_par_defaut = {"type_coar": "journal"}
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    items = sorted(fonds.items, key=lambda i: i.cote)
    # `journal` → URI COAR Périodique (c_2fe3, corrigée V0.9.10).
    for item in items:
        assert item.type_coar == "http://purl.org/coar/resource_type/c_2fe3"


def test_type_coar_libelle_inconnu_garde_brut(session: Session) -> None:
    """Si la valeur du tableur n'est pas un alias COAR reconnu, on
    garde le texte brut sur `item.type_coar` — l'utilisateur peut
    éditer via inline sans perdre l'information d'origine."""
    profil, chemin = _profil("cas_fichier_colonnes")
    profil.valeurs_par_defaut = {"type_coar": "publication exotique"}
    rapport = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport.erreurs == []
    fonds = session.scalar(select(Fonds).where(Fonds.cote == "PFC"))
    item0 = sorted(fonds.items, key=lambda i: i.cote)[0]
    assert item0.type_coar == "publication exotique"


def test_promotion_url_dedup_deterministe(session: Session) -> None:
    """Trou #8 V0.9.2-import : la promotion d'URL est déterministe (ordre
    figé dans `_SLUGS_URL_PROMUS_SOURCE`). Conséquence : deux passes
    d'import sur le même tableur avec le même mapping aboutissent à la
    même `iiif_url_nakala` — la dédup via `_cle_identite_fichier`
    reconnaît correctement les Fichier déjà importés (champ
    `fichiers_deja_connus` du rapport)."""
    from archives_tool.importers.ecrivain import _fichier_depuis_colonnes
    from archives_tool.importers.transformateur import ItemPrepare

    prep1 = ItemPrepare(
        cote="X-001",
        champs_fichier={},
        champs_fichier_metadonnees={
            "data_url": "https://api.nakala.fr/data/abc/sha1",
            "embed_url": "https://api.nakala.fr/embed/abc/sha1",
            "thumb": "https://api.nakala.fr/iiif/abc/sha1/full/!200,200/0/default.jpg",
        },
    )
    prep2 = ItemPrepare(
        cote="X-001",
        champs_fichier={},
        champs_fichier_metadonnees={
            "data_url": "https://api.nakala.fr/data/abc/sha1",
            "embed_url": "https://api.nakala.fr/embed/abc/sha1",
            "thumb": "https://api.nakala.fr/iiif/abc/sha1/full/!200,200/0/default.jpg",
        },
    )
    f1 = _fichier_depuis_colonnes(prep1, ordre=1)
    f2 = _fichier_depuis_colonnes(prep2, ordre=2)
    # Même URL promue (depuis `data_url` car premier dans la liste
    # `_SLUGS_URL_PROMUS_SOURCE` parmi ceux présents).
    assert f1.iiif_url_nakala == f2.iiif_url_nakala
    assert f1.url_promue_depuis == "data_url"
    assert f2.url_promue_depuis == "data_url"


def test_promotion_url_consistance_dry_run_et_reel(session: Session) -> None:
    """Dry-run et mode réel doivent compter le MÊME nombre de Fichier
    après promotion. Garantit que `_executer_dry_run`
    (`f.chemin_relatif or f.iiif_url_nakala`) voit l'URL promue, et
    pas seulement le mode réel via `_ecrire_fichiers`."""
    from archives_tool.profils.schema import MappingSimple

    profil, chemin = _profil("cas_fichier_colonnes")
    del profil.mapping.champs["fichier.iiif_url_nakala"]
    profil.mapping.champs["fichier.metadonnees.data_url"] = MappingSimple(
        source="iiif"
    )
    rapport_dry = importer(profil, chemin, session, _config({}), dry_run=True)
    assert rapport_dry.erreurs == []
    assert rapport_dry.fichiers_ajoutes == 3

    rapport_reel = importer(
        profil, chemin, session, _config({}), dry_run=False, cree_par="Alice"
    )
    assert rapport_reel.erreurs == []
    assert rapport_reel.fichiers_ajoutes == 3
