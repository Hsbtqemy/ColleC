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


@dataclass(frozen=True)
class ApercuRepartitionSimple:
    """Décompte par catégorie de cibles si l'utilisateur soumettait
    le mode simple avec les suggestions actuelles (Trou #2 V0.9.2-import).

    Sert au récap inline en bas du formulaire pour annoncer
    honnêtement combien de colonnes seront promues en champ dédié vs
    quelles iront vraiment en metadonnees libres — avant le fix Bug B,
    tout tombait en libre et le récap actuel sous-estimerait
    grossièrement les champs dédiés.
    """

    promues_dediees: list[str]  # cote/titre/date dédiés + DC canoniques + Fichier dédiés
    libres_item: list[str]  # metadonnees.<slug> libres
    libres_fichier: list[str]  # fichier.metadonnees.<slug> libres


def apercu_repartition_simple(
    session: SessionImport, suggestions: SuggestionsModeSimple | None
) -> ApercuRepartitionSimple:
    """Simule la promotion mode simple sans poser le mapping en base.

    Lecture seule (pas d'écriture, pas de ré-analyse du tableur — on
    s'appuie sur `colonnes_echantillon` déjà calculée à l'upload).
    Appelée à chaque rendu de l'étape mapping simple pour montrer un
    récap juste, sans coût notable.
    """
    from archives_tool.profils.generateur import proposer_mapping

    colonnes = list(session.colonnes_detectees or [])
    echantillons = session.colonnes_echantillon or {}
    explicites: set[str] = set()
    if suggestions:
        for col in (
            suggestions.colonne_cote,
            suggestions.colonne_titre,
            suggestions.colonne_date,
        ):
            if col:
                explicites.add(col)

    colonnes_hors = [c for c in colonnes if c not in explicites]
    promues: list[str] = []
    libres_item: list[str] = []
    libres_fichier: list[str] = []
    for cible, source, detecte in proposer_mapping(colonnes_hors):
        if detecte and cible not in {"cote", "titre", "date"}:
            if cible.startswith("fichier.metadonnees."):
                # Slug libre côté fichier via `_est_pattern_fichier_meta`
                # (thumb/data_url/embed_url/...) — sémantiquement libre,
                # pas un champ dédié.
                libres_fichier.append(source)
            else:
                # Champ Item dédié (langue, doi_nakala, ...) ou DC
                # canonique (metadonnees.auteur, ...) ou Fichier dédié
                # (fichier.nom_fichier, ...).
                promues.append(source)
            continue
        classif = (echantillons.get(source) or {}).get("classif")
        if classif == "par-fichier":
            libres_fichier.append(source)
        else:
            libres_item.append(source)
    return ApercuRepartitionSimple(
        promues_dediees=promues,
        libres_item=libres_item,
        libres_fichier=libres_fichier,
    )


def colonnes_champs_avances(session: SessionImport) -> list[str]:
    """Colonnes du mapping existant qui seraient ramenées en
    ``metadonnees.<slug>`` si re-soumises depuis le mode simple
    (V0.9.2-import #3).

    Le mode simple n'expose que cote / titre / date dans son
    formulaire. Les autres champs dédiés (``annee``, ``type_coar``,
    ``langue``, ``doi_nakala``, ``fichier.*``, ``metadonnees.<dc
    canonique>``) sont reconstruits à partir des heuristiques
    nominatives de :func:`proposer_mapping` (Bug B V0.9.2-import) :
    si le nom de la colonne suffit à les redétecter, pas de perte.
    Cette fonction ne liste donc que les colonnes dont le nom
    n'évoque PAS leur cible dédiée — typiquement des abréviations
    (``An`` pour année, ``Coar`` pour type COAR) — pour lesquelles
    une bannière non-bloquante invitera l'utilisateur à basculer en
    mode avancé.

    Retourne une liste vide si aucun mapping ou aucun champ avancé.
    """
    from archives_tool.profils.generateur import proposer_mapping

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
        # Bug B : si le nom de la colonne déclenche la même cible
        # via les heuristiques nominatives, le mode simple la
        # réaffectera spontanément — pas de perte.
        propositions = proposer_mapping([colonne])
        cible_heuristique = propositions[0][0] if propositions[0][2] else None
        if cible_heuristique == cible:
            continue
        # Tout le reste est un champ dédié qui sera réellement perdu.
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
    dédié (``cote`` / ``titre`` / ``date``). Pour les colonnes
    restantes, on consulte d'abord les heuristiques nominatives de
    :func:`proposer_mapping` — qui reconnaissent ``doi``, ``langue``,
    ``type_coar``, ``filename``, ``hash``, ``iiif``, ``auteur``,
    ``editeur``, etc. — afin de promouvoir vers les champs dédiés
    Item / Fichier ou les cibles DC canoniques (``metadonnees.auteur``,
    ``metadonnees.sujet``…). C'est la fix Bug B V0.9.2-import : sans
    cette étape, mode simple écraserait silencieusement tous les champs
    dédiés en ``metadonnees.<slug>``, ce que l'utilisateur ne voulait
    pas en venant via la voie ergonomique.

    Le fallback ``metadonnees.<slug>`` (préfixé ``fichier.`` selon la
    classif) ne s'applique que si l'heuristique ne reconnaît rien.
    Les rôles ``cote`` / ``titre`` / ``date`` restent exclusivement
    contrôlés par l'utilisateur : une heuristique qui les détecterait
    sur une autre colonne est filtrée (sinon mode simple promouvrait
    deux colonnes sur ``titre``).

    Lève :class:`MappingInvalide` si la colonne cote n'existe pas
    dans le tableur, si une colonne titre/date inconnue est passée,
    ou si la même colonne est choisie pour plusieurs rôles.
    """
    from archives_tool.profils.generateur import (
        proposer_mapping,
        slug_metadonnee,
    )

    colonnes = list(session.colonnes_detectees or [])
    echantillons = session.colonnes_echantillon or {}
    # Safe-guard #2 V0.9.2-import : si echantillons a déjà filtré les
    # colonnes 100 % vides, on les retire aussi de `colonnes` pour
    # qu'elles ne soient pas mappées en `metadonnees.<slug>` libres
    # inutiles (cas d'un session import où colonnes_detectees et
    # colonnes_echantillon ont divergé). Pas appliqué si echantillons
    # est vide (session sans analyse — bénéfice du doute).
    if echantillons:
        colonnes = [c for c in colonnes if c in echantillons]
    colonnes_set = set(colonnes)

    if colonne_cote not in colonnes_set:
        raise MappingInvalide(
            f"La colonne « {colonne_cote} » choisie pour la cote n'existe "
            "pas dans le tableur."
        )

    # Recalcul classif si la cote choisie diffère de celle auto-détectée
    # à l'upload (fix bug PF 2026-05-23). Cas courant : tableur Nakala
    # où la vraie cote est dupliquée sur tous les scans (donc pas 100 %
    # unique au global, donc invisible au fallback de
    # `_identifier_colonne_cote`). L'auto détecte alors aucune cote (ou
    # pire une fausse — data_url avant le fix #1) → classifs toutes
    # `indetermine` → mode simple ne promeut rien. Une fois la cote
    # choisie explicitement, on re-analyse le tableur en forçant cette
    # cote pour faire émerger les vraies classifs par-fichier.
    cote_auto = next(
        (
            col for col, s in echantillons.items()
            if (s or {}).get("classif") == "cote"
        ),
        None,
    )
    if cote_auto != colonne_cote and session.chemin_tableur:
        chemin = RACINE_IMPORT_TMP / session.chemin_tableur
        if chemin.is_file():
            try:
                echantillons = analyser_colonnes_tableur(
                    chemin, session.feuille, cote_col_force=colonne_cote
                )
            except LectureTableurErreur:
                # Fallback : on garde la classif d'upload, le mode simple
                # ne promouvra pas en `fichier.metadonnees.<slug>` mais
                # le rapport dry-run remontera les divergences agrégées
                # (T6) — l'utilisateur verra quand même les colonnes
                # à reclasser.
                pass
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

    # Bug B : pré-calcul des heuristiques nominatives sur les colonnes
    # non choisies explicitement. `proposer_mapping` gère la dédup
    # interne (deux colonnes « Titre » → la première gagne le champ
    # dédié, la seconde tombe en slug). On filtre les heuristiques qui
    # toucheraient un rôle explicite (cote/titre/date) — l'utilisateur
    # a déjà tranché, on ne veut pas un doublon.
    _ROLES_EXPLICITES = {"cote", "titre", "date"}
    colonnes_hors_explicites = [c for c in colonnes if c not in explicites]
    heuristiques: dict[str, str | None] = {}
    for cible, source, detecte in proposer_mapping(colonnes_hors_explicites):
        if detecte and cible not in _ROLES_EXPLICITES:
            heuristiques[source] = cible
        else:
            heuristiques[source] = None

    mapping: dict[str, str] = {}
    # Pré-peupler les sets de slugs avec ceux déjà revendiqués par les
    # heuristiques DC canoniques (`metadonnees.auteur`, …) et par
    # `_est_pattern_fichier_meta` (`fichier.metadonnees.thumb`, …) —
    # évite qu'une colonne sans heuristique tombe sur le même slug et
    # écrase la cible dédiée déjà posée. Ex : colonnes "Auteur" +
    # "AUTEUR" → la première va en `metadonnees.auteur`, la seconde en
    # `metadonnees.auteur_2` (sans cette pré-population, elle aurait
    # repris `metadonnees.auteur` et écrasé la première).
    slugs_item: set[str] = set()
    slugs_fichier: set[str] = set()
    for cible in heuristiques.values():
        if cible is None:
            continue
        if cible.startswith("metadonnees."):
            slugs_item.add(cible[len("metadonnees."):])
        elif cible.startswith("fichier.metadonnees."):
            slugs_fichier.add(cible[len("fichier.metadonnees."):])

    # Suivi des cibles dédiées déjà posées pour défense en profondeur :
    # même après le filtre `_ROLES_EXPLICITES`, deux heuristiques sur
    # deux colonnes peuvent en théorie viser la même cible si la
    # dédup interne de `proposer_mapping` rate (cas pathologique).
    cibles_dediees_prises: set[str] = set(explicites.values())

    for colonne in colonnes:
        cible_explicite = explicites.get(colonne)
        if cible_explicite:
            mapping[cible_explicite] = colonne
            continue
        cible_heuristique = heuristiques.get(colonne)
        if cible_heuristique and cible_heuristique not in cibles_dediees_prises:
            mapping[cible_heuristique] = colonne
            cibles_dediees_prises.add(cible_heuristique)
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
