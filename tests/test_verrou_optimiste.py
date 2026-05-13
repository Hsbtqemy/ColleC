"""Tests du verrou optimiste sur Fonds, Collection, Item.

Le formulaire porte la `version` lue à l'ouverture ; le service la
compare à la version en base au save. Mismatch → `ConflitVersion`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    FormulaireCollection,
    creer_collection_libre,
    modifier_collection,
)
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    modifier_fonds,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    creer_item,
    modifier_item,
)


@pytest.fixture
def fonds_existant(session: Session):
    return creer_fonds(
        session,
        FormulaireFonds(cote="VAL", titre="Vérif optimiste"),
        cree_par="seeder",
    )


def test_modifier_fonds_sans_version_passe(session: Session, fonds_existant) -> None:
    """version=None côté formulaire : pas de vérification (back-compat)."""
    formulaire = FormulaireFonds(cote="VAL", titre="Renommé")
    fonds = modifier_fonds(session, fonds_existant.id, formulaire)
    assert fonds.titre == "Renommé"


def test_modifier_fonds_version_correcte_passe(
    session: Session, fonds_existant
) -> None:
    version_initiale = fonds_existant.version
    formulaire = FormulaireFonds(
        cote="VAL", titre="Renommé v2", version=version_initiale
    )
    fonds = modifier_fonds(session, fonds_existant.id, formulaire)
    assert fonds.titre == "Renommé v2"
    # Version incrémentée.
    assert fonds.version == version_initiale + 1


def test_modifier_fonds_version_perimee_leve(session: Session, fonds_existant) -> None:
    """Modification entre deux ouvertures du formulaire : la seconde
    soumission échoue avec ConflitVersion."""
    version_ouverture = fonds_existant.version
    # Quelqu'un d'autre modifie d'abord, en passant la bonne version.
    modifier_fonds(
        session,
        fonds_existant.id,
        FormulaireFonds(cote="VAL", titre="Première", version=version_ouverture),
    )
    # On tente de soumettre avec la version pré-modif.
    with pytest.raises(ConflitVersion) as exc:
        modifier_fonds(
            session,
            fonds_existant.id,
            FormulaireFonds(cote="VAL", titre="Seconde", version=version_ouverture),
        )
    assert exc.value.version_attendue == version_ouverture
    assert exc.value.version_actuelle == version_ouverture + 1


def test_modifier_item_verrou(session: Session, fonds_existant) -> None:
    item = creer_item(
        session,
        FormulaireItem(cote="VAL-001", titre="T", fonds_id=fonds_existant.id),
        cree_par="seeder",
    )
    version = item.version

    # Première modification avec la bonne version.
    modifier_item(
        session,
        item.id,
        FormulaireItem(
            cote="VAL-001",
            titre="Premier",
            fonds_id=fonds_existant.id,
            version=version,
        ),
    )

    # Seconde soumission avec la même (donc obsolète) version.
    with pytest.raises(ConflitVersion):
        modifier_item(
            session,
            item.id,
            FormulaireItem(
                cote="VAL-001",
                titre="Doublon",
                fonds_id=fonds_existant.id,
                version=version,
            ),
        )


def test_modifier_collection_verrou(session: Session, fonds_existant) -> None:
    col = creer_collection_libre(
        session,
        FormulaireCollection(cote="VAL-COL", titre="Lib", fonds_id=fonds_existant.id),
        cree_par="seeder",
    )
    version = col.version

    modifier_collection(
        session,
        col.id,
        FormulaireCollection(
            cote="VAL-COL",
            titre="Premier",
            fonds_id=fonds_existant.id,
            version=version,
        ),
    )

    with pytest.raises(ConflitVersion):
        modifier_collection(
            session,
            col.id,
            FormulaireCollection(
                cote="VAL-COL",
                titre="Doublon",
                fonds_id=fonds_existant.id,
                version=version,
            ),
        )


def test_message_exception_versions(session: Session, fonds_existant) -> None:
    """L'exception contient les deux versions pour affichage CLI/UI."""
    version = fonds_existant.version
    modifier_fonds(
        session,
        fonds_existant.id,
        FormulaireFonds(cote="VAL", titre="A", version=version),
    )
    try:
        modifier_fonds(
            session,
            fonds_existant.id,
            FormulaireFonds(cote="VAL", titre="B", version=version),
        )
    except ConflitVersion as e:
        msg = str(e)
        assert str(version) in msg
        assert str(version + 1) in msg
    else:
        raise AssertionError("ConflitVersion attendu")
