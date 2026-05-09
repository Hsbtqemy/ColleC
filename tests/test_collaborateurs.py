"""Tests du service `collaborateurs` (V0.8.0).

Couvre listage, groupement par rôle, validation d'ajout/modification,
suppression, cascade depuis Collection.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

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
from archives_tool.models import (
    CollaborateurCollection,
    Collection,
    RoleCollaborateur,
)


@pytest.fixture
def col(session: Session) -> Collection:
    c = Collection(cote_collection="HK", titre="Hara-Kiri", phase="catalogage")
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


def test_ajout_collection_inexistante(session: Session) -> None:
    formulaire = FormulaireCollaborateur(nom="Marie", roles=["numerisation"])
    with pytest.raises(LookupError):
        ajouter_collaborateur(session, 99999, formulaire)


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
