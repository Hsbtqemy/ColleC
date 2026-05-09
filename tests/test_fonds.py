"""Tests du service Fonds + invariants modèle V0.9.0-alpha."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    FondsInvalide,
    FormulaireFonds,
    creer_fonds,
    lire_fonds,
    lire_fonds_par_cote,
    lister_fonds,
    modifier_fonds,
    supprimer_fonds,
)
from archives_tool.models import (
    Collection,
    Fonds,
    Item,
    TypeCollection,
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_creer_cote_vide(session: Session) -> None:
    with pytest.raises(FondsInvalide) as exc:
        creer_fonds(session, FormulaireFonds(cote="", titre="X"))
    assert "cote" in exc.value.erreurs


def test_creer_titre_vide(session: Session) -> None:
    with pytest.raises(FondsInvalide) as exc:
        creer_fonds(session, FormulaireFonds(cote="HK", titre=""))
    assert "titre" in exc.value.erreurs


# ---------------------------------------------------------------------------
# Création — invariants 1, 5
# ---------------------------------------------------------------------------


def test_creer_fonds_minimal(session: Session) -> None:
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    assert fonds.id is not None
    assert fonds.cote == "HK"
    assert fonds.titre == "Hara-Kiri"


def test_creer_fonds_cree_collection_miroir(session: Session) -> None:
    """Invariants 1 + 5 : une miroir est créée avec même cote / même titre."""
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    miroir = fonds.collection_miroir
    assert miroir is not None
    assert miroir.type_collection == TypeCollection.MIROIR.value
    assert miroir.cote == "HK"
    assert miroir.titre == "Hara-Kiri"
    assert miroir.fonds_id == fonds.id


def test_creer_fonds_strip_chaines(session: Session) -> None:
    fonds = creer_fonds(
        session,
        FormulaireFonds(
            cote="  TRIM  ",
            titre="  Titre  ",
            responsable_archives="  Marie  ",
        ),
    )
    assert fonds.cote == "TRIM"
    assert fonds.titre == "Titre"
    assert fonds.responsable_archives == "Marie"


def test_creer_fonds_optionnels_vides_a_none(session: Session) -> None:
    fonds = creer_fonds(session, FormulaireFonds(cote="X", titre="X"))
    assert fonds.description is None
    assert fonds.editeur is None
    assert fonds.responsable_archives is None


def test_creer_fonds_cote_doublon_rejete(session: Session) -> None:
    creer_fonds(session, FormulaireFonds(cote="HK", titre="A"))
    with pytest.raises(FondsInvalide) as exc:
        creer_fonds(session, FormulaireFonds(cote="HK", titre="B"))
    assert "cote" in exc.value.erreurs


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------


def test_lire_par_id_inexistant(session: Session) -> None:
    with pytest.raises(FondsIntrouvable):
        lire_fonds(session, 99999)


def test_lire_par_cote_inexistante(session: Session) -> None:
    with pytest.raises(FondsIntrouvable):
        lire_fonds_par_cote(session, "N_EXISTE_PAS")


def test_lister_vide(session: Session) -> None:
    assert lister_fonds(session) == []


def test_lister_avec_compteurs(session: Session) -> None:
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    # Ajout direct de 2 items pour tester le compteur (le service Item
    # n'est pas encore disponible dans cette tranche).
    session.add_all(
        [
            Item(fonds_id=fonds.id, cote="HK-001", etat_catalogage="brouillon"),
            Item(fonds_id=fonds.id, cote="HK-002", etat_catalogage="brouillon"),
        ]
    )
    session.commit()
    resumes = lister_fonds(session)
    assert len(resumes) == 1
    assert resumes[0].cote == "HK"
    assert resumes[0].nb_items == 2
    assert resumes[0].nb_collections == 1  # la miroir
    assert resumes[0].miroir_cote == "HK"


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------


def test_modifier_titre(session: Session) -> None:
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="Ancien"))
    nouv = modifier_fonds(
        session,
        fonds.id,
        FormulaireFonds(cote="HK", titre="Nouveau"),
    )
    assert nouv.titre == "Nouveau"


def test_modifier_cote_doublon_rejete(session: Session) -> None:
    creer_fonds(session, FormulaireFonds(cote="A", titre="A"))
    fonds_b = creer_fonds(session, FormulaireFonds(cote="B", titre="B"))
    with pytest.raises(FondsInvalide):
        modifier_fonds(session, fonds_b.id, FormulaireFonds(cote="A", titre="B"))


def test_modifier_inexistant(session: Session) -> None:
    with pytest.raises(FondsIntrouvable):
        modifier_fonds(session, 99999, FormulaireFonds(cote="X", titre="X"))


# ---------------------------------------------------------------------------
# Suppression — invariant 8
# ---------------------------------------------------------------------------


def test_supprimer_cascade_items_et_miroir(session: Session) -> None:
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    session.add(Item(fonds_id=fonds.id, cote="HK-001", etat_catalogage="brouillon"))
    session.commit()
    fonds_id = fonds.id
    miroir_id = fonds.collection_miroir.id

    supprimer_fonds(session, fonds_id)

    assert session.get(Fonds, fonds_id) is None
    assert session.get(Collection, miroir_id) is None
    assert session.scalar(select(Item).where(Item.fonds_id == fonds_id)) is None


def test_supprimer_libres_deviennent_transversales(session: Session) -> None:
    """Une collection libre rattachée à un fonds passe fonds_id=NULL
    au lieu d'être supprimée — préserve le travail."""
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    libre = Collection(
        cote="HK-OEUVRES",
        titre="Œuvres",
        type_collection=TypeCollection.LIBRE.value,
        fonds_id=fonds.id,
    )
    session.add(libre)
    session.commit()
    libre_id = libre.id

    supprimer_fonds(session, fonds.id)

    libre_relue = session.get(Collection, libre_id)
    assert libre_relue is not None
    assert libre_relue.fonds_id is None
    assert libre_relue.type_collection == TypeCollection.LIBRE.value


def test_supprimer_inexistant(session: Session) -> None:
    with pytest.raises(FondsIntrouvable):
        supprimer_fonds(session, 99999)


# ---------------------------------------------------------------------------
# Invariants modèle
# ---------------------------------------------------------------------------


def test_invariant_item_sans_fonds_rejete(session: Session) -> None:
    """Invariant 4 : un Item doit avoir un fonds_id."""
    session.add(Item(cote="ORPH", etat_catalogage="brouillon"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_invariant_miroir_sans_fonds_rejete(session: Session) -> None:
    """Invariant 2 : une Collection MIROIR doit avoir fonds_id."""
    session.add(
        Collection(cote="X", titre="X", type_collection=TypeCollection.MIROIR.value)
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_invariant_libre_sans_fonds_acceptee(session: Session) -> None:
    """Invariant 3 : une Collection LIBRE peut être transversale."""
    session.add(
        Collection(
            cote="TRANSV",
            titre="Transversale",
            type_collection=TypeCollection.LIBRE.value,
        )
    )
    session.commit()
    relue = session.scalar(select(Collection).where(Collection.cote == "TRANSV"))
    assert relue is not None
    assert relue.fonds_id is None


def test_invariant_cote_fonds_et_collection_peuvent_coincider(
    session: Session,
) -> None:
    """Invariant 9 : une cote de fonds peut être identique à une cote
    de collection libre. Le fonds HK a sa miroir cote=HK ; rien
    n'empêche par ailleurs une collection libre cote=HK d'exister
    (transversale)."""
    creer_fonds(session, FormulaireFonds(cote="HK", titre="HK"))
    session.add(
        Collection(
            cote="HK",
            titre="HK transversale",
            type_collection=TypeCollection.LIBRE.value,
        )
    )
    session.commit()
    # 2 collections cote=HK : la miroir + la transversale.
    rows = (
        session.execute(
            select(Collection).where(Collection.cote == "HK").order_by(Collection.id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2


def test_invariant_cote_collection_unique_par_fonds(session: Session) -> None:
    """Index unique (fonds_id, cote) : on ne peut pas avoir deux
    collections de même cote dans le même fonds."""
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="HK"))
    session.add(
        Collection(
            cote="HK",  # même cote que la miroir
            titre="Doublon",
            type_collection=TypeCollection.LIBRE.value,
            fonds_id=fonds.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_invariant_cote_item_unique_par_fonds(session: Session) -> None:
    fonds = creer_fonds(session, FormulaireFonds(cote="HK", titre="HK"))
    session.add(Item(fonds_id=fonds.id, cote="HK-001", etat_catalogage="brouillon"))
    session.commit()
    session.add(Item(fonds_id=fonds.id, cote="HK-001", etat_catalogage="brouillon"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_invariant_cote_item_peut_se_repeter_entre_fonds(session: Session) -> None:
    fonds_a = creer_fonds(session, FormulaireFonds(cote="A", titre="A"))
    fonds_b = creer_fonds(session, FormulaireFonds(cote="B", titre="B"))
    session.add_all(
        [
            Item(fonds_id=fonds_a.id, cote="001", etat_catalogage="brouillon"),
            Item(fonds_id=fonds_b.id, cote="001", etat_catalogage="brouillon"),
        ]
    )
    session.commit()
    nb = session.scalar(select(Item.id).where(Item.cote == "001"))
    assert nb is not None  # au moins un, et le commit n'a pas échoué
