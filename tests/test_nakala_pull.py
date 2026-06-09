"""Tests rapatrier / rafraîchir Nakala (P1c)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala import (
    RafraichissementImpossible,
    RapatriementInvalide,
    _cote_depuis_doi,
    rafraichir,
    rapatrier,
)
from archives_tool.external.nakala.mapper import DepotNakala
from archives_tool.models import Fonds, Item, LienExterneItem, RessourceExterne

_DOI = "10.34847/nkl.abcdef12"


def _depot(identifiant: str = _DOI, titre: str = "Titre Nakala") -> DepotNakala:
    return DepotNakala(
        identifiant=identifiant,
        statut="published",
        titre=titre,
        createurs=["Topor, Roland"],
        date="1969-09",
        type_coar="http://purl.org/coar/resource_type/c_2fe3",
        langues=["fra"],
        description="desc",
        sujets=["satire"],
        licence="CC-BY-4.0",
        metadonnees={"dcterms_publisher": "Square"},
    )


# ---------------------------------------------------------------------------
# _cote_depuis_doi
# ---------------------------------------------------------------------------


def test_cote_depuis_doi() -> None:
    assert _cote_depuis_doi("10.34847/nkl.abcdef12") == "abcdef12"
    assert _cote_depuis_doi("10.34847/nkl.abcdef12.v2") == "abcdef12"  # version retirée
    assert _cote_depuis_doi("") is None


# ---------------------------------------------------------------------------
# rapatrier
# ---------------------------------------------------------------------------


def test_rapatrier_dry_run_ne_cree_rien(session: Session, fonds_hk: Fonds) -> None:
    r = rapatrier(session, _depot(), {}, fonds_id=fonds_hk.id, dry_run=True)
    assert r.dry_run is True
    assert r.cote == "abcdef12"  # dérivée du DOI
    assert r.item_id is None
    assert r.deja_existant is False
    assert session.scalar(select(func.count(Item.id))) == 0


def test_rapatrier_reel_cree_item_cache_et_lien(
    session: Session, fonds_hk: Fonds
) -> None:
    r = rapatrier(
        session, _depot(), {"identifier": _DOI}, fonds_id=fonds_hk.id, cree_par="Marie"
    )
    assert r.deja_existant is False and r.item_id is not None
    item = session.get(Item, r.item_id)
    assert item.cote == "abcdef12"
    assert item.titre == "Titre Nakala"
    assert item.doi_nakala == _DOI
    assert item.langue == "fra"
    assert item.type_coar == "http://purl.org/coar/resource_type/c_2fe3"
    assert item.metadonnees["createurs"] == ["Topor, Roland"]
    assert item.metadonnees["sujets"] == ["satire"]
    assert item.metadonnees["dcterms_publisher"] == "Square"
    # Cache + lien créés.
    assert session.scalar(select(func.count(RessourceExterne.id))) == 1
    assert session.scalar(select(func.count(LienExterneItem.id))) == 1


def test_rapatrier_deja_existant_ne_duplique_pas(
    session: Session, fonds_hk: Fonds
) -> None:
    rapatrier(session, _depot(), {}, fonds_id=fonds_hk.id)
    r2 = rapatrier(session, _depot(titre="Autre"), {}, fonds_id=fonds_hk.id)
    assert r2.deja_existant is True
    assert session.scalar(select(func.count(Item.id))) == 1  # pas de doublon


def test_rapatrier_item_preexistant_est_cache_et_lie(
    session: Session, fonds_hk: Fonds
) -> None:
    """Item créé manuellement avec le DOI (jamais rapatrié) : rapatrier
    ne recrée pas, mais cache + lie quand même (run réel)."""
    item = creer_item(
        session, FormulaireItem(cote="abcdef12", titre="Manuel", fonds_id=fonds_hk.id)
    )
    item.doi_nakala = _DOI
    session.commit()

    r = rapatrier(session, _depot(), {"identifier": _DOI}, fonds_id=fonds_hk.id)
    assert r.deja_existant is True and r.item_id == item.id
    assert session.scalar(select(func.count(Item.id))) == 1  # pas de doublon
    # Cache + lien créés malgré le déjà-existant.
    assert session.scalar(select(func.count(RessourceExterne.id))) == 1
    assert session.scalar(select(func.count(LienExterneItem.id))) == 1


def test_rapatrier_deja_existant_dry_run_n_ecrit_pas(
    session: Session, fonds_hk: Fonds
) -> None:
    item = creer_item(
        session, FormulaireItem(cote="abcdef12", titre="Manuel", fonds_id=fonds_hk.id)
    )
    item.doi_nakala = _DOI
    session.commit()
    r = rapatrier(session, _depot(), {}, fonds_id=fonds_hk.id, dry_run=True)
    assert r.deja_existant is True
    assert session.scalar(select(func.count(RessourceExterne.id))) == 0  # rien caché


def test_rapatrier_cote_inderivable_leve(session: Session, fonds_hk: Fonds) -> None:
    # DOI sans suffixe exploitable.
    with pytest.raises(RapatriementInvalide):
        rapatrier(session, _depot(identifiant="..."), {}, fonds_id=fonds_hk.id)


def test_rapatrier_cote_explicite(session: Session, fonds_hk: Fonds) -> None:
    r = rapatrier(session, _depot(), {}, fonds_id=fonds_hk.id, cote="PF-001")
    assert r.cote == "PF-001"
    assert session.get(Item, r.item_id).cote == "PF-001"


# ---------------------------------------------------------------------------
# rafraichir
# ---------------------------------------------------------------------------


def _item_lie(session: Session, fonds: Fonds, titre: str = "Ancien titre") -> Item:
    item = creer_item(
        session,
        FormulaireItem(cote="abcdef12", titre=titre, fonds_id=fonds.id),
    )
    item.doi_nakala = _DOI
    session.commit()
    return item


def test_rafraichir_sans_item_lie_leve(session: Session) -> None:
    with pytest.raises(RafraichissementImpossible):
        rafraichir(session, _depot(), {})


def test_rafraichir_dry_run_diff_sans_ecriture(
    session: Session, fonds_hk: Fonds
) -> None:
    _item_lie(session, fonds_hk, titre="Ancien titre")
    r = rafraichir(session, _depot(titre="Titre Nakala"), {})  # dry_run défaut True
    assert r.applique is False
    titres = {(d.champ, d.avant, d.apres) for d in r.diffs}
    assert ("titre", "Ancien titre", "Titre Nakala") in titres
    assert r.metadonnees_modifiees is True  # createurs/sujets ajoutés
    # Rien écrit : le titre en base est inchangé.
    item = session.scalar(select(Item).where(Item.doi_nakala == _DOI))
    assert item.titre == "Ancien titre"


def test_rafraichir_applique_overwrite_documentaire(
    session: Session, fonds_hk: Fonds
) -> None:
    item = _item_lie(session, fonds_hk, titre="Ancien titre")
    version_avant = item.version
    r = rafraichir(
        session, _depot(titre="Titre Nakala"), {}, modifie_par="Jean", dry_run=False
    )
    assert r.applique is True
    session.expire_all()
    item = session.scalar(select(Item).where(Item.doi_nakala == _DOI))
    assert item.titre == "Titre Nakala"  # overwrite appliqué
    assert item.description == "desc"
    assert item.metadonnees["createurs"] == ["Topor, Roland"]
    assert item.modifie_par == "Jean"
    assert item.version > version_avant  # version bumpée
    # cote / fonds préservés (champs ColleC-only).
    assert item.cote == "abcdef12"
    assert item.fonds_id == fonds_hk.id


def test_rafraichir_sans_changement_ne_applique_pas(
    session: Session, fonds_hk: Fonds
) -> None:
    # On crée un item déjà aligné sur le dépôt, puis on rafraîchit : pas
    # de diff documentaire → rien appliqué même hors dry-run. (Les
    # métadonnées diffèrent toujours ici, donc on teste juste le no-op
    # documentaire via un dépôt minimal sans méta.)
    depot_nu = DepotNakala(
        identifiant=_DOI, statut="published", titre="T", createurs=[],
        date="1900", type_coar="", langues=[], description="", sujets=[],
        licence=None,
    )
    item = creer_item(
        session, FormulaireItem(cote="abcdef12", titre="T", fonds_id=fonds_hk.id, date="1900")
    )
    item.doi_nakala = _DOI
    session.commit()
    version_avant = item.version
    r = rafraichir(session, depot_nu, {}, dry_run=False)
    assert r.diffs == []
    assert r.metadonnees_modifiees is False
    assert r.applique is False
    session.expire_all()
    assert session.scalar(
        select(Item.version).where(Item.doi_nakala == _DOI)
    ) == version_avant  # pas touché
