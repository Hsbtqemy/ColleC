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

from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import SessionImport

# Dossier de travail des tableurs uploadés. Sous `data/` (gitignoré),
# distinct des bases. Créé à la demande.
RACINE_IMPORT_TMP = Path("data") / "_import_tmp"


class SessionImportIntrouvable(Exception):
    """Aucune session d'import pour l'id demandé."""


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
