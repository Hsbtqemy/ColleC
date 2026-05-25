"""Tests de la synthèse de collection (V0.9.6) — section dense
au-dessus du tableau d'items qui répond à *quoi / quand / quelle
gueule / quoi finir / où j'en suis*."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from archives_tool.api.services.dashboard import (
    BarreTemporelle,
    DistributionTemporelle,
    _agreger_item_metadonnees_quali,
    _calculer_distribution_temporelle,
    _ids_echantillonnes,
    composer_synthese_collection,
)
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Item,
    TypeCollection,
)


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


# ---------------------------------------------------------------------------
# Helpers purs : distribution temporelle, échantillonnage, agrégat meta
# ---------------------------------------------------------------------------


def test_distribution_temporelle_vide_si_aucune_annee() -> None:
    dist = _calculer_distribution_temporelle([])
    assert dist.vide
    assert dist.annee_min is None
    assert dist.annee_max is None
    assert dist.pas is None


def test_distribution_temporelle_par_an_si_span_court() -> None:
    """Plage ≤ 30 ans → pas annuel, barres sans trou (count=0 sur les
    années vides pour visualiser les manques)."""
    dist = _calculer_distribution_temporelle([1973, 1974, 1974, 1976])
    assert dist.pas == "annee"
    assert dist.annee_min == 1973
    assert dist.annee_max == 1976
    assert len(dist.barres) == 4  # 1973, 1974, 1975, 1976
    counts = {b.annee_debut: b.count for b in dist.barres}
    assert counts == {1973: 1, 1974: 2, 1975: 0, 1976: 1}


def test_distribution_temporelle_par_decennie_si_span_long() -> None:
    """Plage > 30 ans → pas décennal aligné sur multiples de 10."""
    dist = _calculer_distribution_temporelle([1923, 1955, 1990, 2024])
    assert dist.pas == "decennie"
    assert dist.annee_min == 1923
    assert dist.annee_max == 2024
    # Décennies alignées : 1920, 1930, ..., 2020 → 11 barres
    decennies = [b.annee_debut for b in dist.barres]
    assert decennies[0] == 1920
    assert decennies[-1] == 2020
    assert len(dist.barres) == 11
    # Vérifie une borne supérieure : la décennie 2020 doit englober 2024
    bar_2020 = next(b for b in dist.barres if b.annee_debut == 2020)
    assert bar_2020.annee_fin == 2029
    assert bar_2020.count == 1


def test_distribution_count_max_pour_normalisation() -> None:
    """`count_max` est utilisé par le template pour normaliser la
    hauteur des barres en %. Doit retourner 0 si vide."""
    dist_vide = DistributionTemporelle(
        annee_min=None, annee_max=None, pas=None, barres=()
    )
    assert dist_vide.count_max == 0
    dist_plein = DistributionTemporelle(
        annee_min=2000,
        annee_max=2001,
        pas="annee",
        barres=(
            BarreTemporelle(annee_debut=2000, annee_fin=2000, count=3),
            BarreTemporelle(annee_debut=2001, annee_fin=2001, count=7),
        ),
    )
    assert dist_plein.count_max == 7


def test_ids_echantillonnes_pleins_si_petit() -> None:
    """≤ N items → on retourne tout, dans l'ordre source."""
    assert _ids_echantillonnes([], 12) == []
    assert _ids_echantillonnes([5, 3, 8], 12) == [5, 3, 8]


def test_ids_echantillonnes_uniformes_si_grand() -> None:
    """N items > cap → échantillonnage uniforme par stride flottant.

    Sur 100 éléments échantillonnés à 10 : on prend ~ tous les 10
    (indices 0, 10, 20, ...). On vérifie la couverture et l'absence
    de doublons.
    """
    ids = list(range(100))
    selection = _ids_echantillonnes(ids, 10)
    assert len(selection) == 10
    assert len(set(selection)) == 10  # pas de doublon
    assert selection[0] == 0  # commence au début
    assert selection[-1] >= 80  # couvre la fin


def test_agreger_meta_skip_structurelles_et_vides() -> None:
    """`hierarchie` / `typologie` sont dict structurés (décompositions
    de cote) — pas d'agrégation. Les valeurs `None` et `""` sont
    ignorées."""
    metas = [
        {"auteur": "Topor", "hierarchie": {"a": "b"}, "vide": None},
        {"auteur": "Reiser", "typologie": {"x": "y"}, "vide": ""},
        {"auteur": "Topor", "sujet": "satire"},
    ]
    par_cle = _agreger_item_metadonnees_quali(metas)
    assert set(par_cle.keys()) == {"auteur", "sujet"}
    assert par_cle["auteur"]["Topor"] == 2
    assert par_cle["auteur"]["Reiser"] == 1
    assert par_cle["sujet"]["satire"] == 1


def test_agreger_meta_depile_listes_multivalues() -> None:
    """Une valeur list (vocabulaire multi) → chaque valeur compte
    indépendamment."""
    metas = [
        {"tags": ["bd", "satire"]},
        {"tags": ["bd"]},
        {"tags": "monovaleur"},  # str scalaire pris tel quel
    ]
    par_cle = _agreger_item_metadonnees_quali(metas)
    assert par_cle["tags"]["bd"] == 2
    assert par_cle["tags"]["satire"] == 1
    assert par_cle["tags"]["monovaleur"] == 1


def test_agreger_meta_robuste_a_meta_non_dict() -> None:
    """Si `Item.metadonnees` est `None` ou autre que dict, on skip
    silencieusement (pas de crash sur données legacy)."""
    par_cle = _agreger_item_metadonnees_quali([None, "garbage", 42, {}])
    assert par_cle == {}


# ---------------------------------------------------------------------------
# composer_synthese_collection — bout en bout sur demo
# ---------------------------------------------------------------------------


def test_synthese_demo_structure_globale(base_demo: Path) -> None:
    """Sur la base demo, la collection miroir HK contient ≥ 1 item.
    La synthèse retourne une structure non vide avec timeline, items
    récents et compteurs."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        assert col is not None
        synthese = composer_synthese_collection(s, col, fonds_query="HK")

        assert synthese.nb_items_total > 0
        # Items récents = au plus 5
        assert len(synthese.items_recents) <= 5
        # Tous portent un modifie_le défini (filtré dans le service)
        assert all(r.modifie_le is not None for r in synthese.items_recents)
        # Échantillon vignettes ≤ 12
        assert len(synthese.vignettes) <= 12
    engine.dispose()


def test_synthese_agregats_langue_et_type_avec_libelles_humains(
    base_demo: Path,
) -> None:
    """Les agrégats `langue` / `type_coar` doivent apparaître avec
    leurs **libellés humains** (Français, Périodique, …) — sinon
    l'utilisateur voit `fra` / `http://purl.org/coar/...` brut."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        # On garantit que des items ont une langue et un type COAR
        # connu pour activer l'agrégat (la demo le fait, mais on
        # rebascule pour être sûr).
        items = list(s.scalars(select(Item).limit(5)).all())
        for i, it in enumerate(items):
            it.langue = "fra"
            it.type_coar = "http://purl.org/coar/resource_type/c_3e5a"  # Périodique
        s.commit()

        synthese = composer_synthese_collection(s, col, fonds_query="HK")
        cles = {a.cle for a in synthese.agregats}
        # On veut au moins langue + type_coar dans les agrégats.
        assert "langue" in cles
        assert "type_coar" in cles
        ag_langue = next(a for a in synthese.agregats if a.cle == "langue")
        # Le libellé humain (Français) doit avoir remplacé le code "fra".
        valeurs = {tv.valeur for tv in ag_langue.top}
        assert "fra" not in valeurs  # code brut absent
        assert any("français" in v.lower() for v in valeurs)
    engine.dispose()


def test_synthese_top_n_capacite(base_demo: Path) -> None:
    """Les agrégats sont cappés à _TOP_AGREGAT (5) par défaut.
    `nb_distinct` reflète le vrai total — l'écart est exposé pour
    que l'UI puisse dire « top 5 sur 12 »."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        # Injecte 8 dessinateurs distincts sur 10 items pour
        # dépasser le cap top-5.
        items = list(s.scalars(select(Item).limit(10)).all())
        for i, it in enumerate(items):
            it.metadonnees = {"dessinateur": f"Dessinateur{i % 8}"}
            flag_modified(it, "metadonnees")
        s.commit()

        synthese = composer_synthese_collection(s, col, fonds_query="HK")
        ag = next(
            (a for a in synthese.agregats if a.cle == "dessinateur"), None
        )
        assert ag is not None
        assert len(ag.top) <= 5  # cap
        assert ag.nb_distinct == 8  # vrai total préservé
    engine.dispose()


def test_synthese_trous_a_corriger_avec_filtre_url(base_demo: Path) -> None:
    """Le trou « à corriger » porte un `filtre_url` qui pointe vers
    le tableau filtré (`?etat=a_corriger`) — c'est le seul deep-link
    actif aujourd'hui."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        # Force un item à corriger pour activer le trou.
        item = s.scalar(select(Item).limit(1))
        assert item is not None
        item.etat_catalogage = EtatCatalogage.A_CORRIGER.value
        s.commit()

        synthese = composer_synthese_collection(s, col, fonds_query="HK")
        trou_corr = next(
            (t for t in synthese.trous if t.code == "a_corriger"), None
        )
        assert trou_corr is not None
        assert trou_corr.filtre_url is not None
        assert "etat=a_corriger" in trou_corr.filtre_url
        assert "fonds=HK" in trou_corr.filtre_url
    engine.dispose()


def test_synthese_trous_sans_filtre_url_pour_codes_non_supportes(
    base_demo: Path,
) -> None:
    """Les trous `sans_titre` / `sans_annee` / `sans_fichier` n'ont
    pas (encore) de filtre dédié — `filtre_url` doit être None pour
    ne pas créer un lien mort."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        # Force un item sans titre + sans année pour déclencher 2
        # trous.
        item = s.scalar(select(Item).limit(1))
        assert item is not None
        item.titre = ""
        item.annee = None
        s.commit()

        synthese = composer_synthese_collection(s, col, fonds_query="HK")
        for t in synthese.trous:
            if t.code in ("sans_titre", "sans_annee", "sans_fichier"):
                assert t.filtre_url is None
    engine.dispose()


def test_synthese_collection_vide_renvoie_objet_vide(
    base_demo: Path,
) -> None:
    """Sur une collection sans aucun item (libre transversale fraîche),
    la synthèse est `.vide` — le template peut s'auto-masquer."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col_vide = Collection(
            cote="SYNTHESE-VIDE-TEST",
            titre="Collection de test (vide)",
            type_collection=TypeCollection.LIBRE.value,
            fonds_id=None,
            cree_par="test",
            modifie_par="test",
        )
        s.add(col_vide)
        s.commit()

        synthese = composer_synthese_collection(s, col_vide, fonds_query=None)
        assert synthese.vide
        assert synthese.nb_items_total == 0
        assert synthese.agregats == ()
        assert synthese.vignettes == ()
        assert synthese.trous == ()
        assert synthese.items_recents == ()
    engine.dispose()


def test_synthese_rendu_html_collection_page(base_demo: Path) -> None:
    """Garde-fou intégration : la page collection rend bien la
    synthèse, avec sa balise `<details>` et au moins une section
    qualitative."""
    from fastapi.testclient import TestClient
    from archives_tool.api.main import app

    client = TestClient(app)
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    # Marqueur du composant synthèse (texte du summary)
    assert "Synthèse" in resp.text
    # Le composant a bien créé un <details> ouvert
    assert "<details open" in resp.text
    # Sections présentes (au moins l'une des trois colonnes)
    assert (
        "Échantillon" in resp.text
        or "Activité récente" in resp.text
        or "Période" in resp.text
    )


def test_synthese_pas_dans_swap_htmx(base_demo: Path) -> None:
    """Sur un swap HTMX (tri ou pagination), seul le partial tableau
    est rendu — la synthèse n'a aucune raison d'être recalculée ni
    renvoyée. Garde-fou perf + UX (sinon la synthèse réapparaîtrait
    au moindre tri de colonne).
    """
    from fastapi.testclient import TestClient
    from archives_tool.api.main import app

    client = TestClient(app)
    resp = client.get(
        "/collection/HK?fonds=HK", headers={"HX-Request": "true"}
    )
    assert resp.status_code == 200
    assert "Synthèse" not in resp.text
    assert "<details open" not in resp.text
