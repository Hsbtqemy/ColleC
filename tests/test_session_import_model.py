"""Tests du modèle SessionImport (refonte v2 / fonds).

Validation : statut whitelist, FK ON DELETE SET NULL vers Fonds,
indexes, JSON nullable pour les états transients (fonds_data,
mappings, configuration_fichiers, colonnes_detectees).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.models import Fonds, SessionImport


def test_creation_minimale(session: Session) -> None:
    """Créer une session avec juste l'utilisateur — défauts appliqués."""
    s = SessionImport(utilisateur="marie")
    session.add(s)
    session.commit()
    assert s.id is not None
    assert s.statut == "en_cours"
    assert s.etape == "tableur"
    assert s.cree_le is not None


def test_statut_whitelist_valide(session: Session) -> None:
    for statut in ("en_cours", "validee", "abandonnee"):
        session.add(SessionImport(utilisateur="u", statut=statut))
    session.commit()


def test_statut_hors_whitelist_rejete(session: Session) -> None:
    session.add(SessionImport(utilisateur="u", statut="bidon"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_fonds_supprime_set_null(session: Session) -> None:
    """ON DELETE SET NULL : la session survit à la suppression du fonds créé."""
    fonds = Fonds(cote="X", titre="X")
    session.add(fonds)
    session.flush()
    s = SessionImport(utilisateur="u", fonds_cree_id=fonds.id)
    session.add(s)
    session.commit()

    session.delete(fonds)
    session.commit()
    session.refresh(s)
    assert s.fonds_cree_id is None


def test_etats_json_persistes(session: Session) -> None:
    s = SessionImport(
        utilisateur="u",
        colonnes_detectees=["Cote", "Titre", "Date"],
        fonds_data={"cote": "Z", "titre": "Fonds Z"},
        collection_miroir_data={"phase": "catalogage"},
        mappings={"cote": "Cote", "titre": "Titre"},
        configuration_fichiers={"racine": "scans", "motif_chemin": "{cote}/*.tif"},
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    assert s.colonnes_detectees == ["Cote", "Titre", "Date"]
    assert s.fonds_data == {"cote": "Z", "titre": "Fonds Z"}
    assert s.collection_miroir_data == {"phase": "catalogage"}
    assert s.mappings["cote"] == "Cote"
    assert s.configuration_fichiers["motif_chemin"] == "{cote}/*.tif"
