"""Composition de la page de contrôles de cohérence (`/controler`, lecture seule).

Surface en UI le module `qa` (14 contrôles, déjà exposé en CLI). La page
réutilise tel quel `composer_perimetre` + `executer_controles` — aucune
logique de contrôle ici, juste l'assemblage d'une vue : résolution du
périmètre (base entière ou un fonds), libellé, options du sélecteur, et
partition problèmes / contrôles OK pour l'affichage.

Périmètre limité à **base entière | fonds** côté UI (le périmètre
collection reste accessible en CLI — `archives-tool controler --collection` :
une cote de collection seule est ambiguë entre fonds, et l'intérêt UI est
le bilan global / par fonds).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import Fonds
from archives_tool.qa._commun import RapportQa, ResultatControle, Severite
from archives_tool.qa.orchestrateur import (
    composer_perimetre,
    executer_controles,
)

#: Rang de tri des problèmes : erreurs d'abord, infos en dernier.
_RANG_SEVERITE: dict[Severite, int] = {
    Severite.ERREUR: 0,
    Severite.AVERTISSEMENT: 1,
    Severite.INFO: 2,
}


@dataclass(frozen=True)
class VueControle:
    """Tout ce dont la page `controle.html` a besoin."""

    rapport: RapportQa
    scope_label: str
    fonds_cote: str | None  # fonds courant (pour pré-sélectionner le picker)
    fonds_options: tuple[tuple[str, str], ...]  # (cote, libellé) triés par cote
    racines_configurees: bool

    @property
    def perimetre(self):
        return self.rapport.perimetre

    @property
    def horodatage_affichage(self) -> datetime:
        """Horodatage du run en naïf local, pour le filtre `temps_relatif`.

        `RapportQa.horodatage` est aware (UTC) ; `temps_relatif` compare à
        `datetime.now()` naïf (convention du reste du projet) — passer un
        datetime aware lèverait `TypeError` (soustraction aware/naïf)."""
        h = self.rapport.horodatage
        if h.tzinfo is not None:
            return h.astimezone().replace(tzinfo=None)
        return h

    @property
    def nb_erreurs(self) -> int:
        return self.rapport.nb_erreurs

    @property
    def nb_avertissements(self) -> int:
        return self.rapport.nb_avertissements

    @property
    def nb_infos(self) -> int:
        return self.rapport.nb_infos

    @property
    def tout_va_bien(self) -> bool:
        """Aucun contrôle en échec, toutes sévérités confondues."""
        return all(c.passe for c in self.rapport.controles)

    @property
    def controles_problemes(self) -> tuple[ResultatControle, ...]:
        """Contrôles en échec, triés erreur → avertissement → info."""
        echecs = [c for c in self.rapport.controles if not c.passe]
        return tuple(sorted(echecs, key=lambda c: _RANG_SEVERITE.get(c.severite, 9)))

    @property
    def controles_ok(self) -> tuple[ResultatControle, ...]:
        """Contrôles passés (pour le repli « tout ce qui va bien »)."""
        return tuple(c for c in self.rapport.controles if c.passe)


def composer_page_controle(
    db: Session,
    *,
    racines: Mapping[str, Path] | None = None,
    fonds: Fonds | None = None,
) -> VueControle:
    """Exécute la suite qa sur le périmètre demandé et assemble la vue.

    `fonds=None` → base entière. La résolution de la cote (et le 404 si
    inconnue) est faite en amont par le routeur via `charger_fonds_ou_404` —
    le composeur reçoit l'entité déjà chargée, pas une cote à re-résoudre.
    """
    fonds_id: int | None = None
    scope_label = "Base entière"
    cote_courante: str | None = None
    if fonds is not None:
        fonds_id = fonds.id
        cote_courante = fonds.cote
        scope_label = f"Fonds {fonds.cote}" + (f" — {fonds.titre}" if fonds.titre else "")

    perimetre = composer_perimetre(db, fonds_id=fonds_id)
    rapport = executer_controles(db, perimetre, racines=racines)

    fonds_options = tuple(
        (cote, f"{cote} — {titre}" if titre else cote)
        for cote, titre in db.execute(
            select(Fonds.cote, Fonds.titre).order_by(Fonds.cote)
        ).all()
    )

    return VueControle(
        rapport=rapport,
        scope_label=scope_label,
        fonds_cote=cote_courante,
        fonds_options=fonds_options,
        racines_configurees=bool(racines),
    )


__all__ = ["VueControle", "composer_page_controle"]
