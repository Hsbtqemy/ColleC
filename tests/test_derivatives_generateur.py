"""Tests de la génération de dérivés.

Modèle V0.9.0+ : les fichiers sont sélectionnés via un `Perimetre`
(fonds_cote / collection_cote / item_cote / fichier_ids) — la sélection
par collection passe par la junction `ItemCollection`, plus par un
`Item.collection_id` direct.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    CollectionIntrouvable,
    FormulaireCollection,
    creer_collection_libre,
    lire_collection_par_cote,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.derivatives.generateur import generer_derives, nettoyer_derives
from archives_tool.derivatives.rapport import StatutDerive
from archives_tool.models import Fichier, Item, ItemCollection
from archives_tool.renamer import Perimetre


def _ecrire_image(
    chemin: Path, taille: tuple[int, int] = (2000, 1500), mode: str = "RGB"
) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, taille, color=(120, 200, 80)).save(chemin)


def _setup(session: Session, racine_source: Path, fichiers: list[str]) -> None:
    """Fonds HK + 1 item HK-001 (rattaché à la miroir HK) + N fichiers."""
    racine_source.mkdir(parents=True, exist_ok=True)
    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    fonds = lire_fonds_par_cote(session, "HK")
    item = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id),
    )
    for i, nom in enumerate(fichiers, start=1):
        _ecrire_image(racine_source / nom)
        session.add(
            Fichier(
                item_id=item.id,
                racine="src",
                chemin_relatif=nom,
                nom_fichier=nom,
                ordre=i,
            )
        )
    session.commit()


def test_generation_par_fonds(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])

    rap = generer_derives(
        session,
        perimetre=Perimetre(fonds_cote="HK"),
        racines={"src": src, "miniatures": cible},
    )
    assert rap.nb_generes == 1
    assert rap.nb_erreurs == 0
    vignette = cible / "vignette" / "01.jpg"
    apercu = cible / "apercu" / "01.jpg"
    assert vignette.exists()
    assert apercu.exists()

    with Image.open(vignette) as v:
        assert max(v.size) == 300
    with Image.open(apercu) as a:
        assert max(a.size) == 1200

    f = session.scalar(select(Fichier))
    assert f.derive_genere is True
    assert f.largeur_px == 2000
    assert f.hauteur_px == 1500


def test_generation_par_collection_miroir(session: Session, tmp_path: Path) -> None:
    """La miroir auto du fonds HK contient l'item — sélection via la junction."""
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])

    rap = generer_derives(
        session,
        perimetre=Perimetre(collection_cote="HK", collection_fonds_cote="HK"),
        racines={"src": src, "miniatures": cible},
    )
    assert rap.nb_generes == 1


def test_generation_par_collection_libre(session: Session, tmp_path: Path) -> None:
    """Une libre rattachée filtre uniquement ses items."""
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png", "02.png"])
    fonds = lire_fonds_par_cote(session, "HK")
    creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-FAV", titre="Favoris", fonds_id=fonds.id),
    )
    fav = lire_collection_par_cote(session, "HK-FAV", fonds_id=fonds.id)
    item = session.scalar(select(Item))
    session.add(ItemCollection(item_id=item.id, collection_id=fav.id))
    session.commit()

    rap = generer_derives(
        session,
        perimetre=Perimetre(
            collection_cote="HK-FAV", collection_fonds_cote="HK"
        ),
        racines={"src": src, "miniatures": cible},
    )
    # Les 2 fichiers de l'item rattaché.
    assert rap.nb_generes == 2


def test_idempotence_skip_si_deja_genere(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])
    racines = {"src": src, "miniatures": cible}

    generer_derives(session, perimetre=Perimetre(fonds_cote="HK"), racines=racines)
    rap = generer_derives(
        session, perimetre=Perimetre(fonds_cote="HK"), racines=racines
    )
    assert rap.nb_generes == 0
    assert rap.nb_deja_generes == 1


def test_force_regenere(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])
    racines = {"src": src, "miniatures": cible}

    generer_derives(session, perimetre=Perimetre(fonds_cote="HK"), racines=racines)
    _ecrire_image(src / "01.png", taille=(1000, 500))
    rap = generer_derives(
        session,
        perimetre=Perimetre(fonds_cote="HK"),
        racines=racines,
        force=True,
    )
    assert rap.nb_generes == 1


def test_dry_run_n_ecrit_rien(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])

    rap = generer_derives(
        session,
        perimetre=Perimetre(fonds_cote="HK"),
        racines={"src": src, "miniatures": cible},
        dry_run=True,
    )
    assert rap.nb_generes == 1
    assert not (cible / "vignette" / "01.jpg").exists()
    f = session.scalar(select(Fichier))
    assert f.derive_genere is False


def test_source_absente_remonte_erreur(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    src.mkdir()
    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    fonds = lire_fonds_par_cote(session, "HK")
    item = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id),
    )
    session.add(
        Fichier(
            item_id=item.id,
            racine="src",
            chemin_relatif="absent.png",
            nom_fichier="absent.png",
            ordre=1,
        )
    )
    session.commit()

    rap = generer_derives(
        session,
        perimetre=Perimetre(fonds_cote="HK"),
        racines={"src": src, "miniatures": cible},
    )
    assert rap.nb_erreurs == 1
    assert rap.resultats[0].statut == StatutDerive.ERREUR
    assert "absent" in (rap.resultats[0].message or "").lower()


def test_racine_cible_non_configuree(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    _setup(session, src, ["01.png"])
    rap = generer_derives(
        session,
        perimetre=Perimetre(fonds_cote="HK"),
        racines={"src": src},
    )
    assert rap.nb_erreurs == 1
    assert "miniatures" in (rap.resultats[0].message or "")


def test_rgba_compose_sur_blanc(session: Session, tmp_path: Path) -> None:
    """Une image RGBA est aplatie sur fond blanc avant la sauvegarde JPEG."""
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    src.mkdir()
    chemin = src / "transparent.png"
    Image.new("RGBA", (100, 100), color=(255, 0, 0, 0)).save(chemin)

    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    fonds = lire_fonds_par_cote(session, "HK")
    item = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id),
    )
    session.add(
        Fichier(
            item_id=item.id,
            racine="src",
            chemin_relatif="transparent.png",
            nom_fichier="transparent.png",
            ordre=1,
        )
    )
    session.commit()

    rap = generer_derives(
        session,
        perimetre=Perimetre(fonds_cote="HK"),
        racines={"src": src, "miniatures": cible},
    )
    assert rap.nb_generes == 1
    with Image.open(cible / "vignette" / "transparent.jpg") as v:
        assert v.mode == "RGB"


def test_filtre_par_item(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    src.mkdir()
    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    fonds = lire_fonds_par_cote(session, "HK")
    i1 = creer_item(
        session, FormulaireItem(cote="HK-A", titre="A", fonds_id=fonds.id)
    )
    i2 = creer_item(
        session, FormulaireItem(cote="HK-B", titre="B", fonds_id=fonds.id)
    )
    for nom, item in [("a.png", i1), ("b.png", i2)]:
        _ecrire_image(src / nom)
        session.add(
            Fichier(
                item_id=item.id,
                racine="src",
                chemin_relatif=nom,
                nom_fichier=nom,
                ordre=1,
            )
        )
    session.commit()

    rap = generer_derives(
        session,
        perimetre=Perimetre(item_cote="HK-A", item_fonds_cote="HK"),
        racines={"src": src, "miniatures": cible},
    )
    assert rap.nb_generes == 1
    assert (cible / "vignette" / "a.jpg").exists()
    assert not (cible / "vignette" / "b.jpg").exists()


def test_collection_inconnue_leve(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    with pytest.raises(CollectionIntrouvable):
        generer_derives(
            session,
            perimetre=Perimetre(
                collection_cote="INCONNUE", collection_fonds_cote="HK"
            ),
            racines={"src": src, "miniatures": tmp_path},
        )


def test_nettoyer_supprime_les_derives(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])
    racines = {"src": src, "miniatures": cible}

    generer_derives(session, perimetre=Perimetre(fonds_cote="HK"), racines=racines)
    assert (cible / "vignette" / "01.jpg").exists()

    rap = nettoyer_derives(
        session, perimetre=Perimetre(fonds_cote="HK"), racines=racines
    )
    assert rap.nb_nettoyes == 1
    assert not (cible / "vignette" / "01.jpg").exists()
    assert not (cible / "apercu" / "01.jpg").exists()

    f = session.scalar(select(Fichier))
    assert f.derive_genere is False


def test_nettoyer_dry_run_n_efface_pas(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])
    racines = {"src": src, "miniatures": cible}

    generer_derives(session, perimetre=Perimetre(fonds_cote="HK"), racines=racines)
    rap = nettoyer_derives(
        session,
        perimetre=Perimetre(fonds_cote="HK"),
        racines=racines,
        dry_run=True,
    )
    assert rap.nb_nettoyes == 1
    assert (cible / "vignette" / "01.jpg").exists()
