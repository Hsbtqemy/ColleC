"""Tests de l'édition inline d'un collaborateur de fonds depuis l'UI
(Lot B du chantier d'audit front/back).

Pattern identique au `?modifier=<vid>` de la page vocabulaire détail :
- GET `/fonds/<cote>?modifier_collab=<id>` ouvre la ligne en form pré-rempli.
- POST `/fonds/<cote>/collaborateurs/<id>` (route existante depuis V0.8)
  sauvegarde ou ré-affiche avec les erreurs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services.collaborateurs_fonds import (
    FormulaireCollaborateurFonds,
    ajouter_collaborateur_fonds,
)
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import CollaborateurFonds


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _amorcer_collab(db_path: Path) -> tuple[str, int]:
    """Ajoute un collaborateur sur HK et retourne (cote_fonds, collab_id)."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        hk = lire_fonds_par_cote(s, "HK")
        c = ajouter_collaborateur_fonds(
            s, hk.id,
            FormulaireCollaborateurFonds(
                nom="Camille Dupont",
                roles=["numerisation"],
                periode="2024",
                notes="Notes initiales.",
            ),
        )
        s.commit()
        cid = c.id
    engine.dispose()
    return "HK", cid


def test_page_fonds_avec_modifier_collab_ouvre_form_inline(
    base_demo: Path,
) -> None:
    """`?modifier_collab=<id>` active le mode édition sur la ligne ciblée."""
    cote, cid = _amorcer_collab(base_demo)
    client = TestClient(app)
    r = client.get(f"/fonds/{cote}?modifier_collab={cid}")
    assert r.status_code == 200
    # Form POST sur la route existante
    assert f'action="/fonds/{cote}/collaborateurs/{cid}"' in r.text
    # Input nom pré-rempli
    assert 'value="Camille Dupont"' in r.text
    # Bouton Enregistrer + lien Annuler
    assert "Enregistrer" in r.text
    assert f'href="/fonds/{cote}"' in r.text


def test_page_fonds_sans_modifier_collab_montre_lien_modifier(
    base_demo: Path,
) -> None:
    """Sans `?modifier_collab=`, chaque ligne expose un lien Modifier
    vers `?modifier_collab=<id>`. Pas de form inline ouvert."""
    cote, cid = _amorcer_collab(base_demo)
    client = TestClient(app)
    r = client.get(f"/fonds/{cote}")
    assert r.status_code == 200
    # Lien Modifier présent pour le collab
    assert f"/fonds/{cote}?modifier_collab={cid}" in r.text
    # Pas de form POST de modification dans la liste
    assert f'action="/fonds/{cote}/collaborateurs/{cid}"' not in r.text


def test_post_modifier_collab_persiste_changements(base_demo: Path) -> None:
    """POST avec form valide → 303 vers /fonds/<cote>, données changées."""
    cote, cid = _amorcer_collab(base_demo)
    client = TestClient(app, follow_redirects=False)
    r = client.post(
        f"/fonds/{cote}/collaborateurs/{cid}",
        data={
            "nom": "Camille Dupont-Martin",
            "roles": ["numerisation", "catalogage"],
            "periode": "2024-2025",
            "notes": "Notes modifiées.",
        },
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/fonds/{cote}"

    # Vérifie en base
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = s.get(CollaborateurFonds, cid)
        assert c is not None
        assert c.nom == "Camille Dupont-Martin"
        assert sorted(c.roles) == ["catalogage", "numerisation"]
        assert c.periode == "2024-2025"
        assert c.notes == "Notes modifiées."
    engine.dispose()


def test_post_modifier_collab_nom_vide_reaffiche_erreurs(
    base_demo: Path,
) -> None:
    """POST avec nom vide → 400 + page ré-affichée avec form inline +
    erreur visible."""
    cote, cid = _amorcer_collab(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/fonds/{cote}/collaborateurs/{cid}",
        data={
            "nom": "",
            "roles": ["numerisation"],
            "periode": "",
            "notes": "",
        },
    )
    assert r.status_code == 400
    # Form ré-ouvert sur la même ligne
    assert f'action="/fonds/{cote}/collaborateurs/{cid}"' in r.text
    # Message d'erreur exact rendu par valider_formulaire()
    assert "Le nom est obligatoire." in r.text


def test_post_erreur_rerender_garde_synthese_et_consultation(
    base_demo: Path,
) -> None:
    """Le re-render d'erreur passe `synthese` + `consultation_url` au
    template — sinon le bandeau synthèse et le bouton « Mode
    consultation » disparaissent au moment d'une erreur de validation,
    UX incohérente avec le GET nominal. Pré-existant rattrapé Lot B."""
    cote, cid = _amorcer_collab(base_demo)
    client = TestClient(app)

    # GET nominal : vérifie qu'il y a bien un bloc synthèse + lien consultation
    r_get = client.get(f"/fonds/{cote}")
    assert r_get.status_code == 200
    a_synthese = "Synthèse" in r_get.text or "synthese-fonds" in r_get.text
    a_consultation = "/lire/" in r_get.text

    # POST avec erreur → page rerender avec 400 ; doit conserver
    # les mêmes blocs (synthèse + consultation) que le GET.
    r_post = client.post(
        f"/fonds/{cote}/collaborateurs/{cid}",
        data={"nom": "", "roles": ["numerisation"], "periode": "", "notes": ""},
    )
    assert r_post.status_code == 400
    if a_synthese:
        assert "Synthèse" in r_post.text or "synthese-fonds" in r_post.text
    if a_consultation:
        assert "/lire/" in r_post.text


def test_modifier_collab_id_d_un_autre_fonds_ignore(base_demo: Path) -> None:
    """`?modifier_collab=<id>` où id pointe sur un collab d'un autre fonds :
    la page rend normalement, sans bascule edit (anti-confused-deputy
    léger). Sym. au pattern de la page vocab détail."""
    cote_hk, cid_hk = _amorcer_collab(base_demo)
    # Ajoute aussi un collab sur le fonds PF (existe dans la demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        # On vérifie qu'un autre fonds existe avant de tester
        autre_fonds = s.scalars(
            select(__import__("archives_tool.models", fromlist=["Fonds"]).Fonds)
            .where(__import__("archives_tool.models", fromlist=["Fonds"]).Fonds.cote != "HK")
        ).first()
        assert autre_fonds is not None, "Demo doit avoir un autre fonds que HK"
        cote_autre = autre_fonds.cote
    engine.dispose()

    client = TestClient(app)
    # cid_hk appartient à HK ; on l'utilise via l'URL d'un autre fonds
    r = client.get(f"/fonds/{cote_autre}?modifier_collab={cid_hk}")
    assert r.status_code == 200
    # Pas de form de modification rendu
    assert f'action="/fonds/{cote_autre}/collaborateurs/{cid_hk}"' not in r.text


def test_modifier_collab_lien_absent_en_lecture_seule(
    base_demo: Path, monkeypatch, tmp_path: Path
) -> None:
    """Lecture seule : pas de lien Modifier sur la liste."""
    cote, cid = _amorcer_collab(base_demo)
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  d: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    client = TestClient(app)
    r = client.get(f"/fonds/{cote}?modifier_collab={cid}")
    assert r.status_code == 200
    # Pas de lien Modifier
    assert f"?modifier_collab={cid}" not in r.text
    # Pas de form action POST de modif
    assert f'action="/fonds/{cote}/collaborateurs/{cid}"' not in r.text
