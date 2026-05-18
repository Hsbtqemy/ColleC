"""Service de l'assistant d'import web (V0.7).

Orchestre les `SessionImport` : création, reprise, abandon. Les
étapes du wizard (upload tableur, fonds, mapping, fichiers, aperçu)
viendront enrichir ce module ; cette première passe ne porte que le
cycle de vie d'une session.

Le tableur uploadé est stocké hors base, sous `data/_import_tmp/`
(gitignoré). Le chemin stocké en base est relatif à ce dossier —
jamais un chemin absolu (principe de portabilité).
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import ETAPES_IMPORT, SessionImport

# Dossier de travail des tableurs uploadés. Sous `data/` (gitignoré),
# distinct des bases. Créé à la demande.
RACINE_IMPORT_TMP = Path("data") / "_import_tmp"

# Extensions de tableur acceptées à l'upload.
EXTENSIONS_TABLEUR: frozenset[str] = frozenset(
    {".xlsx", ".xls", ".csv", ".tsv"}
)

# Taille maximale d'un tableur uploadé (octets). Un inventaire reste
# petit ; cette borne protège surtout d'un upload accidentel énorme.
TAILLE_MAX_TABLEUR = 20 * 1024 * 1024  # 20 Mio


class SessionImportIntrouvable(Exception):
    """Aucune session d'import pour l'id demandé."""


class TableurInvalide(Exception):
    """Le fichier uploadé n'est pas un tableur exploitable."""


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
    """Lit les en-têtes de colonnes d'un tableur (xlsx/xls/csv/tsv).

    Lève `TableurInvalide` si l'extension n'est pas gérée ou si le
    fichier est illisible. Pour les CSV, tente UTF-8 puis CP1252
    (tableurs anciens sous Windows) — détection bienveillante.
    """
    import pandas as pd  # import local : pandas est lourd

    ext = chemin.suffix.lower()
    if ext not in EXTENSIONS_TABLEUR:
        raise TableurInvalide(f"Extension non supportée : {ext!r}.")
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(
                chemin, sheet_name=feuille if feuille else 0, dtype=str, nrows=1
            )
        else:
            sep = "\t" if ext == ".tsv" else ";"
            try:
                df = pd.read_csv(chemin, sep=sep, encoding="utf-8", dtype=str, nrows=1)
            except UnicodeDecodeError:
                df = pd.read_csv(
                    chemin, sep=sep, encoding="cp1252", dtype=str, nrows=1
                )
    except TableurInvalide:
        raise
    except Exception as e:  # noqa: BLE001 — toute erreur pandas → message propre
        raise TableurInvalide(f"Lecture du tableur impossible : {e}") from e

    colonnes = [str(c).strip() for c in df.columns]
    if not colonnes:
        raise TableurInvalide("Le tableur ne contient aucune colonne.")
    return colonnes


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
