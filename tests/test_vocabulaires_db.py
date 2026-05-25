"""Tests du CRUD vocabulaires + valeurs contrôlées (V0.9.4 lot 3a)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archives_tool.api.main import app
from archives_tool.api.services.champs_personnalises import (
    FormulaireChamp,
    creer_champ,
)
from archives_tool.api.services.vocabulaires_db import (
    FormulaireValeur,
    FormulaireVocabulaire,
    ValeurInvalide,
    VocabulaireInvalide,
    VocabulaireReference,
    ajouter_valeur,
    creer_vocabulaire,
    deprecier_valeur,
    lister_vocabulaires,
    modifier_valeur,
    modifier_vocabulaire,
    options_depuis_vocabulaire,
    reactiver_valeur,
    supprimer_valeur,
    supprimer_vocabulaire,
)
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


# ---------------------------------------------------------------------------
# Vocabulaire CRUD
# ---------------------------------------------------------------------------


def test_creer_vocabulaire_persiste(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        vocab = creer_vocabulaire(
            s, FormulaireVocabulaire(code="tag_personnage", libelle="Personnages")
        )
        assert vocab.id is not None
        assert vocab.code == "tag_personnage"
        assert vocab.libelle == "Personnages"
        assert vocab.valeurs == []
    engine.dispose()


def test_creer_vocabulaire_refuse_code_invalide(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        with pytest.raises(VocabulaireInvalide) as exc:
            creer_vocabulaire(s, FormulaireVocabulaire(code="tag personnage", libelle="X"))
        assert "code" in exc.value.erreurs
    engine.dispose()


def test_creer_vocabulaire_refuse_doublon(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        with pytest.raises(VocabulaireInvalide) as exc:
            creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="B"))
        assert "déjà" in exc.value.erreurs["code"]
    engine.dispose()


def test_creer_vocabulaire_refuse_libelle_vide(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        with pytest.raises(VocabulaireInvalide) as exc:
            creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle=""))
        assert "libelle" in exc.value.erreurs
    engine.dispose()


def test_modifier_vocabulaire(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        modifier_vocabulaire(
            s, v.id,
            FormulaireVocabulaire(code="tag", libelle="B", description="desc"),
        )
        s.refresh(v)
        assert v.libelle == "B"
        assert v.description == "desc"
    engine.dispose()


def test_supprimer_vocabulaire_libre(base_demo: Path) -> None:
    """Suppression OK quand aucun ChampPersonnalise ne réfère."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        vid = v.id
        supprimer_vocabulaire(s, vid)
        assert lister_vocabulaires(s) == []
    engine.dispose()


def test_supprimer_vocabulaire_refuse_si_reference(base_demo: Path) -> None:
    """Si un ChampPersonnalise pointe sur ce vocab, la suppression
    est refusée. Le message liste les champs en cause."""
    from archives_tool.models import Collection, Fonds, TypeCollection
    from sqlalchemy import select

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(
            s, FormulaireVocabulaire(code="tag", libelle="A")
        )
        # Crée un ChampPersonnalise référant le vocab.
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        c = creer_champ(s, miroir.id, FormulaireChamp(cle="auteur", libelle="A"))
        # Wire valeurs_controlees_id manuellement (lot 3b n'est pas
        # encore là — le formulaire ChampPersonnalise ne l'expose pas
        # encore).
        c.valeurs_controlees_id = v.id
        s.commit()

        with pytest.raises(VocabulaireReference) as exc:
            supprimer_vocabulaire(s, v.id)
        assert "auteur" in exc.value.champs_referents
    engine.dispose()


# ---------------------------------------------------------------------------
# Valeurs CRUD
# ---------------------------------------------------------------------------


def test_ajouter_valeur_attribue_ordre_par_defaut(base_demo: Path) -> None:
    """Si ordre=0 dans le formulaire, on attribue max+1 — la nouvelle
    valeur arrive en fin de liste."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        v1 = ajouter_valeur(s, v.id, FormulaireValeur(code="a", libelle="A"))
        v2 = ajouter_valeur(s, v.id, FormulaireValeur(code="b", libelle="B"))
        v3 = ajouter_valeur(s, v.id, FormulaireValeur(code="c", libelle="C"))
        assert v1.ordre == 1
        assert v2.ordre == 2
        assert v3.ordre == 3
    engine.dispose()


def test_ajouter_valeur_refuse_doublon_dans_meme_vocab(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        ajouter_valeur(s, v.id, FormulaireValeur(code="a", libelle="A"))
        with pytest.raises(ValeurInvalide) as exc:
            ajouter_valeur(s, v.id, FormulaireValeur(code="a", libelle="B"))
        assert "déjà" in exc.value.erreurs["code"]
    engine.dispose()


def test_ajouter_valeur_meme_code_ok_sur_vocabs_distincts(base_demo: Path) -> None:
    """Deux vocabulaires peuvent avoir une valeur avec le même code
    — l'unicité est par (vocabulaire_id, code)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v1 = creer_vocabulaire(s, FormulaireVocabulaire(code="vocab1", libelle="V1"))
        v2 = creer_vocabulaire(s, FormulaireVocabulaire(code="vocab2", libelle="V2"))
        ajouter_valeur(s, v1.id, FormulaireValeur(code="a", libelle="A1"))
        ajouter_valeur(s, v2.id, FormulaireValeur(code="a", libelle="A2"))
        # Pas d'exception.
    engine.dispose()


def test_modifier_valeur_change_libelle(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        val = ajouter_valeur(s, v.id, FormulaireValeur(code="fra", libelle="Français"))
        modifier_valeur(
            s, val.id,
            FormulaireValeur(code="fra", libelle="French", uri="http://lex"),
        )
        s.refresh(val)
        assert val.libelle == "French"
        assert val.uri == "http://lex"
    engine.dispose()


def test_deprecier_reactiver_valeur_idempotent(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        val = ajouter_valeur(s, v.id, FormulaireValeur(code="a", libelle="A"))
        deprecier_valeur(s, val.id)
        deprecier_valeur(s, val.id)  # idempotent
        s.refresh(val)
        assert val.actif is False
        reactiver_valeur(s, val.id)
        reactiver_valeur(s, val.id)
        s.refresh(val)
        assert val.actif is True
    engine.dispose()


def test_supprimer_valeur_hard_delete(base_demo: Path) -> None:
    from archives_tool.models import ValeurControlee
    from sqlalchemy import select
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        val = ajouter_valeur(s, v.id, FormulaireValeur(code="a", libelle="A"))
        val_id = val.id
        supprimer_valeur(s, val_id)
        assert s.scalar(select(ValeurControlee).where(ValeurControlee.id == val_id)) is None
    engine.dispose()


# ---------------------------------------------------------------------------
# Helper options_depuis_vocabulaire
# ---------------------------------------------------------------------------


def test_options_depuis_vocabulaire_trie_par_ordre(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        ajouter_valeur(s, v.id, FormulaireValeur(code="z", libelle="Z"))  # ordre=1
        ajouter_valeur(s, v.id, FormulaireValeur(code="a", libelle="A"))  # ordre=2
        s.refresh(v)
        options = options_depuis_vocabulaire(v)
        # Triés par (ordre, code) — z en premier (ordre=1), a après (ordre=2)
        assert options == (("z", "Z"), ("a", "A"))
    engine.dispose()


def test_options_depuis_vocabulaire_exclut_deprecies_par_defaut(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        ajouter_valeur(s, v.id, FormulaireValeur(code="actif", libelle="A"))
        v2 = ajouter_valeur(s, v.id, FormulaireValeur(code="depr", libelle="D"))
        deprecier_valeur(s, v2.id)
        s.refresh(v)
        # Par défaut : exclut déprécié.
        actifs = options_depuis_vocabulaire(v)
        assert ("actif", "A") in actifs
        assert ("depr", "D") not in actifs
        # Avec flag : inclut.
        tout = options_depuis_vocabulaire(v, inclure_deprecies=True)
        assert ("depr", "D") in tout
    engine.dispose()


# ---------------------------------------------------------------------------
# Routes web
# ---------------------------------------------------------------------------


def test_route_vocabulaires_liste(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/vocabulaires")
    assert resp.status_code == 200
    assert "Vocabulaires personnalisés" in resp.text


def test_route_creer_vocabulaire_redirige(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/vocabulaires/creer",
        data={
            "code": "tag_personnage",
            "libelle": "Personnages",
            "description": "",
            "description_interne": "",
            "uri_base": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # Redirect vers /vocabulaires/{id}
    assert resp.headers["location"].startswith("/vocabulaires/")


def test_route_creer_vocabulaire_400_si_invalide(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/vocabulaires/creer",
        data={
            "code": "tag personnage",  # espace invalide
            "libelle": "X",
            "description": "",
            "description_interne": "",
            "uri_base": "",
        },
    )
    assert resp.status_code == 400


def test_route_ajouter_valeur(base_demo: Path) -> None:
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        vid = v.id
    engine.dispose()

    client = TestClient(app)
    resp = client.post(
        f"/vocabulaires/{vid}/valeurs/ajouter",
        data={
            "code": "fra",
            "libelle": "Français",
            "uri": "",
            "description_interne": "",
            "ordre": "0",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert f"/vocabulaires/{vid}" == resp.headers["location"]


def test_route_supprimer_valeur_appartenance_anti_confused_deputy(
    base_demo: Path,
) -> None:
    """Si l'id de la valeur n'appartient pas au vocab du chemin, 404."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v1 = creer_vocabulaire(s, FormulaireVocabulaire(code="v1", libelle="V1"))
        v2 = creer_vocabulaire(s, FormulaireVocabulaire(code="v2", libelle="V2"))
        val_v1 = ajouter_valeur(s, v1.id, FormulaireValeur(code="a", libelle="A"))
        v2_id = v2.id
        val_id = val_v1.id
    engine.dispose()

    client = TestClient(app)
    # Tente de supprimer la valeur de v1 via l'URL de v2.
    resp = client.post(
        f"/vocabulaires/{v2_id}/valeurs/{val_id}/supprimer",
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_route_supprimer_vocabulaire_refuse_si_reference(base_demo: Path) -> None:
    from archives_tool.models import Collection, Fonds, TypeCollection
    from sqlalchemy import select

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tag", libelle="A"))
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        c = creer_champ(s, miroir.id, FormulaireChamp(cle="auteur", libelle="A"))
        c.valeurs_controlees_id = v.id
        s.commit()
        vid = v.id
    engine.dispose()

    client = TestClient(app)
    resp = client.post(
        f"/vocabulaires/{vid}/supprimer",
        follow_redirects=False,
    )
    assert resp.status_code == 409
    assert "référencé" in resp.text
