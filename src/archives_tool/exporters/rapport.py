"""Rapport de pré-export : ce qui manque, ce qui ne mappe pas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archives_tool.models import Item
from archives_tool.reference.loaders import licence_reconnue

_RE_URI_COAR = re.compile(r"^http://purl\.org/coar/resource_type/")
_RE_ISO_639_3 = re.compile(r"^[a-z]{3}$")


@dataclass
class RapportExport:
    format: str
    nb_items_selectionnes: int = 0
    nb_fichiers_selectionnes: int = 0
    items_incomplets: list[tuple[str, list[str]]] = field(default_factory=list)
    valeurs_non_mappees: list[tuple[str, str]] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    chemin_sortie: Path | None = None
    duree_secondes: float = 0.0


def _valeur_champ(item: Item, champ: str) -> Any:
    """Extrait la valeur d'un champ interne. Partagé avec mapping_dc."""
    if "." in champ:
        zone, cle = champ.split(".", 1)
        if zone == "metadonnees":
            return (item.metadonnees or {}).get(cle)
    return getattr(item, champ, None)


def verifier_pre_export(
    items: list[Item] | tuple[Item, ...],
    champs_obligatoires: list[str],
    format: str,
    *,
    valider_licence: bool = False,
) -> RapportExport:
    """Analyse les items et remplit un rapport de pré-export.

    - Items manquant un champ obligatoire → listés avec les champs KO.
    - Valeurs `type_coar` qui ne sont pas des URI COAR → signalées.
    - Valeurs `langue` qui ne sont pas ISO 639-3 → signalées.
    - Si `valider_licence` (export Nakala) : licence `metadonnees.licence`
      (ou `rights`) non reconnue par Nakala → signalée. Permet d'échouer
      tôt avec un message clair plutôt qu'un 422 distant. **Signalement
      seul, jamais bloquant** (cf. `licence_reconnue`). Le défaut de licence
      (appliqué côté exporter) n'est pas vérifié ici — seule une valeur
      explicitement saisie l'est. Désactivé pour Dublin Core, dont
      `dcterms:license` n'est pas contraint à SPDX.
    """
    rapport = RapportExport(format=format, nb_items_selectionnes=len(items))

    for item in items:
        manquants: list[str] = []
        for champ in champs_obligatoires:
            val = _valeur_champ(item, champ)
            if val is None or (isinstance(val, str) and not val.strip()):
                manquants.append(champ)
        if manquants:
            rapport.items_incomplets.append((item.cote, manquants))

        if item.type_coar and not _RE_URI_COAR.match(item.type_coar):
            rapport.valeurs_non_mappees.append(("type_coar", item.type_coar))
        if item.langue and not _RE_ISO_639_3.match(item.langue):
            rapport.valeurs_non_mappees.append(("langue", item.langue))

        if valider_licence:
            # Miroir exact de l'exporter (`nakala.py` : `licence or rights or
            # défaut`). Une valeur **truthy** est émise VERBATIM dans le CSV —
            # y compris une liste/dict (`str()`-ifiés) ou des espaces seuls,
            # qui provoquent un 422 Nakala. On signale donc tout ce qui n'est
            # pas un code string reconnu (sans strip : Nakala valide la valeur
            # exacte). Une valeur falsy laisse le défaut valide s'appliquer.
            meta = item.metadonnees or {}
            licence = meta.get("licence") or meta.get("rights")
            if licence and not (isinstance(licence, str) and licence_reconnue(licence)):
                rapport.valeurs_non_mappees.append(("licence", str(licence)))

    return rapport
