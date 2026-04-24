"""Correspondance champs internes → URI Dublin Core Terms.

Source de vérité du projet. Quand un nouveau champ de `metadonnees`
devient assez fréquent pour être exporté proprement, on l'ajoute ici.

Les champs `metadonnees.hierarchie.*` ne sont volontairement pas
mappés : ils servent à reconstruire la structure archivistique en
consultation, pas à être exportés en DC plat.
"""

from __future__ import annotations

from typing import Any

from archives_tool.models import Item

DC = "http://purl.org/dc/terms/"

MAPPING_DC: dict[str, str] = {
    # Colonnes dédiées d'Item
    "cote": f"{DC}identifier",
    "titre": f"{DC}title",
    "date": f"{DC}date",
    "description": f"{DC}description",
    "type_coar": f"{DC}type",
    "langue": f"{DC}language",
    # Métadonnées étendues fréquemment présentes
    "metadonnees.auteurs": f"{DC}creator",
    "metadonnees.createurs": f"{DC}creator",
    "metadonnees.editeur": f"{DC}publisher",
    "metadonnees.publisher": f"{DC}publisher",
    "metadonnees.sujets": f"{DC}subject",
    "metadonnees.rubrique": f"{DC}subject",
    "metadonnees.collaborateurs": f"{DC}contributor",
    "metadonnees.droits": f"{DC}rights",
    "metadonnees.source": f"{DC}source",
    "metadonnees.relation": f"{DC}relation",
    "metadonnees.format": f"{DC}format",
}


def extraire_valeur(item: Item, champ_interne: str) -> Any:
    """Extrait la valeur correspondante sur un `Item`.

    - `"cote"` → `item.cote`
    - `"metadonnees.auteurs"` → `(item.metadonnees or {}).get("auteurs")`

    Retourne None si absent.
    """
    if "." in champ_interne:
        zone, cle = champ_interne.split(".", 1)
        if zone == "metadonnees":
            meta = item.metadonnees or {}
            # Support des clés imbriquées superficiellement :
            # "metadonnees.hierarchie.fonds" → meta["hierarchie"]["fonds"]
            if "." in cle:
                tete, reste = cle.split(".", 1)
                valeur = meta.get(tete)
                if isinstance(valeur, dict):
                    return valeur.get(reste)
                return None
            return meta.get(cle)
    return getattr(item, champ_interne, None)


def valeur_en_liste(valeur: Any) -> list[str]:
    """Convertit une valeur scalaire ou liste en liste de chaînes non vides,
    triée alphabétiquement pour reproductibilité des exports."""
    if valeur is None:
        return []
    if isinstance(valeur, list):
        parts = [str(v).strip() for v in valeur if v is not None and str(v).strip()]
    elif isinstance(valeur, str):
        parts = [valeur.strip()] if valeur.strip() else []
    else:
        parts = [str(valeur).strip()]
    return sorted(parts)
