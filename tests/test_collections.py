"""Tests du service Collection (V0.9.0-alpha.1)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    CollectionIntrouvable,
    CollectionInvalide,
    FormulaireCollection,
    OperationCollectionInterdite,
    ajouter_item_a_collection,
    creer_collection_libre,
    lire_collection,
    lire_collection_par_cote,
    lister_collections,
    modifier_collection,
    retirer_item_de_collection,
    supprimer_collection_libre,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
)
from archives_tool.models import (
    Collection,
    Fonds,
    Item,
    ItemCollection,
    TypeCollection,
)
from _helpers import make_item as _item


# ---------------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------------


def test_creer_libre_rattachee(session: Session, fonds_hk: Fonds) -> None:
    col = creer_collection_libre(
        session,
        FormulaireCollection(
            cote="HK-OEUVRES", titre="Œuvres", fonds_id=fonds_hk.id
        ),
    )
    assert col.id is not None
    assert col.type_collection == TypeCollection.LIBRE.value
    assert col.fonds_id == fonds_hk.id


def test_creer_libre_transversale(session: Session) -> None:
    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="TRANSV", titre="Témoignages d'exil"),
    )
    assert col.fonds_id is None
    assert col.type_collection == TypeCollection.LIBRE.value


def test_creer_libre_strip_chaines(session: Session) -> None:
    col = creer_collection_libre(
        session,
        FormulaireCollection(
            cote="  TRIM  ",
            titre="  Titre  ",
            description="  ok  ",
        ),
    )
    assert col.cote == "TRIM"
    assert col.titre == "Titre"
    assert col.description == "ok"


def test_creer_libre_cote_vide_rejete(session: Session) -> None:
    with pytest.raises(CollectionInvalide) as exc:
        creer_collection_libre(session, FormulaireCollection(cote="", titre="X"))
    assert "cote" in exc.value.erreurs


def test_creer_libre_titre_vide_rejete(session: Session) -> None:
    with pytest.raises(CollectionInvalide) as exc:
        creer_collection_libre(session, FormulaireCollection(cote="X", titre=""))
    assert "titre" in exc.value.erreurs


def test_creer_libre_cote_caracteres_speciaux_rejete(session: Session) -> None:
    with pytest.raises(CollectionInvalide) as exc:
        creer_collection_libre(
            session, FormulaireCollection(cote="ma cote", titre="X")
        )
    assert "cote" in exc.value.erreurs


def test_creer_libre_phase_inconnue_rejete(session: Session) -> None:
    # Pydantic field_validator lève ValueError → ValidationError
    with pytest.raises(Exception):  # ValidationError
        FormulaireCollection(cote="X", titre="X", phase="bidon")


def test_creer_libre_fonds_inexistant_rejete(session: Session) -> None:
    with pytest.raises(CollectionInvalide) as exc:
        creer_collection_libre(
            session,
            FormulaireCollection(cote="X", titre="X", fonds_id=99999),
        )
    assert "fonds_id" in exc.value.erreurs


def test_creer_libre_cote_doublon_meme_fonds_rejete(
    session: Session, fonds_hk: Fonds
) -> None:
    creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-OEUVRES", titre="A", fonds_id=fonds_hk.id),
    )
    with pytest.raises(CollectionInvalide):
        creer_collection_libre(
            session,
            FormulaireCollection(
                cote="HK-OEUVRES", titre="B", fonds_id=fonds_hk.id
            ),
        )


def test_creer_libre_cote_doublon_avec_miroir_meme_fonds_rejete(
    session: Session, fonds_hk: Fonds
) -> None:
    """La miroir de HK porte cote=HK ; on ne peut pas créer une libre
    cote=HK dans le même fonds."""
    with pytest.raises(CollectionInvalide):
        creer_collection_libre(
            session,
            FormulaireCollection(cote="HK", titre="HK doublon", fonds_id=fonds_hk.id),
        )


def test_creer_libre_cote_se_repete_entre_fonds(session: Session) -> None:
    """Index unique est par fonds : deux fonds peuvent avoir une
    collection « OEUVRES »."""
    fonds_a = creer_fonds(session, FormulaireFonds(cote="A", titre="A"))
    fonds_b = creer_fonds(session, FormulaireFonds(cote="B", titre="B"))
    creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUVRES", titre="A œuvres", fonds_id=fonds_a.id),
    )
    creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUVRES", titre="B œuvres", fonds_id=fonds_b.id),
    )
    nb = session.scalar(
        select(func.count(Collection.id)).where(Collection.cote == "OEUVRES")
    )
    assert nb == 2


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------


def test_lire_collection_inexistante(session: Session) -> None:
    with pytest.raises(CollectionIntrouvable):
        lire_collection(session, 99999)


def test_lire_par_cote_avec_fonds(session: Session, fonds_hk: Fonds) -> None:
    col = lire_collection_par_cote(session, "HK", fonds_id=fonds_hk.id)
    assert col.type_collection == TypeCollection.MIROIR.value


def test_lire_par_cote_inexistante(session: Session) -> None:
    with pytest.raises(CollectionIntrouvable):
        lire_collection_par_cote(session, "INCONNUE")


def test_lire_par_cote_ambigue_sans_fonds(session: Session, fonds_hk: Fonds) -> None:
    """Une cote partagée par la miroir d'un fonds et une transversale
    libre — sans fonds_id, on ne peut pas trancher."""
    creer_collection_libre(
        session, FormulaireCollection(cote="HK", titre="HK transversale")
    )
    with pytest.raises(OperationCollectionInterdite):
        lire_collection_par_cote(session, "HK")


def test_lire_par_cote_sans_fonds_unique(session: Session, fonds_hk: Fonds) -> None:
    creer_collection_libre(
        session,
        FormulaireCollection(cote="UNIQUE", titre="Transversale"),
    )
    col = lire_collection_par_cote(session, "UNIQUE")
    assert col.titre == "Transversale"


# ---------------------------------------------------------------------------
# Listage
# ---------------------------------------------------------------------------


def test_lister_sans_filtre(session: Session, fonds_hk: Fonds) -> None:
    creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-OEUVRES", titre="Œuvres", fonds_id=fonds_hk.id),
    )
    cols = lister_collections(session)
    # Miroir HK + libre HK-OEUVRES.
    assert len(cols) == 2


def test_lister_filtre_par_fonds(session: Session, fonds_hk: Fonds) -> None:
    fonds_b = creer_fonds(session, FormulaireFonds(cote="B", titre="B"))
    creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUVRES", titre="HK œuvres", fonds_id=fonds_hk.id),
    )
    creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUVRES", titre="B œuvres", fonds_id=fonds_b.id),
    )
    cols = lister_collections(session, fonds_id=fonds_hk.id)
    cotes = {c.cote for c in cols}
    assert cotes == {"HK", "OEUVRES"}  # miroir HK + libre HK-OEUVRES


def test_lister_filtre_miroir(session: Session, fonds_hk: Fonds) -> None:
    creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-OEUVRES", titre="Œuvres", fonds_id=fonds_hk.id),
    )
    miroirs = lister_collections(session, type_collection=TypeCollection.MIROIR)
    assert len(miroirs) == 1
    assert miroirs[0].cote == "HK"


def test_lister_filtre_libre(session: Session, fonds_hk: Fonds) -> None:
    creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-OEUVRES", titre="Œuvres", fonds_id=fonds_hk.id),
    )
    libres = lister_collections(session, type_collection=TypeCollection.LIBRE)
    assert len(libres) == 1
    assert libres[0].cote == "HK-OEUVRES"


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------


def test_modifier_libre_change_titre(
    session: Session, fonds_hk: Fonds
) -> None:
    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-OEUV", titre="Ancien", fonds_id=fonds_hk.id),
    )
    nouv = modifier_collection(
        session,
        col.id,
        FormulaireCollection(cote="HK-OEUV", titre="Nouveau", fonds_id=fonds_hk.id),
    )
    assert nouv.titre == "Nouveau"


def test_modifier_libre_devient_transversale(
    session: Session, fonds_hk: Fonds
) -> None:
    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="MOVE", titre="Move", fonds_id=fonds_hk.id),
    )
    nouv = modifier_collection(
        session,
        col.id,
        FormulaireCollection(cote="MOVE", titre="Move", fonds_id=None),
    )
    assert nouv.fonds_id is None


def test_modifier_miroir_changer_fonds_rejete(
    session: Session, fonds_hk: Fonds
) -> None:
    fonds_b = creer_fonds(session, FormulaireFonds(cote="B", titre="B"))
    miroir = lire_collection_par_cote(session, "HK", fonds_id=fonds_hk.id)
    with pytest.raises(OperationCollectionInterdite):
        modifier_collection(
            session,
            miroir.id,
            FormulaireCollection(cote="HK", titre="HK", fonds_id=fonds_b.id),
        )


def test_modifier_cote_conflit_meme_fonds_rejete(
    session: Session, fonds_hk: Fonds
) -> None:
    creer_collection_libre(
        session,
        FormulaireCollection(cote="A", titre="A", fonds_id=fonds_hk.id),
    )
    col_b = creer_collection_libre(
        session,
        FormulaireCollection(cote="B", titre="B", fonds_id=fonds_hk.id),
    )
    with pytest.raises(CollectionInvalide):
        modifier_collection(
            session,
            col_b.id,
            FormulaireCollection(cote="A", titre="B", fonds_id=fonds_hk.id),
        )


def test_modifier_inexistant(session: Session) -> None:
    with pytest.raises(CollectionIntrouvable):
        modifier_collection(
            session, 99999, FormulaireCollection(cote="X", titre="X")
        )


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------


def test_supprimer_libre(session: Session, fonds_hk: Fonds) -> None:
    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="DEL", titre="Del", fonds_id=fonds_hk.id),
    )
    cid = col.id
    supprimer_collection_libre(session, cid)
    assert session.get(Collection, cid) is None


def test_supprimer_miroir_rejete(session: Session, fonds_hk: Fonds) -> None:
    miroir = lire_collection_par_cote(session, "HK", fonds_id=fonds_hk.id)
    with pytest.raises(OperationCollectionInterdite):
        supprimer_collection_libre(session, miroir.id)


def test_supprimer_libre_avec_items_garde_les_items(
    session: Session, fonds_hk: Fonds
) -> None:
    """Cascade ItemCollection : les liaisons disparaissent, les items
    eux-mêmes restent dans leur fonds."""
    item = _item(fonds_hk, "HK-001")
    session.add(item)
    session.commit()

    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-DEL", titre="Del", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item.id, col.id)
    cid = col.id
    iid = item.id

    supprimer_collection_libre(session, cid)

    assert session.get(Collection, cid) is None
    assert session.get(Item, iid) is not None
    assert session.get(ItemCollection, (iid, cid)) is None


# ---------------------------------------------------------------------------
# Liaisons N-N
# ---------------------------------------------------------------------------


def test_ajouter_item_a_collection(session: Session, fonds_hk: Fonds) -> None:
    item = _item(fonds_hk, "HK-001")
    session.add(item)
    session.commit()
    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-OEUV", titre="Œuv", fonds_id=fonds_hk.id),
    )
    liaison = ajouter_item_a_collection(session, item.id, col.id)
    assert liaison.item_id == item.id
    assert liaison.collection_id == col.id


def test_ajouter_item_idempotent(session: Session, fonds_hk: Fonds) -> None:
    item = _item(fonds_hk, "HK-001")
    session.add(item)
    session.commit()
    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="HK-OEUV", titre="Œuv", fonds_id=fonds_hk.id),
    )
    a = ajouter_item_a_collection(session, item.id, col.id)
    b = ajouter_item_a_collection(session, item.id, col.id)
    assert (a.item_id, a.collection_id) == (b.item_id, b.collection_id)
    nb = session.scalar(
        select(func.count())
        .select_from(ItemCollection)
        .where(ItemCollection.item_id == item.id)
    )
    assert nb == 1


def test_ajouter_item_cross_fonds(session: Session) -> None:
    """Une collection libre transversale peut accueillir des items de
    n'importe quel fonds."""
    fonds_a = creer_fonds(session, FormulaireFonds(cote="A", titre="A"))
    fonds_b = creer_fonds(session, FormulaireFonds(cote="B", titre="B"))
    item_a = _item(fonds_a, "A-001")
    item_b = _item(fonds_b, "B-001")
    session.add_all([item_a, item_b])
    session.commit()

    transv = creer_collection_libre(
        session, FormulaireCollection(cote="TRANSV", titre="T")
    )
    ajouter_item_a_collection(session, item_a.id, transv.id)
    ajouter_item_a_collection(session, item_b.id, transv.id)

    nb = session.scalar(
        select(func.count())
        .select_from(ItemCollection)
        .where(ItemCollection.collection_id == transv.id)
    )
    assert nb == 2


def test_ajouter_item_inexistant(session: Session, fonds_hk: Fonds) -> None:
    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="X", titre="X", fonds_id=fonds_hk.id),
    )
    with pytest.raises(LookupError):
        ajouter_item_a_collection(session, 99999, col.id)


def test_ajouter_collection_inexistante(session: Session, fonds_hk: Fonds) -> None:
    item = _item(fonds_hk, "HK-001")
    session.add(item)
    session.commit()
    with pytest.raises(CollectionIntrouvable):
        ajouter_item_a_collection(session, item.id, 99999)


def test_retirer_item(session: Session, fonds_hk: Fonds) -> None:
    item = _item(fonds_hk, "HK-001")
    session.add(item)
    session.commit()
    col = creer_collection_libre(
        session, FormulaireCollection(cote="X", titre="X", fonds_id=fonds_hk.id)
    )
    ajouter_item_a_collection(session, item.id, col.id)
    retirer_item_de_collection(session, item.id, col.id)
    assert session.get(ItemCollection, (item.id, col.id)) is None


def test_retirer_item_idempotent(session: Session, fonds_hk: Fonds) -> None:
    item = _item(fonds_hk, "HK-001")
    session.add(item)
    session.commit()
    col = creer_collection_libre(
        session, FormulaireCollection(cote="X", titre="X", fonds_id=fonds_hk.id)
    )
    # Pas de liaison préalable — l'appel doit être un no-op.
    retirer_item_de_collection(session, item.id, col.id)


def test_retirer_item_de_miroir_garde_dans_fonds(
    session: Session, fonds_hk: Fonds
) -> None:
    """Invariant 7 : retirer un item de la miroir ne le supprime pas
    du fonds."""
    item = _item(fonds_hk, "HK-001")
    session.add(item)
    session.commit()
    miroir = lire_collection_par_cote(session, "HK", fonds_id=fonds_hk.id)
    ajouter_item_a_collection(session, item.id, miroir.id)
    retirer_item_de_collection(session, item.id, miroir.id)
    # L'item subsiste dans le fonds.
    assert session.get(Item, item.id) is not None
    assert session.get(Item, item.id).fonds_id == fonds_hk.id
