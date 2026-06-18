"""Validation de licence au pré-export Nakala (`verifier_pre_export`,
`valider_licence=True`) — backlog S6.

Signalement **non bloquant** d'une licence non reconnue par Nakala, pour
échouer tôt avec un message clair plutôt qu'un 422 distant. Garde
anti-faux-positif sur les licences non-SPDX acceptées par Nakala
(`etalab-2.0`). Items construits en mémoire (la fonction ne lit que
`cote`/`type_coar`/`langue`/`metadonnees`, aucun accès base)."""

from __future__ import annotations

from archives_tool.exporters.rapport import verifier_pre_export
from archives_tool.models import Item


def _item(licence: str | None = None, *, cle: str = "licence") -> Item:
    meta = {cle: licence} if licence is not None else {}
    return Item(cote="L", titre="T", metadonnees=meta)


def _licences_signalees(rapport) -> list[str]:
    return [v for champ, v in rapport.valeurs_non_mappees if champ == "licence"]


def test_licence_inconnue_signalee() -> None:
    r = verifier_pre_export(
        [_item("CC-BY-BIDON")], [], format="nakala_csv", valider_licence=True
    )
    assert _licences_signalees(r) == ["CC-BY-BIDON"]


def test_licence_spdx_valide_non_signalee() -> None:
    r = verifier_pre_export(
        [_item("CC-BY-4.0")], [], format="nakala_csv", valider_licence=True
    )
    assert _licences_signalees(r) == []


def test_licence_etalab_non_spdx_mais_acceptee_nakala_non_signalee() -> None:
    """Garde anti-faux-positif : `etalab-2.0` n'est PAS un code SPDX mais est
    accepté par Nakala (sondé S6) → ne doit JAMAIS être signalé."""
    r = verifier_pre_export(
        [_item("etalab-2.0")], [], format="nakala_csv", valider_licence=True
    )
    assert _licences_signalees(r) == []


def test_licence_lue_aussi_depuis_rights() -> None:
    r = verifier_pre_export(
        [_item("PAS-UNE-LICENCE", cle="rights")],
        [],
        format="nakala_csv",
        valider_licence=True,
    )
    assert _licences_signalees(r) == ["PAS-UNE-LICENCE"]


def test_licence_absente_non_signalee() -> None:
    """Sans licence saisie, le défaut (valide) s'applique côté exporter."""
    r = verifier_pre_export([_item()], [], format="nakala_csv", valider_licence=True)
    assert _licences_signalees(r) == []


def test_licence_casse_exacte() -> None:
    """Les codes SPDX sont sensibles à la casse (`CC-BY-4.0`, pas
    `cc-by-4.0`) — une casse erronée est signalée (Nakala la rejetterait)."""
    r = verifier_pre_export(
        [_item("cc-by-4.0")], [], format="nakala_csv", valider_licence=True
    )
    assert _licences_signalees(r) == ["cc-by-4.0"]


def test_licence_non_validee_sans_le_flag_dublin_core() -> None:
    """Dublin Core (valider_licence par défaut False) ne contraint pas la
    licence à SPDX → une licence libre n'est pas signalée."""
    r = verifier_pre_export([_item("licence maison")], [], format="dc_xml")
    assert _licences_signalees(r) == []


def test_licence_non_str_signalee() -> None:
    """Une licence en liste (cas import Nakala valeurs multiples) est émise
    verbatim par l'exporter → 422 ; on la signale (sa repr str)."""
    item = Item(cote="L", titre="T", metadonnees={"licence": ["CC-BY-4.0"]})
    r = verifier_pre_export([item], [], format="nakala_csv", valider_licence=True)
    assert _licences_signalees(r) == ["['CC-BY-4.0']"]


def test_licence_espaces_seuls_signalee() -> None:
    """Espaces seuls : truthy → l'exporter l'émet tel quel (pas de défaut) →
    422 ; signalé (pas de strip, on valide la valeur exacte)."""
    r = verifier_pre_export(
        [_item("   ")], [], format="nakala_csv", valider_licence=True
    )
    assert _licences_signalees(r) == ["   "]


def test_licence_avec_espaces_parasites_signalee() -> None:
    """Un code valide entouré d'espaces n'est PAS le code exact attendu par
    Nakala → signalé (le strip masquerait ce vrai problème)."""
    r = verifier_pre_export(
        [_item(" CC-BY-4.0 ")], [], format="nakala_csv", valider_licence=True
    )
    assert _licences_signalees(r) == [" CC-BY-4.0 "]
