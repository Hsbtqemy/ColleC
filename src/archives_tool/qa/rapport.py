"""Dataclasses des rapports de contrôle."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AnomalieFichierManquant:
    fichier_id: int
    item_cote: str
    racine: str
    chemin_relatif: str


@dataclass
class AnomalieOrphelinDisque:
    racine: str
    chemin_relatif: str


@dataclass
class AnomalieItemVide:
    item_id: int
    cote: str
    collection_cote: str


@dataclass
class FichierDoublon:
    fichier_id: int
    item_cote: str
    racine: str
    chemin_relatif: str


@dataclass
class GroupeDoublons:
    hash_sha256: str
    fichiers: list[FichierDoublon] = field(default_factory=list)


@dataclass
class RapportControle:
    """Résultat d'un contrôle individuel.

    `code` est l'identifiant stable utilisé en CLI (`--check ...`).
    `anomalies` peut contenir n'importe lequel des dataclasses ci-dessus
    selon le contrôle.
    """

    code: str
    libelle: str
    anomalies: list = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    duree_secondes: float = 0.0

    @property
    def nb_anomalies(self) -> int:
        return len(self.anomalies)


@dataclass
class RapportQa:
    """Résultat global d'une session de contrôles."""

    controles: list[RapportControle] = field(default_factory=list)
    portee: str = "global"
    duree_secondes: float = 0.0

    @property
    def nb_anomalies(self) -> int:
        return sum(c.nb_anomalies for c in self.controles)
