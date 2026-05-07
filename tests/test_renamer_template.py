"""Tests du module renamer.template."""

from __future__ import annotations

import unicodedata

import pytest

from archives_tool.models import Collection, Fichier, Item
from archives_tool.renamer.template import EchecTemplate, evaluer_template


def _f(**kwargs) -> Fichier:
    base = dict(
        item_id=1,
        racine="s",
        chemin_relatif="dossier/01.png",
        nom_fichier="01.png",
        ordre=1,
        type_page="page",
    )
    base.update(kwargs)
    return Fichier(**base)


def _i(**kwargs) -> Item:
    base = dict(collection_id=1, cote="HK-1960-01", titre="Numéro un", annee=1960)
    base.update(kwargs)
    return Item(**base)


def test_template_basique() -> None:
    res = evaluer_template("{cote}-{ordre:02d}.{ext}", _f(), _i())
    assert res == "HK-1960-01-01.png"


def test_template_avec_sous_dossier() -> None:
    res = evaluer_template("{annee}/{cote}-{ordre:02d}.{ext}", _f(), _i(annee=1960))
    assert res == "1960/HK-1960-01-01.png"


def test_template_extension_normalisee_lowercase() -> None:
    res = evaluer_template("{cote}.{ext}", _f(nom_fichier="X.PNG"), _i())
    assert res == "HK-1960-01.png"


def test_template_ext_majuscule_disponible() -> None:
    res = evaluer_template("{cote}.{ext_majuscule}", _f(nom_fichier="x.tif"), _i())
    assert res == "HK-1960-01.TIF"


def test_template_nom_original_sans_extension() -> None:
    res = evaluer_template(
        "{nom_original}_renomme.{ext}", _f(nom_fichier="scan_42.JPG"), _i()
    )
    assert res == "scan_42_renomme.jpg"


def test_template_collection_disponible_si_passee() -> None:
    col = Collection(cote_collection="HK", titre="Hara-Kiri")
    res = evaluer_template("{cote_collection}/{cote}.{ext}", _f(), _i(), col)
    assert res == "HK/HK-1960-01.png"


def test_template_valeur_none_devient_chaine_vide() -> None:
    # `folio` est None dans la fixture par défaut.
    res = evaluer_template("p{folio}{cote}.{ext}", _f(), _i())
    assert res == "pHK-1960-01.png"


def test_template_variable_inconnue_leve_echec() -> None:
    with pytest.raises(EchecTemplate, match="inconnue"):
        evaluer_template("{xxx}.{ext}", _f(), _i())


def test_template_format_invalide_leve_echec() -> None:
    with pytest.raises(EchecTemplate):
        evaluer_template("{cote:%}.{ext}", _f(), _i())


def test_template_resultat_vide_rejete() -> None:
    with pytest.raises(EchecTemplate, match="vide"):
        evaluer_template("", _f(), _i())


def test_template_dotdot_rejete() -> None:
    # Échappement basique : un template ne peut pas faire sortir de la racine.
    with pytest.raises(EchecTemplate, match=r"\.\."):
        evaluer_template("../{cote}.{ext}", _f(), _i())


def test_template_resultat_nfc() -> None:
    # On force un titre NFD ; le résultat doit être en NFC.
    titre_nfd = unicodedata.normalize("NFD", "café")
    res = evaluer_template("{titre}-{cote}.{ext}", _f(), _i(titre=titre_nfd))
    assert res == unicodedata.normalize("NFC", res)
    assert "café" in res
