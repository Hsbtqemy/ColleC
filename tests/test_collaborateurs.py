"""Tests du service `collaborateurs` et des routes HTMX (V0.8.0).

Couvre :
- Service : listage, groupement par rôle, validation, suppression,
  cascade depuis Collection.
- Routes : ajouter / modifier / supprimer + form fragments.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.api.services.collaborateurs import (
    CollaborateurIntrouvable,
    CollaborateurInvalide,
    FormulaireCollaborateur,
    ajouter_collaborateur,
    lister_collaborateurs,
    lister_collaborateurs_par_role,
    modifier_collaborateur,
    supprimer_collaborateur,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import (
    CollaborateurCollection,
    Collection,
    RoleCollaborateur,
)


@pytest.fixture
def col(session: Session) -> Collection:
    c = Collection(cote="HK", titre="Hara-Kiri", phase="catalogage")
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_ajout_nom_vide_rejete(session: Session, col: Collection) -> None:
    formulaire = FormulaireCollaborateur(nom="", roles=["numerisation"])
    with pytest.raises(CollaborateurInvalide) as exc:
        ajouter_collaborateur(session, col.id, formulaire)
    assert "nom" in exc.value.erreurs


def test_ajout_roles_vides_rejetes(session: Session, col: Collection) -> None:
    formulaire = FormulaireCollaborateur(nom="Marie", roles=[])
    with pytest.raises(CollaborateurInvalide) as exc:
        ajouter_collaborateur(session, col.id, formulaire)
    assert "roles" in exc.value.erreurs


def test_ajout_role_inconnu_rejete(session: Session, col: Collection) -> None:
    formulaire = FormulaireCollaborateur(nom="Marie", roles=["bidon"])
    with pytest.raises(CollaborateurInvalide) as exc:
        ajouter_collaborateur(session, col.id, formulaire)
    assert "roles" in exc.value.erreurs


# L'existence de la collection est garantie par les routes
# (`charger_collection_ou_404`) ; le service ne re-vérifie pas.
# Voir `test_post_collection_inexistante_404`.


# ---------------------------------------------------------------------------
# Ajout / lecture
# ---------------------------------------------------------------------------


def test_ajout_minimal(session: Session, col: Collection) -> None:
    formulaire = FormulaireCollaborateur(nom="Marie", roles=["numerisation"])
    res = ajouter_collaborateur(session, col.id, formulaire)
    assert res.id is not None
    assert res.nom == "Marie"
    assert res.roles == [RoleCollaborateur.NUMERISATION]
    assert res.periode is None
    assert res.notes is None


def test_ajout_complet_strip_chaines(session: Session, col: Collection) -> None:
    formulaire = FormulaireCollaborateur(
        nom="  Hugo  ",
        roles=["transcription", "indexation"],
        periode="  2022-2023  ",
        notes="  ok  ",
    )
    res = ajouter_collaborateur(session, col.id, formulaire)
    assert res.nom == "Hugo"
    assert res.periode == "2022-2023"
    assert res.notes == "ok"
    assert RoleCollaborateur.TRANSCRIPTION in res.roles
    assert RoleCollaborateur.INDEXATION in res.roles


def test_lister_vide(session: Session, col: Collection) -> None:
    assert lister_collaborateurs(session, col.id) == []


def test_lister_ordre_stable_par_creation(session: Session, col: Collection) -> None:
    ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="A", roles=["numerisation"]),
    )
    ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="B", roles=["catalogage"]),
    )
    res = lister_collaborateurs(session, col.id)
    assert [c.nom for c in res] == ["A", "B"]


# ---------------------------------------------------------------------------
# Groupement par rôle
# ---------------------------------------------------------------------------


def test_groupement_par_role_ordre_enum(session: Session, col: Collection) -> None:
    ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="X", roles=["catalogage"]),
    )
    ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="Y", roles=["numerisation"]),
    )
    groupes = lister_collaborateurs_par_role(session, col.id)
    cles = list(groupes.keys())
    # NUMERISATION avant CATALOGAGE (ordre de l'enum).
    assert cles == [RoleCollaborateur.NUMERISATION, RoleCollaborateur.CATALOGAGE]


def test_personne_multi_roles_dans_plusieurs_groupes(
    session: Session, col: Collection
) -> None:
    ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(
            nom="Marie",
            roles=["numerisation", "indexation"],
        ),
    )
    groupes = lister_collaborateurs_par_role(session, col.id)
    assert "Marie" in [c.nom for c in groupes[RoleCollaborateur.NUMERISATION]]
    assert "Marie" in [c.nom for c in groupes[RoleCollaborateur.INDEXATION]]


def test_groupement_filtre_roles_vides(session: Session, col: Collection) -> None:
    """Un rôle sans collaborateur n'apparaît pas dans le dict."""
    ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="X", roles=["numerisation"]),
    )
    groupes = lister_collaborateurs_par_role(session, col.id)
    assert RoleCollaborateur.CATALOGAGE not in groupes


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------


def test_modifier_remplace_les_champs(session: Session, col: Collection) -> None:
    res = ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="Ancien", roles=["numerisation"]),
    )
    nouv = modifier_collaborateur(
        session,
        res.id,
        FormulaireCollaborateur(
            nom="Nouveau",
            roles=["catalogage", "indexation"],
            periode="2024",
            notes="commentaire",
        ),
    )
    assert nouv.nom == "Nouveau"
    assert RoleCollaborateur.NUMERISATION not in nouv.roles
    assert nouv.periode == "2024"
    assert nouv.notes == "commentaire"


def test_modifier_inexistant(session: Session) -> None:
    with pytest.raises(CollaborateurIntrouvable):
        modifier_collaborateur(
            session,
            99999,
            FormulaireCollaborateur(nom="X", roles=["numerisation"]),
        )


def test_modifier_validation(session: Session, col: Collection) -> None:
    res = ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="Marie", roles=["numerisation"]),
    )
    with pytest.raises(CollaborateurInvalide):
        modifier_collaborateur(
            session,
            res.id,
            FormulaireCollaborateur(nom="", roles=["numerisation"]),
        )


# ---------------------------------------------------------------------------
# Suppression + cascade
# ---------------------------------------------------------------------------


def test_supprimer(session: Session, col: Collection) -> None:
    res = ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="X", roles=["numerisation"]),
    )
    supprimer_collaborateur(session, res.id)
    assert lister_collaborateurs(session, col.id) == []


def test_supprimer_inexistant(session: Session) -> None:
    with pytest.raises(CollaborateurIntrouvable):
        supprimer_collaborateur(session, 99999)


def test_cascade_suppression_collection(session: Session, col: Collection) -> None:
    """Supprimer la collection supprime ses collaborateurs."""
    ajouter_collaborateur(
        session,
        col.id,
        FormulaireCollaborateur(nom="X", roles=["numerisation"]),
    )
    session.delete(col)
    session.commit()
    nb_restants = session.query(CollaborateurCollection).count()
    assert nb_restants == 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


@pytest.fixture
def session_demo(base_demo: Path):
    """Session sur la même base que celle utilisée par TestClient.

    Permet aux tests de routes de relire des objets (ex. récupérer
    l'id du collaborateur juste créé) sans reconstruire un engine.
    """
    factory = creer_session_factory(creer_engine(base_demo))
    with factory() as s:
        yield s


def _premier_id_collab(session) -> int:
    return session.query(CollaborateurCollection).first().id


def test_get_section_vide(base_demo: Path) -> None:
    """GET section : 200, message « Aucun collaborateur »."""
    client = TestClient(app)
    resp = client.get("/collection/HK/collaborateurs")
    assert resp.status_code == 200
    assert "Aucun collaborateur" in resp.text


def test_get_formulaire_nouveau(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK/collaborateurs/nouveau")
    assert resp.status_code == 200
    assert 'name="nom"' in resp.text
    assert 'name="roles"' in resp.text
    assert "Numérisation" in resp.text


def test_post_ajout_valide_renvoie_section(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/collection/HK/collaborateurs",
        data={
            "nom": "Marie Dupont",
            "roles": ["numerisation", "indexation"],
            "periode": "2022-2023",
            "notes": "",
        },
    )
    assert resp.status_code == 200
    assert "Marie Dupont" in resp.text
    assert "Numérisation" in resp.text
    assert "Indexation" in resp.text


def test_post_ajout_nom_vide_renvoie_formulaire(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/collection/HK/collaborateurs",
        data={"nom": "", "roles": ["numerisation"]},
    )
    assert resp.status_code == 400
    assert "nom est obligatoire" in resp.text


def test_post_ajout_sans_role_renvoie_formulaire(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post("/collection/HK/collaborateurs", data={"nom": "Marie"})
    assert resp.status_code == 400
    assert "rôle" in resp.text.lower()


def test_post_collection_inexistante_404(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/collection/N_EXISTE_PAS/collaborateurs",
        data={"nom": "X", "roles": ["numerisation"]},
    )
    assert resp.status_code == 404


def test_modifier_pre_remplissage(session_demo) -> None:
    client = TestClient(app)
    add = client.post(
        "/collection/HK/collaborateurs",
        data={"nom": "Hugo", "roles": ["transcription"], "periode": "2024"},
    )
    assert add.status_code == 200
    cid = _premier_id_collab(session_demo)

    resp = client.get(f"/collection/HK/collaborateurs/{cid}/modifier")
    assert resp.status_code == 200
    assert 'value="Hugo"' in resp.text
    assert "checked" in resp.text  # rôle transcription pré-coché
    assert 'value="2024"' in resp.text


def test_post_modifier(session_demo) -> None:
    client = TestClient(app)
    client.post(
        "/collection/HK/collaborateurs",
        data={"nom": "Ancien", "roles": ["numerisation"]},
    )
    cid = _premier_id_collab(session_demo)

    resp = client.post(
        f"/collection/HK/collaborateurs/{cid}",
        data={
            "nom": "Nouveau",
            "roles": ["catalogage"],
            "periode": "",
            "notes": "",
        },
    )
    assert resp.status_code == 200
    assert "Nouveau" in resp.text
    assert "Ancien" not in resp.text


def test_post_supprimer(session_demo) -> None:
    client = TestClient(app)
    client.post(
        "/collection/HK/collaborateurs",
        data={"nom": "X", "roles": ["numerisation"]},
    )
    cid = _premier_id_collab(session_demo)

    resp = client.post(f"/collection/HK/collaborateurs/{cid}/supprimer")
    assert resp.status_code == 200
    assert "Aucun collaborateur" in resp.text


def test_modifier_collaborateur_autre_collection_404(session_demo) -> None:
    """Un collaborateur de FA-AA ne peut pas être muté via la cote HK."""
    client = TestClient(app)
    client.post(
        "/collection/FA-AA/collaborateurs",
        data={"nom": "X", "roles": ["numerisation"]},
    )
    cid = _premier_id_collab(session_demo)

    resp = client.post(
        f"/collection/HK/collaborateurs/{cid}",
        data={"nom": "Hijack", "roles": ["catalogage"]},
    )
    assert resp.status_code == 404


def test_page_modifier_inclut_section(base_demo: Path) -> None:
    """La page /collection/HK/modifier inclut la section collaborateurs."""
    client = TestClient(app)
    resp = client.get("/collection/HK/modifier")
    assert resp.status_code == 200
    assert 'id="section-collaborateurs"' in resp.text
    assert "Ajouter un collaborateur" in resp.text
