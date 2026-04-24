"""Transformation d'une ligne de tableur en structure `ItemPrepare`.

Fonctions pures (pas d'accès base, pas d'accès disque). Applique :
- le mapping du profil (trois formes : simple, transformée, agrégée) ;
- les valeurs_par_defaut (copiées, pas référencées — principe
  d'autonomie des items) ;
- la décomposition de cote par regex nommée ;
- la décomposition de type par colonne à séparateur.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from archives_tool.profils.schema import (
    MappingAgrege,
    MappingChamp,
    MappingSimple,
    MappingTransforme,
    Profil,
    TypeTransformation,
)

# Noms de colonnes dédiées sur `Item`. Toute autre clé dans le mapping
# est stockée dans `metadonnees` (préfixe "metadonnees." obligatoire).
COLONNES_ITEM = {
    "cote",
    "numero",
    "titre",
    "date",
    "annee",
    "type_coar",
    "langue",
    "description",
    "doi_nakala",
    "doi_collection_nakala",
    "etat_catalogage",
}


@dataclass
class ItemPrepare:
    """Structure intermédiaire avant écriture en base."""

    cote: str
    champs_colonne: dict[str, Any] = field(default_factory=dict)
    metadonnees: dict[str, Any] = field(default_factory=dict)
    hierarchie: dict[str, str] | None = None
    typologie: dict[str, str] | None = None
    ligne_source: int = 0


def _appliquer_transformation(
    valeur: str, transformation: TypeTransformation | None
) -> str:
    if transformation is None:
        return valeur
    if transformation == "upper":
        return valeur.upper()
    if transformation == "lower":
        return valeur.lower()
    if transformation == "strip":
        return valeur.strip()
    if transformation == "strip_accents":
        nfd = unicodedata.normalize("NFD", valeur)
        sans = "".join(c for c in nfd if not unicodedata.combining(c))
        return unicodedata.normalize("NFC", sans)
    if transformation == "slug":
        nfd = unicodedata.normalize("NFD", valeur.lower())
        sans = "".join(c for c in nfd if not unicodedata.combining(c))
        slug = re.sub(r"[^a-z0-9]+", "-", sans).strip("-")
        return slug
    return valeur


def _extraire_brut(ligne: dict[str, Any], colonne: str) -> Any:
    if colonne not in ligne:
        raise KeyError(
            f"Colonne {colonne!r} attendue par le mapping mais absente du tableur."
        )
    return ligne[colonne]


def _appliquer_mapping(
    champ_cible: str, mapping: MappingChamp, ligne: dict[str, Any]
) -> Any:
    if isinstance(mapping, MappingSimple):
        valeur = _extraire_brut(ligne, mapping.source)
        return valeur

    if isinstance(mapping, MappingTransforme):
        valeur = _extraire_brut(ligne, mapping.source)
        if valeur is None:
            return None
        if isinstance(valeur, str) and mapping.separateur is not None:
            seps = (
                [mapping.separateur]
                if isinstance(mapping.separateur, str)
                else list(mapping.separateur)
            )
            parts: list[str] = [valeur]
            for s in seps:
                parts = [p for morceau in parts for p in morceau.split(s)]
            parts = [p.strip() for p in parts if p.strip()]
            if mapping.transformation:
                parts = [
                    _appliquer_transformation(p, mapping.transformation) for p in parts
                ]
            return parts
        if isinstance(valeur, str) and mapping.transformation:
            return _appliquer_transformation(valeur, mapping.transformation)
        return valeur

    if isinstance(mapping, MappingAgrege):
        valeurs: list[str] = []
        for src in mapping.sources:
            v = _extraire_brut(ligne, src)
            if v is None:
                continue
            if isinstance(v, str):
                if mapping.transformation:
                    v = _appliquer_transformation(v, mapping.transformation)
                valeurs.append(v)
            else:
                valeurs.append(str(v))
        if not valeurs:
            return None
        return mapping.separateur_sortie.join(valeurs)

    raise TypeError(f"Type de mapping inattendu : {type(mapping).__name__}")


def _classer(champ_cible: str) -> tuple[str, str]:
    """Retourne (zone, cle) où zone ∈ {"colonne", "metadonnees"}."""
    if champ_cible.startswith("metadonnees."):
        return ("metadonnees", champ_cible[len("metadonnees.") :])
    if champ_cible in COLONNES_ITEM:
        return ("colonne", champ_cible)
    # Clé inconnue : on tolère mais on range dans metadonnees, pour ne
    # pas casser sur une évolution du schéma ou un champ non encore
    # modélisé. Le rapport d'import pourra lister ces cas.
    return ("metadonnees", champ_cible)


def _decomposer_cote(cote: str | None, profil: Profil) -> dict[str, str] | None:
    if profil.decomposition_cote is None or cote is None:
        return None
    m = re.match(profil.decomposition_cote.regex, cote)
    if m is None:
        return None
    return {k: v for k, v in m.groupdict().items() if v is not None}


def _decomposer_type(ligne: dict[str, Any], profil: Profil) -> dict[str, str] | None:
    if profil.decomposition_type is None:
        return None
    dec = profil.decomposition_type
    if dec.colonne not in ligne:
        return None
    valeur = ligne[dec.colonne]
    if not isinstance(valeur, str):
        return None
    parts = [p.strip() for p in valeur.split(dec.separateur)]
    return {
        nom: parts[i]
        for i, nom in enumerate(dec.niveaux)
        if i < len(parts) and parts[i]
    }


def _ligne_toute_vide(ligne: dict[str, Any], profil: Profil) -> bool:
    """Une ligne est ignorable si toutes les colonnes mappées sont None."""
    colonnes_utilisees: set[str] = set()
    for mapping in profil.mapping.champs.values():
        if isinstance(mapping, MappingAgrege):
            colonnes_utilisees.update(mapping.sources)
        else:
            colonnes_utilisees.add(mapping.source)
    return all(ligne.get(c) is None for c in colonnes_utilisees)


_COTE_INTERDITS = re.compile(r"[\n/]")


def transformer_ligne(
    ligne: dict[str, Any],
    numero_ligne: int,
    profil: Profil,
) -> ItemPrepare | None:
    """Convertit une ligne en `ItemPrepare`, ou `None` si toute vide.

    Raises:
        ValueError: cote manquante sur une ligne non vide, ou cote
            contenant des caractères interdits (\\n, /).
    """
    if _ligne_toute_vide(ligne, profil):
        return None

    item = ItemPrepare(cote="", ligne_source=numero_ligne)

    # 1. Application du mapping.
    for champ_cible, mapping in profil.mapping.champs.items():
        valeur = _appliquer_mapping(champ_cible, mapping, ligne)
        zone, cle = _classer(champ_cible)
        if zone == "colonne":
            item.champs_colonne[cle] = valeur
        else:
            item.metadonnees[cle] = valeur

    # 2. Valeurs par défaut : n'écrasent pas une valeur déjà présente,
    # mais couvrent les champs absents du mapping.
    for cle, val in profil.valeurs_par_defaut.items():
        zone, cle_locale = _classer(cle)
        cible = item.champs_colonne if zone == "colonne" else item.metadonnees
        if cle_locale not in cible or cible[cle_locale] is None:
            cible[cle_locale] = val

    # 3. Cote : obligatoire, lève sinon.
    cote = item.champs_colonne.get("cote")
    if cote is None or (isinstance(cote, str) and not cote.strip()):
        raise ValueError(
            f"Ligne {numero_ligne} : cote absente ou vide "
            "(la cote est obligatoire, même en granularité fichier)."
        )
    if not isinstance(cote, str):
        raise ValueError(
            f"Ligne {numero_ligne} : cote doit être une chaîne, "
            f"reçu {type(cote).__name__}."
        )
    if _COTE_INTERDITS.search(cote):
        raise ValueError(
            f"Ligne {numero_ligne} : cote contient un caractère interdit "
            r"(\n ou /) : " + repr(cote)
        )
    item.cote = cote

    # 4. Décompositions (n'émettent pas d'erreur si elles ne matchent pas).
    item.hierarchie = _decomposer_cote(cote, profil)
    item.typologie = _decomposer_type(ligne, profil)

    return item
