"""Tests du service `composer_dashboard` (stats, répartitions, activité).

Couverture :
- Compteurs globaux (`DashboardStats`).
- Répartition d'états par fonds et par collection.
- Activité récente : ordre + sources mélangées (item / collection / fonds).
- Performance SQL : décompte des requêtes émises par
  `composer_dashboard` sur la base demo (objectif < 12 queries quel
  que soit le volume).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    FormulaireCollection,
    creer_collection_libre,
)
from archives_tool.api.services.dashboard import (
    ActiviteRecente,
    DashboardResume,
    DashboardStats,
    composer_dashboard,
)
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Base, Collection, EtatCatalogage, Item


# ---------------------------------------------------------------------------
# Fixtures : base demo + bases ad-hoc construites par les tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_demo_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    chemin = tmp_path_factory.mktemp("demo_dashboard") / "demo.db"
    peupler_base(chemin)
    return chemin


@pytest.fixture
def session_demo(base_demo_path: Path) -> Iterator[Session]:
    engine = creer_engine(base_demo_path)
    factory = creer_session_factory(engine)
    with factory() as db:
        yield db
    engine.dispose()


@pytest.fixture
def session_neuve(tmp_path: Path) -> Iterator[Session]:
    """Base SQLite vierge (schéma initialisé, sans peuplement)."""
    db_path = tmp_path / "neuve.db"
    engine = creer_engine(db_path)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as db:
        yield db
    engine.dispose()


# ---------------------------------------------------------------------------
# Stats globales
# ---------------------------------------------------------------------------


def test_dashboard_stats_compteurs_demo(session_demo: Session) -> None:
    """Les compteurs globaux correspondent au seed (5 fonds, 333 items)."""
    resume: DashboardResume = composer_dashboard(session_demo)
    assert resume.stats.nb_fonds == 5
    assert resume.stats.nb_collections >= 5  # au moins une miroir par fonds
    assert resume.stats.nb_items == 333
    assert resume.stats.nb_fichiers > 0
    assert 0 <= resume.stats.nb_items_valides <= resume.stats.nb_items


def test_dashboard_pct_valides_proportionnel(session_demo: Session) -> None:
    resume = composer_dashboard(session_demo)
    attendu = (resume.stats.nb_items_valides / resume.stats.nb_items) * 100
    assert resume.stats.pct_valides == pytest.approx(attendu, abs=1e-6)


def test_dashboard_pct_valides_zero_division_safe() -> None:
    """Sur une base vide, `pct_valides` reste 0.0 (pas de division)."""
    s = DashboardStats(
        nb_fonds=0, nb_collections=0, nb_items=0, nb_fichiers=0, nb_items_valides=0
    )
    assert s.pct_valides == 0.0


# ---------------------------------------------------------------------------
# Répartition d'états
# ---------------------------------------------------------------------------


def test_dashboard_repartition_par_fonds_complete(session_demo: Session) -> None:
    """Chaque fonds expose les 5 clés d'EtatCatalogage (zéros inclus) et
    leur somme égale le nombre d'items du fonds."""
    resume = composer_dashboard(session_demo)
    cles_attendues = {e.value for e in EtatCatalogage}
    for fonds in resume.fonds:
        assert set(fonds.repartition_etats.keys()) == cles_attendues
        assert sum(fonds.repartition_etats.values()) == fonds.nb_items


def test_dashboard_repartition_par_collection(session_demo: Session) -> None:
    """La somme de la répartition d'une collection égale son nb_items."""
    resume = composer_dashboard(session_demo)
    for fonds in resume.fonds:
        if fonds.collection_miroir:
            col = fonds.collection_miroir
            assert sum(col.repartition_etats.values()) == col.nb_items
        for col in fonds.collections_libres:
            assert sum(col.repartition_etats.values()) == col.nb_items


# ---------------------------------------------------------------------------
# Activité récente
# ---------------------------------------------------------------------------


def test_dashboard_activite_recente_base_neuve(session_neuve: Session) -> None:
    """Sur une base sans modifications, l'activité est vide."""
    creer_fonds(session_neuve, FormulaireFonds(cote="X", titre="Fonds X"))
    resume = composer_dashboard(session_neuve)
    assert resume.activite_recente == ()


def test_dashboard_activite_recente_tri_decroissant(
    session_neuve: Session,
) -> None:
    """L'activité est triée par date décroissante, types mélangés."""
    fonds = creer_fonds(session_neuve, FormulaireFonds(cote="X", titre="Fonds X"))
    item = creer_item(
        session_neuve,
        FormulaireItem(cote="X-001", titre="Item un", fonds_id=fonds.id),
    )
    creer_collection_libre(
        session_neuve,
        FormulaireCollection(cote="X-LIB", titre="Libre X", fonds_id=fonds.id),
    )

    # Pose des timestamps déterministes : item le plus récent, puis
    # collection, puis fonds.
    ref = datetime(2026, 1, 1, 12, 0, 0)
    item.modifie_le = ref + timedelta(hours=2)
    item.modifie_par = "Marie"
    col = session_neuve.scalar(select(Collection).where(Collection.cote == "X-LIB"))
    assert col is not None
    col.modifie_le = ref + timedelta(hours=1)
    col.modifie_par = "Paul"
    fonds.modifie_le = ref
    fonds.modifie_par = "Hugo"
    session_neuve.commit()

    resume = composer_dashboard(session_neuve)
    assert len(resume.activite_recente) == 3
    types_ordre = [a.type for a in resume.activite_recente]
    assert types_ordre == ["item", "collection", "fonds"]
    assert resume.activite_recente[0].modifie_par == "Marie"
    assert resume.activite_recente[2].modifie_par == "Hugo"


def test_dashboard_activite_recente_limite_10_par_defaut(
    session_neuve: Session,
) -> None:
    """L'activité est limitée à 10 entrées par défaut."""
    fonds = creer_fonds(session_neuve, FormulaireFonds(cote="X", titre="Fonds X"))
    for i in range(15):
        creer_item(
            session_neuve,
            FormulaireItem(
                cote=f"X-{i:03d}", titre=f"Item {i}", fonds_id=fonds.id
            ),
        )
    ref = datetime(2026, 1, 1, 12, 0, 0)
    for i, item in enumerate(session_neuve.scalars(select(Item)).all()):
        item.modifie_le = ref + timedelta(minutes=i)
    session_neuve.commit()

    resume = composer_dashboard(session_neuve)
    assert len(resume.activite_recente) == 10


# ---------------------------------------------------------------------------
# Performance SQL
# ---------------------------------------------------------------------------


def test_dashboard_n_emet_pas_plus_de_11_requetes(session_demo: Session) -> None:
    """Garde-fou : `composer_dashboard` reste sous 11 requêtes SQL sur la
    base demo (5 fonds, 10 collections, 333 items, ~1300 fichiers).

    Indépendamment du volume — toute boucle Python ne fait
    qu'attacher des agrégats déjà calculés. Si ce test régresse,
    quelqu'un a réintroduit un N+1 ou une query dérivable.
    """
    queries: list[str] = []

    def _on_execute(_conn, _cur, statement, *_args, **_kwargs):
        queries.append(statement)

    engine = session_demo.get_bind()
    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        composer_dashboard(session_demo)
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)

    assert len(queries) <= 11, (
        f"composer_dashboard a émis {len(queries)} requêtes "
        f"(limite : 11). Première requête : {queries[0][:80]}"
    )


# ---------------------------------------------------------------------------
# Sanité du DashboardResume retourné
# ---------------------------------------------------------------------------


def test_dashboard_resume_dataclasses_sont_frozen(session_demo: Session) -> None:
    """`DashboardResume` et `DashboardStats` sont immuables — un
    consommateur ne peut pas modifier le résultat par accident."""
    resume = composer_dashboard(session_demo)
    with pytest.raises((AttributeError, TypeError)):
        resume.stats = None  # type: ignore[misc]


def test_dashboard_activite_recente_typage(session_demo: Session) -> None:
    """Les entrées d'activité ont les attributs attendus."""
    resume = composer_dashboard(session_demo)
    for a in resume.activite_recente:
        assert isinstance(a, ActiviteRecente)
        assert a.type in ("item", "collection", "fonds")
        assert a.cote
        assert a.modifie_le is not None
