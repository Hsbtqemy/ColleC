"""Lecture d'un tableur (CSV ou Excel) selon un profil d'import.

Retourne une liste de dictionnaires `{nom_colonne: valeur}`. Les
valeurs sont déjà normalisées :
- chaînes strip + NFC ;
- sentinelles de `profil.tableur.valeurs_nulles` → `None` ;
- NaN pandas → `None`.

Les types ne sont pas inférés : toutes les cellules sont lues en
`dtype=str` pour préserver les dates archivistiques incertaines
(« s.d. », « vers 1923 ») telles quelles. Le mapping en aval se
chargera de l'interprétation.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

from archives_tool.profils.schema import Profil


class LectureTableurErreur(Exception):
    """Erreur de lecture du tableur (fichier absent, feuille manquante, ...)."""


def _normaliser_cellule(valeur: Any, valeurs_nulles: set[str]) -> Any:
    if valeur is None:
        return None
    # pandas renvoie NaN (float) pour les cellules vides.
    try:
        if pd.isna(valeur):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valeur, str):
        brut = unicodedata.normalize("NFC", valeur.strip())
        if brut in valeurs_nulles:
            return None
        return brut
    return valeur


def _chemin_tableur(profil: Profil, chemin_profil: Path) -> Path:
    brut = Path(profil.tableur.chemin)
    if brut.is_absolute():
        return brut
    return (chemin_profil.parent / brut).resolve()


def lire_tableur(profil: Profil, chemin_profil: Path) -> list[dict[str, Any]]:
    """Lit le tableur décrit par `profil.tableur` et renvoie les lignes.

    Args:
        profil: profil d'import déjà validé.
        chemin_profil: chemin du YAML du profil — sert à résoudre le
            chemin relatif du tableur.

    Raises:
        LectureTableurErreur: fichier introuvable, feuille inexistante,
            encodage invalide, extension non gérée.
    """
    chemin = _chemin_tableur(profil, chemin_profil)
    if not chemin.is_file():
        raise LectureTableurErreur(f"Fichier tableur introuvable : {chemin}")

    tab = profil.tableur
    ext = chemin.suffix.lower()

    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(
                chemin,
                sheet_name=tab.feuille if tab.feuille else 0,
                header=tab.ligne_entete - 1,
                skiprows=(
                    range(
                        tab.ligne_entete,
                        tab.ligne_entete + tab.lignes_ignorer_apres_entete,
                    )
                    if tab.lignes_ignorer_apres_entete
                    else None
                ),
                dtype=str,
                engine="openpyxl",
            )
        elif ext in (".csv", ".tsv"):
            sep = "\t" if ext == ".tsv" else tab.separateur_csv
            df = pd.read_csv(
                chemin,
                sep=sep,
                encoding=tab.encodage,
                header=tab.ligne_entete - 1,
                skiprows=(
                    range(
                        tab.ligne_entete,
                        tab.ligne_entete + tab.lignes_ignorer_apres_entete,
                    )
                    if tab.lignes_ignorer_apres_entete
                    else None
                ),
                dtype=str,
                keep_default_na=True,
            )
        else:
            raise LectureTableurErreur(f"Extension non supportée : {ext}")
    except FileNotFoundError as e:
        raise LectureTableurErreur(f"Fichier tableur introuvable : {chemin}") from e
    except ValueError as e:
        # pandas lève ValueError pour feuille inexistante, encodage KO, etc.
        raise LectureTableurErreur(f"Lecture du tableur impossible : {e}") from e
    except UnicodeDecodeError as e:
        raise LectureTableurErreur(
            f"Encodage invalide ({tab.encodage}) pour {chemin} : {e}"
        ) from e

    # Noms de colonnes normalisés NFC (les valeurs le seront cellule par cellule).
    df.columns = [
        unicodedata.normalize("NFC", str(c)) if isinstance(c, str) else c
        for c in df.columns
    ]

    valeurs_nulles = set(tab.valeurs_nulles)
    lignes: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ligne: dict[str, Any] = {}
        for col in df.columns:
            ligne[col] = _normaliser_cellule(row[col], valeurs_nulles)
        lignes.append(ligne)
    return lignes
