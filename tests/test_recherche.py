"""Tests du service de recherche FTS5 (V0.9.x Lot A)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.recherche import (
    Scope,
    _preparer_requete_fts,
    rechercher,
)


@pytest.fixture
def session_avec_corpus(session: Session) -> Session:
    """Base avec 2 fonds et quelques items pour les tests recherche."""
    # Fonds 1 : revue spécialisée
    creer_fonds(
        session,
        FormulaireFonds(
            cote="HK",
            titre="Hara-Kiri",
            description="Revue satirique française mensuelle des années 60",
        ),
    )
    # Fonds 2 : périodique étranger
    creer_fonds(
        session,
        FormulaireFonds(
            cote="PF",
            titre="Por Favor",
            description="Revue satirique espagnole, années 70",
        ),
    )
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    fonds_hk = lire_fonds_par_cote(session, "HK")
    fonds_pf = lire_fonds_par_cote(session, "PF")

    for cote, titre, desc in [
        ("HK-001", "Numéro 1 — Lancement", "Cavanna éditorial sur la satire"),
        ("HK-002", "Numéro 2 — Caricatures", "Wolinski et Reiser dessinent"),
        ("HK-003", "Numéro 3 — Politique", "Mai 1968 vu par la rédaction"),
    ]:
        creer_item(
            session,
            FormulaireItem(
                cote=cote, titre=titre, description=desc, fonds_id=fonds_hk.id,
            ),
        )
    for cote, titre, desc in [
        ("PF-001", "Por Favor número uno", "Lancement du journal espagnol"),
        ("PF-002", "Por Favor número dos", "Caricatures politiques"),
    ]:
        creer_item(
            session,
            FormulaireItem(
                cote=cote, titre=titre, description=desc, fonds_id=fonds_pf.id,
            ),
        )
    return session


# ---------------------------------------------------------------------------
# _preparer_requete_fts — sanitization de la query utilisateur
# ---------------------------------------------------------------------------


def test_requete_fts_vide_retourne_none() -> None:
    assert _preparer_requete_fts("") is None
    assert _preparer_requete_fts("   ") is None
    assert _preparer_requete_fts('"":') is None  # uniquement réservés


def test_requete_fts_tokens_simples() -> None:
    """Mots séparés par espace → AND FTS5 (espace = AND par défaut)."""
    assert _preparer_requete_fts("cavanna") == '"cavanna"*'
    assert _preparer_requete_fts("mai 68") == '"mai"* "68"*'


def test_requete_fts_echappe_caracteres_reserves() -> None:
    """Les caractères réservés FTS5 (`":-()^*+`) sont retirés."""
    # Le `-` est échappé en espace puis split en deux tokens
    assert _preparer_requete_fts("hara-kiri") == '"hara"* "kiri"*'
    # Caractère réservé seul → split + filtre
    out = _preparer_requete_fts("rev:revue")
    assert '"rev"*' in out and '"revue"*' in out


def test_requete_fts_prefix_match() -> None:
    """Chaque token reçoit `*` pour matcher les préfixes — utile pour
    rechercher partiellement une cote (PF-0 → PF-001, PF-002…)."""
    assert _preparer_requete_fts("pf") == '"pf"*'


# ---------------------------------------------------------------------------
# rechercher — service principal
# ---------------------------------------------------------------------------


def test_recherche_simple_titre(session_avec_corpus: Session) -> None:
    """Recherche dans titre d'item."""
    resultats = rechercher(session_avec_corpus, "caricatures")
    cotes = {r.cote for r in resultats if r.type_entite == "item"}
    assert "HK-002" in cotes  # « Numéro 2 — Caricatures »
    assert "PF-002" in cotes  # « Caricatures politiques » dans description


def test_recherche_dans_description(session_avec_corpus: Session) -> None:
    """Recherche sur description d'item — pas que le titre."""
    resultats = rechercher(session_avec_corpus, "Wolinski")
    cotes = {r.cote for r in resultats if r.type_entite == "item"}
    assert "HK-002" in cotes


def test_recherche_dans_cote(session_avec_corpus: Session) -> None:
    """Cote est indexée — recherche par cote partielle fonctionne
    grâce au préfixe `*`."""
    resultats = rechercher(session_avec_corpus, "HK-00")
    cotes = {r.cote for r in resultats if r.type_entite == "item"}
    assert cotes == {"HK-001", "HK-002", "HK-003"}


def test_recherche_diacritique_insensible(session_avec_corpus: Session) -> None:
    """Tokeniseur `remove_diacritics 2` : `numero` matche `Numéro`,
    indispensable en archives multilingues."""
    resultats = rechercher(session_avec_corpus, "numero")
    cotes = {r.cote for r in resultats if r.type_entite == "item"}
    assert "HK-001" in cotes  # « Numéro 1 »
    assert "PF-001" in cotes  # « número uno »


def test_recherche_renvoie_aussi_fonds_et_collections(
    session_avec_corpus: Session,
) -> None:
    """Par défaut, les 3 types d'entités sont cherchés. La requête
    `satirique` matche HK + PF (description) + leurs miroirs (si
    elles ont la même description)."""
    resultats = rechercher(session_avec_corpus, "satirique")
    types_trouves = {r.type_entite for r in resultats}
    assert "fonds" in types_trouves  # HK + PF descriptions matchent


def test_recherche_types_filtres(session_avec_corpus: Session) -> None:
    """`types={"item"}` ne renvoie que les items, même si la requête
    matcherait fonds/collection aussi."""
    resultats = rechercher(session_avec_corpus, "satirique", types={"item"})
    assert all(r.type_entite == "item" for r in resultats)


def test_recherche_scope_fonds(session_avec_corpus: Session) -> None:
    """`scope.fonds_id` limite aux items/collections du fonds donné."""
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    fonds_hk = lire_fonds_par_cote(session_avec_corpus, "HK")
    resultats = rechercher(
        session_avec_corpus, "caricatures",
        scope=Scope(fonds_id=fonds_hk.id),
    )
    # Items HK uniquement (PF-002 « Caricatures politiques » exclu)
    items = [r for r in resultats if r.type_entite == "item"]
    cotes = {r.cote for r in items}
    assert "HK-002" in cotes
    assert "PF-002" not in cotes


def test_recherche_snippet_avec_mark(session_avec_corpus: Session) -> None:
    """Le snippet entoure les mots matchés de balises `<mark>`."""
    resultats = rechercher(session_avec_corpus, "Wolinski")
    items = [r for r in resultats if r.type_entite == "item"]
    assert items
    assert any("<mark>" in r.snippet for r in items)


def test_recherche_synchro_apres_creation_item(session_avec_corpus: Session) -> None:
    """Trigger `item_fts_insert` synchronise FTS au creer_item :
    un nouvel item est immédiatement trouvable."""
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    fonds_hk = lire_fonds_par_cote(session_avec_corpus, "HK")
    creer_item(
        session_avec_corpus,
        FormulaireItem(
            cote="HK-NEW", titre="Tout nouveau article",
            description="Sur le sujet Esperanto",
            fonds_id=fonds_hk.id,
        ),
    )
    resultats = rechercher(session_avec_corpus, "Esperanto")
    cotes = {r.cote for r in resultats if r.type_entite == "item"}
    assert "HK-NEW" in cotes


def test_recherche_synchro_apres_modification(
    session_avec_corpus: Session,
) -> None:
    """Trigger `item_fts_update` réindexe lors d'une modification.
    Avant modif : pas de match « Esperanto ». Après modif : match."""
    from archives_tool.api.services.items import (
        FormulaireItem, lire_item_par_cote, modifier_item,
    )
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    fonds_hk = lire_fonds_par_cote(session_avec_corpus, "HK")
    item = lire_item_par_cote(session_avec_corpus, "HK-001", fonds_id=fonds_hk.id)
    assert "Esperanto" not in (item.description or "")

    nouveau = FormulaireItem(
        cote=item.cote, titre=item.titre, fonds_id=fonds_hk.id,
        description="Esperanto et autres langues construites",
        version=item.version,
    )
    modifier_item(session_avec_corpus, item.id, nouveau)

    resultats = rechercher(session_avec_corpus, "Esperanto")
    cotes = {r.cote for r in resultats if r.type_entite == "item"}
    assert "HK-001" in cotes


def test_recherche_synchro_apres_suppression(
    session_avec_corpus: Session,
) -> None:
    """Trigger `item_fts_delete` retire de l'index. Un item supprimé
    n'apparaît plus dans la recherche."""
    from archives_tool.api.services.items import (
        lire_item_par_cote, supprimer_item,
    )
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    fonds_hk = lire_fonds_par_cote(session_avec_corpus, "HK")
    item = lire_item_par_cote(session_avec_corpus, "HK-002", fonds_id=fonds_hk.id)
    supprimer_item(session_avec_corpus, item.id)

    resultats = rechercher(session_avec_corpus, "caricatures")
    cotes = {r.cote for r in resultats if r.type_entite == "item"}
    assert "HK-002" not in cotes


def test_recherche_dans_metadonnees(session_avec_corpus: Session) -> None:
    """Le champ `metadonnees` (JSON) est flattené et indexé. Recherche
    sur une valeur libre y est trouvable."""
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    fonds_hk = lire_fonds_par_cote(session_avec_corpus, "HK")
    creer_item(
        session_avec_corpus,
        FormulaireItem(
            cote="HK-META", titre="Item avec meta",
            description="rien dans description",
            fonds_id=fonds_hk.id,
            metadonnees={"auteur": "Topor", "rubrique": "humour noir"},
        ),
    )
    resultats = rechercher(session_avec_corpus, "Topor")
    cotes = {r.cote for r in resultats if r.type_entite == "item"}
    assert "HK-META" in cotes


def test_recherche_score_pertinence(session_avec_corpus: Session) -> None:
    """Le ranking bm25 met le match le plus pertinent en premier.
    Le titre étant un champ court avec match dense, son score est
    typiquement meilleur que la description (champ long avec dilution)."""
    resultats = rechercher(session_avec_corpus, "Cavanna")
    items = [r for r in resultats if r.type_entite == "item"]
    assert items
    # Score ASC (meilleur en premier — convention bm25 SQLite)
    scores = [r.score for r in items]
    assert scores == sorted(scores)


def test_recherche_requete_vide_retourne_vide(
    session_avec_corpus: Session,
) -> None:
    """Recherche vide → resultats vides (pas de match « tout »)."""
    res = rechercher(session_avec_corpus, "")
    assert len(res) == 0
    assert res.total == 0
    assert rechercher(session_avec_corpus, "   ").total == 0


def test_recherche_total_par_type_vs_page(
    session_avec_corpus: Session,
) -> None:
    """`ResultatsRecherche` distingue total EXACT (compte FTS5
    sans LIMIT) du nombre sur la PAGE COURANTE (paginé). Permet
    d'afficher « 173 résultats trouvés (51–100 sur cette page) »."""
    # Cherche `numero` qui matche les 5 items du corpus de test
    res = rechercher(session_avec_corpus, "numero", par_page=2, page=1)
    # Total exact 5 items (HK-001/002/003 + PF-001/002 ont tous
    # "Numéro" dans le titre)
    assert res.total_par_type["item"] >= 5
    # Mais on n'affiche que `par_page=2` résultats sur la page
    assert len(res.resultats) == 2
    # nb_pages calculé sur le total global
    assert res.nb_pages >= 3  # 5 items / 2 par page = 3 pages

    # Page 2 : 2 autres résultats
    res2 = rechercher(session_avec_corpus, "numero", par_page=2, page=2)
    assert len(res2.resultats) == 2
    # Les résultats de page 2 sont différents de page 1
    assert {r.id for r in res.resultats} != {r.id for r in res2.resultats}


def test_recherche_page_hors_borne_retourne_vide(
    session_avec_corpus: Session,
) -> None:
    """Une page au-delà du nb_pages retourne une liste vide sans
    crash (offset > taille de la liste = slice vide en Python)."""
    res = rechercher(session_avec_corpus, "numero", par_page=10, page=999)
    assert res.resultats == []
    # Le total exact reste correct
    assert res.total >= 5
    assert res.page == 999


def test_recherche_pagination_meta(
    session_avec_corpus: Session,
) -> None:
    """Propriétés méta de pagination : nb_pages, premier_index,
    dernier_index sont cohérentes avec page et par_page."""
    res = rechercher(session_avec_corpus, "numero", par_page=3, page=2)
    # par_page=3, page=2 → résultats 4, 5, 6 (index 1-based)
    assert res.premier_index == 4
    assert res.dernier_index == 4 + len(res.resultats) - 1
    # Si total=7 items + 2 fonds + 0 col, nb_pages = ceil(9/3) = 3
    total = res.total
    expected_pages = (total + 2) // 3  # math.ceil
    assert res.nb_pages == max(1, expected_pages)


# ---------------------------------------------------------------------------
# Filtres avancés (état, langue, type COAR, période) + q_dans_resultats
# ---------------------------------------------------------------------------


@pytest.fixture
def session_avec_corpus_filtrable(session: Session) -> Session:
    """Corpus avec items aux champs état/langue/type_coar/annee variés
    pour tester les filtres avancés et le calcul des options dynamiques."""
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    creer_fonds(session, FormulaireFonds(cote="REVS", titre="Revues"))
    fonds = lire_fonds_par_cote(session, "REVS")

    # Items aux états/langues/types/années distincts pour vérifier
    # que chaque filtre discrimine correctement.
    specs = [
        # (cote, etat, langue, type_coar, annee)
        ("R-001", "brouillon", "fra", "journal", 1965),
        ("R-002", "verifie", "fra", "journal", 1966),
        ("R-003", "valide", "spa", "book", 1972),
        ("R-004", "a_verifier", "eng", "journal", 1980),
    ]
    for cote, etat, langue, type_coar, annee in specs:
        creer_item(
            session,
            FormulaireItem(
                cote=cote,
                titre=f"Titre {cote}",
                description=f"Description pour matcher : caricature {cote}",
                fonds_id=fonds.id,
                etat_catalogage=etat,
                langue=langue,
                type_coar=type_coar,
                annee=annee,
            ),
        )
    return session


def test_calculer_options_filtres_global(
    session_avec_corpus_filtrable: Session,
) -> None:
    """`calculer_options_filtres_recherche` agrège les valeurs
    distinctes (état, langue, type COAR, bornes années) sur toute
    la base quand scope est global."""
    from archives_tool.api.services.recherche import (
        calculer_options_filtres_recherche,
    )

    options = calculer_options_filtres_recherche(session_avec_corpus_filtrable)
    assert "brouillon" in options.etats
    assert "verifie" in options.etats
    assert "valide" in options.etats
    assert "fra" in options.langues
    assert "spa" in options.langues
    assert "eng" in options.langues
    assert "journal" in options.types_coar
    assert "book" in options.types_coar
    assert options.annee_min_base == 1965
    assert options.annee_max_base == 1980


def test_calculer_options_filtres_scope_fonds(
    session_avec_corpus_filtrable: Session,
) -> None:
    """Avec scope fonds_id, les options sont restreintes au périmètre.
    Un fonds en français seulement n'affiche pas espagnol/anglais."""
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.api.services.items import FormulaireItem, creer_item
    from archives_tool.api.services.recherche import (
        Scope, calculer_options_filtres_recherche,
    )

    creer_fonds(session_avec_corpus_filtrable, FormulaireFonds(cote="MONO", titre="Mono"))
    fonds_mono = lire_fonds_par_cote(session_avec_corpus_filtrable, "MONO")
    creer_item(
        session_avec_corpus_filtrable,
        FormulaireItem(
            cote="M-001", titre="seul", fonds_id=fonds_mono.id,
            langue="ita", annee=2000,
        ),
    )

    options_mono = calculer_options_filtres_recherche(
        session_avec_corpus_filtrable, scope=Scope(fonds_id=fonds_mono.id),
    )
    assert options_mono.langues == ("ita",)
    assert "fra" not in options_mono.langues  # pas dans ce fonds
    assert options_mono.annee_min_base == 2000
    assert options_mono.annee_max_base == 2000


def test_parser_filtres_silencieux_hors_options(
    session_avec_corpus_filtrable: Session,
) -> None:
    """Les valeurs hors whitelist sont silencieusement ignorées.
    Jamais de 400 sur paramètre invalide (cohérent avec
    `parser_filtres_collection`)."""
    from archives_tool.api.services.recherche import (
        OptionsFiltresRecherche, parser_filtres_recherche,
    )

    options = OptionsFiltresRecherche(
        etats=("brouillon", "valide"),
        langues=("fra",),
        types_coar=("journal",),
        annee_min_base=1900, annee_max_base=2000,
    )
    filtres = parser_filtres_recherche(
        etat=["brouillon", "INEXISTANT"],  # INEXISTANT ignoré
        langue=["fra", "klingon"],  # klingon ignoré
        type_coar=["journal", "fake"],  # fake ignoré
        annee_min=1800,  # hors bornes → ignoré
        annee_max=1950,
        q_dans_resultats="  raffin  ",  # stripé
        options=options,
    )
    assert filtres.etats == ("brouillon",)
    assert filtres.langues == ("fra",)
    assert filtres.types_coar == ("journal",)
    assert filtres.annee_min is None  # rejeté (< 1900)
    assert filtres.annee_max == 1950
    assert filtres.q_dans_resultats == "raffin"


def test_parser_filtres_swap_intervalle_inverse(
    session_avec_corpus_filtrable: Session,
) -> None:
    """Si annee_min > annee_max, on swap pour donner un résultat
    exploitable plutôt qu'une plage vide muette."""
    from archives_tool.api.services.recherche import (
        OptionsFiltresRecherche, parser_filtres_recherche,
    )

    options = OptionsFiltresRecherche(annee_min_base=1900, annee_max_base=2000)
    filtres = parser_filtres_recherche(
        etat=None, langue=None, type_coar=None,
        annee_min=1980, annee_max=1920,
        q_dans_resultats=None, options=options,
    )
    assert filtres.annee_min == 1920
    assert filtres.annee_max == 1980


def test_rechercher_filtre_etat(session_avec_corpus_filtrable: Session) -> None:
    """Avec un filtre `etats=('brouillon',)`, seuls les items en
    brouillon remontent — même si la query matche d'autres états."""
    from archives_tool.api.services.recherche import FiltresRecherche

    res = rechercher(
        session_avec_corpus_filtrable, "caricature",
        filtres=FiltresRecherche(etats=("brouillon",)),
    )
    items = [r for r in res if r.type_entite == "item"]
    cotes = {r.cote for r in items}
    assert cotes == {"R-001"}  # brouillon uniquement


def test_rechercher_filtre_langue(
    session_avec_corpus_filtrable: Session,
) -> None:
    """Filtre langue multi-valeur."""
    from archives_tool.api.services.recherche import FiltresRecherche

    res = rechercher(
        session_avec_corpus_filtrable, "caricature",
        filtres=FiltresRecherche(langues=("fra", "spa")),
    )
    items = [r for r in res if r.type_entite == "item"]
    cotes = {r.cote for r in items}
    assert "R-001" in cotes  # fra
    assert "R-002" in cotes  # fra
    assert "R-003" in cotes  # spa
    assert "R-004" not in cotes  # eng exclu


def test_rechercher_filtre_annee_plage(
    session_avec_corpus_filtrable: Session,
) -> None:
    """Filtre par plage d'années (min ET max)."""
    from archives_tool.api.services.recherche import FiltresRecherche

    res = rechercher(
        session_avec_corpus_filtrable, "caricature",
        filtres=FiltresRecherche(annee_min=1970, annee_max=1985),
    )
    items = [r for r in res if r.type_entite == "item"]
    cotes = {r.cote for r in items}
    # R-001 (1965) et R-002 (1966) exclus, R-003 (1972) et R-004 (1980) inclus
    assert cotes == {"R-003", "R-004"}


def test_rechercher_q_dans_resultats_raffine(
    session_avec_corpus_filtrable: Session,
) -> None:
    """`q_dans_resultats` raffine la query principale via AND FTS5
    implicite : `q=caricature` + `q2=R-003` ne retourne que R-003."""
    from archives_tool.api.services.recherche import FiltresRecherche

    # Sans raffinement : tous les 4 items matchent (caricature)
    sans = rechercher(session_avec_corpus_filtrable, "caricature")
    assert len([r for r in sans if r.type_entite == "item"]) == 4

    # Avec raffinement sur "R-003"
    avec = rechercher(
        session_avec_corpus_filtrable, "caricature",
        filtres=FiltresRecherche(q_dans_resultats="R-003"),
    )
    items = [r for r in avec if r.type_entite == "item"]
    cotes = {r.cote for r in items}
    assert cotes == {"R-003"}


def test_rechercher_filtres_items_n_affecte_pas_fonds(
    session_avec_corpus_filtrable: Session,
) -> None:
    """Choix d'UX V0.9.x : les filtres item-specific (état, langue,
    type, période) ne s'appliquent qu'aux items. Les fonds et
    collections continuent d'apparaître normalement."""
    from archives_tool.api.services.recherche import FiltresRecherche

    # Filtre très restrictif sur les items (état seulement)
    res = rechercher(
        session_avec_corpus_filtrable, "Revues",
        filtres=FiltresRecherche(etats=("brouillon",)),
    )
    # Le fonds REVS matche son titre "Revues" et doit toujours apparaître
    # même si aucun item n'est en brouillon ne matche cette query.
    fonds_trouves = [r for r in res if r.type_entite == "fonds"]
    cotes_fonds = {r.cote for r in fonds_trouves}
    assert "REVS" in cotes_fonds


def test_rechercher_tout_afficher_via_types(
    session_avec_corpus_filtrable: Session,
) -> None:
    """Mode « tout afficher » : `q=""` + `types={"item"}` retourne
    tous les items du périmètre via SELECT direct (sans FTS). Permet
    aux cartes du dashboard (« Items 173 ») de mener à une vraie
    liste plutôt qu'à la page « Tapez une requête »."""
    res = rechercher(session_avec_corpus_filtrable, "", types={"item"})
    # 4 items créés dans la fixture (R-001 à R-004)
    assert res.total_par_type.get("item") == 4
    assert len(res.resultats) == 4
    # Tri par cote ASC (canonique mode tout afficher)
    cotes = [r.cote for r in res.resultats if r.type_entite == "item"]
    assert cotes == sorted(cotes)
    # Pas de snippet (rien à surligner sans query)
    assert all(r.snippet == "" for r in res.resultats)


def test_rechercher_tout_afficher_via_filtre(
    session_avec_corpus_filtrable: Session,
) -> None:
    """`q=""` + filtre `etats=('brouillon',)` retourne tous les items
    en brouillon sans devoir taper de query — mode équivalent à
    « liste filtrée »."""
    from archives_tool.api.services.recherche import FiltresRecherche

    res = rechercher(
        session_avec_corpus_filtrable, "",
        filtres=FiltresRecherche(etats=("brouillon",)),
    )
    items = [r for r in res if r.type_entite == "item"]
    cotes = {r.cote for r in items}
    # R-001 est en brouillon dans la fixture
    assert cotes == {"R-001"}


def test_rechercher_tout_afficher_via_scope(
    session_avec_corpus: Session,
) -> None:
    """`q=""` + `scope.fonds_id` posé → liste tous les items/collections
    du fonds. Permet d'utiliser la recherche comme un parcours du fonds
    quand on sait juste le périmètre."""
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.api.services.recherche import Scope

    fonds_hk = lire_fonds_par_cote(session_avec_corpus, "HK")
    res = rechercher(session_avec_corpus, "", scope=Scope(fonds_id=fonds_hk.id))
    # Items HK uniquement (HK-001/002/003), pas les items PF
    items = [r for r in res if r.type_entite == "item"]
    cotes_items = {r.cote for r in items}
    assert cotes_items == {"HK-001", "HK-002", "HK-003"}


def test_rechercher_aucune_intention_retourne_vide(
    session_avec_corpus: Session,
) -> None:
    """`q=""` + rien d'autre → objet vide qui déclenche l'invitation
    « Tapez une requête » côté template. Le mode « tout afficher »
    ne se déclenche QUE si une intention est posée (scope, types,
    filtre) — sinon on aurait des centaines de résultats sans
    intention claire."""
    res = rechercher(session_avec_corpus, "")
    assert res.total == 0
    assert res.resultats == []


def test_filtres_recherche_actifs_et_affecte_items(
    session_avec_corpus_filtrable: Session,
) -> None:
    """`FiltresRecherche.actifs` et `.affecte_items_seulement`
    distinguent l'état des filtres pour piloter l'affichage du
    template (pastilles, repli de la section)."""
    from archives_tool.api.services.recherche import FiltresRecherche

    vide = FiltresRecherche()
    assert not vide.actifs
    assert not vide.affecte_items_seulement

    avec_q2 = FiltresRecherche(q_dans_resultats="raffin")
    assert avec_q2.actifs
    assert not avec_q2.affecte_items_seulement  # q2 affecte les 3 types

    avec_etat = FiltresRecherche(etats=("brouillon",))
    assert avec_etat.actifs
    assert avec_etat.affecte_items_seulement


def test_reindexer_fts_idempotent_et_compte_correct(
    session_avec_corpus: Session,
) -> None:
    """Passe de revue Lot A : `reindexer_fts` vide puis repeuple les
    3 tables FTS. Utile pour réindexer une base existante (cas
    upgrade ColleC sur une base pré-FTS sans relancer la migration).
    Idempotent — peut être appelé plusieurs fois sans dupliquer."""
    from archives_tool.db import reindexer_fts

    engine = session_avec_corpus.get_bind()
    counts1 = reindexer_fts(engine)
    counts2 = reindexer_fts(engine)
    # Même résultat à chaque appel (pas de duplication)
    assert counts1 == counts2
    # 5 items (HK-001..003 + PF-001..002), 2 fonds, 2 collections (miroirs auto)
    assert counts1["item"] == 5
    assert counts1["fonds"] == 2
    assert counts1["collection"] == 2
    # Et la recherche fonctionne toujours après reindex
    resultats = rechercher(session_avec_corpus, "caricatures")
    assert any(r.cote == "HK-002" for r in resultats)
