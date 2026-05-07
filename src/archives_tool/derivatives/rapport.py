"""Dataclasses des résultats de génération de dérivés."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class StatutDerive(enum.StrEnum):
    GENERE = "genere"
    DEJA_GENERE = "deja_genere"
    NETTOYE = "nettoye"
    ERREUR = "erreur"


@dataclass
class ResultatDerive:
    fichier_id: int
    statut: StatutDerive
    message: str | None = None
    derives_crees: dict[str, str] = field(default_factory=dict)
    largeur_originale: int | None = None
    hauteur_originale: int | None = None


@dataclass
class RapportDerivation:
    dry_run: bool
    racine_cible: str
    nb_traites: int = 0
    nb_generes: int = 0
    nb_deja_generes: int = 0
    nb_erreurs: int = 0
    nb_nettoyes: int = 0
    resultats: list[ResultatDerive] = field(default_factory=list)
    duree_secondes: float = 0.0

    def comptabiliser(self, resultat: ResultatDerive) -> None:
        self.nb_traites += 1
        self.resultats.append(resultat)
        if resultat.statut == StatutDerive.GENERE:
            self.nb_generes += 1
        elif resultat.statut == StatutDerive.DEJA_GENERE:
            self.nb_deja_generes += 1
        elif resultat.statut == StatutDerive.NETTOYE:
            self.nb_nettoyes += 1
        elif resultat.statut == StatutDerive.ERREUR:
            self.nb_erreurs += 1
