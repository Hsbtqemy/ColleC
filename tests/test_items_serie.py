"""Tests de la création en série d'items (V0.9.7).

Cas d'usage : préparer N fiches placeholders avant numérisation, pour
pouvoir rattacher les scans au fil. Voir `docs/developpeurs/plan-de-chantier.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import (
    ItemInvalide,
    creer_items_en_serie,
)
from archives_tool.api.services.collections import (
    FormulaireCollection,
    creer_collection_libre,
)
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import (
    Collection,
    Item,
    ItemCollection,
    TypeCollection,
)


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


# ---------------------------------------------------------------------------
# Cas nominal : créer N items dans la miroir
# ---------------------------------------------------------------------------


def test_creer_serie_dans_la_miroir(base_demo: Path) -> None:
    """Cas le plus simple : 5 items dans la miroir d'un fonds frais."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZX", titre="Test serie"))
        rapport = creer_items_en_serie(
            s,
            fonds_id=fonds.id,
            pattern_cote="ZX-{n:03d}",
            de_n=1,
            a_n=5,
            titre_template="Numéro {n}",
            cree_par="marie",
        )
        assert rapport.nb_crees == 5
        assert rapport.nb_ignores == 0
        # Cotes générées dans l'ordre attendu
        cotes = [i.cote for i in rapport.crees]
        assert cotes == ["ZX-001", "ZX-002", "ZX-003", "ZX-004", "ZX-005"]
        # Titres formatés
        titres = [i.titre for i in rapport.crees]
        assert titres == [
            "Numéro 1", "Numéro 2", "Numéro 3", "Numéro 4", "Numéro 5"
        ]
        # Tous rattachés à la miroir
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        nb_dans_miroir = s.scalar(
            select(func.count(ItemCollection.item_id))
            .where(ItemCollection.collection_id == miroir.id)
        )
        assert nb_dans_miroir == 5
        # Tracabilité posée
        for item in rapport.crees:
            assert item.cree_par == "marie"
            assert item.fonds_id == fonds.id
            assert item.etat_catalogage == "brouillon"
    engine.dispose()


def test_creer_serie_sans_titre_template(base_demo: Path) -> None:
    """Sans `titre_template`, les items créés ont un titre vide.
    Acceptable — l'utilisateur les éditera plus tard."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZY", titre="Test"))
        rapport = creer_items_en_serie(
            s, fonds_id=fonds.id, pattern_cote="ZY-{n}", de_n=1, a_n=3,
        )
        assert rapport.nb_crees == 3
        assert all(i.titre == "" for i in rapport.crees)
    engine.dispose()


def test_creer_serie_dans_collection_libre(base_demo: Path) -> None:
    """Si collection_id pointe sur une libre rattachée, les items sont
    rattachés AUSSI à la miroir (invariant 6 : tout item est dans la
    miroir de son fonds)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZA", titre="Test"))
        libre = creer_collection_libre(
            s,
            FormulaireCollection(
                cote="ZA-FAV", titre="Favoris", fonds_id=fonds.id,
            ),
        )
        rapport = creer_items_en_serie(
            s,
            fonds_id=fonds.id,
            collection_id=libre.id,
            pattern_cote="ZA-{n:02d}",
            de_n=1,
            a_n=3,
        )
        assert rapport.nb_crees == 3
        # Items dans la libre
        nb_dans_libre = s.scalar(
            select(func.count(ItemCollection.item_id))
            .where(ItemCollection.collection_id == libre.id)
        )
        assert nb_dans_libre == 3
        # Items dans la miroir aussi (invariant 6)
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        nb_dans_miroir = s.scalar(
            select(func.count(ItemCollection.item_id))
            .where(ItemCollection.collection_id == miroir.id)
        )
        assert nb_dans_miroir == 3
    engine.dispose()


def test_creer_serie_avec_metadonnees_par_defaut(base_demo: Path) -> None:
    """`type_coar` / `langue` / `etat` sont appliqués à tous les items
    créés (mêmes valeurs par défaut sur toute la série)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZB", titre="Test"))
        type_uri = "http://purl.org/coar/resource_type/c_2fe3"
        rapport = creer_items_en_serie(
            s,
            fonds_id=fonds.id,
            pattern_cote="ZB-{n}",
            de_n=1, a_n=4,
            etat="a_verifier",
            type_coar=type_uri,
            langue="fra",
        )
        assert all(i.type_coar == type_uri for i in rapport.crees)
        assert all(i.langue == "fra" for i in rapport.crees)
        assert all(i.etat_catalogage == "a_verifier" for i in rapport.crees)
    engine.dispose()


# ---------------------------------------------------------------------------
# Validation : plage, pattern, état
# ---------------------------------------------------------------------------


def test_creer_serie_plage_inversee_refuse(base_demo: Path) -> None:
    """de_n > a_n → ItemInvalide."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZC", titre="Test"))
        with pytest.raises(ItemInvalide) as exc:
            creer_items_en_serie(
                s, fonds_id=fonds.id, pattern_cote="ZC-{n}", de_n=10, a_n=5,
            )
        assert "plage" in exc.value.erreurs
    engine.dispose()


def test_creer_serie_plage_trop_large_refuse(base_demo: Path) -> None:
    """Cap dur à 1000 items par appel."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZD", titre="Test"))
        with pytest.raises(ItemInvalide) as exc:
            creer_items_en_serie(
                s, fonds_id=fonds.id, pattern_cote="ZD-{n}",
                de_n=1, a_n=2000,
            )
        assert "plage" in exc.value.erreurs
        assert "cap" in exc.value.erreurs["plage"]
    engine.dispose()


def test_creer_serie_pattern_sans_variable_n(base_demo: Path) -> None:
    """Un pattern sans `{n}` produit la même cote pour tous les items
    → conflit dès la 2e cote. On accepte techniquement (toutes les
    cotes valides individuellement) mais la 2e insertion va échouer.
    Pour éviter ça, le service détecte les doublons en amont via le
    SELECT de conflits — mais celui-ci ne voit que les conflits DB,
    pas les doublons intra-série.

    Garde-fou : on s'assure qu'au moins le 1er item est créé puis
    la 2e échoue avec un IntegrityError métier propre.
    """
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZE", titre="Test"))
        with pytest.raises(ItemInvalide):
            creer_items_en_serie(
                s,
                fonds_id=fonds.id,
                pattern_cote="ZE-fixe",  # pas de {n}
                de_n=1, a_n=3,
            )
    engine.dispose()


def test_creer_serie_pattern_format_invalide_refuse(base_demo: Path) -> None:
    """Pattern avec syntaxe `str.format` invalide → ItemInvalide
    explicite plutôt que crash."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZF", titre="Test"))
        with pytest.raises(ItemInvalide) as exc:
            creer_items_en_serie(
                s,
                fonds_id=fonds.id,
                pattern_cote="ZF-{inconnu}",  # variable inconnue
                de_n=1, a_n=3,
            )
        assert "pattern_cote" in exc.value.erreurs
    engine.dispose()


def test_creer_serie_etat_invalide_refuse(base_demo: Path) -> None:
    """État hors enum → ItemInvalide."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZG", titre="Test"))
        with pytest.raises(ItemInvalide) as exc:
            creer_items_en_serie(
                s, fonds_id=fonds.id, pattern_cote="ZG-{n}",
                de_n=1, a_n=2, etat="inexistant",
            )
        assert "etat" in exc.value.erreurs
    engine.dispose()


# ---------------------------------------------------------------------------
# Conflits de cote
# ---------------------------------------------------------------------------


def test_creer_serie_conflit_refuse_par_defaut(base_demo: Path) -> None:
    """Si une cote existe déjà, l'appel par défaut refuse toute la
    série (transactionnel, rien n'est créé). Liste les cotes en
    conflit."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZH", titre="Test"))
        # 1er appel : crée ZH-001 à ZH-003
        creer_items_en_serie(
            s, fonds_id=fonds.id, pattern_cote="ZH-{n:03d}", de_n=1, a_n=3,
        )
        # 2e appel : tentative de re-créer ZH-002 à ZH-005 → conflit
        # sur ZH-002, ZH-003
        with pytest.raises(ItemInvalide) as exc:
            creer_items_en_serie(
                s, fonds_id=fonds.id, pattern_cote="ZH-{n:03d}",
                de_n=2, a_n=5,
            )
        assert "cotes_en_conflit" in exc.value.erreurs
        # ZH-004 et ZH-005 ne doivent PAS avoir été créés
        n = s.scalar(
            select(func.count(Item.id)).where(Item.fonds_id == fonds.id)
        )
        assert n == 3
    engine.dispose()


def test_creer_serie_conflit_ignore_si_demande(base_demo: Path) -> None:
    """Avec `ignorer_existants=True`, les cotes en conflit sont
    sautées silencieusement, le reste est créé."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZI", titre="Test"))
        creer_items_en_serie(
            s, fonds_id=fonds.id, pattern_cote="ZI-{n:03d}", de_n=1, a_n=3,
        )
        rapport = creer_items_en_serie(
            s,
            fonds_id=fonds.id,
            pattern_cote="ZI-{n:03d}",
            de_n=2, a_n=5,
            ignorer_existants=True,
        )
        assert rapport.nb_crees == 2  # ZI-004 + ZI-005
        assert rapport.nb_ignores == 2  # ZI-002 + ZI-003
        assert set(rapport.ignores) == {"ZI-002", "ZI-003"}
        assert {i.cote for i in rapport.crees} == {"ZI-004", "ZI-005"}
        n = s.scalar(
            select(func.count(Item.id)).where(Item.fonds_id == fonds.id)
        )
        assert n == 5
    engine.dispose()


def test_creer_serie_tout_existe_deja_avec_ignore(base_demo: Path) -> None:
    """Cas limite : tous les items existent déjà, ignorer_existants=True
    → rapport vide en `crees`, tout dans `ignores`."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZJ", titre="Test"))
        creer_items_en_serie(
            s, fonds_id=fonds.id, pattern_cote="ZJ-{n}", de_n=1, a_n=3,
        )
        rapport = creer_items_en_serie(
            s, fonds_id=fonds.id, pattern_cote="ZJ-{n}",
            de_n=1, a_n=3, ignorer_existants=True,
        )
        assert rapport.nb_crees == 0
        assert rapport.nb_ignores == 3
    engine.dispose()


# ---------------------------------------------------------------------------
# Erreurs metier
# ---------------------------------------------------------------------------


def test_creer_serie_fonds_inexistant_refuse(base_demo: Path) -> None:
    """fonds_id qui n'existe pas → ItemInvalide."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        with pytest.raises(ItemInvalide) as exc:
            creer_items_en_serie(
                s, fonds_id=99999, pattern_cote="X-{n}", de_n=1, a_n=3,
            )
        assert "fonds_id" in exc.value.erreurs
    engine.dispose()


def test_creer_serie_collection_d_un_autre_fonds_refuse(base_demo: Path) -> None:
    """collection_id qui pointe sur une collection rattachée à un
    AUTRE fonds → refus."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds_a = creer_fonds(s, FormulaireFonds(cote="ZK", titre="A"))
        fonds_b = creer_fonds(s, FormulaireFonds(cote="ZL", titre="B"))
        # Collection libre rattachée au fonds B
        libre_b = creer_collection_libre(
            s,
            FormulaireCollection(
                cote="ZL-FAV", titre="Favoris B", fonds_id=fonds_b.id,
            ),
        )
        with pytest.raises(ItemInvalide) as exc:
            creer_items_en_serie(
                s,
                fonds_id=fonds_a.id,
                collection_id=libre_b.id,
                pattern_cote="ZK-{n}", de_n=1, a_n=3,
            )
        assert "collection_id" in exc.value.erreurs
    engine.dispose()


def test_creer_serie_dans_transversale_autorise(base_demo: Path) -> None:
    """Une transversale (fonds_id NULL) accepte des items de n'importe
    quel fonds. La création doit aboutir."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="ZM", titre="Test"))
        transversale = creer_collection_libre(
            s,
            FormulaireCollection(
                cote="TRANS", titre="Transversale", fonds_id=None,
            ),
        )
        rapport = creer_items_en_serie(
            s,
            fonds_id=fonds.id,
            collection_id=transversale.id,
            pattern_cote="ZM-{n}", de_n=1, a_n=3,
        )
        assert rapport.nb_crees == 3
        # Items dans la transversale + dans la miroir du fonds source
        # (invariant 6)
        for item in rapport.crees:
            nb_appartenance = s.scalar(
                select(func.count(ItemCollection.collection_id))
                .where(ItemCollection.item_id == item.id)
            )
            assert nb_appartenance == 2
    engine.dispose()
