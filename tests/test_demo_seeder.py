"""Tests d'intégrité de la base de démonstration (V0.9.0-alpha.2).

Vérifie que `peupler_base` produit une base conforme aux invariants
et à la composition cible (5 fonds, 1 transversale, ~333 items).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    lire_collection_par_cote,
    supprimer_collection_libre,
)
from archives_tool.api.services.fonds import (
    lire_fonds_par_cote,
    lister_fonds,
)
from archives_tool.api.services.items import (
    collections_de_item,
    lire_item,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import RapportDemo, peupler_base
from archives_tool.models import (
    Collection,
    Fichier,
    Fonds,
    Item,
    TypeCollection,
)


def _all_fonds_models(db: Session) -> list[Fonds]:
    """Charge tous les `Fonds` ORM (vs `lister_fonds` qui rend des
    `FondsResume` sans accès aux relationships)."""
    return list(db.scalars(select(Fonds).order_by(Fonds.cote)).all())


@pytest.fixture(scope="module")
def base_demo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    chemin = tmp_path_factory.mktemp("demo") / "demo.db"
    peupler_base(chemin)
    return chemin


@pytest.fixture
def db_demo(base_demo: Path) -> Session:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Comptages globaux
# ---------------------------------------------------------------------------


def test_5_fonds(db_demo: Session) -> None:
    fonds = lister_fonds(db_demo)
    assert len(fonds) == 5
    cotes = {f.cote for f in fonds}
    assert cotes == {"HK", "FA", "RDM", "MAR", "CONC-1789"}


def test_compteurs_globaux(db_demo: Session) -> None:
    """Vérifie les chiffres approximatifs de la composition cible."""
    nb_items = db_demo.scalar(select(func.count()).select_from(Item)) or 0
    nb_fichiers = db_demo.scalar(select(func.count()).select_from(Fichier)) or 0
    nb_collections = (
        db_demo.scalar(select(func.count()).select_from(Collection)) or 0
    )

    assert 300 <= nb_items <= 350, f"Attendu ~333 items, obtenu {nb_items}"
    assert 800 <= nb_fichiers <= 1500, f"Attendu ~1000 fichiers, obtenu {nb_fichiers}"
    # 5 miroirs + 4 libres FA + 1 transversale = 10.
    assert nb_collections == 10


# ---------------------------------------------------------------------------
# Invariants par fonds
# ---------------------------------------------------------------------------


def test_chaque_fonds_a_sa_miroir(db_demo: Session) -> None:
    """Invariant 1 : tout fonds a exactement une miroir."""
    for fonds in _all_fonds_models(db_demo):
        miroir = fonds.collection_miroir
        assert miroir is not None, f"{fonds.cote} n'a pas de miroir"
        assert miroir.cote == fonds.cote
        assert miroir.titre == fonds.titre
        assert miroir.type_collection == TypeCollection.MIROIR.value


def test_ainsa_a_4_libres_rattachees(db_demo: Session) -> None:
    fonds_fa = lire_fonds_par_cote(db_demo, "FA")
    libres = [
        c
        for c in fonds_fa.collections
        if c.type_collection == TypeCollection.LIBRE.value
    ]
    assert len(libres) == 4
    cotes = {c.cote for c in libres}
    assert cotes == {"FA-OEUVRES", "FA-CORRESP", "FA-DOCU", "FA-PHOTOS"}


def test_hk_a_40_items(db_demo: Session) -> None:
    fonds_hk = lire_fonds_par_cote(db_demo, "HK")
    nb = db_demo.scalar(
        select(func.count()).select_from(Item).where(Item.fonds_id == fonds_hk.id)
    )
    assert nb == 40


def test_ainsa_a_167_items(db_demo: Session) -> None:
    """39 + 32 + 47 + 49 = 167 items répartis dans les 4 libres."""
    fonds_fa = lire_fonds_par_cote(db_demo, "FA")
    nb = db_demo.scalar(
        select(func.count()).select_from(Item).where(Item.fonds_id == fonds_fa.id)
    )
    assert nb == 167


# ---------------------------------------------------------------------------
# Multi-appartenance et transversale
# ---------------------------------------------------------------------------


def test_items_ainsa_dans_miroir_et_libre(db_demo: Session) -> None:
    """Invariant 6 : chaque item d'une libre Aínsa est aussi dans la
    miroir du fonds."""
    fonds_fa = lire_fonds_par_cote(db_demo, "FA")
    miroir = fonds_fa.collection_miroir
    assert miroir is not None

    for libre in fonds_fa.collections:
        if libre.type_collection != TypeCollection.LIBRE.value:
            continue
        # On échantillonne quelques items pour ne pas exploser le test.
        for item in libre.items[:5]:
            collections_item = collections_de_item(db_demo, item.id)
            cotes = {c.cote for c in collections_item}
            assert miroir.cote in cotes, (
                f"Item {item.cote} absent de la miroir {miroir.cote}"
            )
            assert libre.cote in cotes, (
                f"Item {item.cote} absent de la libre {libre.cote}"
            )


def test_collection_transversale_existe(db_demo: Session) -> None:
    coll = lire_collection_par_cote(db_demo, "TEMOIG")
    assert coll.fonds_id is None
    assert coll.type_collection == TypeCollection.LIBRE.value


def test_collection_transversale_traverse_plusieurs_fonds(
    db_demo: Session,
) -> None:
    """La transversale doit contenir des items provenant de >= 2 fonds."""
    coll = lire_collection_par_cote(db_demo, "TEMOIG")
    fonds_des_items = {item.fonds_id for item in coll.items}
    assert len(fonds_des_items) >= 2


def test_collection_transversale_a_18_items(db_demo: Session) -> None:
    coll = lire_collection_par_cote(db_demo, "TEMOIG")
    assert len(coll.items) == 18  # 12 Aínsa + 6 Concorde


# ---------------------------------------------------------------------------
# Cascades et invariants
# ---------------------------------------------------------------------------


def test_supprimer_transversale_garde_items(db_demo: Session) -> None:
    """Supprimer la transversale ne touche pas aux items eux-mêmes."""
    coll = lire_collection_par_cote(db_demo, "TEMOIG")
    items_ids = [i.id for i in coll.items]

    supprimer_collection_libre(db_demo, coll.id)

    for item_id in items_ids:
        item = lire_item(db_demo, item_id)
        assert item.fonds_id is not None


def test_collaborateurs_presents(db_demo: Session) -> None:
    """Au moins quelques collaborateurs sur les fonds principaux."""
    fonds_hk = lire_fonds_par_cote(db_demo, "HK")
    fonds_fa = lire_fonds_par_cote(db_demo, "FA")
    fonds_rdm = lire_fonds_par_cote(db_demo, "RDM")
    assert len(fonds_hk.collaborateurs) >= 2
    assert len(fonds_fa.collaborateurs) >= 2
    assert len(fonds_rdm.collaborateurs) >= 1


def test_invariants_complets(db_demo: Session) -> None:
    """Tous les invariants V0.9.0 tiennent sur la base demo."""
    # Invariant 4 : tout item a fonds_id non NULL (NOT NULL côté schéma,
    # mais on vérifie quand même qu'aucun item n'est orphelin).
    items_orphelins = db_demo.scalar(
        select(func.count()).select_from(Item).where(Item.fonds_id.is_(None))
    )
    assert items_orphelins == 0

    # Invariant 1 : tout fonds a une miroir.
    for fonds in _all_fonds_models(db_demo):
        assert fonds.collection_miroir is not None

    # Invariant 6 : tout item est dans la miroir de son fonds.
    for fonds in _all_fonds_models(db_demo):
        miroir = fonds.collection_miroir
        nb_items_fonds = db_demo.scalar(
            select(func.count()).select_from(Item).where(Item.fonds_id == fonds.id)
        )
        nb_dans_miroir = len(miroir.items)
        assert nb_dans_miroir == nb_items_fonds, (
            f"{fonds.cote} : {nb_items_fonds} items, "
            f"{nb_dans_miroir} dans la miroir"
        )


def test_reproductibilite(tmp_path: Path) -> None:
    """Deux appels successifs avec le même seed produisent le même
    nombre d'items / fichiers / collections."""
    chemin_a = tmp_path / "a.db"
    chemin_b = tmp_path / "b.db"
    rapport_a: RapportDemo = peupler_base(chemin_a, seed=42)
    rapport_b: RapportDemo = peupler_base(chemin_b, seed=42)
    assert rapport_a.nb_fonds == rapport_b.nb_fonds
    assert rapport_a.nb_collections == rapport_b.nb_collections
    assert rapport_a.nb_items == rapport_b.nb_items
    assert rapport_a.nb_fichiers == rapport_b.nb_fichiers
