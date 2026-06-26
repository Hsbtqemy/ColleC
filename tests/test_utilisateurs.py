"""Tests de la couche identité Phase 1 — modèle + service + CLI Utilisateur."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from archives_tool.api.services.utilisateurs import (
    NomDejaUtilise,
    UtilisateurIntrouvable,
    creer_utilisateur,
    desactiver_utilisateur,
    lire_utilisateur_par_nom,
    lister_utilisateurs,
    modifier_utilisateur,
)
from archives_tool.cli import app
from archives_tool.db import creer_engine
from archives_tool.models import Base

runner = CliRunner()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_creer_defaut_actif_editeur(session: Session) -> None:
    u = creer_utilisateur(session, "Marie")
    assert u.id is not None
    assert u.nom == "Marie"
    assert u.actif is True
    assert u.peut_editer is True


def test_creer_lecteur(session: Session) -> None:
    u = creer_utilisateur(session, "Hugo", peut_editer=False)
    assert u.peut_editer is False
    assert u.actif is True


def test_creer_normalise_strip_et_nfc(session: Session) -> None:
    # Espaces externes retirés + forme décomposée → NFC composée.
    u = creer_utilisateur(session, "  José  ")
    assert u.nom == "José"  # "José" composé
    # On retrouve le compte via la forme composée (même clé).
    assert lire_utilisateur_par_nom(session, "José").id == u.id


def test_creer_nom_vide_leve_valueerror(session: Session) -> None:
    with pytest.raises(ValueError):
        creer_utilisateur(session, "   ")


def test_creer_doublon_leve(session: Session) -> None:
    creer_utilisateur(session, "Marie")
    with pytest.raises(NomDejaUtilise):
        creer_utilisateur(session, "Marie")


def test_lire_introuvable(session: Session) -> None:
    with pytest.raises(UtilisateurIntrouvable):
        lire_utilisateur_par_nom(session, "Inconnu")


def test_lister_tri_et_filtre_inactifs(session: Session) -> None:
    creer_utilisateur(session, "Zoe")
    creer_utilisateur(session, "Ana")
    desactiver_utilisateur(session, "Zoe")
    tous = lister_utilisateurs(session)
    assert [u.nom for u in tous] == ["Ana", "Zoe"]  # tri par nom
    actifs = lister_utilisateurs(session, inclure_inactifs=False)
    assert [u.nom for u in actifs] == ["Ana"]


def test_modifier_renomme(session: Session) -> None:
    creer_utilisateur(session, "Marie")
    u = modifier_utilisateur(session, "Marie", nouveau_nom="Marie D.")
    assert u.nom == "Marie D."
    with pytest.raises(UtilisateurIntrouvable):
        lire_utilisateur_par_nom(session, "Marie")


def test_modifier_tristate_laisse_inchange(session: Session) -> None:
    creer_utilisateur(session, "Marie", peut_editer=True)
    # Aucun paramètre fourni : tout reste inchangé.
    u = modifier_utilisateur(session, "Marie")
    assert u.peut_editer is True
    assert u.actif is True
    # Seul peut_editer bascule ; actif intact.
    u = modifier_utilisateur(session, "Marie", peut_editer=False)
    assert u.peut_editer is False
    assert u.actif is True


def test_modifier_renomme_collision(session: Session) -> None:
    creer_utilisateur(session, "Marie")
    creer_utilisateur(session, "Hugo")
    with pytest.raises(NomDejaUtilise):
        modifier_utilisateur(session, "Hugo", nouveau_nom="Marie")


def test_modifier_introuvable(session: Session) -> None:
    with pytest.raises(UtilisateurIntrouvable):
        modifier_utilisateur(session, "Inconnu", actif=False)


def test_desactiver_puis_reactiver(session: Session) -> None:
    creer_utilisateur(session, "Marie")
    u = desactiver_utilisateur(session, "Marie")
    assert u.actif is False
    u = modifier_utilisateur(session, "Marie", actif=True)
    assert u.actif is True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _base_vide(tmp_path: Path) -> Path:
    db = tmp_path / "u.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def test_cli_ajouter_et_lister(tmp_path: Path) -> None:
    db = _base_vide(tmp_path)
    r = runner.invoke(app, ["utilisateurs", "ajouter", "Marie", "--db-path", str(db)])
    assert r.exit_code == 0, r.output
    assert "créé" in r.output
    r = runner.invoke(app, ["utilisateurs", "lister", "--db-path", str(db)])
    assert r.exit_code == 0
    assert "Marie" in r.output


def test_cli_ajouter_doublon_exit1(tmp_path: Path) -> None:
    db = _base_vide(tmp_path)
    runner.invoke(app, ["utilisateurs", "ajouter", "Marie", "--db-path", str(db)])
    r = runner.invoke(app, ["utilisateurs", "ajouter", "Marie", "--db-path", str(db)])
    assert r.exit_code == 1
    assert "existe déjà" in r.output


def test_cli_ajouter_lecteur(tmp_path: Path) -> None:
    db = _base_vide(tmp_path)
    r = runner.invoke(
        app, ["utilisateurs", "ajouter", "Hugo", "--lecteur", "--db-path", str(db)]
    )
    assert r.exit_code == 0
    assert "lecteur seul" in r.output


def test_cli_modifier_inactif_puis_actifs_seuls(tmp_path: Path) -> None:
    db = _base_vide(tmp_path)
    runner.invoke(app, ["utilisateurs", "ajouter", "Marie", "--db-path", str(db)])
    runner.invoke(app, ["utilisateurs", "ajouter", "Hugo", "--db-path", str(db)])
    r = runner.invoke(
        app, ["utilisateurs", "modifier", "Hugo", "--inactif", "--db-path", str(db)]
    )
    assert r.exit_code == 0
    r = runner.invoke(
        app, ["utilisateurs", "lister", "--actifs-seuls", "--db-path", str(db)]
    )
    assert r.exit_code == 0
    assert "Marie" in r.output
    assert "Hugo" not in r.output


def test_cli_desactiver(tmp_path: Path) -> None:
    db = _base_vide(tmp_path)
    runner.invoke(app, ["utilisateurs", "ajouter", "Marie", "--db-path", str(db)])
    r = runner.invoke(
        app, ["utilisateurs", "desactiver", "Marie", "--db-path", str(db)]
    )
    assert r.exit_code == 0
    assert "désactivé" in r.output


def test_cli_modifier_introuvable_exit1(tmp_path: Path) -> None:
    db = _base_vide(tmp_path)
    r = runner.invoke(
        app, ["utilisateurs", "modifier", "Inconnu", "--actif", "--db-path", str(db)]
    )
    assert r.exit_code == 1
    assert "aucun compte" in r.output.lower()
