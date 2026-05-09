"""Tests d'intégration cross-services V0.9.0-alpha.1.

Valident les invariants 5, 6, 7 et les cascades sur des workflows
end-to-end qui traversent les trois services Fonds / Collection / Item.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    FormulaireCollection,
    ajouter_item_a_collection,
    creer_collection_libre,
    lire_collection_par_cote,
    retirer_item_de_collection,
    supprimer_collection_libre,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    supprimer_fonds,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    collections_de_item,
    creer_item,
    supprimer_item,
)
from archives_tool.models import Collection, Item, ItemCollection


def test_workflow_complet_fonds_item_libre(session: Session) -> None:
    """Création d'un fonds → vérifier qu'il a sa miroir → créer un item
    → vérifier qu'il est dans la miroir → créer une libre dans le fonds
    → ajouter l'item à la libre → vérifier qu'il est dans les 2 →
    retirer de la libre → vérifier qu'il reste dans la miroir →
    supprimer l'item → vérifier qu'il n'est plus nulle part.
    """
    # Fonds + miroir auto.
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    miroir = fonds.collection_miroir
    assert miroir is not None
    assert miroir.cote == "HK"

    # Item → auto-rattaché à la miroir (invariant 6).
    item = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="Numéro 1", fonds_id=fonds.id),
    )
    assert miroir in item.collections

    # Libre dans le fonds → ajouter l'item.
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œuvres", fonds_id=fonds.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)
    cotes = {c.cote for c in collections_de_item(session, item.id)}
    assert cotes == {"HK", "OEUV"}

    # Retrait de la libre → reste dans la miroir.
    retirer_item_de_collection(session, item.id, libre.id)
    cotes = {c.cote for c in collections_de_item(session, item.id)}
    assert cotes == {"HK"}

    # Suppression de l'item → plus de liaisons, item disparu.
    iid = item.id
    supprimer_item(session, iid)
    assert session.get(Item, iid) is None
    nb_liaisons = session.scalar(
        select(func.count())
        .select_from(ItemCollection)
        .where(ItemCollection.item_id == iid)
    )
    assert nb_liaisons == 0


def test_workflow_transversale_avec_cascade_fonds(session: Session) -> None:
    """Création d'un fonds + items → création d'une collection
    transversale (sans fonds_id) → ajout des items → suppression du
    fonds → vérifier que la transversale survit mais que ses items
    ont disparu (cascade depuis Item.fonds_id)."""
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    item1 = creer_item(
        session, FormulaireItem(cote="HK-001", titre="A", fonds_id=fonds.id)
    )
    item2 = creer_item(
        session, FormulaireItem(cote="HK-002", titre="B", fonds_id=fonds.id)
    )

    transv = creer_collection_libre(
        session, FormulaireCollection(cote="TRANSV", titre="Témoignages")
    )
    ajouter_item_a_collection(session, item1.id, transv.id)
    ajouter_item_a_collection(session, item2.id, transv.id)
    transv_id = transv.id

    nb_avant = session.scalar(
        select(func.count())
        .select_from(ItemCollection)
        .where(ItemCollection.collection_id == transv_id)
    )
    assert nb_avant == 2

    supprimer_fonds(session, fonds.id)

    transv_relue = session.get(Collection, transv_id)
    assert transv_relue is not None
    assert transv_relue.fonds_id is None
    nb_apres = session.scalar(
        select(func.count())
        .select_from(ItemCollection)
        .where(ItemCollection.collection_id == transv_id)
    )
    assert nb_apres == 0


def test_workflow_libre_devient_transversale_au_supprimer_fonds(
    session: Session,
) -> None:
    """Une collection libre rattachée passe à transversale (fonds_id
    NULL) quand son fonds disparaît, mais ses items du fonds disparaissent
    aussi (cascade depuis Item.fonds_id)."""
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="HK"))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-OEUV", titre="Œuvres", fonds_id=fonds.id),
    )
    item = creer_item(
        session, FormulaireItem(cote="HK-001", titre="A", fonds_id=fonds.id)
    )
    ajouter_item_a_collection(session, item.id, libre.id)
    libre_id, item_id = libre.id, item.id

    supprimer_fonds(session, fonds.id)

    libre_relue = session.get(Collection, libre_id)
    assert libre_relue is not None
    assert libre_relue.fonds_id is None
    assert session.get(Item, item_id) is None


def test_workflow_supprimer_libre_garde_items_dans_fonds(
    session: Session,
) -> None:
    """Supprimer une libre n'affecte ni le fonds, ni les items, ni la
    miroir. Seules les liaisons N-N de cette libre disparaissent."""
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="HK"))
    item = creer_item(
        session, FormulaireItem(cote="HK-001", titre="A", fonds_id=fonds.id)
    )
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)

    supprimer_collection_libre(session, libre.id)

    miroir = lire_collection_par_cote(session, "HK", fonds_id=fonds.id)
    cotes = {c.cote for c in collections_de_item(session, item.id)}
    assert cotes == {"HK"}
    assert miroir.id in [c.id for c in collections_de_item(session, item.id)]
