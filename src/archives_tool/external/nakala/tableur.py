"""Aplatissement d'une collection Nakala en tableur (Lot 1, T1.2).

Fonctions **pures** : prennent des dépôts Nakala bruts (tels que rendus
par `iterer_donnees_collection`) et produisent un :class:`TableurNakala`
(colonnes ordonnées + lignes en dict). L'écriture CSV/xlsx vit dans
`tableur_io.py` ; l'itération réseau dans `collection.py`.

Deux granularités :

- **donnée** : une ligne par dépôt, toutes les propriétés Nakala en
  colonnes (valeurs multiples jointes par ` | `) ;
- **fichier** : une ligne par fichier, les métadonnées de la donnée
  recopiées + colonnes techniques du fichier (nom, sha1, mime, taille,
  embargo, …). Une donnée sans fichier produit quand même une ligne (avec
  les colonnes fichier vides) pour ne pas la perdre.

Différence assumée avec `mapper.py` : le mapper projette vers un Item
ColleC (lossy, champs dédiés) ; ici on veut l'**exhaustivité** des
propriétés, pour un tableur fidèle à ce que contient Nakala.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from archives_tool.external.nakala.mapper import normaliser_orcid

# Espaces de noms Nakala / Dublin Core.
_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"

#: Séparateur des valeurs multiples d'une même propriété dans une cellule.
SEP_VALEURS = " | "

#: Colonnes propres au dépôt (toujours en tête, dans cet ordre).
COLONNES_FIXES: tuple[str, ...] = ("identifier", "uri", "status", "version")

#: Ordre privilégié des propriétés (le reste suit, par ordre d'apparition).
_ORDRE_PREFERE: tuple[str, ...] = (
    "nkl:title", "nkl:created", "nkl:type", "nkl:license", "nkl:creator",
    "dcterms:creator", "dcterms:contributor", "dcterms:publisher",
    "dcterms:date", "dcterms:type", "dcterms:language", "dcterms:subject",
    "dcterms:description", "dcterms:abstract", "dcterms:spatial",
    "dcterms:temporal", "dcterms:source", "dcterms:relation", "dcterms:rights",
    "dcterms:rightsHolder", "dcterms:identifier", "dcterms:format",
    "dcterms:medium", "dcterms:coverage", "dcterms:bibliographicCitation",
)

#: Colonnes techniques d'un fichier (granularité fichier), dans l'ordre.
#: `(clé Nakala, nom de colonne)`.
_CHAMPS_FICHIER: tuple[tuple[str, str], ...] = (
    ("name", "fichier_nom"),
    ("extension", "fichier_extension"),
    ("size", "fichier_taille"),
    ("mime_type", "fichier_mime"),
    ("sha1", "fichier_sha1"),
    ("embargoed", "fichier_embargo"),
    ("description", "fichier_description"),
    ("puid", "fichier_puid"),
    ("format", "fichier_format"),
)
COLONNES_FICHIER: tuple[str, ...] = tuple(col for _, col in _CHAMPS_FICHIER)


@dataclass
class TableurNakala:
    """Un tableur aplati : colonnes ordonnées + lignes (dict par ligne)."""

    colonnes: list[str]
    lignes: list[dict[str, Any]] = field(default_factory=list)


def _nom_propriete(uri: str) -> str:
    """propertyUri → nom de colonne court (`nkl:title`, `dcterms:subject`,
    ou l'URI brute si hors des deux espaces de noms connus)."""
    if uri.startswith(_NKL):
        return "nkl:" + uri[len(_NKL):]
    if uri.startswith(_DCT):
        return "dcterms:" + uri[len(_DCT):]
    return uri


def _fmt_valeur(meta: dict) -> str:
    """Rend une valeur de `metas[]` en chaîne.

    - créateur structuré `{surname, givenname, orcid}` → `Nom, Prénom [orcid]` ;
    - valeur multilingue (`lang` non nul) → préfixée `[xx]` ;
    - sinon `str(value).strip()`. `None` → "".
    """
    v = meta.get("value")
    if isinstance(v, dict):
        sur = (v.get("surname") or "").strip()
        giv = (v.get("givenname") or "").strip()
        orc = normaliser_orcid(v.get("orcid"))  # Nakala renvoie l'URL → nu
        base = ", ".join(p for p in (sur, giv) if p) or str(v)
        return f"{base} [{orc}]" if orc else base
    if v is None:
        return ""
    texte = str(v).strip()
    if not texte:
        return ""
    lang = meta.get("lang")
    return f"[{lang}] {texte}" if lang else texte


def _grouper_metas(donnee: dict) -> dict[str, str]:
    """metas[] d'une donnée → {colonne: valeurs jointes}, vides ignorées."""
    groupes: dict[str, list[str]] = {}
    for meta in donnee.get("metas") or []:
        uri = meta.get("propertyUri")
        if not uri:
            continue
        valeur = _fmt_valeur(meta)
        if not valeur:
            continue
        groupes.setdefault(_nom_propriete(uri), []).append(valeur)
    return {col: SEP_VALEURS.join(vals) for col, vals in groupes.items()}


def _ligne_fixe(donnee: dict) -> dict[str, Any]:
    """Colonnes propres au dépôt (identifier, uri, status, version)."""
    version = donnee.get("version")
    return {
        "identifier": donnee.get("identifier") or "",
        "uri": donnee.get("uri") or "",
        "status": donnee.get("status") or "",
        "version": "" if version is None else version,
    }


def _ordonner_proprietes(vues: Iterable[str]) -> list[str]:
    """Propriétés vues → ordre préféré d'abord, puis le reste (ordre stable)."""
    vues_liste = list(dict.fromkeys(vues))  # dédupe en préservant l'ordre
    prefere = [p for p in _ORDRE_PREFERE if p in vues_liste]
    reste = [p for p in vues_liste if p not in _ORDRE_PREFERE]
    return prefere + reste


def lignes_niveau_donnee(donnees: Iterable[dict]) -> TableurNakala:
    """Une ligne par donnée, toutes les propriétés Nakala en colonnes."""
    lignes: list[dict[str, Any]] = []
    props_vues: list[str] = []
    for donnee in donnees:
        ligne = _ligne_fixe(donnee)
        groupes = _grouper_metas(donnee)
        for col in groupes:
            if col not in props_vues:
                props_vues.append(col)
        ligne.update(groupes)
        lignes.append(ligne)

    colonnes = list(COLONNES_FIXES) + _ordonner_proprietes(props_vues)
    return TableurNakala(colonnes=colonnes, lignes=lignes)


def _ligne_fichier(fichier: dict) -> dict[str, Any]:
    """Colonnes techniques d'un fichier Nakala."""
    ligne: dict[str, Any] = {}
    for cle, col in _CHAMPS_FICHIER:
        valeur = fichier.get(cle)
        ligne[col] = "" if valeur is None else valeur
    return ligne


def lignes_niveau_fichier(donnees: Iterable[dict]) -> TableurNakala:
    """Une ligne par fichier : métadonnées de la donnée recopiées + colonnes
    fichier. Une donnée sans fichier produit une ligne (colonnes fichier
    vides) pour ne pas la perdre."""
    lignes: list[dict[str, Any]] = []
    props_vues: list[str] = []
    for donnee in donnees:
        base = _ligne_fixe(donnee)
        groupes = _grouper_metas(donnee)
        for col in groupes:
            if col not in props_vues:
                props_vues.append(col)
        base.update(groupes)

        fichiers = donnee.get("files") or []
        if not fichiers:
            lignes.append(dict(base))
            continue
        for fichier in fichiers:
            ligne = dict(base)
            ligne.update(_ligne_fichier(fichier))
            lignes.append(ligne)

    colonnes = (
        list(COLONNES_FIXES)
        + _ordonner_proprietes(props_vues)
        + list(COLONNES_FICHIER)
    )
    return TableurNakala(colonnes=colonnes, lignes=lignes)
