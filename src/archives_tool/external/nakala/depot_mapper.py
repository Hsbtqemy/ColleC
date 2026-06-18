"""Aplatissement valeurs slug → `metas[]` Nakala (P2/A2).

Carte de vérité d'écriture, portée de
`plugins-madbot/madbot_nakala_submission/mapper.py` (`SLUG_TO_NAKALA`,
57 champs). Découplée de madbot : prend un **dict slug → valeur** au lieu
des DTO `MetadataObject`, et lève `MetaInvalide` (local) au lieu de
`PluginSubmissionError`.

Chaque slug → un ou plusieurs `{propertyUri, value, lang?, typeUri?}`.
Traitements : multilingue `{value, lang}`, listes de chaînes, dates W3CDTF,
créateur structuré `"Nom, Prénom [ORCID]"`, spatial/temporal en DCSV,
sentinels anonyme/inconnu → `null`. `nkl_creator`/`nkl_created` émettent
toujours au moins une meta (même `null`) — convention ColleC pour alimenter
la cascade `preflight` ; Nakala n'exige que `nkl:title`+`nkl:type`.
"""

from __future__ import annotations

import re
from typing import Any


class MetaInvalide(ValueError):
    """Valeur de métadonnée non conforme à la forme attendue par Nakala."""


# slug → propertyUri Nakala + typeUri (indice XSD pour le rendu Nakala).
SLUG_TO_NAKALA: dict[str, dict[str, str]] = {
    "nkl_type": {
        "propertyUri": "http://nakala.fr/terms#type",
        "typeUri": "http://www.w3.org/2001/XMLSchema#anyURI",
    },
    "nkl_title": {
        "propertyUri": "http://nakala.fr/terms#title",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "nkl_creator": {
        "propertyUri": "http://nakala.fr/terms#creator",
        # Pas de typeUri — valeur = objet structuré, Nakala gère.
    },
    "nkl_created": {
        "propertyUri": "http://nakala.fr/terms#created",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "nkl_license": {
        "propertyUri": "http://nakala.fr/terms#license",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_description": {
        "propertyUri": "http://purl.org/dc/terms/description",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_subject": {
        "propertyUri": "http://purl.org/dc/terms/subject",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_language": {
        "propertyUri": "http://purl.org/dc/terms/language",
        "typeUri": "http://purl.org/dc/terms/RFC5646",
    },
    "dcterms_contributor": {
        "propertyUri": "http://purl.org/dc/terms/contributor",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_temporal": {
        "propertyUri": "http://purl.org/dc/terms/temporal",
        # typeUri posé par item (W3CDTF pour str, Period pour objet).
    },
    "dcterms_spatial": {
        "propertyUri": "http://purl.org/dc/terms/spatial",
        # typeUri posé par item (Point ou Box).
    },
    "dcterms_coverage": {
        "propertyUri": "http://purl.org/dc/terms/coverage",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_title": {
        "propertyUri": "http://purl.org/dc/terms/title",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_creator": {
        "propertyUri": "http://purl.org/dc/terms/creator",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_created": {
        "propertyUri": "http://purl.org/dc/terms/created",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_license": {
        "propertyUri": "http://purl.org/dc/terms/license",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
    "dcterms_type": {
        "propertyUri": "http://purl.org/dc/terms/type",
        "typeUri": "http://www.w3.org/2001/XMLSchema#string",
    },
}

# 38 champs DC qualifiés optionnels (4 catégories de forme).
_CAT_A_MULTILINGUE = (
    ("dcterms_abstract", "http://purl.org/dc/terms/abstract"),
    ("dcterms_accessRights", "http://purl.org/dc/terms/accessRights"),
    ("dcterms_alternative", "http://purl.org/dc/terms/alternative"),
    ("dcterms_audience", "http://purl.org/dc/terms/audience"),
    ("dcterms_bibliographicCitation", "http://purl.org/dc/terms/bibliographicCitation"),
    ("dcterms_educationLevel", "http://purl.org/dc/terms/educationLevel"),
    ("dcterms_instructionalMethod", "http://purl.org/dc/terms/instructionalMethod"),
    ("dcterms_mediator", "http://purl.org/dc/terms/mediator"),
    ("dcterms_medium", "http://purl.org/dc/terms/medium"),
    ("dcterms_provenance", "http://purl.org/dc/terms/provenance"),
    ("dcterms_publisher", "http://purl.org/dc/terms/publisher"),
    ("dcterms_rights", "http://purl.org/dc/terms/rights"),
    ("dcterms_rightsHolder", "http://purl.org/dc/terms/rightsHolder"),
    ("dcterms_source", "http://purl.org/dc/terms/source"),
    ("dcterms_tableOfContents", "http://purl.org/dc/terms/tableOfContents"),
)
_CAT_B_CHAINES = (
    ("dcterms_identifier", "http://purl.org/dc/terms/identifier"),
    ("dcterms_format", "http://purl.org/dc/terms/format"),
    ("dcterms_extent", "http://purl.org/dc/terms/extent"),
)
_CAT_C_RELATIONS = (
    ("dcterms_conformsTo", "http://purl.org/dc/terms/conformsTo"),
    ("dcterms_hasFormat", "http://purl.org/dc/terms/hasFormat"),
    ("dcterms_hasPart", "http://purl.org/dc/terms/hasPart"),
    ("dcterms_hasVersion", "http://purl.org/dc/terms/hasVersion"),
    ("dcterms_isFormatOf", "http://purl.org/dc/terms/isFormatOf"),
    ("dcterms_isPartOf", "http://purl.org/dc/terms/isPartOf"),
    ("dcterms_isReferencedBy", "http://purl.org/dc/terms/isReferencedBy"),
    ("dcterms_isReplacedBy", "http://purl.org/dc/terms/isReplacedBy"),
    ("dcterms_isRequiredBy", "http://purl.org/dc/terms/isRequiredBy"),
    ("dcterms_isVersionOf", "http://purl.org/dc/terms/isVersionOf"),
    ("dcterms_references", "http://purl.org/dc/terms/references"),
    ("dcterms_replaces", "http://purl.org/dc/terms/replaces"),
    ("dcterms_requires", "http://purl.org/dc/terms/requires"),
    ("dcterms_relation", "http://purl.org/dc/terms/relation"),
)
_CAT_D_DATES = (
    ("dcterms_date", "http://purl.org/dc/terms/date"),
    ("dcterms_issued", "http://purl.org/dc/terms/issued"),
    ("dcterms_modified", "http://purl.org/dc/terms/modified"),
    ("dcterms_available", "http://purl.org/dc/terms/available"),
    ("dcterms_dateAccepted", "http://purl.org/dc/terms/dateAccepted"),
    ("dcterms_dateCopyrighted", "http://purl.org/dc/terms/dateCopyrighted"),
    ("dcterms_dateSubmitted", "http://purl.org/dc/terms/dateSubmitted"),
    ("dcterms_valid", "http://purl.org/dc/terms/valid"),
)

_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
_W3CDTF = "http://purl.org/dc/terms/W3CDTF"


def _enregistrer_v03() -> None:
    for slug, uri in _CAT_A_MULTILINGUE + _CAT_B_CHAINES + _CAT_C_RELATIONS:
        SLUG_TO_NAKALA[slug] = {"propertyUri": uri, "typeUri": _XSD_STRING}
    for slug, uri in _CAT_D_DATES:
        SLUG_TO_NAKALA[slug] = {"propertyUri": uri, "typeUri": _W3CDTF}


_enregistrer_v03()

MULTILINGUE_SLUGS = (
    "nkl_title",
    "dcterms_description",
    "dcterms_subject",
    "dcterms_coverage",
    "dcterms_title",
) + tuple(slug for slug, _ in _CAT_A_MULTILINGUE)
LISTE_CHAINES_SLUGS = ("nkl_creator", "dcterms_language", "dcterms_contributor")
TABLEAU_CHAINES_SLUGS = (
    tuple(slug for slug, _ in _CAT_B_CHAINES)
    + tuple(slug for slug, _ in _CAT_C_RELATIONS)
    + tuple(slug for slug, _ in _CAT_D_DATES)
    + ("dcterms_creator", "dcterms_created", "dcterms_license", "dcterms_type")
)
SCALAIRE_SLUGS = ("nkl_type", "nkl_created", "nkl_license")
STRUCTURE_SLUGS = ("dcterms_temporal", "dcterms_spatial")

PERIOD_TYPE_URI = "http://purl.org/dc/terms/Period"
W3CDTF_TYPE_URI = "http://purl.org/dc/terms/W3CDTF"
POINT_TYPE_URI = "http://purl.org/dc/terms/Point"
BOX_TYPE_URI = "http://purl.org/dc/terms/Box"

_POINT_KEYS = ("east", "north", "elevation", "name")
_BOX_KEYS = (
    "northlimit",
    "southlimit",
    "eastlimit",
    "westlimit",
    "uplimit",
    "downlimit",
    "units",
    "zunits",
    "projection",
    "name",
)
_PERIOD_KEYS = ("start", "end", "name")

# "Nom, Prénom [ORCID]" — ORCID optionnel.
_CREATOR_RE = re.compile(
    r"""
    ^
    (?P<surname>[^\[,]+?)
    \s*,\s*
    (?P<givenname>[^\[,]+?)
    (?:\s*\[(?P<orcid>\d{4}-\d{4}-\d{4}-\d{3}[\dX])\])?
    \s*$
    """,
    re.VERBOSE,
)

_CREATOR_ANONYME = frozenset(("[s.n.]", "anonyme"))
_CREATED_INCONNU = frozenset(("[s.d.]", "inconnue"))


def parse_creator(brut: str | None) -> dict[str, str] | None:
    """`"Nom, Prénom [ORCID]"` → objet structuré, ou `None` si anonyme
    (`None` / `"[s.n.]"` / `"anonyme"`). Lève `MetaInvalide` sinon."""
    if brut is None:
        return None
    brut = brut.strip()
    if brut in _CREATOR_ANONYME:
        return None
    match = _CREATOR_RE.match(brut)
    if not match:
        raise MetaInvalide(
            f"créateur {brut!r} ne correspond pas à "
            f"'Nom, Prénom [ORCID]' (ou '[s.n.]'/'anonyme'/null)"
        )
    out: dict[str, str] = {
        "surname": match.group("surname").strip(),
        "givenname": match.group("givenname").strip(),
    }
    if match.group("orcid"):
        out["orcid"] = match.group("orcid")
    return out


def parse_created(brut: str | None) -> str | None:
    """Date de création → forme Nakala. `None`/`"[s.d.]"`/`"inconnue"` → None ;
    sinon la chaîne telle quelle (W3CDTF déjà validé en amont)."""
    if brut is None:
        return None
    brut = brut.strip()
    if brut in _CREATED_INCONNU:
        return None
    return brut


def _meta(
    slug: str, value: Any, lang: str | None = None, type_uri_override: str | None = None
) -> dict[str, Any]:
    spec = SLUG_TO_NAKALA[slug]
    out: dict[str, Any] = {"propertyUri": spec["propertyUri"], "value": value}
    if type_uri_override is not None:
        out["typeUri"] = type_uri_override
    elif "typeUri" in spec:
        out["typeUri"] = spec["typeUri"]
    if lang is not None:
        out["lang"] = lang
    return out


def _vers_dcsv(obj: dict[str, Any], ordre_cles: tuple[str, ...]) -> str:
    parts: list[str] = []
    for cle in ordre_cles:
        if cle not in obj:
            continue
        valeur = obj[cle]
        if valeur is None or valeur == "":
            continue
        parts.append(f"{cle}={valeur}")
    return "; ".join(parts)


def _entree_temporal(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return _meta("dcterms_temporal", item, type_uri_override=W3CDTF_TYPE_URI)
    if isinstance(item, dict):
        return _meta(
            "dcterms_temporal",
            _vers_dcsv(item, _PERIOD_KEYS),
            lang=item.get("lang"),
            type_uri_override=PERIOD_TYPE_URI,
        )
    raise MetaInvalide(
        f"dcterms_temporal : chaque item doit être chaîne ou objet, reçu "
        f"{type(item).__name__}"
    )


def _entree_spatial(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise MetaInvalide(
            f"dcterms_spatial : chaque item doit être un objet, reçu "
            f"{type(item).__name__}"
        )
    kind = item.get("kind")
    if kind == "Point":
        return _meta(
            "dcterms_spatial",
            _vers_dcsv(item, _POINT_KEYS),
            lang=item.get("lang"),
            type_uri_override=POINT_TYPE_URI,
        )
    if kind == "Box":
        return _meta(
            "dcterms_spatial",
            _vers_dcsv(item, _BOX_KEYS),
            lang=item.get("lang"),
            type_uri_override=BOX_TYPE_URI,
        )
    raise MetaInvalide(
        f"dcterms_spatial : 'kind' doit être 'Point' ou 'Box', reçu {kind!r}"
    )


def _entrees_pour_slug(slug: str, brut: Any) -> list[dict[str, Any]]:
    """Développe un couple (slug, valeur) en N entrées meta Nakala.

    `nkl_creator`/`nkl_created` émettent toujours au moins une meta (valeur
    `null` si anonyme/inconnu) — convention ColleC alimentant la cascade
    `preflight` (Nakala n'exige que `nkl:title`+`nkl:type`)."""
    if slug == "nkl_creator":
        if brut is None:
            return [_meta(slug, None)]
        if not isinstance(brut, list):
            raise MetaInvalide(
                f"nkl_creator : liste de chaînes (ou null) attendue, reçu "
                f"{type(brut).__name__}"
            )
        return [_meta(slug, parse_creator(item)) for item in brut]

    if slug == "nkl_created":
        return [_meta(slug, parse_created(brut))]

    # Autres slugs : None = pas de meta (champs optionnels).
    if brut is None:
        return []

    if slug in MULTILINGUE_SLUGS:
        if not isinstance(brut, list):
            raise MetaInvalide(
                f"{slug} : liste de {{value, lang}} attendue, reçu {type(brut).__name__}"
            )
        out: list[dict[str, Any]] = []
        for item in brut:
            if not isinstance(item, dict) or "value" not in item or "lang" not in item:
                raise MetaInvalide(
                    f"{slug} : chaque item doit être {{'value':…, 'lang':…}}, reçu {item!r}"
                )
            out.append(_meta(slug, item["value"], lang=item["lang"]))
        return out

    if slug == "dcterms_language":
        if not isinstance(brut, list):
            raise MetaInvalide(
                f"dcterms_language : liste de codes attendue, reçu {type(brut).__name__}"
            )
        return [_meta(slug, code) for code in brut]

    if slug == "dcterms_contributor" or slug in TABLEAU_CHAINES_SLUGS:
        if not isinstance(brut, list):
            raise MetaInvalide(
                f"{slug} : liste de chaînes attendue, reçu {type(brut).__name__}"
            )
        return [_meta(slug, str(item)) for item in brut]

    if slug == "dcterms_temporal":
        if not isinstance(brut, list):
            raise MetaInvalide(
                f"dcterms_temporal : liste attendue, reçu {type(brut).__name__}"
            )
        return [_entree_temporal(item) for item in brut]

    if slug == "dcterms_spatial":
        if not isinstance(brut, list):
            raise MetaInvalide(
                f"dcterms_spatial : liste attendue, reçu {type(brut).__name__}"
            )
        return [_entree_spatial(item) for item in brut]

    if slug in SCALAIRE_SLUGS:
        return [_meta(slug, brut)]

    return []  # slug connu mais non géré — ne devrait pas arriver


def slugs_vers_metas(slugs: dict[str, Any]) -> list[dict[str, Any]]:
    """Aplatis un dict slug → valeur en tableau `metas[]` Nakala.

    Ordre préservé (ordre d'insertion du dict). Les slugs inconnus sont
    ignorés silencieusement (cf. `slugs_inconnus` pour les remonter)."""
    metas: list[dict[str, Any]] = []
    for slug, valeur in slugs.items():
        if slug not in SLUG_TO_NAKALA:
            continue
        metas.extend(_entrees_pour_slug(slug, valeur))
    return metas


def slugs_inconnus(slugs: dict[str, Any]) -> list[str]:
    """Slugs fournis mais inconnus de la carte (à signaler à l'utilisateur)."""
    return [slug for slug in slugs if slug not in SLUG_TO_NAKALA]
