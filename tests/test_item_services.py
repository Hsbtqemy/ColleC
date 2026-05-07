"""Tests du service de la vue item."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from archives_tool.api.services.item import ItemIntrouvable, item_detail
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Item,
    PhaseChantier,
)


def _peupler(session: Session) -> None:
    col = Collection(
        cote_collection="C", titre="T", phase=PhaseChantier.CATALOGAGE.value
    )
    session.add(col)
    session.flush()
    item = Item(
        collection_id=col.id,
        cote="C-001",
        titre="Item un",
        annee=1960,
        etat_catalogage=EtatCatalogage.VERIFIE.value,
    )
    session.add(item)
    session.flush()
    for ordre in range(1, 4):
        session.add(
            Fichier(
                item_id=item.id,
                racine="s",
                chemin_relatif=f"C-001/{ordre:02d}.png",
                nom_fichier=f"{ordre:02d}.png",
                ordre=ordre,
                apercu_chemin=f"apercu/C-001/{ordre:02d}.jpg",
                vignette_chemin=f"vignette/C-001/{ordre:02d}.jpg",
            )
        )
    session.commit()


def test_item_detail_charge_collection_et_fichiers(session: Session) -> None:
    _peupler(session)
    detail = item_detail(session, "C-001")
    assert detail.cote == "C-001"
    assert detail.collection_cote == "C"
    assert detail.collection_phase == PhaseChantier.CATALOGAGE
    assert detail.etat == EtatCatalogage.VERIFIE
    assert len(detail.fichiers) == 3
    # Fichiers triés par ordre.
    assert [f.ordre for f in detail.fichiers] == [1, 2, 3]
    # Sources d'image résolues.
    f1 = detail.fichiers[0]
    assert f1.source.primary == {
        "type": "image",
        "url": "/derives/miniatures/apercu/C-001/01.jpg",
    }
    assert f1.source.vignette_url == "/derives/miniatures/vignette/C-001/01.jpg"


def test_item_introuvable(session: Session) -> None:
    with pytest.raises(ItemIntrouvable):
        item_detail(session, "N_EXISTE_PAS")


def test_filtre_par_collection(session: Session) -> None:
    """Deux items partagent la même cote dans des collections distinctes."""
    c1 = Collection(cote_collection="A", titre="A", phase="catalogage")
    c2 = Collection(cote_collection="B", titre="B", phase="catalogage")
    session.add_all([c1, c2])
    session.flush()
    session.add_all(
        [
            Item(collection_id=c1.id, cote="X-001", titre="dans A"),
            Item(collection_id=c2.id, cote="X-001", titre="dans B"),
        ]
    )
    session.commit()

    detail_a = item_detail(session, "X-001", collection_cote="A")
    assert detail_a.titre == "dans A"
    detail_b = item_detail(session, "X-001", collection_cote="B")
    assert detail_b.titre == "dans B"
