"""Tests de robustesse des dialogs `onsubmit='return confirm(...)'`
embarquant du texte libre utilisateur.

Trouve en audit transversal : `c.nom | e` (collab) et
`vocabulaire.libelle` (vocab) étaient embed dans une chaine JS via
attribut HTML double-quote. Si le texte contient `'`, le JS string
casse — dialog cassée ou submit qui n'invoque pas confirm() du tout
(donc suppression silencieuse au clic !).

Fix V0.9.x : attribut `'` + filtre `| tojson` qui escape via `\\u0027`
(safe pour HTML attr + JS string). Ce fichier verrouille le pattern.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archives_tool.api.main import app
from archives_tool.api.services.collaborateurs_fonds import (
    FormulaireCollaborateurFonds,
    ajouter_collaborateur_fonds,
)
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.api.services.vocabulaires_db import (
    FormulaireVocabulaire,
    creer_vocabulaire,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_supprimer_collab_avec_apostrophe_dans_nom(base_demo: Path) -> None:
    """Un collaborateur dont le nom contient une apostrophe (« L'auteur »)
    doit rendre une dialog robuste — pas un JS string cassé."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        hk = lire_fonds_par_cote(s, "HK")
        ajouter_collaborateur_fonds(
            s,
            hk.id,
            FormulaireCollaborateurFonds(
                nom="L'auteur principal",  # apostrophe dans nom
                roles=["catalogage"],
                periode="",
                notes="",
            ),
        )
        s.commit()
    engine.dispose()

    client = TestClient(app)
    r = client.get("/fonds/HK")
    assert r.status_code == 200
    # Le JS escape Unicode (') doit apparaître, PAS l'apostrophe
    # brute dans l'attribut JS string (qui le casserait).
    assert "\\u0027auteur" in r.text or "L\\u0027auteur" in r.text
    # Et le rendu de l'attribut utilise des `'` (single-quote) en
    # delimiteur, pas `"`.
    assert "onsubmit='return confirm(" in r.text


def test_supprimer_vocabulaire_avec_apostrophe_dans_libelle(
    base_demo: Path,
) -> None:
    """Un vocabulaire dont le libellé contient une apostrophe
    (« Dessinateurs d'une époque ») doit rendre une dialog robuste."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(
            s,
            FormulaireVocabulaire(
                code="apostrophe_test",
                libelle="Dessinateurs d'une époque",  # apostrophe dans libelle
            ),
        )
        s.commit()
        vid = v.id
    engine.dispose()

    client = TestClient(app)
    r = client.get(f"/vocabulaires/{vid}")
    assert r.status_code == 200
    # Vérifie que le JS escape Unicode est présent pour l'apostrophe
    # dans le contenu de la dialog
    assert "d\\u0027une" in r.text
    # Attribut delimite par `'` (pas par `"`)
    # → chercher le pattern dans la zone suppression
    assert "onsubmit='return confirm(" in r.text


def test_retirer_item_dialog_reste_stable(base_demo: Path) -> None:
    """Garde-fou : le bouton Retirer item utilise it.cote (safe via
    PATTERN_COTE) — la dialog n'a pas besoin de tojson. Ce test
    vérifie qu'on n'a pas accidentellement cassé le rendu existant."""
    client = TestClient(app)
    r = client.get("/collection/HK?fonds=HK")
    assert r.status_code == 200
    # Pattern original conservé : double-quote attr + confirm() avec
    # l'item cote interpolée directement
    assert 'onsubmit="return confirm(' in r.text


def test_supprimer_champ_dialog_reste_stable(base_demo: Path) -> None:
    """Garde-fou : la dialog Supprimer champ utilise c.cle (safe via
    PATTERN_CLE strict). Pas besoin de tojson."""
    from archives_tool.api.services.champs_personnalises import (
        FormulaireChamp,
        creer_champ,
    )
    from archives_tool.models import Collection, TypeCollection
    from sqlalchemy import select

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        miroir = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        creer_champ(
            s,
            miroir.id,
            FormulaireChamp(cle="test_garde_fou", libelle="Test"),
        )
        s.commit()
    engine.dispose()

    client = TestClient(app)
    r = client.get("/collection/HK/champs?fonds=HK")
    assert r.status_code == 200
    # Pattern double-quote attr + interpolation directe de la cle
    assert 'onsubmit="return confirm(' in r.text
    assert "test_garde_fou" in r.text
