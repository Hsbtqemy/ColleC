"""Tests du service Item (V0.9.0-alpha.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
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
    ItemIntrouvable,
    ItemInvalide,
    OperationItemInterdite,
    annee_depuis_date_edtf,
    collections_de_item,
    creer_item,
    formulaire_depuis_item,
    lire_item,
    lire_item_par_cote,
    lister_items_collection,
    lister_items_fonds,
    modifier_item,
    supprimer_item,
)
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
)


def _form(fonds: Fonds, cote: str = "HK-001", titre: str = "Item HK") -> FormulaireItem:
    return FormulaireItem(cote=cote, titre=titre, fonds_id=fonds.id)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_creer_cote_vide_rejete(session: Session, fonds_hk: Fonds) -> None:
    with pytest.raises(ItemInvalide) as exc:
        creer_item(session, FormulaireItem(cote="", titre="X", fonds_id=fonds_hk.id))
    assert "cote" in exc.value.erreurs


def test_creer_titre_vide_rejete(session: Session, fonds_hk: Fonds) -> None:
    with pytest.raises(ItemInvalide) as exc:
        creer_item(session, FormulaireItem(cote="X", titre="", fonds_id=fonds_hk.id))
    assert "titre" in exc.value.erreurs


def test_creer_cote_caracteres_speciaux_rejete(
    session: Session, fonds_hk: Fonds
) -> None:
    with pytest.raises(ItemInvalide) as exc:
        creer_item(
            session,
            FormulaireItem(cote="ma cote", titre="X", fonds_id=fonds_hk.id),
        )
    assert "cote" in exc.value.erreurs


def test_creer_fonds_id_zero_rejete(session: Session) -> None:
    with pytest.raises(ItemInvalide) as exc:
        creer_item(session, FormulaireItem(cote="X", titre="X", fonds_id=0))
    assert "fonds_id" in exc.value.erreurs


def test_creer_fonds_inexistant_rejete(session: Session) -> None:
    with pytest.raises(ItemInvalide) as exc:
        creer_item(session, FormulaireItem(cote="X", titre="X", fonds_id=99999))
    assert "fonds_id" in exc.value.erreurs


def test_creer_annee_invalide_rejete(session: Session, fonds_hk: Fonds) -> None:
    with pytest.raises(ValidationError):
        FormulaireItem(cote="X", titre="X", fonds_id=fonds_hk.id, annee=-100)
    with pytest.raises(ValidationError):
        FormulaireItem(cote="X", titre="X", fonds_id=fonds_hk.id, annee=4000)


def test_creer_etat_inconnu_rejete(session: Session, fonds_hk: Fonds) -> None:
    with pytest.raises(ValidationError):
        FormulaireItem(
            cote="X", titre="X", fonds_id=fonds_hk.id, etat_catalogage="bidon"
        )


# ---------------------------------------------------------------------------
# Création + invariant 6 (auto-rattachement à la miroir)
# ---------------------------------------------------------------------------


def test_creer_item_minimal(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(session, _form(fonds_hk))
    assert item.id is not None
    assert item.cote == "HK-001"
    assert item.fonds_id == fonds_hk.id
    assert item.etat_catalogage == EtatCatalogage.BROUILLON.value


def test_creer_item_ajoute_dans_miroir(session: Session, fonds_hk: Fonds) -> None:
    """Invariant 6 : l'item est automatiquement dans la miroir."""
    item = creer_item(session, _form(fonds_hk))
    miroir = lire_collection_par_cote(session, "HK", fonds_id=fonds_hk.id)
    assert miroir in item.collections


def test_creer_item_strip_chaines(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(
        session,
        FormulaireItem(
            cote="  TRIM  ",
            titre="  Titre  ",
            fonds_id=fonds_hk.id,
            description="  d  ",
        ),
    )
    assert item.cote == "TRIM"
    assert item.titre == "Titre"
    assert item.description == "d"


def test_creer_item_optionnels_vides_a_none(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(session, _form(fonds_hk))
    assert item.description is None
    assert item.type_coar is None
    assert item.langue is None


def test_creer_item_cote_doublon_meme_fonds_rejete(
    session: Session, fonds_hk: Fonds
) -> None:
    creer_item(session, _form(fonds_hk, cote="HK-001"))
    with pytest.raises(ItemInvalide) as exc:
        creer_item(session, _form(fonds_hk, cote="HK-001"))
    assert "cote" in exc.value.erreurs


def test_creer_item_cote_se_repete_entre_fonds(session: Session) -> None:
    fonds_a = creer_fonds(session, FormulaireFonds(cote="A", titre="A"))
    fonds_b = creer_fonds(session, FormulaireFonds(cote="B", titre="B"))
    creer_item(session, FormulaireItem(cote="001", titre="A1", fonds_id=fonds_a.id))
    creer_item(session, FormulaireItem(cote="001", titre="B1", fonds_id=fonds_b.id))
    nb = session.scalar(select(func.count(Item.id)).where(Item.cote == "001"))
    assert nb == 2


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------


def test_lire_item_inexistant(session: Session) -> None:
    with pytest.raises(ItemIntrouvable):
        lire_item(session, 99999)


def test_lire_item_par_cote(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(session, _form(fonds_hk))
    relu = lire_item_par_cote(session, "HK-001", fonds_id=fonds_hk.id)
    assert relu.id == item.id


def test_lire_item_par_cote_inexistant(session: Session, fonds_hk: Fonds) -> None:
    with pytest.raises(ItemIntrouvable):
        lire_item_par_cote(session, "X", fonds_id=fonds_hk.id)


def test_collections_de_item(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(session, _form(fonds_hk))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)
    collections = collections_de_item(session, item.id)
    cotes = {c.cote for c in collections}
    assert cotes == {"HK", "OEUV"}  # miroir + libre


# ---------------------------------------------------------------------------
# Listage
# ---------------------------------------------------------------------------


def test_lister_items_fonds(session: Session, fonds_hk: Fonds) -> None:
    creer_item(session, _form(fonds_hk, cote="HK-002"))
    creer_item(session, _form(fonds_hk, cote="HK-001"))
    listing = lister_items_fonds(session, fonds_hk.id)
    assert listing.total == 2
    # Tri par défaut = cote asc.
    assert [i.cote for i in listing.items] == ["HK-001", "HK-002"]


def test_lister_items_fonds_filtre_etat(session: Session, fonds_hk: Fonds) -> None:
    creer_item(
        session,
        FormulaireItem(
            cote="HK-001",
            titre="A",
            fonds_id=fonds_hk.id,
            etat_catalogage=EtatCatalogage.VALIDE.value,
        ),
    )
    creer_item(
        session,
        FormulaireItem(cote="HK-002", titre="B", fonds_id=fonds_hk.id),
    )
    listing = lister_items_fonds(session, fonds_hk.id, etat=EtatCatalogage.VALIDE.value)
    assert listing.total == 1
    assert listing.items[0].cote == "HK-001"


def test_lister_items_fonds_pagination(session: Session, fonds_hk: Fonds) -> None:
    for i in range(1, 6):
        creer_item(session, _form(fonds_hk, cote=f"HK-{i:03d}"))
    page1 = lister_items_fonds(session, fonds_hk.id, par_page=2, page=1)
    page2 = lister_items_fonds(session, fonds_hk.id, par_page=2, page=2)
    assert page1.total == 5
    assert len(page1.items) == 2
    assert len(page2.items) == 2
    assert page1.items[0].cote == "HK-001"
    assert page2.items[0].cote == "HK-003"


def test_lister_items_fonds_tri_desc(session: Session, fonds_hk: Fonds) -> None:
    creer_item(session, _form(fonds_hk, cote="HK-001"))
    creer_item(session, _form(fonds_hk, cote="HK-002"))
    listing = lister_items_fonds(session, fonds_hk.id, tri="cote", ordre="desc")
    assert [i.cote for i in listing.items] == ["HK-002", "HK-001"]


def test_mapping_tri_items_couvre_exactement_tris_items() -> None:
    """Garde-fou anti-dérive : les clés du mapping SQL de tri doivent être
    exactement la whitelist publique `TRIS_ITEMS` (qui pilote l'affordance
    UI). Sans ça, une colonne peut être annoncée triable mais retomber
    silencieusement sur le tri par défaut (le bug d'origine), ou l'inverse."""
    from archives_tool.api.services.items import _MAPPING_TRI_ITEMS
    from archives_tool.api.services.tri import TRIS_ITEMS

    assert set(_MAPPING_TRI_ITEMS) == set(TRIS_ITEMS)


def test_lister_items_fonds_tri_honore_chaque_colonne_triable(
    session: Session, fonds_hk: Fonds
) -> None:
    """Chaque clé de `TRIS_ITEMS` est réellement honorée (tri effectif =
    clé demandée) ; une clé non triable retombe sur le défaut `cote`."""
    from archives_tool.api.services.tri import TRIS_ITEMS

    creer_item(session, _form(fonds_hk, cote="HK-001"))
    for cle in TRIS_ITEMS:
        listing = lister_items_fonds(session, fonds_hk.id, tri=cle, ordre="asc")
        assert listing.tri == cle, f"colonne {cle!r} non honorée par le tri"
    # Colonne inconnue / non triable (métadonnée perso, nombre de fichiers) :
    # retombe silencieusement sur le défaut sans erreur.
    bidon = lister_items_fonds(session, fonds_hk.id, tri="auteur", ordre="asc")
    assert bidon.tri == "cote"


def test_lister_items_collection(session: Session, fonds_hk: Fonds) -> None:
    item1 = creer_item(session, _form(fonds_hk, cote="HK-001"))
    creer_item(session, _form(fonds_hk, cote="HK-002"))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item1.id, libre.id)

    listing = lister_items_collection(session, libre.id)
    assert listing.total == 1
    assert listing.items[0].cote == "HK-001"

    miroir = lire_collection_par_cote(session, "HK", fonds_id=fonds_hk.id)
    listing_miroir = lister_items_collection(session, miroir.id)
    assert listing_miroir.total == 2  # item1 + item2 (auto-miroir)


def test_lister_items_compte_collections_par_item(
    session: Session, fonds_hk: Fonds
) -> None:
    item = creer_item(session, _form(fonds_hk))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)
    listing = lister_items_fonds(session, fonds_hk.id)
    assert listing.items[0].nb_collections == 2  # miroir + libre


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------


def test_modifier_item_change_titre(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(session, _form(fonds_hk))
    nouv = modifier_item(
        session,
        item.id,
        FormulaireItem(cote="HK-001", titre="Nouveau", fonds_id=fonds_hk.id),
    )
    assert nouv.titre == "Nouveau"


def test_modifier_item_changer_fonds_rejete(session: Session, fonds_hk: Fonds) -> None:
    fonds_b = creer_fonds(session, FormulaireFonds(cote="B", titre="B"))
    item = creer_item(session, _form(fonds_hk))
    with pytest.raises(OperationItemInterdite):
        modifier_item(
            session,
            item.id,
            FormulaireItem(cote="HK-001", titre="X", fonds_id=fonds_b.id),
        )


def test_modifier_item_cote_conflit(session: Session, fonds_hk: Fonds) -> None:
    creer_item(session, _form(fonds_hk, cote="HK-001"))
    item_b = creer_item(session, _form(fonds_hk, cote="HK-002"))
    with pytest.raises(ItemInvalide):
        modifier_item(
            session,
            item_b.id,
            FormulaireItem(cote="HK-001", titre="X", fonds_id=fonds_hk.id),
        )


def test_modifier_item_inexistant(session: Session, fonds_hk: Fonds) -> None:
    with pytest.raises(ItemIntrouvable):
        modifier_item(
            session,
            99999,
            FormulaireItem(cote="X", titre="X", fonds_id=fonds_hk.id),
        )


# ---------------------------------------------------------------------------
# Dérivation automatique de l'année depuis la date EDTF (V0.9.8)
# ---------------------------------------------------------------------------


def test_annee_helper_extrait_annee_edtf() -> None:
    """Le helper isolé couvre les cas EDTF tolérants."""
    assert annee_depuis_date_edtf("1974") == 1974
    assert annee_depuis_date_edtf("1974-03") == 1974
    assert annee_depuis_date_edtf("1974-03-11") == 1974
    assert annee_depuis_date_edtf("  1974-03  ") == 1974  # strip
    # Imprécis / vide → None (l'incertitude est préservée).
    assert annee_depuis_date_edtf(None) is None
    assert annee_depuis_date_edtf("") is None
    assert annee_depuis_date_edtf("vers 1974") is None
    assert annee_depuis_date_edtf("19XX") is None
    assert annee_depuis_date_edtf("s.d.") is None
    # Hors plage plausible → None : aligné sur le validateur
    # `_annee_borne`, sinon la valeur dérivée casse le round-trip
    # `formulaire_depuis_item` (BCE négatif, année aberrante > 3000).
    assert annee_depuis_date_edtf("-0044") is None  # BCE hors plage
    assert annee_depuis_date_edtf("9999") is None  # > 3000


def test_annee_derivee_jamais_hors_borne_validateur(
    session: Session, fonds_hk: Fonds
) -> None:
    """Régression : une date BCE/aberrante ne doit pas écrire une annee
    que le validateur rejette — sinon `formulaire_depuis_item` plante
    au prochain chargement. La date garde son texte, annee reste None."""
    item = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="X", fonds_id=fonds_hk.id, date="-0044"),
    )
    assert item.date == "-0044"  # texte préservé
    assert item.annee is None  # index non pollué
    # Le round-trip ne lève pas.
    formulaire = formulaire_depuis_item(item)
    assert formulaire.annee is None


def test_creer_item_annee_derivee_de_date(session: Session, fonds_hk: Fonds) -> None:
    """Date parsable → année dérivée à la création, sans saisie."""
    item = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="X", fonds_id=fonds_hk.id, date="1974-03"),
    )
    assert item.annee == 1974


def test_modifier_item_date_fait_autorite_sur_annee(
    session: Session, fonds_hk: Fonds
) -> None:
    """Branche 1 : date parsable → l'année dérivée écrase l'annee fournie."""
    item = creer_item(session, _form(fonds_hk))
    nouv = modifier_item(
        session,
        item.id,
        FormulaireItem(
            cote="HK-001",
            titre="X",
            fonds_id=fonds_hk.id,
            date="1969-09",
            annee=1900,  # contredit la date — la date gagne
        ),
    )
    assert nouv.annee == 1969


def test_modifier_item_date_imprecise_utilise_annee_fournie(
    session: Session, fonds_hk: Fonds
) -> None:
    """Branche 2 : date non parsable + annee fournie (CLI/API/import) → use it."""
    item = creer_item(session, _form(fonds_hk))
    nouv = modifier_item(
        session,
        item.id,
        FormulaireItem(
            cote="HK-001",
            titre="X",
            fonds_id=fonds_hk.id,
            date="vers 1960",
            annee=1960,
        ),
    )
    assert nouv.annee == 1960


def test_modifier_item_date_imprecise_sans_annee_preserve_existant(
    session: Session, fonds_hk: Fonds
) -> None:
    """Branche 3 : date non parsable + pas d'annee → conserve l'existant.

    Couvre les imports legacy où seule `annee` était peuplée : une
    modif ultérieure sur une date incertaine ne doit pas l'effacer.
    """
    item = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="X", fonds_id=fonds_hk.id, date="1974"),
    )
    assert item.annee == 1974
    nouv = modifier_item(
        session,
        item.id,
        FormulaireItem(
            cote="HK-001",
            titre="X",
            fonds_id=fonds_hk.id,
            date="vers 1980",
            annee=None,
        ),
    )
    assert nouv.annee == 1974  # préservé, pas effacé


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------


def test_supprimer_item(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(session, _form(fonds_hk))
    iid = item.id
    supprimer_item(session, iid)
    assert session.get(Item, iid) is None


def test_supprimer_item_cascade_liaisons(session: Session, fonds_hk: Fonds) -> None:
    """Liaisons supprimées en cascade ; collections elles-mêmes restent."""
    item = creer_item(session, _form(fonds_hk))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)
    iid, libre_id = item.id, libre.id

    supprimer_item(session, iid)

    nb_liaisons = session.scalar(
        select(func.count())
        .select_from(ItemCollection)
        .where(ItemCollection.item_id == iid)
    )
    assert nb_liaisons == 0
    assert session.get(Collection, libre_id) is not None


def test_supprimer_item_cascade_fichiers(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(session, _form(fonds_hk))
    session.add(
        Fichier(
            item_id=item.id,
            racine="scans",
            chemin_relatif="HK/HK-001-001.tif",
            nom_fichier="HK-001-001.tif",
            ordre=1,
        )
    )
    session.commit()
    iid = item.id

    supprimer_item(session, iid)

    nb_fichiers = session.scalar(
        select(func.count(Fichier.id)).where(Fichier.item_id == iid)
    )
    assert nb_fichiers == 0


def test_supprimer_item_inexistant(session: Session) -> None:
    with pytest.raises(ItemIntrouvable):
        supprimer_item(session, 99999)


# ---------------------------------------------------------------------------
# Multi-appartenance
# ---------------------------------------------------------------------------


def test_item_dans_plusieurs_collections(session: Session, fonds_hk: Fonds) -> None:
    item = creer_item(session, _form(fonds_hk))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)
    collections = collections_de_item(session, item.id)
    assert len(collections) == 2


def test_retirer_item_de_miroir_garde_dans_libre(
    session: Session, fonds_hk: Fonds
) -> None:
    item = creer_item(session, _form(fonds_hk))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)
    miroir = lire_collection_par_cote(session, "HK", fonds_id=fonds_hk.id)

    retirer_item_de_collection(session, item.id, miroir.id)

    collections = collections_de_item(session, item.id)
    cotes = {c.cote for c in collections}
    assert cotes == {"OEUV"}


def test_retirer_item_de_toutes_collections_garde_dans_fonds(
    session: Session, fonds_hk: Fonds
) -> None:
    """Les collections sont une projection ; retirer un item de toutes
    ses collections ne le supprime pas du fonds."""
    item = creer_item(session, _form(fonds_hk))
    miroir = lire_collection_par_cote(session, "HK", fonds_id=fonds_hk.id)
    retirer_item_de_collection(session, item.id, miroir.id)
    assert session.get(Item, item.id) is not None
    assert collections_de_item(session, item.id) == []


def test_supprimer_libre_avec_item_garde_item_dans_miroir(
    session: Session, fonds_hk: Fonds
) -> None:
    item = creer_item(session, _form(fonds_hk))
    libre = creer_collection_libre(
        session,
        FormulaireCollection(cote="OEUV", titre="Œ", fonds_id=fonds_hk.id),
    )
    ajouter_item_a_collection(session, item.id, libre.id)

    supprimer_collection_libre(session, libre.id)

    collections = collections_de_item(session, item.id)
    assert len(collections) == 1
    assert collections[0].cote == "HK"  # miroir


# ---------------------------------------------------------------------------
# Cascade depuis Fonds (cross-services)
# ---------------------------------------------------------------------------


def test_supprimer_fonds_supprime_items_et_libere_transversales(
    session: Session, fonds_hk: Fonds
) -> None:
    """Cascade combinée : suppression du fonds → items disparaissent
    (FK CASCADE) → liaisons N-N disparaissent aussi → collection
    transversale survit mais perd ses items issus du fonds."""
    item = creer_item(session, _form(fonds_hk))
    transv = creer_collection_libre(
        session, FormulaireCollection(cote="TRANSV", titre="T")
    )
    ajouter_item_a_collection(session, item.id, transv.id)
    iid, transv_id, fonds_id = item.id, transv.id, fonds_hk.id

    supprimer_fonds(session, fonds_id)

    assert session.get(Item, iid) is None
    transv_relue = session.get(Collection, transv_id)
    assert transv_relue is not None
    assert transv_relue.fonds_id is None  # déjà transversale, reste transversale
    nb_liaisons = session.scalar(
        select(func.count())
        .select_from(ItemCollection)
        .where(ItemCollection.collection_id == transv_id)
    )
    assert nb_liaisons == 0
