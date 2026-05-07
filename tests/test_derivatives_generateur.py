"""Tests de la génération de dérivés."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.derivatives.generateur import (
    generer_derives,
    nettoyer_derives,
)
from archives_tool.derivatives.rapport import StatutDerive
from archives_tool.models import Collection, Fichier, Item


def _ecrire_image(
    chemin: Path, taille: tuple[int, int] = (2000, 1500), mode: str = "RGB"
) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, taille, color=(120, 200, 80)).save(chemin)


def _setup(session: Session, racine_source: Path, fichiers: list[str]) -> Collection:
    racine_source.mkdir(parents=True, exist_ok=True)
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    item = Item(collection_id=col.id, cote="C-001")
    session.add(item)
    session.flush()
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
    return col


def test_generation_simple(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])

    rap = generer_derives(
        session,
        racines={"src": src, "miniatures": cible},
        collection_cote="C",
    )
    assert rap.nb_generes == 1
    assert rap.nb_erreurs == 0
    # Disque : deux dérivés JPEG.
    vignette = cible / "vignette" / "01.jpg"
    apercu = cible / "apercu" / "01.jpg"
    assert vignette.exists()
    assert apercu.exists()

    # Tailles correctes (côté long).
    with Image.open(vignette) as v:
        assert max(v.size) == 300
    with Image.open(apercu) as a:
        assert max(a.size) == 1200

    # Base : derive_genere passé à True, dimensions originales notées.
    f = session.scalar(select(Fichier))
    assert f.derive_genere is True
    assert f.largeur_px == 2000
    assert f.hauteur_px == 1500


def test_idempotence_skip_si_deja_genere(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])
    racines = {"src": src, "miniatures": cible}

    generer_derives(session, racines=racines, collection_cote="C")
    rap = generer_derives(session, racines=racines, collection_cote="C")
    assert rap.nb_generes == 0
    assert rap.nb_deja_generes == 1


def test_force_regenere(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])
    racines = {"src": src, "miniatures": cible}

    generer_derives(session, racines=racines, collection_cote="C")
    # Modifier la source : régénération doit prendre la nouvelle taille.
    _ecrire_image(src / "01.png", taille=(1000, 500))
    rap = generer_derives(session, racines=racines, collection_cote="C", force=True)
    assert rap.nb_generes == 1


def test_dry_run_n_ecrit_rien(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])

    rap = generer_derives(
        session,
        racines={"src": src, "miniatures": cible},
        collection_cote="C",
        dry_run=True,
    )
    assert rap.nb_generes == 1
    assert not (cible / "vignette" / "01.jpg").exists()
    # Base inchangée.
    f = session.scalar(select(Fichier))
    assert f.derive_genere is False


def test_source_absente_remonte_erreur(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    src.mkdir()
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    item = Item(collection_id=col.id, cote="C-001")
    session.add(item)
    session.flush()
    # Fichier en base mais pas sur disque.
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
        racines={"src": src, "miniatures": cible},
        collection_cote="C",
    )
    assert rap.nb_erreurs == 1
    assert rap.resultats[0].statut == StatutDerive.ERREUR
    assert (
        "absente" in (rap.resultats[0].message or "").lower()
        or "absent" in (rap.resultats[0].message or "").lower()
    )


def test_racine_cible_non_configuree(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    _setup(session, src, ["01.png"])
    rap = generer_derives(
        session,
        racines={"src": src},  # pas de racine "miniatures"
        collection_cote="C",
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

    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    item = Item(collection_id=col.id, cote="C-001")
    session.add(item)
    session.flush()
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
        racines={"src": src, "miniatures": cible},
        collection_cote="C",
    )
    assert rap.nb_generes == 1
    # Le JPEG produit doit être lisible et en mode RGB.
    with Image.open(cible / "vignette" / "transparent.jpg") as v:
        assert v.mode == "RGB"


def test_filtre_par_item(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    src.mkdir()
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    i1 = Item(collection_id=col.id, cote="A")
    i2 = Item(collection_id=col.id, cote="B")
    session.add_all([i1, i2])
    session.flush()
    for i, nom in enumerate(["a.png", "b.png"], start=1):
        _ecrire_image(src / nom)
        session.add(
            Fichier(
                item_id=(i1.id if nom == "a.png" else i2.id),
                racine="src",
                chemin_relatif=nom,
                nom_fichier=nom,
                ordre=1,
            )
        )
    session.commit()

    rap = generer_derives(
        session,
        racines={"src": src, "miniatures": cible},
        item_cote="A",
    )
    assert rap.nb_generes == 1
    assert (cible / "vignette" / "a.jpg").exists()
    assert not (cible / "vignette" / "b.jpg").exists()


def test_perimetre_vide_leve(session: Session, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="périmètre"):
        generer_derives(session, racines={"miniatures": tmp_path})


def test_nettoyer_supprime_les_derives(session: Session, tmp_path: Path) -> None:
    src = tmp_path / "src"
    cible = tmp_path / "cible"
    cible.mkdir()
    _setup(session, src, ["01.png"])
    racines = {"src": src, "miniatures": cible}

    generer_derives(session, racines=racines, collection_cote="C")
    assert (cible / "vignette" / "01.jpg").exists()

    rap = nettoyer_derives(session, racines=racines, collection_cote="C")
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

    generer_derives(session, racines=racines, collection_cote="C")
    rap = nettoyer_derives(session, racines=racines, collection_cote="C", dry_run=True)
    assert rap.nb_nettoyes == 1
    # Le fichier dérivé existe toujours.
    assert (cible / "vignette" / "01.jpg").exists()
