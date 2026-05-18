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
CIBLE_IGNORE = "__ignore__"  # colonne non importée


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

    try:
        colonnes = lire_colonnes_tableur(chemin, feuille)
    except TableurInvalide:
        chemin.unlink(missing_ok=True)
        raise

    session.chemin_tableur = nom_stocke
    session.nom_tableur_original = nom_origine
    session.feuille = feuille
    session.colonnes_detectees = colonnes
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
    for colonne, cible in zip(colonnes, cibles):
        if cible == CIBLE_IGNORE:
            continue
        if cible == CIBLE_META:
            slug = slug_metadonnee(colonne, slugs_pris)
            mapping[f"metadonnees.{slug}"] = colonne
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
    l'étape), on le restitue. Sinon on applique l'heuristique de
    détection. Les colonnes vers `metadonnees.*` rendent `CIBLE_META`.
    """
    colonnes = list(session.colonnes_detectees or [])
    col_vers_cible: dict[str, str] = {}

    source = session.mappings
    if source:
        for cle, colonne in source.items():
            col_vers_cible[colonne] = (
                CIBLE_META if cle.startswith("metadonnees.") else cle
            )
        defaut = CIBLE_IGNORE
    else:
        from archives_tool.profils.generateur import proposer_mapping

        for cible, colonne, _detecte in proposer_mapping(colonnes):
            col_vers_cible[colonne] = (
                CIBLE_META if cible.startswith("metadonnees.") else cible
            )
        defaut = CIBLE_META

    return [col_vers_cible.get(c, defaut) for c in colonnes]


def enregistrer_mapping(
    db: Session, session: SessionImport, mapping: dict[str, str]
) -> None:
    """Stocke le mapping colonnes → champs, puis avance à l'étape
    de résolution des fichiers."""
    session.mappings = mapping
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
        "mapping": dict(session.mappings),
        "ignorer_lignes_sans_cote": ignorer_lignes_sans_cote,
    }
    if session.collection_miroir_data:
        data["collection_miroir"] = dict(session.collection_miroir_data)
    if session.configuration_fichiers:
        data["fichiers"] = dict(session.configuration_fichiers)

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
