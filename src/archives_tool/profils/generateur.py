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

# Pattern nominatif de la colonne « cote » — exporté pour être
# réutilisé par `importers.lecteur_tableur._identifier_colonne_cote`
# (le fallback de classif par-item/fichier de V0.9.2-import #1 doit
# utiliser le MÊME pattern que la détection structurante, sinon un
# drift entre les deux casse silencieusement la classif).
PATTERN_COTE = re.compile(r"^cote$|^cote_collection$|^cote_item$|^côte$", re.IGNORECASE)

# Détection nom de colonne → champ structurant (heuristique conservatrice).
# En cas de doute on range plutôt dans metadonnees, qu'on impose au
# code une fausse détection ennuyeuse à corriger.
#
# La cible peut être :
# - un champ dédié d'Item ("cote", "titre", "doi_nakala"...) ;
# - un champ dédié de Fichier ("fichier.nom_fichier"...) ;
# - une métadonnée DC fréquente ("metadonnees.auteur"...) traitée comme
#   champ dédié (un seul mapping possible).
_HEURISTIQUES: list[tuple[re.Pattern[str], str]] = [
    # --- Champs structurants Item ---
    (PATTERN_COTE, "cote"),
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
        re.compile(
            r"^description$|^desc$|^résumé$|^resume$|^summary$",
            re.IGNORECASE,
        ),
        "description",
    ),
    # `^type$` est ambigu : peut désigner `type_coar` (catégorie
    # documentaire, niveau item) OU `type_page` (couverture/planche,
    # niveau fichier). On défaut sur `type_coar` car c'est le cas
    # dominant dans les exports DC/Nakala. Si le tableur décrit en
    # vrai des types de page, l'utilisateur remappe en mode avancé.
    (
        re.compile(
            r"^type$|^type_coar$|^type_document$|^doctype$",
            re.IGNORECASE,
        ),
        "type_coar",
    ),
    # Identifiant DOI sur l'item. Le cas spécial "doi" + "nakala" dans
    # `_detecter_champ_structurant` reste pour les composés (`doi nakala
    # item`, ...). Ici on capture les noms courts usuels.
    (re.compile(r"^doi$|^doi_item$|^item_doi$", re.IGNORECASE), "doi_nakala"),
    # Tolérant à l'espace / tiret / underscore entre `doi` et
    # `collection` : sur Nakala, les exports utilisent souvent
    # « DOI collection » avec espace plutôt qu'un slug technique.
    (
        re.compile(
            r"^doi[\s_-]?collection$|^collection[\s_-]?doi$",
            re.IGNORECASE,
        ),
        "doi_collection_nakala",
    ),
    # --- Champs Fichier ---
    (
        re.compile(
            r"^filename$|^file_?name$|^nom_fichier$|^fichier$|^file$|^name$",
            re.IGNORECASE,
        ),
        "fichier.nom_fichier",
    ),
    (
        re.compile(
            r"^hash$|^sha$|^sha256$|^hash_?sha256$|^checksum$|^empreinte$",
            re.IGNORECASE,
        ),
        "fichier.hash_sha256",
    ),
    (
        re.compile(
            r"^iiif$|^iiif_url$|^iiif_url_nakala$|^info\.json$|^info_json$",
            re.IGNORECASE,
        ),
        "fichier.iiif_url_nakala",
    ),
    # --- Métadonnées DC fréquentes (rangées dans Item.metadonnees) ---
    (
        re.compile(
            r"^auteur$|^auteurs$|^author$|^authors$|^creator$|^createur$|^créateur$",
            re.IGNORECASE,
        ),
        "metadonnees.auteur",
    ),
    (
        re.compile(r"^editeur$|^éditeur$|^publisher$", re.IGNORECASE),
        "metadonnees.editeur",
    ),
    (
        re.compile(
            r"^contributeur$|^contributeurs$|^contributor$|^contributors$",
            re.IGNORECASE,
        ),
        "metadonnees.contributeur",
    ),
    (
        re.compile(
            r"^sujet$|^sujets$|^subject$|^subjects$"
            r"|^mots[-_ ]?cles?$|^mots[-_ ]?clés$|^keywords?$",
            re.IGNORECASE,
        ),
        "metadonnees.sujet",
    ),
    (
        re.compile(r"^droits$|^licence$|^license$|^rights$", re.IGNORECASE),
        "metadonnees.droits",
    ),
    (re.compile(r"^source$|^sources$", re.IGNORECASE), "metadonnees.source"),
]

# Patterns qui forcent un classement en niveau-fichier (préfixe
# `fichier.metadonnees.<slug>`) sans être un champ dédié unique :
# plusieurs colonnes peuvent y atterrir (chacune avec son propre slug).
# Concerne typiquement les URLs Nakala (data_url, embed_url, ...) et les
# vignettes — varient page-par-page, doivent donc vivre côté Fichier
# pour éviter les warnings de divergence à la fusion par cote.
_HEURISTIQUES_FICHIER_META: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^thumb$|^thumbnail$|^thumb_url$|^vignette$|^miniature$", re.IGNORECASE
    ),
    re.compile(
        r"^data_url$|^embed_url$|^preview_url$"
        r"|^url_data$|^url_embed$|^url_preview$",
        re.IGNORECASE,
    ),
)


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


def slug_metadonnee(nom: str, pris: set[str]) -> str:
    """Slug de colonne pour `metadonnees.<slug>`, dédoublonné.

    Slugifie `nom`, puis suffixe `_2`, `_3`… tant que le slug est déjà
    dans `pris` (deux colonnes distinctes peuvent slugifier pareil).
    Le slug retenu est ajouté à `pris` — l'appelant n'a rien à faire.
    """
    slug = _slugifier(nom)
    base, n = slug, 2
    while slug in pris:
        slug = f"{base}_{n}"
        n += 1
    pris.add(slug)
    return slug


def _detecter_champ_structurant(nom_colonne: str) -> str | None:
    """Renvoie le nom du champ dédié si détecté, ``None`` sinon.

    Reconnaît :
    - les URI Dublin Core (via :data:`_DC_INVERSE`) ;
    - les patterns de :data:`_HEURISTIQUES` (cote, titre, fichier.*,
      metadonnees.auteur, ...) ;
    - les colonnes composées contenant "doi" et "nakala" → ``doi_nakala``.
    """
    nom = nom_colonne.strip()
    if nom.startswith(DC) and nom in _DC_INVERSE:
        return _DC_INVERSE[nom]
    for pattern, champ in _HEURISTIQUES:
        if pattern.match(nom):
            return champ
    bas = nom.lower()
    if "doi" in bas and "nakala" in bas:
        # "doi collection nakala", "doi_nakala_collection"… → DOI de la
        # collection Nakala (champ dédié distinct du DOI de l'item).
        if "collection" in bas:
            return "doi_collection_nakala"
        return "doi_nakala"
    return None


def _est_pattern_fichier_meta(nom_colonne: str) -> bool:
    """Vrai si le nom de colonne désigne typiquement une donnée propre
    à un scan (thumb, URLs Nakala data/embed/preview...).

    Pour ces colonnes, l'heuristique pré-remplit
    ``fichier.metadonnees.<slug>`` plutôt que ``metadonnees.<slug>`` —
    elles varieraient par-page sinon et déclencheraient des warnings
    de divergence à la fusion par cote.
    """
    nom = nom_colonne.strip()
    return any(p.match(nom) for p in _HEURISTIQUES_FICHIER_META)


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


def proposer_mapping(colonnes: list[str]) -> list[tuple[str, str, bool]]:
    """Propose un mapping colonne → champ depuis les noms de colonnes.

    Renvoie une liste de triplets `(champ_cible, colonne, detecte)` :
    - `detecte=True` : la colonne a matché un pattern connu — soit un
      champ dédié (cote, fichier.nom_fichier, metadonnees.auteur...),
      soit forcée en `fichier.metadonnees.<slug>` (thumb, URLs Nakala
      par-page) ;
    - `detecte=False` : pas de pattern → `metadonnees.<slug>`.

    En cas de plusieurs colonnes candidates pour le même champ dédié
    (ex. deux « Titre »), seule la première gagne ; les suivantes
    basculent en `metadonnees.`. Les slugs en collision sont suffixés.
    """
    mappings: list[tuple[str, str, bool]] = []
    dedies_pris: set[str] = set()
    slugs_pris: set[str] = set()
    slugs_pris_fichier: set[str] = set()

    for nom in colonnes:
        champ_dedie = _detecter_champ_structurant(nom)
        if champ_dedie and champ_dedie not in dedies_pris:
            dedies_pris.add(champ_dedie)
            mappings.append((champ_dedie, nom, True))
            continue
        if _est_pattern_fichier_meta(nom):
            slug = slug_metadonnee(nom, slugs_pris_fichier)
            mappings.append((f"fichier.metadonnees.{slug}", nom, True))
            continue
        slug = slug_metadonnee(nom, slugs_pris)
        mappings.append((f"metadonnees.{slug}", nom, False))
    return mappings


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
    """
    from archives_tool.importers.lecteur_tableur import (
        LectureTableurErreur,
        lire_entetes_tableur,
    )

    chemin = Path(chemin_tableur)
    if not chemin.is_file():
        raise FileNotFoundError(f"Tableur introuvable : {chemin}")

    # Lecture des en-têtes mutualisée avec le reste de l'application.
    # `analyser_tableur` n'exploite que les noms de colonnes — l'erreur
    # de lecture est traduite en `ValueError` (contrat historique).
    try:
        colonnes = lire_entetes_tableur(chemin, feuille)
    except LectureTableurErreur as e:
        raise ValueError(str(e)) from e

    return _gabarit(
        cote=cote_collection or "A_COMPLETER",
        titre=titre_collection or "À compléter",
        chemin=chemin.name,
        granularite="item",
        mappings=proposer_mapping(colonnes),
    )
