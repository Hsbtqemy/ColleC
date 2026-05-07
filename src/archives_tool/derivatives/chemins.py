"""Convention de stockage des dérivés sous une racine logique cible.

Pour une source `HK/01.png` et la taille `vignette`, le dérivé se
trouve sous la racine cible à `vignette/HK/01.jpg`.

Avantages de la mise en sous-dossier par taille :
- nettoyage sélectif d'une taille sans toucher aux autres ;
- mapping facile pour un service web (un préfixe d'URL par taille).
"""

from __future__ import annotations

from pathlib import PurePosixPath

EXTENSION_DERIVE = "jpg"


def chemin_derive(chemin_relatif_source: str, nom_taille: str) -> str:
    """Calcule le chemin relatif du dérivé sous la racine cible."""
    source = PurePosixPath(chemin_relatif_source)
    nom_jpg = source.with_suffix(f".{EXTENSION_DERIVE}").name
    parent = source.parent
    if str(parent) in (".", ""):
        return f"{nom_taille}/{nom_jpg}"
    return f"{nom_taille}/{parent}/{nom_jpg}"
