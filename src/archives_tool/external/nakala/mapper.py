"""Conversion d'un dépôt Nakala (JSON) → structure neutre ColleC.

Lecture permissive : Nakala renvoie des `metas[]` hétérogènes (valeurs
`str`, `dict` structuré pour les créateurs, `null`, langues en ISO 639-1
ou 639-3…). On tolère sans planter et on produit un :class:`DepotNakala`
aligné sur les champs d'un Item ColleC, prêt à être consommé par les
services de rapatriement / rafraîchissement (P1b+). **Aucune écriture en
base ici.**

Mapping porté du plugin `madbot_nakala_data` (`PROPERTY_URI_TO_SLUG`,
`_pick_label`, `_format_creator`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# Espaces de noms Nakala / DC.
_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"

#: propertyUri Nakala → slug court. Les `nkl:*` (champs cœur) sont
#: explicites ; tout `dcterms:*` est mappé génériquement en `dcterms_<nom>`.
PROPERTY_URI_TO_SLUG: dict[str, str] = {
    f"{_NKL}type": "nkl_type",
    f"{_NKL}title": "nkl_title",
    f"{_NKL}creator": "nkl_creator",
    f"{_NKL}created": "nkl_created",
    f"{_NKL}license": "nkl_license",
}

#: ISO 639-1 → 639-3 pour les langues courantes (Nakala/DC exportent
#: souvent en 639-1 `fr`, ColleC stocke en 639-3 `fra`). Jumelle de
#: `dashboard._LANGUES_ISO1_VERS_ISO3` — à consolider (réf. unique) lors
#: du chantier round-trip ; gardé local ici pour ne pas coupler
#: `external/` à `api.services`.
_ISO1_VERS_ISO3: dict[str, str] = {
    "fr": "fra",
    "en": "eng",
    "es": "spa",
    "it": "ita",
    "de": "deu",
    "pt": "por",
    "nl": "nld",
    "ar": "ara",
    "ru": "rus",
    "el": "ell",
    "la": "lat",
    "oc": "oci",
    "br": "bre",
    "ca": "cat",
}


@dataclass
class FichierNakala:
    """Un fichier d'un dépôt Nakala (métadonnées, pas le binaire)."""

    nom: str | None
    sha1: str | None
    taille: int | None
    mime: str | None
    embargo_actif: bool
    #: Transcription/description publique par fichier (S7). `None` si absente.
    description: str | None = None


@dataclass
class DepotNakala:
    """Projection neutre d'un dépôt Nakala, alignée sur un Item ColleC."""

    identifiant: str  # DOI Nakala (10.34847/nkl.xxxxxxxx)
    statut: str | None
    titre: str | None
    createurs: list[str]
    date: str | None
    type_coar: str | None
    langues: list[str]  # ISO 639-3 (best effort)
    description: str | None
    sujets: list[str]
    licence: str | None
    fichiers: list[FichierNakala] = field(default_factory=list)
    #: Slug → valeur(s) pour tout le reste des metas (dcterms_*, etc.),
    #: à verser dans `Item.metadonnees` au rapatriement.
    metadonnees: dict[str, Any] = field(default_factory=dict)
    #: DOIs des collections Nakala auxquelles cette donnée appartient
    #: (champ `collectionsIds` de `GET /datas`). Sert à réconcilier
    #: l'appartenance au pull (S3) : on lie l'item à la Collection ColleC
    #: dont le `doi_nakala` matche. Vide si la donnée n'est dans aucune
    #: collection.
    collections_ids: list[str] = field(default_factory=list)


def _slug(property_uri: str) -> str:
    """propertyUri → slug court. dcterms:* générique, nkl:* explicite."""
    if property_uri in PROPERTY_URI_TO_SLUG:
        return PROPERTY_URI_TO_SLUG[property_uri]
    if property_uri.startswith(_DCT):
        return "dcterms_" + property_uri[len(_DCT) :]
    if property_uri.startswith(_NKL):
        return "nkl_" + property_uri[len(_NKL) :]
    return property_uri


def _valeurs(metas: list[dict], property_uri: str) -> list[Any]:
    return [m.get("value") for m in metas if m.get("propertyUri") == property_uri]


def _pick_label(
    metas: list[dict], property_uri: str, prefer_lang: str = "fr"
) -> str | None:
    """Meilleur libellé parmi des valeurs multilingues (préfère `fr`)."""
    candidats = [m for m in metas if m.get("propertyUri") == property_uri]
    for m in candidats:
        if m.get("lang") == prefer_lang and m.get("value"):
            return str(m["value"])
    for m in candidats:
        if m.get("value"):
            return str(m["value"])
    return None


def normaliser_orcid(orcid: Any) -> str | None:
    """ORCID en forme **nue** (`0000-0001-2345-6789`).

    Nakala stocke l'ORCID en **URL canonique** (`https://orcid.org/0000-…`) ;
    ColleC le dépose et l'affiche nu. Sans cette normalisation, un créateur
    rapatrié diffère de sa forme déposée (vérifié live 2026-06-15 par le
    round-trip end-to-end) et le `diff_push` voyait un faux changement.
    Source unique partagée par la lecture (`_format_createur`) et la
    comparaison de diff (`nakala_depot._canon_valeur`). `None`/vide → `None`."""
    if not orcid:
        return None
    s = str(orcid).strip()
    for prefixe in ("https://orcid.org/", "http://orcid.org/", "orcid.org/"):
        if s.lower().startswith(prefixe):
            return s[len(prefixe) :] or None
    return s or None


def _format_createur(value: Any) -> str | None:
    """Rend un créateur Nakala (`{givenname, surname, orcid}` ou str)
    en chaîne lisible `"Nom, Prénom [ORCID nu]"`. `None`/anonyme → None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        surname = (value.get("surname") or "").strip()
        given = (value.get("givenname") or "").strip()
        orcid = normaliser_orcid(value.get("orcid"))  # Nakala renvoie l'URL
        base = ", ".join(p for p in (surname, given) if p)
        if not base:
            return None
        return f"{base} [{orcid}]" if orcid else base
    return None


def langue_vers_iso639_3(code: Any) -> str | None:
    """Normalise un code langue Nakala vers ISO 639-3 (best effort).

    `fr` → `fra` ; `fr-FR` → `fra` (sous-tag région RFC5646 ignoré ;
    Nakala type `dcterms:language` en RFC5646) ; `fra` → `fra` (déjà
    639-3) ; inconnu / non-str → tel quel (str) ou None. Le pont des
    ~185 majeurs reste partiel (P1) — les codes 639-3 longue traîne
    passent inchangés.
    """
    if not isinstance(code, str) or not code.strip():
        return None
    # RFC5646 : on ne garde que le sous-tag primaire (`fr-FR` → `fr`).
    primaire = code.strip().lower().split("-", 1)[0]
    return _ISO1_VERS_ISO3.get(primaire, primaire)


#: Inverse de `_ISO1_VERS_ISO3` : ISO 639-3 → 639-1. Sert au **dépôt**
#: (sens écriture) — cf. `langue_vers_nakala`.
_ISO3_VERS_ISO1: dict[str, str] = {v: k for k, v in _ISO1_VERS_ISO3.items()}


def langue_vers_nakala(code: Any) -> str | None:
    """Convertit un code langue ColleC (ISO 639-3) vers le code attendu par
    Nakala (RFC5646 ≈ 639-1) pour `dcterms:language` **et** l'attribut `lang`
    des littéraux multilingues.

    Nakala type `dcterms:language` en RFC5646 et son vocabulaire emploie le
    639-1 quand il existe (`spa` → `es`, `fra` → `fr`). Sans cette conversion,
    un dépôt/push d'un Item avec langue est **rejeté 422** (`es` est dans le
    vocab Nakala, `spa` non). Jumelle inverse de `langue_vers_iso639_3`.

    `spa` → `es` ; `fra` → `fr` ; `es` (déjà 639-1) → `es` ; code 639-3 sans
    équivalent 639-1 (`spq`, `osp`…) → tel quel (Nakala les accepte) ;
    None/vide → None.
    """
    if not isinstance(code, str) or not code.strip():
        return None
    # Tolère un tag déjà RFC5646 (`es`, `fr-FR`) : on garde le sous-tag primaire.
    primaire = code.strip().lower().split("-", 1)[0]
    return _ISO3_VERS_ISO1.get(primaire, primaire)


def _embargo_actif(brut: Any, aujourdhui: date | None = None) -> bool:
    """Vrai si la date d'embargo est dans le futur. Non parsable → actif
    (prudent : mieux vaut refuser un téléchargement que le promettre à
    tort)."""
    if not brut:
        return False
    if aujourdhui is None:
        aujourdhui = datetime.now().date()
    try:
        texte = str(brut).strip()
        if "T" in texte:
            jusqua = datetime.fromisoformat(texte.replace("Z", "+00:00")).date()
        else:
            jusqua = date.fromisoformat(texte[:10])
    except (ValueError, TypeError):
        return True
    return jusqua > aujourdhui


def _type_coar_interne(uri: Any) -> str | None:
    """Type Nakala (URI COAR) → type interne ColleC.

    Le set COAR accepté par Nakala est inclus dans le vocabulaire interne
    ColleC (`TYPES_COAR_OPTIONS`) → l'URI renvoyée est déjà l'URI interne
    (identité). On la conserve telle quelle ; une URI hors vocabulaire
    restera éditable inline côté ColleC."""
    if not isinstance(uri, str) or not uri.strip():
        return None
    return uri.strip()


def mapper_depot(depot: dict[str, Any]) -> DepotNakala:
    """Convertit le JSON d'un dépôt Nakala en :class:`DepotNakala`."""
    metas: list[dict] = depot.get("metas") or []

    createurs = [
        c
        for v in _valeurs(metas, f"{_NKL}creator")
        if (c := _format_createur(v)) is not None
    ]
    langues = [
        iso
        for v in _valeurs(metas, f"{_DCT}language")
        if (iso := langue_vers_iso639_3(v)) is not None
    ]
    sujets = [str(v) for v in _valeurs(metas, f"{_DCT}subject") if v not in (None, "")]

    # Reste des metas (hors champs dédiés) → metadonnees par slug.
    champs_dedies = {
        f"{_NKL}title",
        f"{_NKL}creator",
        f"{_NKL}created",
        f"{_NKL}type",
        f"{_NKL}license",
        f"{_DCT}description",
        f"{_DCT}subject",
        f"{_DCT}language",
    }
    metadonnees: dict[str, Any] = {}
    for m in metas:
        uri = m.get("propertyUri")
        if not uri or uri in champs_dedies:
            continue
        valeur = m.get("value")
        if valeur in (None, ""):
            continue
        slug = _slug(uri)
        if slug in metadonnees:
            existant = metadonnees[slug]
            metadonnees[slug] = (
                existant + [valeur]
                if isinstance(existant, list)
                else [existant, valeur]
            )
        else:
            metadonnees[slug] = valeur

    fichiers = [
        FichierNakala(
            nom=f.get("name"),
            sha1=f.get("sha1"),
            taille=f.get("size"),
            # L'API Nakala expose `mime_type` (et non `mime`) ; on tolère
            # les deux pour rester robuste aux variantes / fixtures.
            mime=f.get("mime_type") or f.get("mime"),
            embargo_actif=_embargo_actif(f.get("embargoed")),
            description=f.get("description") or None,
        )
        for f in (depot.get("files") or [])
    ]

    type_brut = next(iter(_valeurs(metas, f"{_NKL}type")), None)

    return DepotNakala(
        identifiant=str(depot.get("identifier") or ""),
        statut=depot.get("status"),
        titre=_pick_label(metas, f"{_NKL}title"),
        createurs=createurs,
        date=next(iter(_valeurs(metas, f"{_NKL}created")), None),
        type_coar=_type_coar_interne(type_brut),
        langues=langues,
        description=_pick_label(metas, f"{_DCT}description"),
        sujets=sujets,
        licence=next(iter(_valeurs(metas, f"{_NKL}license")), None),
        fichiers=fichiers,
        metadonnees=metadonnees,
        collections_ids=[str(c) for c in (depot.get("collectionsIds") or []) if c],
    )
