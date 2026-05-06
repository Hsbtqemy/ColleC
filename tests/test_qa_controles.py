"""Tests des contrôles de cohérence (module qa)."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from archives_tool.models import Collection, Fichier, Item
from archives_tool.qa.controles import (
    controler_doublons_par_hash,
    controler_fichiers_manquants_disque,
    controler_items_sans_fichier,
    controler_orphelins_disque,
    controler_tout,
)


# ---------------------------------------------------------------------------
# Helpers de mise en place
# ---------------------------------------------------------------------------


def _collection(
    session: Session, cote: str, titre: str = "T", parent: Collection | None = None
) -> Collection:
    col = Collection(cote_collection=cote, titre=titre, parent=parent)
    session.add(col)
    session.flush()
    return col


def _item(session: Session, col: Collection, cote: str) -> Item:
    item = Item(collection_id=col.id, cote=cote)
    session.add(item)
    session.flush()
    return item


def _fichier(
    session: Session,
    item: Item,
    racine: str,
    chemin_relatif: str,
    *,
    ordre: int = 1,
    nom: str | None = None,
    hash_sha256: str | None = None,
) -> Fichier:
    f = Fichier(
        item_id=item.id,
        racine=racine,
        chemin_relatif=chemin_relatif,
        nom_fichier=nom or chemin_relatif.rsplit("/", 1)[-1],
        ordre=ordre,
        hash_sha256=hash_sha256,
    )
    session.add(f)
    session.flush()
    return f


def _ecrire(racine: Path, chemin_relatif: str, contenu: bytes = b"x") -> Path:
    chemin = racine.joinpath(*chemin_relatif.split("/"))
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    return chemin


# ---------------------------------------------------------------------------
# controler_fichiers_manquants_disque
# ---------------------------------------------------------------------------


def test_fichiers_manquants_signale_uniquement_les_absents(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "scans"
    racine.mkdir()
    _ecrire(racine, "a.png")
    # b.png n'est pas créé sur disque.

    col = _collection(session, "C1")
    it = _item(session, col, "C1-001")
    _fichier(session, it, "scans", "a.png", ordre=1)
    _fichier(session, it, "scans", "b.png", ordre=2)
    session.commit()

    rap = controler_fichiers_manquants_disque(session, {"scans": racine})
    assert rap.nb_anomalies == 1
    assert rap.anomalies[0].chemin_relatif == "b.png"
    assert rap.anomalies[0].racine == "scans"


def test_fichiers_manquants_racine_inconnue_remontee(
    session: Session, tmp_path: Path
) -> None:
    col = _collection(session, "C1")
    it = _item(session, col, "C1-001")
    _fichier(session, it, "manquante", "x.png")
    session.commit()

    rap = controler_fichiers_manquants_disque(session, {})
    # Racine non configurée → chaque fichier rattaché est signalé en avertissement
    # (pas en anomalie « manquant »).
    assert rap.nb_anomalies == 0
    assert any("manquante" in a for a in rap.avertissements)


def test_fichiers_manquants_filtre_par_ids_collections(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "s"
    racine.mkdir()
    c1 = _collection(session, "C1")
    c2 = _collection(session, "C2")
    i1 = _item(session, c1, "C1-001")
    i2 = _item(session, c2, "C2-001")
    _fichier(session, i1, "s", "absent_c1.png")
    _fichier(session, i2, "s", "absent_c2.png")
    session.commit()

    rap = controler_fichiers_manquants_disque(
        session, {"s": racine}, ids_collections=[c1.id]
    )
    assert rap.nb_anomalies == 1
    assert rap.anomalies[0].chemin_relatif == "absent_c1.png"


def test_fichiers_manquants_compare_en_nfc(session: Session, tmp_path: Path) -> None:
    """Sur disque (macOS NFD ou autre), comparaison NFC-stable."""
    racine = tmp_path / "s"
    racine.mkdir()
    # Le nom contient un caractère composé : on l'écrit décomposé sur disque,
    # comme le ferait HFS+/APFS.
    nom_nfd = unicodedata.normalize("NFD", "café.png")
    _ecrire(racine, nom_nfd)

    col = _collection(session, "C")
    it = _item(session, col, "C-1")
    # En base : forme NFC.
    _fichier(session, it, "s", "café.png")
    session.commit()

    rap = controler_fichiers_manquants_disque(session, {"s": racine})
    assert rap.nb_anomalies == 0


# ---------------------------------------------------------------------------
# controler_orphelins_disque
# ---------------------------------------------------------------------------


def test_orphelins_disque_liste_les_fichiers_non_references(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "s"
    racine.mkdir()
    _ecrire(racine, "ref.png")
    _ecrire(racine, "orphelin.png")
    _ecrire(racine, "sous/orph2.tif")

    col = _collection(session, "C")
    it = _item(session, col, "C-1")
    _fichier(session, it, "s", "ref.png")
    session.commit()

    rap = controler_orphelins_disque(session, {"s": racine})
    chemins = sorted(a.chemin_relatif for a in rap.anomalies)
    assert chemins == ["orphelin.png", "sous/orph2.tif"]


def test_orphelins_disque_ignore_extensions_inconnues(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "s"
    racine.mkdir()
    _ecrire(racine, "scan.png")
    _ecrire(racine, "notes.txt")  # ignoré
    _ecrire(racine, ".DS_Store")  # ignoré
    session.commit()

    rap = controler_orphelins_disque(session, {"s": racine})
    assert {a.chemin_relatif for a in rap.anomalies} == {"scan.png"}


def test_orphelins_disque_extensions_personnalisees(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "s"
    racine.mkdir()
    _ecrire(racine, "doc.txt")
    session.commit()

    rap = controler_orphelins_disque(session, {"s": racine}, extensions={"txt"})
    assert {a.chemin_relatif for a in rap.anomalies} == {"doc.txt"}


def test_orphelins_disque_filtre_aux_racines_de_la_collection(
    session: Session, tmp_path: Path
) -> None:
    r1 = tmp_path / "r1"
    r1.mkdir()
    r2 = tmp_path / "r2"
    r2.mkdir()
    _ecrire(r1, "a.png")
    _ecrire(r2, "b.png")

    c1 = _collection(session, "C1")
    c2 = _collection(session, "C2")
    i1 = _item(session, c1, "i1")
    i2 = _item(session, c2, "i2")
    # c1 référence un fichier sur r1, c2 sur r2 (mais pas a.png ni b.png)
    _ecrire(r1, "ref1.png")
    _ecrire(r2, "ref2.png")
    _fichier(session, i1, "r1", "ref1.png")
    _fichier(session, i2, "r2", "ref2.png")
    session.commit()

    rap = controler_orphelins_disque(
        session, {"r1": r1, "r2": r2}, ids_collections=[c1.id]
    )
    # On ne doit voir que les orphelins de r1, pas de r2.
    assert {a.chemin_relatif for a in rap.anomalies} == {"a.png"}


def test_orphelins_disque_nfd_sur_disque_pas_orphelin(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "s"
    racine.mkdir()
    _ecrire(racine, unicodedata.normalize("NFD", "café.png"))

    col = _collection(session, "C")
    it = _item(session, col, "C-1")
    _fichier(session, it, "s", "café.png")  # NFC en base
    session.commit()

    rap = controler_orphelins_disque(session, {"s": racine})
    assert rap.nb_anomalies == 0


# ---------------------------------------------------------------------------
# controler_items_sans_fichier
# ---------------------------------------------------------------------------


def test_items_sans_fichier_liste_les_items_vides(
    session: Session, tmp_path: Path
) -> None:
    col = _collection(session, "C")
    avec = _item(session, col, "AVEC")
    _item(session, col, "SANS-1")
    _item(session, col, "SANS-2")
    racine = tmp_path / "s"
    racine.mkdir()
    _ecrire(racine, "x.png")
    _fichier(session, avec, "s", "x.png")
    session.commit()

    rap = controler_items_sans_fichier(session)
    cotes = sorted(a.cote for a in rap.anomalies)
    assert cotes == ["SANS-1", "SANS-2"]


def test_items_sans_fichier_filtre_par_collections(
    session: Session, tmp_path: Path
) -> None:
    c1 = _collection(session, "C1")
    c2 = _collection(session, "C2")
    _item(session, c1, "A")
    _item(session, c2, "B")
    session.commit()

    rap = controler_items_sans_fichier(session, ids_collections=[c1.id])
    assert {a.cote for a in rap.anomalies} == {"A"}


# ---------------------------------------------------------------------------
# controler_doublons_par_hash
# ---------------------------------------------------------------------------


def test_doublons_groupe_par_hash(session: Session) -> None:
    col = _collection(session, "C")
    i1 = _item(session, col, "I1")
    i2 = _item(session, col, "I2")
    h = "a" * 64
    _fichier(session, i1, "s", "x.png", hash_sha256=h)
    _fichier(session, i2, "s", "y.png", hash_sha256=h)
    _fichier(session, i1, "s", "z.png", ordre=2, hash_sha256="b" * 64)
    session.commit()

    rap = controler_doublons_par_hash(session)
    assert rap.nb_anomalies == 1  # un seul groupe
    groupe = rap.anomalies[0]
    assert groupe.hash_sha256 == h
    assert len(groupe.fichiers) == 2


def test_doublons_signale_les_fichiers_sans_hash_en_avertissement(
    session: Session,
) -> None:
    col = _collection(session, "C")
    it = _item(session, col, "I")
    _fichier(session, it, "s", "x.png", hash_sha256=None)
    _fichier(session, it, "s", "y.png", ordre=2, hash_sha256=None)
    session.commit()

    rap = controler_doublons_par_hash(session)
    assert rap.nb_anomalies == 0
    assert any("hash" in a.lower() for a in rap.avertissements)


# ---------------------------------------------------------------------------
# Orchestrateur controler_tout
# ---------------------------------------------------------------------------


def test_controler_tout_lance_les_quatre_par_defaut(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "s"
    racine.mkdir()
    col = _collection(session, "C")
    _item(session, col, "vide")
    session.commit()

    rapport = controler_tout(session, racines={"s": racine})
    assert {r.code for r in rapport.controles} == {
        "fichiers-manquants",
        "orphelins-disque",
        "items-vides",
        "doublons",
    }


def test_controler_tout_subset(session: Session, tmp_path: Path) -> None:
    col = _collection(session, "C")
    _item(session, col, "vide")
    session.commit()

    rapport = controler_tout(session, racines={}, checks={"items-vides"})
    assert [r.code for r in rapport.controles] == ["items-vides"]


def test_controler_tout_collection_introuvable(session: Session) -> None:
    with pytest.raises(ValueError, match="introuvable"):
        controler_tout(session, racines={}, collection_cote="N_EXISTE_PAS")


def test_controler_tout_collection_recursive(session: Session) -> None:
    parent = _collection(session, "P")
    enfant = _collection(session, "E", parent=parent)
    _item(session, parent, "p-vide")
    _item(session, enfant, "e-vide")
    session.commit()

    rap_non_rec = controler_tout(
        session, racines={}, collection_cote="P", checks={"items-vides"}
    )
    assert rap_non_rec.controles[0].nb_anomalies == 1

    rap_rec = controler_tout(
        session,
        racines={},
        collection_cote="P",
        recursif=True,
        checks={"items-vides"},
    )
    assert rap_rec.controles[0].nb_anomalies == 2


def test_controler_tout_orphelins_sans_racines_avertit(session: Session) -> None:
    col = _collection(session, "C")
    _item(session, col, "I")
    session.commit()

    rapport = controler_tout(session, racines=None, checks={"orphelins-disque"})
    ctrl = rapport.controles[0]
    assert ctrl.nb_anomalies == 0
    assert any("racine" in a.lower() for a in ctrl.avertissements)
