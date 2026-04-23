"""Manipulation de chemins portables entre Windows, macOS et Linux.

Règles transversales du projet :
- Jamais de `os.path.join` ni de concaténation de chaînes sur les chemins.
- Toute chaîne de chemin stockée en base est normalisée NFC et en POSIX
  (séparateur '/'), pour que la même valeur soit utilisable sur les
  trois OS.
- macOS normalise en NFD sur disque ; comparer deux noms sans NFC
  préalable produit des faux négatifs pour les caractères accentués.
"""

from __future__ import annotations

import hashlib
import sys
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

SYSTEME_CASSE_INSENSIBLE = sys.platform in ("win32", "darwin")


def normaliser_nfc(chaine: str) -> str:
    """Normalise en Unicode NFC. Idempotent."""
    return unicodedata.normalize("NFC", chaine)


def vers_posix(chemin: Path | str) -> str:
    """Convertit un chemin en chaîne POSIX normalisée NFC.

    Utilisé pour tout stockage en base : la valeur obtenue est
    indépendante de l'OS d'origine.
    """
    brut = chemin.as_posix() if isinstance(chemin, Path) else str(chemin)
    return normaliser_nfc(brut.replace("\\", "/"))


def resoudre_chemin(
    racines: Mapping[str, Path],
    racine: str,
    chemin_relatif: str,
) -> Path:
    """Résout (racine logique, chemin relatif) → chemin absolu.

    Rejette :
    - les racines inconnues (KeyError) ;
    - les chemins relatifs absolus ou contenant `..` (ValueError),
      pour empêcher qu'une valeur en base ne sorte de la racine.
    """
    if racine not in racines:
        raise KeyError(f"Racine logique inconnue : {racine!r}")
    base = racines[racine]
    rel = PurePosixPath(normaliser_nfc(chemin_relatif))
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Chemin relatif invalide : {chemin_relatif!r}")
    return base.joinpath(*rel.parts)


def hash_sha256(chemin: Path, taille_buffer: int = 1 << 16) -> str:
    """SHA-256 d'un fichier, lu par buffers (constant en mémoire)."""
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(taille_buffer), b""):
            h.update(bloc)
    return h.hexdigest()


def detecter_collisions_casse(noms: Iterable[str]) -> list[tuple[str, str]]:
    """Repère les paires de noms ne différant que par la casse ou la forme
    Unicode.

    Essentiel lors d'un import : sous Linux `Image.TIF` et `image.tif`
    coexistent, mais l'archive deviendra incohérente si elle est migrée
    sur Windows/macOS. On normalise en NFC puis casefold pour que la
    comparaison soit stable entre OS.
    """
    vus: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for nom in noms:
        cle = normaliser_nfc(nom).casefold()
        if cle in vus and vus[cle] != nom:
            collisions.append((vus[cle], nom))
        else:
            vus.setdefault(cle, nom)
    return collisions
