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

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from archives_tool.profils.generateur import PATTERN_COTE
from archives_tool.profils.schema import Profil


class LectureTableurErreur(Exception):
    """Erreur de lecture du tableur (fichier absent, feuille manquante, ...)."""


# Extensions de tableur reconnues par le lecteur.
EXTENSIONS_TABLEUR: frozenset[str] = frozenset(
    {".xlsx", ".xls", ".csv", ".tsv"}
)

# Sentinelles nulles par défaut, utilisées par l'analyse de colonnes
# avant que le profil n'existe (l'assistant n'a pas encore la liste
# `valeurs_nulles` du profil cible). Mêmes valeurs que le défaut du
# schéma Profil (`TableurConfig.valeurs_nulles`), en case-insensible.
_VALEURS_NULLES_DEFAUT: frozenset[str] = frozenset(
    {"", "none", "n/a", "s.d.", "nan"}
)

# Nombre max de lignes lues pour l'analyse d'échantillonnage. Au-delà,
# les stats reflètent un échantillon, pas le total — acceptable pour
# l'usage (donner un aperçu de chaque colonne à l'utilisateur).
N_LIGNES_ECHANTILLON_MAX = 5000

# Pattern nom de colonne candidate à être la cote (utilisé pour la
# classification par-item / par-fichier de V0.9.2-import #1). Importé
# de `profils.generateur` pour éviter le drift entre la détection
# structurante (proposer_mapping) et le fallback de classif —
# centralisation T3 de la passe « trous documentés » V0.9.x.
_PATTERN_COTE_CANDIDATE = PATTERN_COTE

# Patterns à exclure du fallback « première colonne 100 % unique » de
# `_identifier_colonne_cote`. Sans cette exclusion, un tableur où
# `filename` (typiquement 100 % unique) précéderait la vraie cote
# verrait `filename` pris pour cote — et la classif de toutes les
# autres colonnes basculerait en erreur (la moitié des colonnes
# par-item sortirait `par-fichier` parce que les groupes de filename
# n'ont qu'une ligne chacun).
#
# Patterns alignés sur `profils.generateur._HEURISTIQUES` (champs fichier
# dédiés) + `_HEURISTIQUES_FICHIER_META` (URLs Nakala par-page). Test
# d'usage sur PF (2026-05-23) a révélé que `data_url`/`preview_url`/etc.
# étaient pris pour cote à la place de `Nouvelle cote` (dupliquée sur
# tous les scans, donc pas 100 % unique au global) — d'où ajout de
# ces patterns ici.
_PATTERNS_COTE_EXCLUS_DU_FALLBACK: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^filename$|^file_?name$|^nom_fichier$|^fichier$|^file$|^name$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^hash$|^sha$|^sha256$|^hash_?sha256$|^checksum$|^empreinte$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^iiif$|^iiif_url$|^iiif_url_nakala$|^info\.json$|^info_json$",
        re.IGNORECASE,
    ),
    re.compile(r"^doi$|^doi_item$|^doi_collection$", re.IGNORECASE),
    # URLs Nakala par-page (data_url = URL du fichier, preview_url =
    # vignette, embed_url = lecteur intégré, thumb = miniature).
    # Toujours 100 % uniques sur un export Nakala typique.
    re.compile(
        r"^data_url$|^embed_url$|^preview_url$|^thumb$|^thumbnail$",
        re.IGNORECASE,
    ),
)

# Seuils de classification d'une colonne en par-item / par-fichier
# (V0.9.2-import #1). Pour chaque groupe (= ensemble des lignes d'une
# même cote) on compte le nb de valeurs distinctes dans la colonne.
# Au-delà du seuil par-item, on considère la colonne comme stable au
# sein d'un item (donc métadonnée d'item). Au-delà du seuil par-fichier,
# on considère qu'elle varie au sein d'une cote (donc propre au scan).
_SEUIL_PAR_ITEM = 0.90
_SEUIL_PAR_FICHIER = 0.50


def lire_entetes_tableur(
    chemin: Path, feuille: str | None = None
) -> list[str]:
    """Lit la seule ligne d'en-tête d'un tableur et renvoie ses colonnes.

    Lecture minimale (`nrows=1`) — utilisée par l'assistant d'import
    web et par `profils.generateur.analyser_tableur`. Pour les CSV,
    tente UTF-8 puis CP1252 (tableurs anciens sous Windows). Lève
    `LectureTableurErreur` si l'extension est inconnue ou le fichier
    illisible.
    """
    chemin = Path(chemin)
    ext = chemin.suffix.lower()
    if ext not in EXTENSIONS_TABLEUR:
        raise LectureTableurErreur(f"Extension non supportée : {ext!r}.")
    if not chemin.is_file():
        raise LectureTableurErreur(f"Fichier tableur introuvable : {chemin}")
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(
                chemin,
                sheet_name=feuille if feuille else 0,
                dtype=str,
                nrows=1,
            )
        else:
            sep = "\t" if ext == ".tsv" else ";"
            try:
                df = pd.read_csv(
                    chemin, sep=sep, encoding="utf-8", dtype=str, nrows=1
                )
            except UnicodeDecodeError:
                df = pd.read_csv(
                    chemin, sep=sep, encoding="cp1252", dtype=str, nrows=1
                )
    except LectureTableurErreur:
        raise
    except Exception as e:  # noqa: BLE001 — toute erreur pandas → message propre
        raise LectureTableurErreur(
            f"Lecture du tableur impossible : {e}"
        ) from e

    colonnes = [str(c).strip() for c in df.columns]
    if not colonnes:
        raise LectureTableurErreur("Le tableur ne contient aucune colonne.")
    return colonnes


def _normaliser_pour_analyse(valeur: Any) -> str | None:
    """Cellule → ``str`` normalisée NFC, ou ``None`` si nulle/sentinelle.

    Utilisé pour l'analyse d'échantillonnage avant que le profil
    n'existe — diffère de :func:`_normaliser_cellule` qui prend la
    liste `valeurs_nulles` du profil en paramètre.
    """
    if valeur is None:
        return None
    try:
        if pd.isna(valeur):
            return None
    except (TypeError, ValueError):
        pass
    brut = valeur if isinstance(valeur, str) else str(valeur)
    brut = unicodedata.normalize("NFC", brut.strip())
    if brut.lower() in _VALEURS_NULLES_DEFAUT:
        return None
    return brut


def _identifier_colonne_cote(
    df: pd.DataFrame, cote_col_force: str | None = None
) -> str | None:
    """Devine quelle colonne du dataframe identifie chaque item.

    Si `cote_col_force` est fourni (et existe dans le df), il est
    retourné tel quel. Utilisé par l'assistant d'import quand
    l'utilisateur a explicitement choisi sa cote en mode simple —
    on contourne l'auto-détection pour recalculer la classif des
    autres colonnes par rapport à la cote choisie (cf. bug PF
    2026-05-23 : la cote "Nouvelle cote" répétée sur tous les scans
    n'était pas 100 % unique, donc invisible au fallback).

    Sinon stratégie en deux temps :
    1. Pattern nominatif (cote, cote_item, ...).
    2. Fallback : première colonne dont toutes les valeurs non-nulles
       sont distinctes (et au moins 2 lignes peuplées). Ce critère
       est strict — une colonne avec une seule valeur dupliquée
       casserait l'unicité. Les colonnes typiquement par-page
       (filename, hash, iiif, doi, URLs Nakala) sont exclues du
       fallback : sinon un tableur où elles précèdent la vraie cote
       verrait l'une d'elles faussement prise pour cote et casserait
       toutes les classifs en aval.

    Renvoie ``None`` si rien ne convient — la classif des autres
    colonnes basculera alors en ``indetermine``.
    """
    if cote_col_force is not None:
        return cote_col_force if cote_col_force in df.columns else None
    for col in df.columns:
        if _PATTERN_COTE_CANDIDATE.match(col):
            return col
    for col in df.columns:
        if any(p.match(col) for p in _PATTERNS_COTE_EXCLUS_DU_FALLBACK):
            continue
        serie = df[col].dropna()
        if len(serie) >= 2 and int(serie.nunique()) == len(serie):
            return col
    return None


def _classer_par_item_ou_fichier(
    df: pd.DataFrame, cote_col: str, autre_col: str
) -> str:
    """Pour `autre_col`, dit si la valeur est stable au sein d'une cote.

    Retourne :
    - ``"par-item"`` : ≥90 % des cotes ont 1 seule valeur dans
      `autre_col` → métadonnée d'item ;
    - ``"par-fichier"`` : >50 % des cotes ont 2 valeurs ou plus
      → métadonnée propre au scan ;
    - ``"melange"`` : entre les deux ;
    - ``"indetermine"`` : pas assez de cotes peuplées pour conclure.
    """
    masque = df[cote_col].notna() & df[autre_col].notna()
    sub = df.loc[masque, [cote_col, autre_col]]
    if sub.empty:
        return "indetermine"
    # nunique par groupe — dropna=False sans effet ici puisqu'on a déjà
    # masqué les NaN, mais explicite par sécurité.
    counts = sub.groupby(cote_col, dropna=True)[autre_col].nunique(dropna=False)
    total_groupes = int(len(counts))
    if total_groupes < 2:
        return "indetermine"
    nb_un = int((counts == 1).sum())
    nb_plus = int((counts > 1).sum())
    if nb_un / total_groupes >= _SEUIL_PAR_ITEM:
        return "par-item"
    if nb_plus / total_groupes > _SEUIL_PAR_FICHIER:
        return "par-fichier"
    return "melange"


def analyser_colonnes_tableur(
    chemin: Path,
    feuille: str | None = None,
    n_lignes_max: int = N_LIGNES_ECHANTILLON_MAX,
    cote_col_force: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Calcule des statistiques d'échantillonnage et de classification
    par colonne.

    `cote_col_force` (V0.9.x polish 2026-05-23) : si fourni, contourne
    l'auto-détection de la colonne cote. Utile quand l'utilisateur a
    choisi sa cote en mode simple — recalculer les classifs des autres
    colonnes par rapport à la cote choisie permet la promotion auto
    en `fichier.metadonnees.<slug>` même quand la cote n'est pas
    100 % unique au global (cas tableur Nakala typique).

    Pour chaque colonne du tableur, retourne :
    - ``exemples`` : 3 premières valeurs non-nulles distinctes (ordre
      stable d'apparition) ;
    - ``valeur_frequente`` : valeur la plus fréquente (None si colonne
      vide) ;
    - ``uniques`` : nombre de valeurs distinctes non-nulles ;
    - ``remplies`` : nombre de cellules non-nulles ;
    - ``total`` : nombre de lignes lues (peut être tronqué à
      ``n_lignes_max``) ;
    - ``classif`` (V0.9.2-import #1) : ``"cote"`` pour la colonne
      identifiée comme cote, sinon ``"par-item"`` / ``"par-fichier"``
      / ``"melange"`` / ``"indetermine"`` selon la dispersion des
      valeurs au sein des cotes. ``"indetermine"`` aussi quand aucune
      cote n'a pu être devinée.

    Les sentinelles de :data:`_VALEURS_NULLES_DEFAUT` sont traitées
    comme nulles (l'assistant n'a pas encore la liste du profil cible).

    Pour les CSV, tente UTF-8 puis CP1252 (tableurs anciens sous
    Windows). Lève :class:`LectureTableurErreur` si fichier inconnu /
    illisible — même contrat que :func:`lire_entetes_tableur`.
    """
    chemin = Path(chemin)
    ext = chemin.suffix.lower()
    if ext not in EXTENSIONS_TABLEUR:
        raise LectureTableurErreur(f"Extension non supportée : {ext!r}.")
    if not chemin.is_file():
        raise LectureTableurErreur(f"Fichier tableur introuvable : {chemin}")
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(
                chemin,
                sheet_name=feuille if feuille else 0,
                dtype=str,
                nrows=n_lignes_max,
            )
        else:
            sep = "\t" if ext == ".tsv" else ";"
            try:
                df = pd.read_csv(
                    chemin,
                    sep=sep,
                    encoding="utf-8",
                    dtype=str,
                    nrows=n_lignes_max,
                )
            except UnicodeDecodeError:
                df = pd.read_csv(
                    chemin,
                    sep=sep,
                    encoding="cp1252",
                    dtype=str,
                    nrows=n_lignes_max,
                )
    except LectureTableurErreur:
        raise
    except Exception as e:  # noqa: BLE001 — toute erreur pandas → message propre
        raise LectureTableurErreur(
            f"Lecture du tableur impossible : {e}"
        ) from e

    df.columns = [
        unicodedata.normalize("NFC", str(c).strip()) for c in df.columns
    ]
    # Normalisation in-place : sentinelles + NaN → None. On a besoin
    # d'un df nettoyé pour le groupby de la classif (sinon "none" ou
    # NaN serait compté comme valeur distincte).
    for col in df.columns:
        df[col] = df[col].map(_normaliser_pour_analyse)

    total = int(len(df))
    cote_col = _identifier_colonne_cote(df, cote_col_force=cote_col_force)
    stats: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        # Après .map() qui retourne None pour les nulls, pandas peut
        # convertir ces None en NaN dans la série object — `v is not
        # None` laisserait alors passer les NaN. On filtre via isinstance
        # (le post-normalize ne contient que str ou None/NaN).
        non_nuls = [v for v in df[col].tolist() if isinstance(v, str)]

        exemples: list[str] = []
        vu: set[str] = set()
        for v in non_nuls:
            if v not in vu:
                vu.add(v)
                exemples.append(v)
                if len(exemples) >= 3:
                    break

        if non_nuls:
            valeur_frequente = Counter(non_nuls).most_common(1)[0][0]
        else:
            valeur_frequente = None

        if col == cote_col:
            classif = "cote"
        elif cote_col is None:
            classif = "indetermine"
        else:
            classif = _classer_par_item_ou_fichier(df, cote_col, col)

        stats[col] = {
            "exemples": exemples,
            "valeur_frequente": valeur_frequente,
            "uniques": len(set(non_nuls)),
            "remplies": len(non_nuls),
            "total": total,
            "classif": classif,
        }
    # Filtre les colonnes 100 % vides (typiquement `Unnamed: 15`,
    # `description_page`… — artefacts pandas de cellules fusionnées
    # ou colonnes header sans données). Sans ce filtre, mode simple
    # les promeut en `metadonnees.<slug>` libres et la page item
    # affiche `Unnamed 15: non renseigne` — bruit visuel pour 0 valeur
    # utile. La colonne cote, même 100 % vide théoriquement (cas
    # absurde), serait quand même filtrée — l'utilisateur verra
    # "colonne cote inconnue" à la soumission mode simple.
    return {
        col: s for col, s in stats.items() if s["remplies"] > 0
    }


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
