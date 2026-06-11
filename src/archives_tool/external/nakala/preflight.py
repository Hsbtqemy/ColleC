"""Cascade pré-dépôt inter-champs (P2/A3).

Portée de `plugins-madbot/madbot_nakala_submission/preflight.py`. Quand
`nkl:creator` ou `nkl:created` résout à `null` (anonyme / inconnu), on
applique une cascade de repli sur les `dcterms:*` compagnons et on
auto-promeut quand c'est possible :

- **Créateur** : `nkl:creator` null + `dcterms:creator` au format strict
  → promotion en `nkl:creator` (le `dcterms:creator` est conservé en
  parallèle). Sinon, exige au moins un `dcterms:creator` OU
  `dcterms:contributor` (traçabilité). Sinon lève.
- **Date** : `nkl:created` null + pas de `dcterms:created` → promotion d'un
  `dcterms:date` W3CDTF. Sinon lève.

Opère sur le `metas[]` wire-format produit par `depot_mapper.slugs_vers_metas`.
Renvoie `(metas mutée, avertissements)`. Lève `MetaInvalide` si insatisfiable.
"""

from __future__ import annotations

import re
from typing import Any

from archives_tool.external.nakala.depot_mapper import MetaInvalide, parse_creator

URI_NKL_CREATOR = "http://nakala.fr/terms#creator"
URI_NKL_CREATED = "http://nakala.fr/terms#created"
URI_DC_CREATOR = "http://purl.org/dc/terms/creator"
URI_DC_CONTRIBUTOR = "http://purl.org/dc/terms/contributor"
URI_DC_CREATED = "http://purl.org/dc/terms/created"
URI_DC_DATE = "http://purl.org/dc/terms/date"

_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

_NAMED_CREATOR_RE = re.compile(
    r"^[^\[,]+,[^\[,]+(?:\s\[\d{4}-\d{4}-\d{4}-\d{3}[\dX]\])?$"
)
_W3CDTF_RE = re.compile(
    r"^-?\d{4,}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2}))?)?)?$"
)


def _grouper_par_uri(metas: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    par_uri: dict[str, list[dict[str, Any]]] = {}
    for m in metas:
        par_uri.setdefault(m["propertyUri"], []).append(m)
    return par_uri


def _resout_a_null(metas: list[dict[str, Any]]) -> bool:
    if not metas:
        return True
    return all(m.get("value") is None for m in metas)


def _createur_promouvable(dc_createurs: list[dict[str, Any]]) -> str | None:
    for dc in dc_createurs:
        v = dc.get("value")
        if isinstance(v, str) and _NAMED_CREATOR_RE.match(v.strip()):
            return v.strip()
    return None


def _date_promouvable(dc_dates: list[dict[str, Any]]) -> str | None:
    for dd in dc_dates:
        v = dd.get("value")
        if isinstance(v, str) and _W3CDTF_RE.match(v.strip()):
            return v.strip()
    return None


def _cascade_createur(
    metas: list[dict[str, Any]],
    par_uri: dict[str, list[dict[str, Any]]],
    avertissements: list[str],
) -> list[dict[str, Any]]:
    if not _resout_a_null(par_uri.get(URI_NKL_CREATOR, [])):
        return metas

    dc_createurs = par_uri.get(URI_DC_CREATOR, [])
    dc_contributeurs = par_uri.get(URI_DC_CONTRIBUTOR, [])

    promu = _createur_promouvable(dc_createurs)
    if promu:
        metas = [m for m in metas if m["propertyUri"] != URI_NKL_CREATOR]
        metas.append({"propertyUri": URI_NKL_CREATOR, "value": parse_creator(promu)})
        avertissements.append(
            f"Auto-promotion : dcterms:creator « {promu} » → nkl:creator "
            f"(nkl:creator était null/anonyme). Le dcterms:creator est conservé."
        )
        return metas

    if not dc_createurs and not dc_contributeurs:
        raise MetaInvalide(
            "nkl:creator est null/anonyme et aucun dcterms:creator ni "
            "dcterms:contributor n'est fourni — au moins un auteur ou "
            "contributeur est requis pour la traçabilité."
        )

    if URI_NKL_CREATOR not in par_uri:
        metas.append({"propertyUri": URI_NKL_CREATOR, "value": None})
    return metas


def _cascade_created(
    metas: list[dict[str, Any]],
    par_uri: dict[str, list[dict[str, Any]]],
    avertissements: list[str],
) -> list[dict[str, Any]]:
    if not _resout_a_null(par_uri.get(URI_NKL_CREATED, [])):
        return metas

    dc_createds = par_uri.get(URI_DC_CREATED, [])
    dc_dates = par_uri.get(URI_DC_DATE, [])

    if dc_createds:
        if URI_NKL_CREATED not in par_uri:
            metas.append({"propertyUri": URI_NKL_CREATED, "value": None})
        return metas

    promu = _date_promouvable(dc_dates)
    if promu:
        metas = [m for m in metas if m["propertyUri"] != URI_NKL_CREATED]
        metas.append(
            {"propertyUri": URI_NKL_CREATED, "value": promu, "typeUri": _XSD_STRING}
        )
        avertissements.append(
            f"Auto-promotion : dcterms:date « {promu} » → nkl:created "
            f"(nkl:created était null, aucun dcterms:created). Le dcterms:date "
            f"est conservé."
        )
        return metas

    if dc_dates:
        raise MetaInvalide(
            "nkl:created est null, aucun dcterms:created, et aucun dcterms:date "
            "au format W3C-DTF."
        )
    raise MetaInvalide(
        "nkl:created est null et aucun dcterms:created ni dcterms:date — une "
        "indication temporelle est requise."
    )


def preflight_appliquer(
    metas: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Applique la cascade créateur/date.

    Renvoie `(metas éventuellement mutée, avertissements FR)`. Lève
    `MetaInvalide` si la cascade ne peut être satisfaite."""
    avertissements: list[str] = []
    par_uri = _grouper_par_uri(metas)
    metas = _cascade_createur(metas, par_uri, avertissements)
    par_uri = _grouper_par_uri(metas)  # rafraîchir si muté
    metas = _cascade_created(metas, par_uri, avertissements)
    return metas, avertissements
