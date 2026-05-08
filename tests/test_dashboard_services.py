"""Tests des services métier du dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services.dashboard import (
    calculer_statistiques_globales,
    lister_activite_recente,
    lister_collections_dashboard,
    lister_points_vigilance,
)
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Item,
    ModificationItem,
    OperationFichier,
    OperationImport,
    PhaseChantier,
    StatutOperation,
    TypeOperationFichier,
)


@pytest.fixture
def base_peuplee(session: Session) -> Session:
    parent = Collection(
        cote_collection="P",
        titre="Parent",
        phase=PhaseChantier.CATALOGAGE.value,
    )
    enfant = Collection(
        cote_collection="P-E",
        titre="Enfant",
        parent=parent,
        phase=PhaseChantier.NUMERISATION.value,
    )
    session.add_all([parent, enfant])
    session.flush()

    items = []
    for i in range(5):
        etat = (
            EtatCatalogage.VALIDE
            if i < 2
            else (EtatCatalogage.A_VERIFIER if i < 4 else EtatCatalogage.BROUILLON)
        )
        item = Item(
            collection_id=parent.id,
            cote=f"P-{i:03d}",
            titre=f"Item {i}",
            etat_catalogage=etat.value,
        )
        items.append(item)
    session.add_all(items)
    session.flush()
    for item in items:
        session.add(
            Fichier(
                item_id=item.id,
                racine="s",
                chemin_relatif=f"{item.cote}.png",
                nom_fichier=f"{item.cote}.png",
                ordre=1,
                taille_octets=1024 * 1024,
            )
        )
    session.commit()
    return session


def test_statistiques_base_vide(session: Session) -> None:
    stats = calculer_statistiques_globales(session)
    assert stats.nb_collections == 0
    assert stats.nb_items == 0
    assert stats.pourcentage_valides == 0.0


def test_statistiques_base_peuplee(base_peuplee: Session) -> None:
    stats = calculer_statistiques_globales(base_peuplee)
    assert stats.nb_collections == 2
    assert stats.nb_collections_racines == 1
    assert stats.nb_sous_collections == 1
    assert stats.nb_items == 5
    assert stats.nb_items_valides == 2
    assert 0 < stats.pourcentage_valides < 100
    assert stats.nb_fichiers == 5
    assert stats.volume_octets == 5 * 1024 * 1024


def test_lister_collections_avec_repartition(base_peuplee: Session) -> None:
    resumes = lister_collections_dashboard(base_peuplee)
    # Une seule collection racine.
    assert len(resumes) == 1
    res = resumes[0]
    assert res.cote == "P"
    assert res.nb_items == 5
    assert res.nb_fichiers == 5
    assert res.sous_collections == 1
    assert res.repartition == {"valide": 2, "a_verifier": 2, "brouillon": 1}
    assert res.href == "/collection/P"


def test_lister_activite_recente_fusion_des_journaux(base_peuplee: Session) -> None:
    item = base_peuplee.scalar(select(Item).order_by(Item.id))
    fichier = base_peuplee.scalar(select(Fichier).limit(1))

    base_peuplee.add_all(
        [
            ModificationItem(
                item_id=item.id,
                champ="titre",
                valeur_apres="X",
                modifie_par="A",
                modifie_le=datetime.now() - timedelta(hours=1),
            ),
            OperationFichier(
                batch_id="b1",
                fichier_id=fichier.id,
                type_operation=TypeOperationFichier.RENAME.value,
                racine_avant="s",
                chemin_avant="x.png",
                racine_apres="s",
                chemin_apres="y.png",
                statut=StatutOperation.REUSSIE.value,
                execute_par="B",
                execute_le=datetime.now() - timedelta(hours=2),
            ),
            OperationImport(
                batch_id="b2",
                profil_chemin="p.yaml",
                items_crees=10,
                fichiers_ajoutes=20,
                execute_par="C",
                execute_le=datetime.now() - timedelta(hours=3),
            ),
        ]
    )
    base_peuplee.commit()

    activite = lister_activite_recente(base_peuplee, limite=10)
    types = [e.type for e in activite]
    assert "modification" in types
    assert "renommage" in types
    assert "import" in types
    # Tri descendant par horodatage.
    assert activite == sorted(activite, key=lambda e: e.horodatage, reverse=True)


def test_points_vigilance_signalent_doublons(base_peuplee: Session) -> None:
    fichiers = list(base_peuplee.scalars(select(Fichier)).all())
    h = "abc" * 21 + "x"  # 64 chars
    fichiers[0].hash_sha256 = h
    fichiers[1].hash_sha256 = h
    base_peuplee.commit()

    points = lister_points_vigilance(base_peuplee)
    types = {p.type for p in points}
    # Doublons doivent ressortir, le contrôle "items vides" peut aussi
    # ressortir si des items existent sans fichier — pas le cas ici.
    assert "doublons" in types


def test_points_vigilance_base_vide_propre(session: Session) -> None:
    points = lister_points_vigilance(session)
    assert points == []
