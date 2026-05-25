"""Tests de la fiche item (V0.9.5) — notice complète sans visionneuse."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from archives_tool.api.services.dashboard import (
    _META_FICHIER_TECHNIQUES,
    _meta_documentaires,
    composer_fiche_item,
)
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Fichier, Item


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


# ---------------------------------------------------------------------------
# Helpers : _meta_documentaires
# ---------------------------------------------------------------------------


def test_meta_documentaires_exclut_techniques() -> None:
    """Les URLs Nakala, hash, extension, chiffre interne sont retirées."""
    meta = {
        "auteur_page": "Topor",  # documentaire
        "data_url": "https://api.nakala.fr/data/X",  # technique
        "embed_url": "https://api.nakala.fr/embed/X",  # technique
        "thumb": "https://api.nakala.fr/iiif/X/thumb",  # technique
        "ext": "jpg",  # technique
        "chiffre": "12",  # technique
        "hash": "abc123",  # technique
        "iiif_url_nakala": "https://api.nakala.fr/iiif/X/info.json",  # technique
        "description": "Dessin satirique",  # documentaire
    }
    docs = _meta_documentaires(meta)
    assert docs == {"auteur_page": "Topor", "description": "Dessin satirique"}


def test_meta_documentaires_none_renvoie_dict_vide() -> None:
    assert _meta_documentaires(None) == {}
    assert _meta_documentaires({}) == {}


def test_meta_documentaires_valeurs_vides_ignorees() -> None:
    """Valeurs None / chaîne vide ne sont pas comptées (cf.
    `_valeur_metadonnee_str` qui retourne None)."""
    meta = {"dessinateur": "Perich", "vide": "", "nul": None}
    assert _meta_documentaires(meta) == {"dessinateur": "Perich"}


# ---------------------------------------------------------------------------
# composer_fiche_item — bout en bout sur demo
# ---------------------------------------------------------------------------


def test_composer_fiche_item_structure(base_demo: Path) -> None:
    """Structure FicheItem complète, sections cohérentes, navigation
    cote précédente / suivante."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        fiche = composer_fiche_item(s, "HK-001", fonds)
        # Sections de base.
        assert fiche.item.cote == "HK-001"
        assert fiche.fonds.cote == "HK"
        assert fiche.nb_fichiers == len(fiche.fichiers)
        assert fiche.nb_fichiers == len(fiche.lignes_fichier)
        # Cartouche identique au composer page item.
        assert "Identification" in fiche.metadonnees_par_section
        assert "Champs personnalisés" in fiche.metadonnees_par_section
        # Au moins 1 collection (la miroir).
        assert any(c.est_miroir for c in fiche.collections)
        # Pas d'agrégat (demo HK n'a pas de Fichier.metadonnees riches).
        assert fiche.agregats_fichier == ()
    engine.dispose()


def test_composer_fiche_item_agregats_si_meta_fichiers(base_demo: Path) -> None:
    """Quand des Fichier.metadonnees ont des valeurs documentaires,
    l'agrégat les liste avec leurs comptes triés desc."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        fichiers = list(s.scalars(
            select(Fichier).where(Fichier.item_id == item.id).limit(5)
        ).all())
        # Injecte des méta documentaires sur 5 fichiers : 3 « Topor »,
        # 2 « Reiser ».
        for i, f in enumerate(fichiers):
            f.metadonnees = {
                "dessinateur": "Topor" if i < 3 else "Reiser",
                "data_url": "https://api.nakala.fr/data/X",  # tech, ignoré
            }
            flag_modified(f, "metadonnees")
        s.commit()

        fonds = lire_fonds_par_cote(s, "HK")
        fiche = composer_fiche_item(s, "HK-001", fonds)
        assert len(fiche.agregats_fichier) == 1
        ag = fiche.agregats_fichier[0]
        assert ag.cle == "dessinateur"
        # Tri : Topor (3) en premier, Reiser (2) ensuite.
        assert ag.valeurs[0] == ("Topor", 3)
        assert ag.valeurs[1] == ("Reiser", 2)
        # data_url NON dans les agrégats (filtré par _META_FICHIER_TECHNIQUES).
        assert all(a.cle != "data_url" for a in fiche.agregats_fichier)
    engine.dispose()


def test_composer_fiche_item_lignes_avec_badge_meta(base_demo: Path) -> None:
    """Les FichierFicheLigne portent `a_meta_documentaires=True`
    quand le fichier a des méta non-techniques — sert au badge ✎ de
    la grille de vignettes."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        fichiers = list(s.scalars(
            select(Fichier).where(Fichier.item_id == item.id).order_by(Fichier.ordre).limit(3)
        ).all())
        # F1 = juste data_url (technique) → pas de badge
        fichiers[0].metadonnees = {"data_url": "https://x"}
        flag_modified(fichiers[0], "metadonnees")
        # F2 = dessinateur (documentaire) → badge
        fichiers[1].metadonnees = {"dessinateur": "Topor"}
        flag_modified(fichiers[1], "metadonnees")
        # F3 = mix → badge (1 documentaire suffit)
        fichiers[2].metadonnees = {"data_url": "https://y", "titre_page": "Une page"}
        flag_modified(fichiers[2], "metadonnees")
        s.commit()

        fonds = lire_fonds_par_cote(s, "HK")
        fiche = composer_fiche_item(s, "HK-001", fonds)
        par_id = {l.id: l for l in fiche.lignes_fichier}
        assert par_id[fichiers[0].id].a_meta_documentaires is False
        assert par_id[fichiers[1].id].a_meta_documentaires is True
        assert par_id[fichiers[2].id].a_meta_documentaires is True
        # meta_extraits ne contient pas les techniques
        assert "data_url" not in par_id[fichiers[2].id].meta_extraits
        assert par_id[fichiers[2].id].meta_extraits.get("titre_page") == "Une page"
    engine.dispose()


def test_composer_fiche_item_introuvable_leve(base_demo: Path) -> None:
    """Cote inexistante → ItemIntrouvable (cohérent avec composer_page_item)."""
    from archives_tool.api.services.items import ItemIntrouvable

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        with pytest.raises(ItemIntrouvable):
            composer_fiche_item(s, "INEXISTANT", fonds)
    engine.dispose()


def test_meta_fichier_techniques_couvre_urls_nakala() -> None:
    """Garde-fou : les patterns d'URL Nakala typiques doivent être dans
    la liste noire — sinon les agrégats sont pollués par fingerprints."""
    pour_etre_couverts = {"data_url", "embed_url", "preview_url", "thumb"}
    assert pour_etre_couverts.issubset(_META_FICHIER_TECHNIQUES)
