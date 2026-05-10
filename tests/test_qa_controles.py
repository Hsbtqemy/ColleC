"""Tests des contrôles qa (V0.9.0-gamma.3).

Une test par contrôle : un cas où il passe et un cas où il échoue.
Les cas d'échec injectent volontairement un problème en base
(suppression de la miroir, retrait d'un item de sa miroir, hash
dupliqué, cote invalide…) et vérifient que le contrôle le détecte.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    FormulaireCollection,
    creer_collection_libre,
    lire_collection_par_cote,
    retirer_item_de_collection,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    creer_item,
)
from archives_tool.models import (
    Fichier,
    Item,
    ItemCollection,
)
from archives_tool.qa import (
    Severite,
    composer_perimetre,
    controler_cross_cote_dupliquee_fonds,
    controler_cross_fonds_vide,
    controler_file_hash_duplique,
    controler_file_hash_manquant,
    controler_file_item_vide,
    controler_file_missing,
    controler_inv1_miroir_unique,
    controler_inv2_miroir_avec_fonds,
    controler_inv4_item_avec_fonds,
    controler_inv6_item_dans_miroir,
    controler_meta_annee_implausible,
    controler_meta_cote_invalide,
    controler_meta_date_invalide,
    controler_meta_titre_vide,
)


@pytest.fixture
def session_un_fonds(session: Session) -> Session:
    """Fonds HK + 3 items + 2 fichiers — base saine, sert de référence."""
    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    fonds = lire_fonds_par_cote(session, "HK")
    item_a = creer_item(
        session,
        FormulaireItem(
            cote="HK-001", titre="N°1", fonds_id=fonds.id, annee=1969
        ),
    )
    item_b = creer_item(
        session,
        FormulaireItem(
            cote="HK-002", titre="N°2", fonds_id=fonds.id, annee=1970
        ),
    )
    creer_item(
        session,
        FormulaireItem(
            cote="HK-003", titre="N°3", fonds_id=fonds.id, annee=1971
        ),
    )
    session.add_all(
        [
            Fichier(
                item_id=item_a.id,
                racine="s",
                chemin_relatif="HK-001/01.tif",
                nom_fichier="01.tif",
                ordre=1,
                hash_sha256="aaaa1111",
            ),
            Fichier(
                item_id=item_b.id,
                racine="s",
                chemin_relatif="HK-002/01.tif",
                nom_fichier="01.tif",
                ordre=1,
                hash_sha256="bbbb2222",
            ),
        ]
    )
    session.commit()
    return session


# ---------------------------------------------------------------------------
# Famille 1 — invariants
# ---------------------------------------------------------------------------


def test_inv1_passe_sur_base_saine(session_un_fonds: Session) -> None:
    perimetre = composer_perimetre(session_un_fonds)
    res = controler_inv1_miroir_unique(session_un_fonds, perimetre)
    assert res.passe
    assert res.compte_total == 1
    assert res.severite == Severite.ERREUR


def test_inv1_detecte_fonds_sans_miroir(session_un_fonds: Session) -> None:
    """Suppression manuelle de la miroir → INV1 le détecte."""
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    miroir = fonds.collection_miroir
    # Retire les liaisons puis la miroir directement (manipulation
    # hors API qui contournerait la garde du service).
    session_un_fonds.execute(
        ItemCollection.__table__.delete().where(
            ItemCollection.collection_id == miroir.id
        )
    )
    session_un_fonds.delete(miroir)
    session_un_fonds.commit()

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_inv1_miroir_unique(session_un_fonds, perimetre)
    assert not res.passe
    assert res.compte_problemes == 1
    assert "HK" in res.exemples[0].message


def test_inv2_passe_sur_base_saine(session_un_fonds: Session) -> None:
    perimetre = composer_perimetre(session_un_fonds)
    res = controler_inv2_miroir_avec_fonds(session_un_fonds, perimetre)
    assert res.passe


def test_inv4_passe_sur_base_saine(session_un_fonds: Session) -> None:
    perimetre = composer_perimetre(session_un_fonds)
    res = controler_inv4_item_avec_fonds(session_un_fonds, perimetre)
    assert res.passe
    assert res.compte_total == 3


def test_inv6_passe_sur_base_saine(session_un_fonds: Session) -> None:
    perimetre = composer_perimetre(session_un_fonds)
    res = controler_inv6_item_dans_miroir(session_un_fonds, perimetre)
    assert res.passe
    assert res.severite == Severite.AVERTISSEMENT  # invariant 7 permet le retrait


def test_inv6_signale_item_retire_miroir(session_un_fonds: Session) -> None:
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    miroir = fonds.collection_miroir
    item_hk1 = session_un_fonds.scalar(
        select(Item).where(Item.cote == "HK-001", Item.fonds_id == fonds.id)
    )
    retirer_item_de_collection(session_un_fonds, item_hk1.id, miroir.id)

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_inv6_item_dans_miroir(session_un_fonds, perimetre)
    assert not res.passe
    assert res.compte_problemes == 1
    assert "HK-001" in res.exemples[0].message


# ---------------------------------------------------------------------------
# Famille 2 — fichiers
# ---------------------------------------------------------------------------


def test_file_missing_signale_racine_non_configuree(
    session_un_fonds: Session,
) -> None:
    """Sans racines configurées, FILE-MISSING signale la config absente."""
    perimetre = composer_perimetre(session_un_fonds)
    res = controler_file_missing(session_un_fonds, perimetre, racines={})
    assert not res.passe
    assert "non configurée" in res.exemples[0].message


def test_file_missing_passe_avec_fichiers_reels(
    session_un_fonds: Session, tmp_path: Path
) -> None:
    """Si on crée vraiment les fichiers sur disque, FILE-MISSING passe."""
    racine = tmp_path / "s"
    (racine / "HK-001").mkdir(parents=True)
    (racine / "HK-002").mkdir(parents=True)
    (racine / "HK-001" / "01.tif").write_bytes(b"fake")
    (racine / "HK-002" / "01.tif").write_bytes(b"fake")

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_file_missing(
        session_un_fonds, perimetre, racines={"s": racine}
    )
    assert res.passe


def test_file_item_vide_signale_item_sans_fichier(
    session_un_fonds: Session,
) -> None:
    """HK-003 n'a aucun fichier → FILE-ITEM-VIDE le voit."""
    perimetre = composer_perimetre(session_un_fonds)
    res = controler_file_item_vide(session_un_fonds, perimetre)
    assert not res.passe
    assert res.compte_problemes == 1
    assert "HK-003" in res.exemples[0].message


def test_file_hash_duplique_detecte(session_un_fonds: Session) -> None:
    """Crée 2 fichiers avec même hash → FILE-HASH-DUPLIQUE le voit."""
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    item = session_un_fonds.scalar(
        select(Item).where(Item.cote == "HK-003", Item.fonds_id == fonds.id)
    )
    session_un_fonds.add_all(
        [
            Fichier(
                item_id=item.id,
                racine="s",
                chemin_relatif="HK-003/01.tif",
                nom_fichier="01.tif",
                ordre=1,
                hash_sha256="cccc3333",
            ),
            Fichier(
                item_id=item.id,
                racine="s",
                chemin_relatif="HK-003/02.tif",
                nom_fichier="02.tif",
                ordre=2,
                hash_sha256="cccc3333",  # même hash
            ),
        ]
    )
    session_un_fonds.commit()

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_file_hash_duplique(session_un_fonds, perimetre)
    assert not res.passe
    assert res.compte_problemes == 2  # 2 fichiers concernés


def test_file_hash_manquant_signale_fichier_sans_hash(
    session_un_fonds: Session,
) -> None:
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    item = session_un_fonds.scalar(
        select(Item).where(Item.cote == "HK-003", Item.fonds_id == fonds.id)
    )
    session_un_fonds.add(
        Fichier(
            item_id=item.id,
            racine="s",
            chemin_relatif="HK-003/01.tif",
            nom_fichier="01.tif",
            ordre=1,
            hash_sha256=None,
        )
    )
    session_un_fonds.commit()

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_file_hash_manquant(session_un_fonds, perimetre)
    assert not res.passe
    assert res.compte_problemes == 1
    assert res.severite == Severite.INFO


# ---------------------------------------------------------------------------
# Famille 3 — métadonnées
# ---------------------------------------------------------------------------


def test_meta_cote_invalide_passe_sur_base_saine(
    session_un_fonds: Session,
) -> None:
    perimetre = composer_perimetre(session_un_fonds)
    res = controler_meta_cote_invalide(session_un_fonds, perimetre)
    assert res.passe


def test_meta_cote_invalide_detecte_cote_avec_espace(
    session_un_fonds: Session,
) -> None:
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    item = session_un_fonds.scalar(
        select(Item).where(Item.cote == "HK-001", Item.fonds_id == fonds.id)
    )
    item.cote = "HK 001"  # espace interdit
    session_un_fonds.commit()

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_meta_cote_invalide(session_un_fonds, perimetre)
    assert not res.passe
    assert "HK 001" in res.exemples[0].message


def test_meta_titre_vide_detecte(session_un_fonds: Session) -> None:
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    item = session_un_fonds.scalar(
        select(Item).where(Item.cote == "HK-002", Item.fonds_id == fonds.id)
    )
    item.titre = "   "  # whitespace-only
    session_un_fonds.commit()

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_meta_titre_vide(session_un_fonds, perimetre)
    assert not res.passe
    assert "HK-002" in res.exemples[0].message


def test_meta_date_invalide_signale_date_libre(session_un_fonds: Session) -> None:
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    item = session_un_fonds.scalar(
        select(Item).where(Item.cote == "HK-001", Item.fonds_id == fonds.id)
    )
    item.date = "n'importe quoi"
    session_un_fonds.commit()

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_meta_date_invalide(session_un_fonds, perimetre)
    assert not res.passe
    assert res.compte_problemes == 1


def test_meta_annee_implausible_detecte_annee_hors_plage(
    session_un_fonds: Session,
) -> None:
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    item = session_un_fonds.scalar(
        select(Item).where(Item.cote == "HK-001", Item.fonds_id == fonds.id)
    )
    item.annee = 500  # < 1000
    session_un_fonds.commit()

    perimetre = composer_perimetre(session_un_fonds)
    res = controler_meta_annee_implausible(session_un_fonds, perimetre)
    assert not res.passe
    assert "500" in res.exemples[0].message


# ---------------------------------------------------------------------------
# Famille 4 — cross
# ---------------------------------------------------------------------------


def test_cross_cote_dupliquee_passe_sur_base_saine(
    session_un_fonds: Session,
) -> None:
    perimetre = composer_perimetre(session_un_fonds)
    res = controler_cross_cote_dupliquee_fonds(session_un_fonds, perimetre)
    assert res.passe


def test_cross_fonds_vide_signale_fonds_sans_items(session: Session) -> None:
    """Un fonds créé sans items → CROSS-FONDS-VIDE le signale (info)."""
    creer_fonds(session, FormulaireFonds(cote="VIDE", titre="Fonds vide"))
    perimetre = composer_perimetre(session)
    res = controler_cross_fonds_vide(session, perimetre)
    assert not res.passe
    assert res.severite == Severite.INFO
    assert any("VIDE" in e.message for e in res.exemples)


# ---------------------------------------------------------------------------
# Périmètre filtré (--fonds, --collection)
# ---------------------------------------------------------------------------


def test_perimetre_par_fonds_restreint_les_items(
    session_un_fonds: Session,
) -> None:
    """Le périmètre fonds limite INV6 aux items de ce fonds."""
    creer_fonds(session_un_fonds, FormulaireFonds(cote="FA", titre="Aínsa"))
    fonds_fa = lire_fonds_par_cote(session_un_fonds, "FA")
    creer_item(
        session_un_fonds,
        FormulaireItem(cote="FA-001", titre="X", fonds_id=fonds_fa.id),
    )

    perimetre_hk = composer_perimetre(
        session_un_fonds, fonds_id=lire_fonds_par_cote(session_un_fonds, "HK").id
    )
    res = controler_inv6_item_dans_miroir(session_un_fonds, perimetre_hk)
    # 3 items HK uniquement (pas FA-001).
    assert res.compte_total == 3


def test_perimetre_par_collection(session_un_fonds: Session) -> None:
    """Le périmètre collection limite FILE-ITEM-VIDE aux items de la collection."""
    fonds = lire_fonds_par_cote(session_un_fonds, "HK")
    creer_collection_libre(
        session_un_fonds,
        FormulaireCollection(cote="HK-FAV", titre="Favoris", fonds_id=fonds.id),
    )
    fav = lire_collection_par_cote(session_un_fonds, "HK-FAV", fonds_id=fonds.id)
    item_hk1 = session_un_fonds.scalar(
        select(Item).where(Item.cote == "HK-001", Item.fonds_id == fonds.id)
    )
    session_un_fonds.add(
        ItemCollection(item_id=item_hk1.id, collection_id=fav.id)
    )
    session_un_fonds.commit()

    perimetre = composer_perimetre(session_un_fonds, collection_id=fav.id)
    res = controler_file_item_vide(session_un_fonds, perimetre)
    # 1 seul item dans la collection HK-FAV, et il a un fichier.
    assert res.compte_total == 1
    assert res.passe
