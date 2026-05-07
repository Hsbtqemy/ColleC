"""Évaluation du template de nommage canonique d'un fichier.

Le template est une chaîne au format `str.format` Python ; les
variables disponibles sont exposées par `_construire_variables`.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from archives_tool.files.paths import normaliser_nfc
from archives_tool.models import Collection, Fichier, Item


class EchecTemplate(ValueError):
    """Le template ne s'applique pas à ce fichier (variable absente,
    format invalide, résultat vide ou hors racine)."""


def _construire_variables(
    fichier: Fichier, item: Item, collection: Collection | None
) -> dict[str, object]:
    p = PurePosixPath(fichier.nom_fichier)
    ext = p.suffix.lstrip(".").lower()
    variables: dict[str, object] = {
        "cote": item.cote,
        "numero": item.numero,
        "titre": item.titre,
        "date": item.date,
        "annee": item.annee,
        "langue": item.langue,
        "type_coar": item.type_coar,
        "ordre": fichier.ordre,
        "type_page": fichier.type_page,
        "folio": fichier.folio,
        "nom_original": p.stem,
        "ext": ext,
        "ext_majuscule": ext.upper(),
    }
    if collection is not None:
        variables["cote_collection"] = collection.cote_collection
        variables["titre_collection"] = collection.titre
    return {k: ("" if v is None else v) for k, v in variables.items()}


def evaluer_template(
    template: str,
    fichier: Fichier,
    item: Item,
    collection: Collection | None = None,
) -> str:
    """Évalue le template et retourne un chemin relatif POSIX/NFC.

    Lève `EchecTemplate` si le template référence une variable inconnue,
    contient un spécificateur de format invalide, produit un résultat
    vide, ou tente de sortir de la racine via `..`.
    """
    if not template.strip():
        raise EchecTemplate("Template vide.")

    variables = _construire_variables(fichier, item, collection)
    try:
        rendu = template.format_map(variables)
    except KeyError as e:
        raise EchecTemplate(f"Variable inconnue dans le template : {e}") from e
    except (ValueError, IndexError, TypeError) as e:
        raise EchecTemplate(f"Template invalide : {e}") from e

    rendu = normaliser_nfc(rendu).replace("\\", "/").strip("/")
    if not rendu:
        raise EchecTemplate("Template vide après évaluation.")
    if ".." in PurePosixPath(rendu).parts:
        raise EchecTemplate(f"Le template tente de sortir de la racine : {rendu!r}")
    return rendu
