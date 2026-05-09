"""Génération de squelettes de profil YAML.

Deux fonctions exposées :
- :func:`generer_squelette` : profil minimal commenté à partir
  d'options basiques (cote, titre, chemin du tableur).
- :func:`analyser_tableur` : profil enrichi avec les colonnes
  détectées dans un tableur, mappées par défaut vers
  ``metadonnees.<slug>``, avec heuristique de détection des
  champs structurants (cote, titre, date, ...).

Le YAML est construit comme une chaîne, ligne par ligne, plutôt que
via ``yaml.dump`` : les commentaires d'aide à l'utilisateur sont une
fonctionnalité de premier ordre, et PyYAML ne les préserve pas.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Literal

from archives_tool.exporters.mapping_dc import DC, MAPPING_DC

# Inversion URI Dublin Core → champ dédié interne, calculée une fois.
# On ignore les clés `metadonnees.*` du mapping : on ne reconnaît que
# les colonnes dédiées d'`Item` (cote, titre, date, ...).
_DC_INVERSE: dict[str, str] = {
    uri: champ for champ, uri in MAPPING_DC.items() if "." not in champ
}

# Détection nom de colonne → champ structurant (heuristique conservatrice).
# En cas de doute on range plutôt dans metadonnees, qu'on impose au
# code une fausse détection ennuyeuse à corriger.
_HEURISTIQUES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^cote$|^cote_collection$|^côte$", re.IGNORECASE), "cote"),
    (re.compile(r"^titre$|^title$", re.IGNORECASE), "titre"),
    (re.compile(r"^date$", re.IGNORECASE), "date"),
    (re.compile(r"^annee$|^année$|^year$", re.IGNORECASE), "annee"),
    (
        re.compile(r"^numero$|^numéro$|^num$|^n°$|^number$", re.IGNORECASE),
        "numero",
    ),
    (
        re.compile(r"^langue$|^langage$|^language$|^lang$", re.IGNORECASE),
        "langue",
    ),
    (
        re.compile(r"^description$|^desc$|^résumé$|^resume$|^summary$", re.IGNORECASE),
        "description",
    ),
]


def _yaml_str(s: str) -> str:
    """Encode une chaîne pour YAML — toujours JSON-quoté.

    Le JSON est un sous-ensemble du YAML pour les chaînes scalaires.
    Toujours quoter évite les ambiguïtés (ex. ``no`` → bool, ``1.0``
    → float, ``"none"`` → reste une chaîne et pas une sentinelle
    nulle accidentelle).
    """
    return json.dumps(s, ensure_ascii=False)


def _slugifier(nom: str) -> str:
    """Normalise un nom de colonne en slug pour ``metadonnees.<slug>``.

    Cohérent avec la transformation ``slug`` de l'importer (lower +
    strip_accents + non-alphanum → ``_`` + collapse + strip), mais
    avec ``_`` au lieu de ``-`` pour rester dans une convention de
    clé Python/JSON.
    """
    nfd = unicodedata.normalize("NFD", nom.lower())
    sans = "".join(c for c in nfd if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sans).strip("_")
    return slug or "champ"


def _detecter_champ_structurant(nom_colonne: str) -> str | None:
    """Renvoie le nom du champ dédié si détecté, ``None`` sinon.

    Reconnaît :
    - les URI Dublin Core (via :data:`_DC_INVERSE`) ;
    - quelques noms de colonnes usuels (cote, titre, date, ...) ;
    - les colonnes contenant "doi" et "nakala" → ``doi_nakala``.
    """
    nom = nom_colonne.strip()
    if nom.startswith(DC) and nom in _DC_INVERSE:
        return _DC_INVERSE[nom]
    for pattern, champ in _HEURISTIQUES:
        if pattern.match(nom):
            return champ
    bas = nom.lower()
    if "doi" in bas and "nakala" in bas:
        return "doi_nakala"
    return None


def _entete_squelette(
    cote: str, titre: str, chemin: str, mappings_vides: bool
) -> list[str]:
    today = date.today().isoformat()
    lignes = [
        "# Profil d'import — généré automatiquement",
        f"# Date : {today}",
        "# À ajuster selon vos besoins avant utilisation.",
    ]
    if mappings_vides:
        lignes += [
            "# ⚠ Le mapping doit être complété (au moins la cote) avant",
            "#   le premier import — sinon transformer_ligne échouera.",
        ]
    lignes += [
        "",
        "version_profil: 2",
        "",
        "fonds:",
        f"  cote: {_yaml_str(cote)}",
        f"  titre: {_yaml_str(titre)}",
        "  # Décommentez et remplissez les champs pertinents :",
        '  # description: ""',
        '  # description_publique: "Notice publique pour les exports DC/Nakala."',
        '  # description_interne: "Notes équipe sur ce chantier"',
        '  # personnalite_associee: ""',
        '  # responsable_archives: ""',
        '  # editeur: ""',
        '  # lieu_edition: ""',
        '  # periodicite: ""',
        '  # date_debut: ""',
        '  # date_fin: ""',
        '  # issn: ""',
        "",
        "# Personnalisations optionnelles de la collection miroir.",
        "# La miroir est créée automatiquement avec le fonds : par défaut",
        "# elle hérite de cote/titre. Décommenter pour overrider.",
        "# collection_miroir:",
        '#   titre: "Titre alternatif de la miroir"',
        '#   description_publique: ""',
        '#   phase: "catalogage"',
        '#   doi_nakala: ""',
        "",
        "tableur:",
        f"  chemin: {_yaml_str(chemin)}",
        '  # feuille: "Hoja 1"  # première feuille Excel par défaut',
        "  ligne_entete: 1",
        "  # lignes_ignorer_apres_entete: 0  # sauter des lignes de notes",
        "  valeurs_nulles:",
    ]
    for v in ["none", "n/a", "s.d.", "NaN", ""]:
        lignes.append(f"    - {_yaml_str(v)}")
    lignes += [
        '  # separateur_csv: ";"  # si CSV',
        '  # encodage: "utf-8"',
        "",
    ]
    return lignes


def _pied_squelette() -> list[str]:
    return [
        "",
        "# Section fichiers : où trouver les scans associés aux items.",
        "# Décommentez et adaptez si l'import doit rattacher des scans.",
        "# fichiers:",
        '#   racine: "scans"  # nom logique défini dans la config locale',
        '#   motif_chemin: "{cote}/*.tif"',
        '#   type_motif: "template"',
        "#   recursif: true",
        "#   extensions:",
        '#     - ".tif"',
        '#     - ".tiff"',
        '#     - ".jpg"',
        '#     - ".jpeg"',
        '#     - ".pdf"',
        "",
        "# Décomposition automatique de la cote (optionnel).",
        "# Utile pour les cotes hiérarchiques type FA-AA-00-01.",
        "# decomposition_cote:",
        '#   regex: "^(?P<fonds>[A-Z]+)-(?P<sous_fonds>[A-Z]+)-(?P<serie>\\\\d+)-(?P<numero>\\\\d+)$"',
        '#   stockage: "hierarchie"',
        "",
        "# Valeurs par défaut écrites sur chaque item importé.",
        "# La valeur du tableur prime si elle est présente.",
        "# valeurs_par_defaut:",
        '#   langue: "fra"',
        '#   etat_catalogage: "brouillon"',
    ]


def _section_granularite(granularite: str) -> list[str]:
    return [
        f"granularite_source: {granularite}",
        '# "item"    : une ligne du tableur = un item (un numéro, un volume).',
        '# "fichier" : une ligne = un fichier ; les items sont regroupés',
        "#            par cote au moment de l'import.",
        "",
    ]


def _gabarit(
    cote: str,
    titre: str,
    chemin: str,
    granularite: str,
    mappings: list[tuple[str, str, bool]],
) -> str:
    """Assemble le YAML final.

    ``mappings`` est une liste de ``(champ_cible, source, detecte)``.
    Si ``mappings`` est vide, un TODO est inséré dans la section
    ``mapping``.
    """
    lignes = _entete_squelette(cote, titre, chemin, mappings_vides=not mappings)
    lignes += _section_granularite(granularite)
    lignes.append("mapping:")

    if not mappings:
        lignes += [
            "  # TODO : remplacer le placeholder par le nom de la colonne",
            "  #        cote dans votre tableur, et ajouter d'autres mappings.",
            "  # Exemple :",
            '  #   cote: "Cote"',
            '  #   titre: "Titre"',
            "  #   metadonnees.auteurs:",
            '  #     source: "Auteurs"',
            '  #     separateur: " / "',
            '  cote: "A_REMPLACER"',
        ]
    else:
        detectes = [(c, s) for c, s, det in mappings if det]
        autres = [(c, s) for c, s, det in mappings if not det]
        if detectes:
            lignes.append(
                "  # Champs structurants détectés automatiquement (à vérifier) :"
            )
            for cible, source in detectes:
                lignes.append(f"  {cible}: {_yaml_str(source)}  # détecté")
        if autres:
            if detectes:
                lignes.append("")
            lignes.append("  # Colonnes restantes, mappées vers metadonnees.<slug>.")
            lignes.append("  # Renommez ou supprimez selon ce que vous voulez en base.")
            for cible, source in autres:
                lignes.append(f"  {cible}: {_yaml_str(source)}")

    lignes += _pied_squelette()
    return "\n".join(lignes) + "\n"


def generer_squelette(
    cote_collection: str,
    titre_collection: str,
    chemin_tableur: str,
    granularite: Literal["item", "fichier"] = "item",
) -> str:
    """Squelette minimal de profil YAML, à compléter manuellement.

    Le YAML retourné a un mapping vide marqué TODO : il charge en
    Pydantic mais l'import échouera tant que la cote n'est pas mappée.
    """
    return _gabarit(
        cote=cote_collection,
        titre=titre_collection,
        chemin=chemin_tableur,
        granularite=granularite,
        mappings=[],
    )


def analyser_tableur(
    chemin_tableur: Path,
    feuille: str | None = None,
    cote_collection: str | None = None,
    titre_collection: str | None = None,
) -> str:
    """Lit un tableur et produit un profil pré-rempli.

    Détection :
    - les colonnes dont le nom matche une heuristique
      (:func:`_detecter_champ_structurant`) sont mappées au champ
      dédié correspondant, marquées ``# détecté`` ;
    - les autres vont dans ``metadonnees.<slug>``.

    En cas de plusieurs colonnes candidates pour le même champ dédié
    (ex. deux colonnes "Titre"), seule la première gagne — les
    suivantes basculent en ``metadonnees.``.
    """
    import pandas as pd  # import local : pandas est lourd

    chemin = Path(chemin_tableur)
    if not chemin.is_file():
        raise FileNotFoundError(f"Tableur introuvable : {chemin}")

    ext = chemin.suffix.lower()
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(
                chemin,
                sheet_name=feuille if feuille else 0,
                dtype=str,
                nrows=500,
            )
        elif ext in (".csv", ".tsv"):
            sep = "\t" if ext == ".tsv" else ";"
            df = pd.read_csv(chemin, sep=sep, encoding="utf-8", dtype=str, nrows=500)
        else:
            raise ValueError(f"Extension non supportée : {ext}")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Lecture du tableur impossible : {e}") from e

    mappings: list[tuple[str, str, bool]] = []
    dedies_pris: set[str] = set()
    slugs_pris: set[str] = set()

    for col in df.columns:
        nom = str(col)
        champ_dedie = _detecter_champ_structurant(nom)
        if champ_dedie and champ_dedie not in dedies_pris:
            dedies_pris.add(champ_dedie)
            mappings.append((champ_dedie, nom, True))
            continue
        slug = _slugifier(nom)
        # Dé-doublonnage si deux colonnes produisent le même slug.
        base = slug
        n = 2
        while slug in slugs_pris:
            slug = f"{base}_{n}"
            n += 1
        slugs_pris.add(slug)
        mappings.append((f"metadonnees.{slug}", nom, False))

    return _gabarit(
        cote=cote_collection or "A_COMPLETER",
        titre=titre_collection or "À compléter",
        chemin=chemin.name,
        granularite="item",
        mappings=mappings,
    )
