"""Tests de la synthèse de fonds (V0.9.6) — section dense
au-dessus de la liste des collections sur /fonds/<cote>."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from archives_tool.api.services.dashboard import (
    CartographieCollections,
    SyntheseFonds,
    _composer_cartographie_collections,
    composer_synthese_fonds,
)
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fonds,
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
# Cartographie cross-collection — cœur de la valeur ajoutée vs synthese
# collection (qui reste, elle, intra-collection).
# ---------------------------------------------------------------------------


def test_cartographie_fonds_sans_libre_montre_la_miroir(
    base_demo: Path,
) -> None:
    """Un fonds avec uniquement sa miroir (cas usuel : PF, HK, MAR) :
    cartographie pas vide (la miroir reste un récap utile). Seul un
    fonds totalement sans collection (cas pathologique) est `vide`.
    """
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        carto = _composer_cartographie_collections(s, fonds)
        # Pas vide : la miroir est un récap utile pour l'utilisateur
        # (« cette collection unique contient tous les items »)
        assert not carto.vide
        assert carto.nb_libres == 0
        # Une seule entrée : la miroir
        assert len(carto.entrees) == 1
        assert carto.entrees[0].est_miroir
        # Tous les items sont dans la miroir, aucun ailleurs
        assert carto.nb_items_dans_libres == 0
    engine.dispose()


def test_cartographie_fonds_avec_libres_recense_chevauchements(
    base_demo: Path,
) -> None:
    """Un fonds avec libres (cas demo `FA`) : la cartographie expose
    pour chaque collection le nb d'items + nb partagés."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "FA")
        carto = _composer_cartographie_collections(s, fonds)
        assert not carto.vide
        assert carto.nb_libres >= 1
        # La miroir est toujours en première position
        assert carto.entrees[0].est_miroir
        # Cohérence : somme des items des libres == nb items dans libres
        # (vrai uniquement si pas de chevauchement entre libres ; sur FA
        # demo c'est le cas)
        items_libres = sum(
            e.nb_items for e in carto.entrees if not e.est_miroir
        )
        # nb_items_dans_libres compte les items distincts présents dans
        # ≥1 libre : si les libres ne chevauchent pas, c'est égal à la
        # somme ; sinon plus petit.
        assert carto.nb_items_dans_libres <= items_libres
    engine.dispose()


def test_cartographie_compte_chevauchement_entre_libres(
    base_demo: Path,
) -> None:
    """Quand un item est explicitement dans 2 libres, il doit être
    compté dans `nb_items_dans_plusieurs_libres` et apparaître comme
    partagé dans les `nb_partages` de chaque libre concernée."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        # Setup : créer 2 libres dans le fonds HK + un item qu'on
        # rattache aux 2.
        fonds = lire_fonds_par_cote(s, "HK")
        libre_a = Collection(
            cote="HK-LIBRE-A",
            titre="HK Libre A",
            type_collection=TypeCollection.LIBRE.value,
            fonds_id=fonds.id,
            cree_par="test",
            modifie_par="test",
        )
        libre_b = Collection(
            cote="HK-LIBRE-B",
            titre="HK Libre B",
            type_collection=TypeCollection.LIBRE.value,
            fonds_id=fonds.id,
            cree_par="test",
            modifie_par="test",
        )
        s.add_all([libre_a, libre_b])
        s.commit()

        item = s.scalar(select(Item).where(Item.fonds_id == fonds.id).limit(1))
        s.add(ItemCollection(item_id=item.id, collection_id=libre_a.id))
        s.add(ItemCollection(item_id=item.id, collection_id=libre_b.id))
        s.commit()

        carto = _composer_cartographie_collections(s, fonds)
        # L'item est dans 2 libres → compté dans
        # nb_items_dans_plusieurs_libres
        assert carto.nb_items_dans_plusieurs_libres >= 1
        # Chaque libre voit ce partage avec l'autre
        e_a = next(e for e in carto.entrees if e.cote == "HK-LIBRE-A")
        e_b = next(e for e in carto.entrees if e.cote == "HK-LIBRE-B")
        assert e_a.nb_partages >= 1
        assert e_b.nb_partages >= 1
    engine.dispose()


def test_cartographie_fonds_sans_collection_renvoie_vide(
    base_demo: Path,
) -> None:
    """Garde-fou : un Fonds sans aucune collection (cas pathologique —
    invariant 1 dit qu'une miroir est créée à la création du fonds,
    mais on teste la robustesse) ne crashe pas."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds_vide = Fonds(
            cote="VIDE-TEST",
            titre="Fonds vide",
            cree_par="test",
            modifie_par="test",
        )
        s.add(fonds_vide)
        s.commit()
        carto = _composer_cartographie_collections(s, fonds_vide)
        assert carto.vide
        assert carto.entrees == ()
    engine.dispose()


# ---------------------------------------------------------------------------
# composer_synthese_fonds — bout en bout
# ---------------------------------------------------------------------------


def test_synthese_fonds_structure_globale(base_demo: Path) -> None:
    """Sur la demo, `HK` contient ≥ 1 item. La synthèse renvoie une
    structure non vide avec items_recents, vignettes éventuelles,
    cartographie qui contient la miroir (V0.9.6-fix : on garde la
    miroir comme récap utile, plus de masquage agressif)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        synthese = composer_synthese_fonds(s, fonds)
        assert isinstance(synthese, SyntheseFonds)
        assert synthese.nb_items_total > 0
        assert len(synthese.items_recents) <= 5
        # Cartographie pas vide : la miroir constitue un récap utile
        assert not synthese.cartographie.vide
        assert synthese.cartographie.nb_libres == 0
        assert len(synthese.cartographie.entrees) == 1
        assert synthese.cartographie.entrees[0].est_miroir
    engine.dispose()


def test_synthese_fonds_etend_aux_items_de_toutes_collections(
    base_demo: Path,
) -> None:
    """Garde-fou clé : la synthèse fonds agrège sur **tous les items
    du fonds** (via `Item.fonds_id`), pas seulement ceux d'une
    collection. Sur `FA` (fonds avec libres) on doit retrouver les 167
    items du fonds (= ceux de la miroir, par invariant)."""
    from sqlalchemy import func
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "FA")
        synthese = composer_synthese_fonds(s, fonds)
        nb_via_fonds_id = s.scalar(
            select(func.count(Item.id)).where(Item.fonds_id == fonds.id)
        )
        assert synthese.nb_items_total == nb_via_fonds_id
    engine.dispose()


def test_synthese_fonds_vignettes_pointent_vers_le_fonds_courant(
    base_demo: Path,
) -> None:
    """Les vignettes échantillonnées portent `fonds_cote=fonds.cote`
    — important pour que le lien `/item/<cote>?fonds=<X>` du template
    soit correct (cote item ambiguë sinon)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        synthese = composer_synthese_fonds(s, fonds)
        for v in synthese.vignettes:
            assert v.fonds_cote == "HK"
    engine.dispose()


def test_synthese_fonds_trous_a_corriger_remontent(base_demo: Path) -> None:
    """Force un item à corriger → trou présent dans la synthèse.
    Garde-fou : le trou est bien comptabilisé au niveau fonds (pas
    juste collection)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        item = s.scalar(select(Item).where(Item.fonds_id == fonds.id).limit(1))
        item.etat_catalogage = EtatCatalogage.A_CORRIGER.value
        s.commit()

        synthese = composer_synthese_fonds(s, fonds)
        trou_corr = next(
            (t for t in synthese.trous if t.code == "a_corriger"), None
        )
        assert trou_corr is not None
        assert trou_corr.nb >= 1
        # Pas de deep-link (la page Fonds n'a pas de filtre par état)
        assert trou_corr.filtre_url is None
    engine.dispose()


def test_synthese_fonds_vide_si_aucun_item(base_demo: Path) -> None:
    """Un fonds frais sans aucun item → synthèse vide."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds_vide = Fonds(
            cote="EMPTY-TEST",
            titre="Fonds sans items",
            cree_par="test",
            modifie_par="test",
        )
        s.add(fonds_vide)
        s.commit()
        synthese = composer_synthese_fonds(s, fonds_vide)
        assert synthese.nb_items_total == 0
        assert synthese.vide
    engine.dispose()


def test_synthese_fonds_rendu_html_page(base_demo: Path) -> None:
    """Garde-fou intégration : la page fonds rend la synthèse."""
    from fastapi.testclient import TestClient
    from archives_tool.api.main import app

    client = TestClient(app)
    resp = client.get("/fonds/HK")
    assert resp.status_code == 200
    # Marqueur du composant synthèse_fonds (texte du summary commun
    # à synthese_collection et synthese_fonds — heureusement le test
    # ci-dessous différencie via le contenu).
    assert "Synthèse" in resp.text
    assert "<details open" in resp.text


def test_synthese_fonds_section_collections_affichee_meme_sans_libre(
    base_demo: Path,
) -> None:
    """Garde-fou : pour un fonds sans libre (HK demo), la section
    « Collections » doit s'afficher avec uniquement la miroir + le
    libellé « uniquement la miroir »."""
    from fastapi.testclient import TestClient
    from archives_tool.api.main import app

    client = TestClient(app)
    resp = client.get("/fonds/HK")
    assert resp.status_code == 200
    # La section Collections est présente même sans libre
    assert "Collections ·" in resp.text
    # Le libellé explicatif est rendu
    assert "uniquement la miroir" in resp.text


def test_synthese_fonds_section_collections_avec_libres(
    base_demo: Path,
) -> None:
    """Garde-fou intégration : pour le fonds FA (4 libres demo), la
    section Collections apparait avec ses libres listées."""
    from fastapi.testclient import TestClient
    from archives_tool.api.main import app

    client = TestClient(app)
    resp = client.get("/fonds/FA")
    assert resp.status_code == 200
    assert "Collections ·" in resp.text
    # Au moins une libre demo doit apparaitre dans le tableau
    # (le seeder crée FA-CORRESP / FA-DOCU / FA-PHOTOS / FA-OEUVRES)
    libres_attendues = ["FA-CORRESP", "FA-DOCU", "FA-PHOTOS", "FA-OEUVRES"]
    assert any(lib in resp.text for lib in libres_attendues)


# ---------------------------------------------------------------------------
# Garde-fous : robustesse + budget SQL
# ---------------------------------------------------------------------------


def test_cartographie_ignore_les_transversales(base_demo: Path) -> None:
    """Décision sémantique : la cartographie liste les collections
    **du fonds** (miroir + libres rattachées), pas les transversales
    qui empruntent des items mais n'appartiennent à aucun fonds.

    Une transversale qui contient des items de HK ne doit donc PAS
    apparaître dans la cartographie de HK.
    """
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        # Crée une transversale qui contient des items de HK
        trans = Collection(
            cote="TRANSVERSAL-TEST",
            titre="Transversale qui pioche dans HK",
            type_collection=TypeCollection.LIBRE.value,
            fonds_id=None,  # transversale = pas rattachée
            cree_par="test",
            modifie_par="test",
        )
        s.add(trans)
        s.commit()
        items_hk = list(s.scalars(
            select(Item).where(Item.fonds_id == fonds.id).limit(3)
        ).all())
        for item in items_hk:
            s.add(ItemCollection(item_id=item.id, collection_id=trans.id))
        s.commit()

        carto = _composer_cartographie_collections(s, fonds)
        cotes = {e.cote for e in carto.entrees}
        # La transversale n'apparaît pas dans les entrées
        assert "TRANSVERSAL-TEST" not in cotes
        # Seule la miroir HK reste (pas de libre rattachée HK)
        assert cotes == {"HK"}
    engine.dispose()


def test_synthese_fonds_budget_sql_borne(base_demo: Path) -> None:
    """Garde-fou perf : la synthèse fonds doit rester dans un budget
    SQL borné indépendant du volume. Doc dit ~5-7 queries. On
    plafonne à 10 (marge de sécurité face aux évolutions futures
    qui pourraient ajouter une ou deux queries).
    """
    from sqlalchemy import event
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)

    queries: list[str] = []

    def _capter(conn, cursor, statement, params, context, executemany):
        # Skip pragma SQLite (configurations, pas du code applicatif).
        if not statement.lower().startswith("pragma"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", _capter)

    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        queries.clear()  # Reset après le lookup fonds
        _ = composer_synthese_fonds(s, fonds)

    event.remove(engine, "before_cursor_execute", _capter)
    engine.dispose()

    assert len(queries) <= 10, (
        f"composer_synthese_fonds a émis {len(queries)} queries "
        f"(plafond 10). Liste : {[q[:60] for q in queries]}"
    )
