"""Composition de la page Journal (traçabilité, lecture seule).

Surface dans l'UI web ce que les services métier journalisent déjà mais
qui n'était consultable qu'en CLI (`montrer suppressions`,
`montrer push-nakala`, `renommer historique`) :

- suppressions d'entités (`OperationEntite`),
- push de fichiers vers Nakala (`OperationPushNakala`),
- batchs de renommage (`OperationFichier` agrégés).

Aucune écriture : ce module ne fait que lire et mettre en forme. Les
trois producteurs restent les seuls à journaliser (principe n°4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from archives_tool.api.services.operations_entite import lister_suppressions
from archives_tool.api.services.operations_push_nakala import lister_push_nakala
from archives_tool.renamer.historique import EntreeHistorique, lister_batchs


@dataclass(frozen=True)
class LigneSuppression:
    """Une suppression d'entité, mise en forme pour l'affichage."""

    type_entite: str
    cote: str | None
    titre: str | None
    fonds_cote: str | None
    resume_cascade: str
    execute_le: datetime | None
    execute_par: str | None


@dataclass(frozen=True)
class LignePush:
    """Un push de fichiers Nakala, mis en forme pour l'affichage."""

    cote_item: str
    fonds_cote: str | None
    doi: str
    nb_uploades: int
    nb_retires: int
    execute_le: datetime | None
    execute_par: str | None


@dataclass(frozen=True)
class JournalView:
    """Vue agrégée des trois journaux pour `pages/journal.html`."""

    suppressions: list[LigneSuppression]
    push_nakala: list[LignePush]
    renommages: list[EntreeHistorique]

    @property
    def vide(self) -> bool:
        return not (self.suppressions or self.push_nakala or self.renommages)


def _taille_liste_json(brut: str | None) -> int:
    """Longueur d'une liste sérialisée en JSON (0 si vide/illisible)."""
    try:
        valeur = json.loads(brut) if brut else []
    except (json.JSONDecodeError, TypeError):
        return 0
    return len(valeur) if isinstance(valeur, list) else 0


def _resume_cascade(type_entite: str, brut: str | None) -> str:
    """Résumé court des effets de cascade d'une suppression, depuis le
    `cascade_resume` JSON journalisé (ex. « 12 items · 340 fichiers »)."""
    try:
        data = json.loads(brut) if brut else {}
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""

    parts: list[str] = []

    def ajouter(nombre: object, singulier: str, pluriel: str | None = None) -> None:
        if isinstance(nombre, int) and nombre > 0:
            libelle = singulier if nombre == 1 else (pluriel or f"{singulier}s")
            parts.append(f"{nombre} {libelle}")

    if type_entite == "fonds":
        ajouter(data.get("items"), "item")
        ajouter(data.get("fichiers"), "fichier")
        ajouter(data.get("annotations"), "annotation")
        ajouter(data.get("collaborateurs"), "collaborateur")
        ajouter(
            data.get("collections_detachees"),
            "collection détachée",
            "collections détachées",
        )
    elif type_entite == "item":
        ajouter(data.get("fichiers"), "fichier")
        ajouter(data.get("annotations"), "annotation")
        ajouter(data.get("junctions"), "rattachement")
    elif type_entite == "collection":
        ajouter(data.get("junctions"), "rattachement")
    return " · ".join(parts)


def composer_journal(db: Session, *, limite: int = 100) -> JournalView:
    """Assemble la vue des trois journaux, plus récents d'abord."""
    suppressions = [
        LigneSuppression(
            type_entite=op.type_entite,
            cote=op.cote,
            titre=op.titre,
            fonds_cote=op.fonds_cote,
            resume_cascade=_resume_cascade(op.type_entite, op.cascade_resume),
            execute_le=op.execute_le,
            execute_par=op.execute_par,
        )
        for op in lister_suppressions(db, limite=limite)
    ]
    push_nakala = [
        LignePush(
            cote_item=op.cote_item,
            fonds_cote=op.fonds_cote,
            doi=op.doi,
            nb_uploades=_taille_liste_json(op.sha1s_uploades),
            nb_retires=_taille_liste_json(op.sha1s_retires),
            execute_le=op.execute_le,
            execute_par=op.execute_par,
        )
        for op in lister_push_nakala(db, limite=limite)
    ]
    renommages = lister_batchs(db, limite=limite)
    return JournalView(
        suppressions=suppressions,
        push_nakala=push_nakala,
        renommages=renommages,
    )
