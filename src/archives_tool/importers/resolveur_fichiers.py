"""Résolution des fichiers sur disque pour un `ItemPrepare`.

Deux modes gouvernés par `profil.fichiers.type_motif` :

- ``template`` : le motif contient des placeholders `{champ}`
  substitués par les valeurs de l'item ; le résultat est un motif
  glob relatif à la racine (`*` et `?` conservés).
- ``regex`` : on liste tous les fichiers de la racine, et on garde
  ceux dont le chemin relatif POSIX matche la regex avec des groupes
  nommés cohérents avec les champs de l'item (ex. le groupe `cote`
  doit égaler l'item.cote).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archives_tool.config import ConfigLocale
from archives_tool.files.paths import hash_sha256, vers_posix
from archives_tool.importers.transformateur import ItemPrepare
from archives_tool.profils.schema import Profil, ResolutionFichiers


class ResolutionFichiersErreur(Exception):
    """Erreur de résolution (racine inconnue, motif invalide...)."""


@dataclass
class FichierPrepare:
    racine: str
    chemin_relatif: str  # POSIX, NFC
    nom_fichier: str
    ordre: int  # 1-indexé
    hash_sha256: str | None = None
    taille_octets: int | None = None
    format: str | None = None


def _valeurs_pour_substitution(item: ItemPrepare) -> dict[str, Any]:
    """Dict de substitution pour un motif template. cote prend la
    valeur de l'item, tous les autres champs_colonne aussi."""
    base = {"cote": item.cote}
    base.update({k: v for k, v in item.champs_colonne.items() if v is not None})
    # Champs de hierarchie accessibles aussi pour les profils qui les
    # référencent dans le motif (ex : {fonds}).
    if item.hierarchie:
        base.update(item.hierarchie)
    return base


def _lister_fichiers(racine: Path, recursif: bool) -> list[Path]:
    """Liste tous les fichiers sous racine, récursif ou non."""
    if recursif:
        return [p for p in racine.rglob("*") if p.is_file()]
    return [p for p in racine.iterdir() if p.is_file()]


def _filtrer_extensions(chemins: list[Path], extensions: list[str]) -> list[Path]:
    lot = {e.lower() for e in extensions}
    return [p for p in chemins if p.suffix.lower() in lot]


def _construire_prepare(
    chemin: Path,
    racine_disque: Path,
    nom_racine: str,
    ordre: int,
    avec_hash: bool,
) -> FichierPrepare:
    rel = chemin.relative_to(racine_disque)
    chemin_rel_posix = vers_posix(rel)
    stat = chemin.stat()
    return FichierPrepare(
        racine=nom_racine,
        chemin_relatif=chemin_rel_posix,
        nom_fichier=chemin.name,
        ordre=ordre,
        hash_sha256=hash_sha256(chemin) if avec_hash else None,
        taille_octets=stat.st_size,
        format=chemin.suffix.lower().lstrip("."),
    )


def _resoudre_template(
    item: ItemPrepare,
    reso: ResolutionFichiers,
    racine_disque: Path,
    avec_hash: bool,
) -> list[FichierPrepare]:
    substitutions = _valeurs_pour_substitution(item)
    try:
        motif = reso.motif_chemin.format(**substitutions)
    except KeyError as e:
        raise ResolutionFichiersErreur(
            f"Motif template référence un champ absent de l'item : {e}"
        ) from e
    # glob.glob / Path.glob ne supporte pas les motifs absolus ; on
    # reste relatif à la racine. Les motifs sans wildcard matchent le
    # fichier unique de ce nom, ce qui est exactement ce qu'on veut.
    iterateur = (
        racine_disque.rglob(motif) if reso.recursif else racine_disque.glob(motif)
    )
    chemins = [p for p in iterateur if p.is_file()]
    chemins = _filtrer_extensions(chemins, reso.extensions)
    # Tri NFC-stable par chemin relatif.
    chemins.sort(key=lambda p: vers_posix(p.relative_to(racine_disque)))
    return [
        _construire_prepare(p, racine_disque, reso.racine, i + 1, avec_hash)
        for i, p in enumerate(chemins)
    ]


def _valeur_pour_groupe(item: ItemPrepare, nom: str) -> Any:
    if nom == "cote":
        return item.cote
    if nom in item.champs_colonne:
        return item.champs_colonne[nom]
    if item.hierarchie and nom in item.hierarchie:
        return item.hierarchie[nom]
    return None


def _resoudre_regex(
    item: ItemPrepare,
    reso: ResolutionFichiers,
    racine_disque: Path,
    avec_hash: bool,
) -> list[FichierPrepare]:
    pattern = re.compile(reso.motif_chemin)
    chemins_candidats = _lister_fichiers(racine_disque, reso.recursif)
    chemins_candidats = _filtrer_extensions(chemins_candidats, reso.extensions)

    matchs: list[Path] = []
    for p in chemins_candidats:
        rel_posix = vers_posix(p.relative_to(racine_disque))
        m = pattern.search(rel_posix)
        if m is None:
            continue
        groupes = m.groupdict()
        # Chaque groupe nommé doit être cohérent avec la valeur
        # correspondante de l'item (si on peut la déterminer).
        coherent = True
        for nom, valeur_fichier in groupes.items():
            attendu = _valeur_pour_groupe(item, nom)
            if attendu is not None and str(attendu) != valeur_fichier:
                coherent = False
                break
        if coherent:
            matchs.append(p)

    matchs.sort(key=lambda p: vers_posix(p.relative_to(racine_disque)))
    return [
        _construire_prepare(p, racine_disque, reso.racine, i + 1, avec_hash)
        for i, p in enumerate(matchs)
    ]


def resoudre_fichiers_pour_item(
    item: ItemPrepare,
    profil: Profil,
    config: ConfigLocale,
    avec_hash: bool = False,
) -> list[FichierPrepare]:
    """Cherche les fichiers de l'item selon `profil.fichiers`.

    Args:
        item: item préparé (cote et éventuelle hierarchie obligatoires).
        profil: profil d'import validé.
        config: config locale qui mappe racine logique → chemin disque.
        avec_hash: si True, calcule le SHA-256 de chaque fichier
            (activer en mode réel, désactiver en dry-run pur).

    Raises:
        ResolutionFichiersErreur: racine inconnue dans la config ou
            non-dossier sur disque.
    """
    if profil.fichiers is None:
        return []

    reso = profil.fichiers
    if reso.racine not in config.racines:
        raise ResolutionFichiersErreur(
            f"Racine logique inconnue dans la config : {reso.racine!r}. "
            f"Racines déclarées : {sorted(config.racines)}"
        )
    racine_disque = config.racines[reso.racine]
    if not racine_disque.is_dir():
        raise ResolutionFichiersErreur(
            f"Racine {reso.racine!r} pointe vers un dossier inexistant : {racine_disque}"
        )

    if reso.type_motif == "template":
        return _resoudre_template(item, reso, racine_disque, avec_hash)
    return _resoudre_regex(item, reso, racine_disque, avec_hash)
