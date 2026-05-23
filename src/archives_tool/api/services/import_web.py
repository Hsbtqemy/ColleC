"""Service de l'assistant d'import web (V0.7).

Orchestre les `SessionImport` de bout en bout : cycle de vie
(création, reprise, abandon), étapes du wizard (tableur, fonds,
mapping, fichiers), puis composition d'un profil v2 et exécution de
l'import via le moteur `importers.ecrivain` — aucune logique métier
dupliquée.

Le tableur uploadé est stocké hors base, sous `data/_import_tmp/`
(gitignoré). Le chemin stocké en base est relatif à ce dossier —
jamais un chemin absolu (principe de portabilité).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.config import ConfigLocale
from archives_tool.importers.ecrivain import RapportImport, importer
from archives_tool.importers.lecteur_tableur import (
    EXTENSIONS_TABLEUR,
    LectureTableurErreur,
    analyser_colonnes_tableur,
    lire_entetes_tableur,
)
from archives_tool.models import ETAPES_IMPORT, SessionImport
from archives_tool.profils.schema import Profil

# Dossier de travail des tableurs uploadés. Sous `data/` (gitignoré),
# distinct des bases. Créé à la demande.
RACINE_IMPORT_TMP = Path("data") / "_import_tmp"

# Taille maximale d'un tableur uploadé (octets). Un inventaire reste
# petit ; cette borne protège surtout d'un upload accidentel énorme.
TAILLE_MAX_TABLEUR = 20 * 1024 * 1024  # 20 Mio


class SessionImportIntrouvable(Exception):
    """Aucune session d'import pour l'id demandé."""


class TableurInvalide(Exception):
    """Le fichier uploadé n'est pas un tableur exploitable."""


class MappingInvalide(Exception):
    """Le mapping colonnes → champs proposé n'est pas exploitable."""


class ProfilIncomplet(Exception):
    """La session ne contient pas de quoi composer un profil valide."""


# Cibles sentinelles du mapping (hors champs dédiés / metadonnées).
CIBLE_META = "__meta__"      # → metadonnees.<slug de la colonne>
CIBLE_META_FICHIER = "__meta_fichier__"  # → fichier.metadonnees.<slug>
CIBLE_IGNORE = "__ignore__"  # colonne non importée

# Clés `metadonnees.<champ>` traitées comme cibles dédiées dans
# l'assistant (l'utilisateur peut les sélectionner explicitement
# depuis le sélecteur, au lieu de la sentinelle `__meta__` générique).
# Permet au sélecteur d'exposer « Auteur », « Éditeur », etc. sans
# que ces champs deviennent des colonnes en base.
_CIBLES_META_CANONIQUES: frozenset[str] = frozenset(
    {
        "metadonnees.auteur",
        "metadonnees.editeur",
        "metadonnees.contributeur",
        "metadonnees.sujet",
        "metadonnees.droits",
        "metadonnees.source",
    }
)


def creer_session(db: Session, utilisateur: str) -> SessionImport:
    """Crée une session d'import vierge à l'étape `tableur`."""
    session = SessionImport(utilisateur=utilisateur, etape="tableur")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def lire_session(db: Session, session_id: int) -> SessionImport:
    """Charge une session par id. Lève `SessionImportIntrouvable`."""
    session = db.get(SessionImport, session_id)
    if session is None:
        raise SessionImportIntrouvable(
            f"Session d'import {session_id} introuvable."
        )
    return session


def lister_sessions_en_cours(db: Session) -> list[SessionImport]:
    """Sessions d'import non finalisées, plus récente d'abord.

    Pas de filtre par utilisateur : l'équipe est réduite et voir les
    imports en cours des collègues évite les doublons de travail.
    """
    return list(
        db.scalars(
            select(SessionImport)
            .where(SessionImport.statut == "en_cours")
            .order_by(SessionImport.cree_le.desc())
        ).all()
    )


def _chemin_tableur_absolu(session: SessionImport) -> Path | None:
    """Résout le chemin disque du tableur uploadé, ou None s'il n'y en
    a pas. `chemin_tableur` est stocké relatif à `RACINE_IMPORT_TMP`."""
    if not session.chemin_tableur:
        return None
    return RACINE_IMPORT_TMP / session.chemin_tableur


def _index_etape(etape: str) -> int:
    """Rang d'une étape dans le wizard (0 = première)."""
    return ETAPES_IMPORT.index(etape)


def _avancer_etape(session: SessionImport, vers: str) -> None:
    """Avance `session.etape` vers `vers`, sans jamais régresser.

    Re-soumettre une étape déjà franchie (l'utilisateur revient en
    arrière corriger) ne doit pas faire reculer le curseur de
    progression — `etape` mémorise le point le plus avancé atteint.
    """
    if _index_etape(vers) > _index_etape(session.etape):
        session.etape = vers


def lire_colonnes_tableur(
    chemin: Path, feuille: str | None = None
) -> list[str]:
    """Détecte les colonnes d'un tableur, en traduisant l'erreur de
    lecture en `TableurInvalide` (exception de l'assistant web).

    La lecture proprement dite est mutualisée avec le reste de
    l'application via `importers.lecteur_tableur.lire_entetes_tableur`.
    """
    try:
        return lire_entetes_tableur(chemin, feuille)
    except LectureTableurErreur as e:
        raise TableurInvalide(str(e)) from e


def attacher_tableur(
    db: Session,
    session: SessionImport,
    contenu: bytes,
    nom_origine: str,
    feuille: str | None = None,
) -> list[str]:
    """Enregistre le tableur uploadé et détecte ses colonnes.

    Le fichier est écrit sous `RACINE_IMPORT_TMP` (nom dérivé de l'id
    de session, jamais le nom uploadé — pas de path traversal). En cas
    de `TableurInvalide`, le fichier temporaire est nettoyé et rien
    n'est committé.
    """
    nom_origine = unicodedata.normalize("NFC", nom_origine)
    ext = Path(nom_origine).suffix.lower()
    if ext not in EXTENSIONS_TABLEUR:
        raise TableurInvalide(
            f"Format non supporté ({ext or 'sans extension'}). "
            "Formats acceptés : xlsx, xls, csv, tsv."
        )
    if len(contenu) > TAILLE_MAX_TABLEUR:
        raise TableurInvalide(
            f"Fichier trop volumineux ({len(contenu) // 1024 // 1024} Mio, "
            f"max {TAILLE_MAX_TABLEUR // 1024 // 1024} Mio)."
        )

    RACINE_IMPORT_TMP.mkdir(parents=True, exist_ok=True)
    nom_stocke = f"session_{session.id}{ext}"
    chemin = RACINE_IMPORT_TMP / nom_stocke
    chemin.write_bytes(contenu)

    # V0.9.2-import T2 : une seule lecture du tableur dans le cas
    # nominal. `analyser_colonnes_tableur` liste les colonnes dans son
    # dict de stats (ordre garanti depuis Python 3.7) — on en dérive
    # `colonnes_detectees` au lieu d'un second `lire_entetes_tableur`
    # à `nrows=1`. Sur PF (7466 lignes), économise ~1s d'upload.
    #
    # Fallback : si l'analyse échoue (cas dégradé — fichier exotique
    # qui plante pandas sur le full read mais que l'entête lit OK), on
    # retombe sur `lire_colonnes_tableur` pour préserver la robustesse.
    # L'utilisateur n'aura pas les stats d'échantillonnage à l'étape
    # mapping mais le wizard reste fonctionnel.
    try:
        echantillons = analyser_colonnes_tableur(chemin, feuille)
        colonnes = list(echantillons.keys())
    except LectureTableurErreur:
        try:
            colonnes = lire_colonnes_tableur(chemin, feuille)
        except TableurInvalide:
            chemin.unlink(missing_ok=True)
            raise
        echantillons = None

    if not colonnes:
        chemin.unlink(missing_ok=True)
        raise TableurInvalide("Le tableur ne contient aucune colonne.")

    session.chemin_tableur = nom_stocke
    session.nom_tableur_original = nom_origine
    session.feuille = feuille
    session.colonnes_detectees = colonnes
    session.colonnes_echantillon = echantillons
    session.modifie_le = datetime.now()
    _avancer_etape(session, "fonds")
    db.commit()
    return colonnes


def enregistrer_fonds(
    db: Session,
    session: SessionImport,
    fonds_data: dict[str, Any],
    collection_miroir_data: dict[str, Any] | None = None,
) -> None:
    """Stocke la section `fonds:` (et la miroir optionnelle) du futur
    profil, puis avance le wizard à l'étape mapping."""
    session.fonds_data = fonds_data
    session.collection_miroir_data = collection_miroir_data
    session.modifie_le = datetime.now()
    _avancer_etape(session, "mapping")
    db.commit()


def construire_mapping(
    colonnes: list[str], cibles: list[str]
) -> dict[str, str]:
    """Construit le dict de mapping `champ_cible → colonne` du profil.

    `colonnes` et `cibles` sont alignés par position (la cible i
    s'applique à la colonne i). Les cibles sentinelles `CIBLE_IGNORE`
    (colonne écartée) et `CIBLE_META` (→ `metadonnees.<slug>`, slug
    dédoublonné) sont traitées à part.

    Lève `MappingInvalide` si deux colonnes visent le même champ dédié
    ou si la `cote` — requise par l'import — n'est mappée nulle part.
    """
    from archives_tool.profils.generateur import slug_metadonnee

    # Alignement positionnel : le formulaire rend un <select name="cible">
    # par colonne dans l'ordre du tableur ; un champ form multi-valeur
    # préserve l'ordre du document (spec HTML). Le garde de longueur
    # ci-dessous attrape le cas d'un select manquant — la seule
    # incohérence réaliste.
    if len(colonnes) != len(cibles):
        raise MappingInvalide(
            "Nombre de cibles incohérent avec le nombre de colonnes."
        )
    mapping: dict[str, str] = {}
    slugs_pris: set[str] = set()
    slugs_pris_fichier: set[str] = set()
    for colonne, cible in zip(colonnes, cibles):
        if cible == CIBLE_IGNORE:
            continue
        if cible == CIBLE_META:
            slug = slug_metadonnee(colonne, slugs_pris)
            mapping[f"metadonnees.{slug}"] = colonne
            continue
        if cible == CIBLE_META_FICHIER:
            slug = slug_metadonnee(colonne, slugs_pris_fichier)
            mapping[f"fichier.metadonnees.{slug}"] = colonne
            continue
        # Champ dédié : un seul mapping possible.
        if cible in mapping:
            raise MappingInvalide(
                f"Deux colonnes visent le champ « {cible} » : "
                f"« {mapping[cible]} » et « {colonne} »."
            )
        mapping[cible] = colonne

    if "cote" not in mapping:
        raise MappingInvalide(
            "Au moins une colonne doit être mappée vers la cote — "
            "c'est l'identifiant des items importés."
        )
    return mapping


def cibles_proposees(session: SessionImport) -> list[str]:
    """Cible de mapping proposée pour chaque colonne du tableur, dans
    l'ordre de `colonnes_detectees`.

    Si un mapping a déjà été enregistré (l'utilisateur revient sur
    l'étape), on le restitue tel quel. Sinon, première visite :
    1. heuristique nominative (:func:`profils.generateur.proposer_mapping`),
    2. **classif par-item / par-fichier** (V0.9.2-import #1) : si une
       colonne classée ``par-fichier`` tombe encore sur la sentinelle
       générique ``CIBLE_META`` (slug libre), on la promeut en
       ``CIBLE_META_FICHIER`` — éviter qu'une valeur par-page atterrisse
       en `metadonnees` d'item et déclenche un warning de divergence.
    """
    colonnes = list(session.colonnes_detectees or [])
    echantillons = session.colonnes_echantillon or {}
    col_vers_cible: dict[str, str] = {}

    def _normaliser(cle: str) -> str:
        # Restitue la sentinelle ou la cible canonique qui correspond
        # au préfixe — important pour que l'utilisateur revoie sa
        # cible sélectionnée à l'identique en revenant sur l'étape.
        # Les `metadonnees.<champ>` qui figurent dans la liste DC
        # fréquente (auteur, éditeur…) restent tels quels ; les autres
        # collapsent vers `__meta__` (slug libre).
        if cle.startswith("fichier.metadonnees."):
            return CIBLE_META_FICHIER
        if cle in _CIBLES_META_CANONIQUES:
            return cle
        if cle.startswith("metadonnees."):
            return CIBLE_META
        return cle

    source = session.mappings
    if source:
        for cle, colonne in source.items():
            col_vers_cible[colonne] = _normaliser(cle)
        defaut = CIBLE_IGNORE
    else:
        from archives_tool.profils.generateur import proposer_mapping

        for cible, colonne, _detecte in proposer_mapping(colonnes):
            cible_norm = _normaliser(cible)
            # Promotion auto vers le niveau fichier si la classif l'indique.
            # On ne touche pas aux champs dédiés ou DC canoniques déjà
            # choisis par l'heuristique — uniquement la sentinelle générique
            # CIBLE_META, qui reflète une colonne sans pattern reconnu.
            if cible_norm == CIBLE_META:
                classif = echantillons.get(colonne, {}).get("classif")
                if classif == "par-fichier":
                    cible_norm = CIBLE_META_FICHIER
            col_vers_cible[colonne] = cible_norm
        defaut = CIBLE_META

    return [col_vers_cible.get(c, defaut) for c in colonnes]


@dataclass(frozen=True)
class SuggestionsModeSimple:
    """Réponses pré-remplies du mode simple (V0.9.2-import #3) calculées
    depuis la classif et l'heuristique nominative.

    `granularite` est `"fichier"` si plus de la moitié des colonnes
    (hors cote) sont classées par-fichier — signal qu'on a affaire à
    un tableur où chaque ligne est un scan. Sinon `"item"`.
    """

    colonne_cote: str | None
    colonne_titre: str | None
    colonne_date: str | None
    granularite: str  # "item" | "fichier"


def suggerer_reponses_simple(session: SessionImport) -> SuggestionsModeSimple:
    """Pré-remplit les 4 questions du mode simple.

    Si un mapping a déjà été enregistré (l'utilisateur revient sur
    l'étape après une première soumission), on en extrait les
    colonnes choisies pour cote / titre / date — sinon l'utilisateur
    perdrait ses sélections entre éditions. Si aucun mapping :
    suggestions auto depuis la classif (Phase 2) et l'heuristique
    nominative (Phase 1 #5).

    Cote : colonne dont la classif vaut ``"cote"`` (calculée par
    :func:`importers.lecteur_tableur._identifier_colonne_cote` à
    l'upload). Titre / date : premier match du pattern correspondant
    dans ``proposer_mapping``. Granularité : ``"fichier"`` si la
    majorité des colonnes hors cote sont par-fichier, sinon
    ``"item"``.
    """
    from archives_tool.profils.generateur import proposer_mapping

    colonnes = list(session.colonnes_detectees or [])
    echantillons = session.colonnes_echantillon or {}

    # Reprise d'un mapping existant : on restaure les choix utilisateur.
    # Les autres colonnes du mapping (metadonnees.<slug>, fichier.*, …)
    # sont ignorées ici — elles seront reconstituées au prochain submit
    # via `construire_mapping_depuis_simple` selon la classif courante.
    mappings = session.mappings
    if mappings:
        return SuggestionsModeSimple(
            colonne_cote=mappings.get("cote"),
            colonne_titre=mappings.get("titre"),
            colonne_date=mappings.get("date"),
            granularite=session.granularite,
        )

    colonne_cote = next(
        (
            col
            for col in colonnes
            if (echantillons.get(col) or {}).get("classif") == "cote"
        ),
        None,
    )

    colonne_titre: str | None = None
    colonne_date: str | None = None
    for cible, source, _detecte in proposer_mapping(colonnes):
        if cible == "titre" and colonne_titre is None:
            colonne_titre = source
        elif cible == "date" and colonne_date is None:
            colonne_date = source

    nb_par_fichier = 0
    nb_par_item = 0
    for col in colonnes:
        if col == colonne_cote:
            continue
        classif = (echantillons.get(col) or {}).get("classif")
        if classif == "par-fichier":
            nb_par_fichier += 1
        elif classif == "par-item":
            nb_par_item += 1
    granularite = "fichier" if nb_par_fichier > nb_par_item else "item"

    return SuggestionsModeSimple(
        colonne_cote=colonne_cote,
        colonne_titre=colonne_titre,
        colonne_date=colonne_date,
        granularite=granularite,
    )


def colonnes_champs_avances(session: SessionImport) -> list[str]:
    """Colonnes du mapping existant qui seraient ramenées en
    ``metadonnees.<slug>`` si re-soumises depuis le mode simple
    (V0.9.2-import #3).

    Le mode simple n'expose que cote / titre / date — tous les autres
    champs dédiés (``annee``, ``type_coar``, ``langue``,
    ``doi_nakala``, ``fichier.*``, ``metadonnees.<dc canonique>``)
    sont écrasés au prochain submit par la slugification automatique.
    Cette fonction liste les colonnes concernées pour qu'un
    avertissement non-bloquant prévienne l'utilisateur (sinon perte
    silencieuse au cours d'un aller-retour avancé → simple).

    Retourne une liste vide si aucun mapping ou aucun champ avancé.
    """
    mappings = session.mappings or {}
    champs_exposes = {"cote", "titre", "date"}
    pertes: list[str] = []
    for cible, colonne in mappings.items():
        if cible in champs_exposes:
            continue
        # Slug libres `metadonnees.<X>` (hors DC canoniques) : on
        # re-slugifiera côté simple, pas une perte de champ dédié.
        if cible.startswith("metadonnees.") and cible not in _CIBLES_META_CANONIQUES:
            continue
        if cible.startswith("fichier.metadonnees."):
            continue
        # Tout le reste est un champ dédié qui sera perdu.
        pertes.append(colonne)
    return pertes


def construire_mapping_depuis_simple(
    session: SessionImport,
    colonne_cote: str,
    colonne_titre: str | None = None,
    colonne_date: str | None = None,
) -> dict[str, str]:
    """Construit un mapping complet depuis les 4 réponses du mode
    simple (V0.9.2-import #3).

    Les colonnes explicitement choisies sont mappées sur leur champ
    dédié (``cote`` / ``titre`` / ``date``). Toutes les autres
    colonnes du tableur vont en ``metadonnees.<slug>`` — préfixées
    par ``fichier.`` si la classif les a marquées par-fichier.

    Lève :class:`MappingInvalide` si la colonne cote n'existe pas
    dans le tableur, si une colonne titre/date inconnue est passée,
    ou si la même colonne est choisie pour plusieurs rôles.
    """
    from archives_tool.profils.generateur import slug_metadonnee

    colonnes = list(session.colonnes_detectees or [])
    echantillons = session.colonnes_echantillon or {}
    colonnes_set = set(colonnes)

    if colonne_cote not in colonnes_set:
        raise MappingInvalide(
            f"La colonne « {colonne_cote} » choisie pour la cote n'existe "
            "pas dans le tableur."
        )
    if colonne_titre and colonne_titre not in colonnes_set:
        raise MappingInvalide(
            f"La colonne « {colonne_titre} » choisie pour le titre n'existe "
            "pas dans le tableur."
        )
    if colonne_date and colonne_date not in colonnes_set:
        raise MappingInvalide(
            f"La colonne « {colonne_date} » choisie pour la date n'existe "
            "pas dans le tableur."
        )

    explicites: dict[str, str] = {colonne_cote: "cote"}
    if colonne_titre:
        if colonne_titre in explicites:
            raise MappingInvalide(
                f"« {colonne_titre} » ne peut pas être à la fois cote et titre."
            )
        explicites[colonne_titre] = "titre"
    if colonne_date:
        if colonne_date in explicites:
            role_existant = explicites[colonne_date]
            raise MappingInvalide(
                f"« {colonne_date} » ne peut pas être à la fois "
                f"{role_existant} et date."
            )
        explicites[colonne_date] = "date"

    mapping: dict[str, str] = {}
    slugs_item: set[str] = set()
    slugs_fichier: set[str] = set()
    for colonne in colonnes:
        cible_explicite = explicites.get(colonne)
        if cible_explicite:
            mapping[cible_explicite] = colonne
            continue
        classif = (echantillons.get(colonne) or {}).get("classif")
        if classif == "par-fichier":
            slug = slug_metadonnee(colonne, slugs_fichier)
            mapping[f"fichier.metadonnees.{slug}"] = colonne
        else:
            slug = slug_metadonnee(colonne, slugs_item)
            mapping[f"metadonnees.{slug}"] = colonne
    return mapping


@dataclass(frozen=True)
class AnomalieMapping:
    """Conflit entre la cible choisie pour une colonne et la classif
    statistique calculée à l'upload (V0.9.2-import #4).

    Trois cas d'usage :
    - colonne classée ``par-fichier`` mais cible item (CIBLE_META ou
      `metadonnees.<dc>`) → suggestion ``CIBLE_META_FICHIER`` ;
    - colonne classée ``par-item`` mais cible fichier (CIBLE_META_FICHIER
      ou `fichier.*`) → suggestion ``CIBLE_META`` ;
    - colonne classée ``melange`` → simple alerte, pas de suggestion
      automatique (l'utilisateur doit trancher).
    """

    colonne: str
    classif: str
    cible_actuelle: str
    cible_suggeree: str  # vide si pas de suggestion automatique
    message: str


def _cible_est_fichier(cible: str) -> bool:
    """Vrai si la cible classe la colonne au niveau fichier.

    `CIBLE_META_FICHIER` (sentinelle slug libre) et tous les
    champs dédiés `fichier.*` (nom_fichier, hash_sha256,
    iiif_url_nakala) sont des cibles fichier.
    """
    return cible == CIBLE_META_FICHIER or cible.startswith("fichier.")


def detecter_anomalies_mapping(
    session: SessionImport, cibles: list[str]
) -> list[AnomalieMapping]:
    """Identifie les colonnes où la cible choisie est en désaccord
    avec la classif par-item / par-fichier (V0.9.2-import #4).

    Sert à afficher une section « Anomalies détectées » à l'étape
    mapping, avec un raccourci pour basculer une colonne d'un niveau
    à l'autre — au lieu de découvrir 44 000 warnings de divergence
    à l'aperçu dry-run.

    Les colonnes mises sur `CIBLE_IGNORE` sont skip (l'utilisateur a
    explicitement choisi de ne pas les importer). Les colonnes dont
    la classif est `cote` ou `indetermine` aussi (rien à signaler).
    """
    echantillons = session.colonnes_echantillon or {}
    colonnes = list(session.colonnes_detectees or [])
    # Invariant tenu par `cibles_proposees` (qui retourne autant
    # d'éléments que `colonnes_detectees`). Si quelqu'un appelle ce
    # service directement avec des listes désalignées, `zip` tronquerait
    # silencieusement et masquerait l'anomalie réelle — on rejette
    # explicitement pour la rendre visible.
    if len(colonnes) != len(cibles):
        raise ValueError(
            f"Désalignement colonnes ({len(colonnes)}) / cibles ({len(cibles)})."
        )
    anomalies: list[AnomalieMapping] = []
    for colonne, cible in zip(colonnes, cibles):
        if cible == CIBLE_IGNORE:
            continue
        stats = echantillons.get(colonne) or {}
        classif = stats.get("classif")
        if classif not in {"par-item", "par-fichier", "melange"}:
            continue

        if classif == "par-fichier" and not _cible_est_fichier(cible):
            uniques = stats.get("uniques", "?")
            remplies = stats.get("remplies", "?")
            anomalies.append(
                AnomalieMapping(
                    colonne=colonne,
                    classif="par-fichier",
                    cible_actuelle=cible,
                    cible_suggeree=CIBLE_META_FICHIER,
                    message=(
                        f"« {colonne} » varie au sein de chaque cote "
                        f"({uniques} valeurs uniques sur {remplies} cellules). "
                        "Probablement propre au scan, pas à l'item — sinon "
                        "toutes les valeurs sauf une seront ignorées à l'import."
                    ),
                )
            )
        elif classif == "par-item" and _cible_est_fichier(cible):
            anomalies.append(
                AnomalieMapping(
                    colonne=colonne,
                    classif="par-item",
                    cible_actuelle=cible,
                    cible_suggeree=CIBLE_META,
                    message=(
                        f"« {colonne} » est stable au sein de chaque cote. "
                        "Cohérent avec une métadonnée d'item — la classer "
                        "au niveau fichier dupliquera la même valeur sur "
                        "tous les scans."
                    ),
                )
            )
        elif classif == "melange":
            anomalies.append(
                AnomalieMapping(
                    colonne=colonne,
                    classif="melange",
                    cible_actuelle=cible,
                    cible_suggeree="",
                    message=(
                        f"« {colonne} » a des valeurs mêlées par cote — "
                        "certaines cotes stables, d'autres avec plusieurs "
                        "valeurs. À vérifier."
                    ),
                )
            )
    return anomalies


def enregistrer_mapping(
    db: Session,
    session: SessionImport,
    mapping: dict[str, str],
    granularite: str = "item",
) -> None:
    """Stocke le mapping colonnes → champs et la granularité du
    tableur, puis avance à l'étape de résolution des fichiers."""
    session.mappings = mapping
    session.granularite = granularite if granularite == "fichier" else "item"
    session.modifie_le = datetime.now()
    _avancer_etape(session, "fichiers")
    db.commit()


def enregistrer_resolution(
    db: Session,
    session: SessionImport,
    configuration: dict[str, Any] | None,
) -> None:
    """Stocke la configuration de résolution des fichiers (ou `None`
    pour un import métadonnées seules), puis avance à l'étape aperçu."""
    session.configuration_fichiers = configuration
    session.modifie_le = datetime.now()
    _avancer_etape(session, "apercu")
    db.commit()


def composer_profil(
    session: SessionImport, *, ignorer_lignes_sans_cote: bool = False
) -> Profil:
    """Assemble un profil d'import v2 depuis l'état de la session.

    Le `tableur.chemin` est absolu (le tableur vit dans le dossier de
    travail) — la résolution `_chemin_tableur` le prend tel quel. Lève
    `ProfilIncomplet` si une étape manque ou si le profil composé
    échoue la validation Pydantic.

    `ignorer_lignes_sans_cote` : si True, les lignes du tableur sans
    cote sont ignorées au lieu de bloquer l'import (lignes de
    documentation en pied d'inventaire).
    """
    if not session.fonds_data or not session.mappings:
        raise ProfilIncomplet(
            "Le fonds ou le mapping n'a pas été renseigné."
        )
    chemin = _chemin_tableur_absolu(session)
    if chemin is None or not chemin.is_file():
        raise ProfilIncomplet("Le tableur de la session est introuvable.")

    data: dict[str, Any] = {
        "version_profil": 2,
        "fonds": dict(session.fonds_data),
        "tableur": {
            "chemin": str(chemin.resolve()),
            "feuille": session.feuille or None,
        },
        "granularite_source": session.granularite,
        "mapping": dict(session.mappings),
        "ignorer_lignes_sans_cote": ignorer_lignes_sans_cote,
    }
    if session.collection_miroir_data:
        data["collection_miroir"] = dict(session.collection_miroir_data)
    if session.configuration_fichiers:
        config = dict(session.configuration_fichiers)
        # `ordre_depuis_nom` est une option de l'assistant rangée à
        # cote de la résolution disque pour simplifier le formulaire,
        # mais elle vit au top-level du profil (s'applique aux deux
        # paths : disque ET colonnes du tableur).
        ordre_regex = config.pop("ordre_depuis_nom", None)
        if ordre_regex:
            data["ordre_depuis_nom"] = ordre_regex
        # Le reste correspond à `ResolutionFichiers`. Vide possible si
        # l'utilisateur n'a saisi que la regex ordre — auquel cas pas
        # de bloc fichiers.
        if config.get("racine"):
            data["fichiers"] = config

    try:
        return Profil.model_validate(data)
    except ValidationError as e:
        premier = e.errors()[0]
        raise ProfilIncomplet(
            f"Profil d'import invalide : {premier.get('msg', 'erreur de validation')}."
        ) from e


def _chemin_profil_notionnel(session: SessionImport) -> Path:
    """Chemin de profil passé au moteur d'import. Ne sert qu'à résoudre
    les chemins relatifs (ici inutile : `tableur.chemin` est absolu) et
    à renseigner `OperationImport.profil_chemin`."""
    return RACINE_IMPORT_TMP / f"profil_session_{session.id}.yaml"


def apercu_import(
    db: Session,
    session: SessionImport,
    config: ConfigLocale,
    *,
    ignorer_lignes_sans_cote: bool = False,
) -> RapportImport:
    """Exécute l'import en dry-run et retourne le rapport (rien écrit)."""
    profil = composer_profil(
        session, ignorer_lignes_sans_cote=ignorer_lignes_sans_cote
    )
    return importer(
        profil,
        _chemin_profil_notionnel(session),
        db,
        config,
        dry_run=True,
    )


def executer_import(
    db: Session,
    session: SessionImport,
    config: ConfigLocale,
    utilisateur: str,
    *,
    ignorer_lignes_sans_cote: bool = False,
) -> RapportImport:
    """Exécute l'import réel. Si aucune erreur, marque la session
    `validee` et mémorise le fonds créé.

    Non-atomicité assumée : `ecrivain.importer` committe lui-même le
    fonds et le journal `OperationImport`, puis on committe à part la
    transition `validee`. Si ce second commit échouait (cas extrême :
    un UPDATE d'une ligne), le fonds existerait sans que la session
    le sache. Acceptable à l'échelle du projet (équipe réduite, pas
    d'édition simultanée) — un statut transitoire en base serait
    sur-ingénierie ici."""
    profil = composer_profil(
        session, ignorer_lignes_sans_cote=ignorer_lignes_sans_cote
    )
    rapport = importer(
        profil,
        _chemin_profil_notionnel(session),
        db,
        config,
        dry_run=False,
        cree_par=utilisateur,
    )
    if not rapport.erreurs:
        session.statut = "validee"
        session.fonds_cree_id = rapport.fonds_id
        session.modifie_le = datetime.now()
        db.commit()
    return rapport


def abandonner_session(db: Session, session: SessionImport) -> None:
    """Marque une session abandonnée et supprime son tableur temporaire.

    La transition de statut est committée *avant* de toucher au disque :
    si la suppression du fichier échoue (handle ouvert, droits — cas
    plausible sous Windows), la session reste cohérente en base. Le
    tableur temporaire est du jetable gitignoré ; un échec de unlink
    laisse au pire un fichier orphelin, sans casser l'état métier.

    Idempotent : ré-abandonner une session déjà abandonnée ne fait que
    re-committer le même statut et retenter le unlink (no-op si parti).
    """
    session.statut = "abandonnee"
    session.modifie_le = datetime.now()
    db.commit()
    chemin = _chemin_tableur_absolu(session)
    if chemin is not None:
        try:
            chemin.unlink(missing_ok=True)
        except OSError:
            # Fichier verrouillé ou droits insuffisants : on laisse
            # l'orphelin plutôt que de faire échouer l'abandon.
            pass
