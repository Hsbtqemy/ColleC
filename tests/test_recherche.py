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
    """Recherche vide → liste vide (pas de match « tout »)."""
    assert rechercher(session_avec_corpus, "") == []
    assert rechercher(session_avec_corpus, "   ") == []


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
