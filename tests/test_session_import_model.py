"""Tests du modèle SessionImport (migration V0.7).

Validation : statut whitelist, FK ON DELETE SET NULL vers Collection,
indexes utilisateur et statut, JSON nullable pour les états transients
(mappings, configuration_fichiers, nouvelle_collection).
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from archives_tool.models import Collection, SessionImport


def test_creation_minimale(session: Session) -> None:
    """Créer une session avec juste l'utilisateur — défauts appliqués."""
    s = SessionImport(utilisateur="marie")
    session.add(s)
    session.commit()
    assert s.id is not None
    assert s.statut == "en_cours"
    assert s.cree_le is not None


def test_statut_whitelist_valide(session: Session) -> None:
    for statut in ("en_cours", "validee", "abandonnee"):
        s = SessionImport(utilisateur="u", statut=statut)
        session.add(s)
    session.commit()


def test_statut_hors_whitelist_rejete(session: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    session.add(SessionImport(utilisateur="u", statut="bidon"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_collection_supprimee_set_null(session: Session) -> None:
    """ON DELETE SET NULL : la session survit à la suppression de la cible."""
    col = Collection(cote_collection="X", titre="X", phase="catalogage")
    session.add(col)
    session.flush()
    s = SessionImport(utilisateur="u", collection_cible_id=col.id)
    session.add(s)
    session.commit()

    session.delete(col)
    session.commit()
    session.refresh(s)
    assert s.collection_cible_id is None


def test_etats_json_persistes(session: Session) -> None:
    s = SessionImport(
        utilisateur="u",
        nouvelle_collection={"cote": "Z", "titre": "Z"},
        mappings={"cote": "Cote", "titre": "Titre"},
        configuration_fichiers={"racine": "scans", "motif": "{cote}/*.tif"},
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    assert s.nouvelle_collection == {"cote": "Z", "titre": "Z"}
    assert s.mappings["cote"] == "Cote"
    assert s.configuration_fichiers["motif"] == "{cote}/*.tif"
