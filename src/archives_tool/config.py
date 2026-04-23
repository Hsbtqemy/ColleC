"""Chargement et validation du `config_local.yaml` par utilisateur.

Ce fichier est hors dépôt : il contient l'identité locale et les chemins
physiques des racines logiques. Jamais versionné, jamais partagé.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class ConfigLocale(BaseModel):
    """Contenu attendu du `config_local.yaml`.

    Exemple :
        utilisateur: "Marie Dupont"
        racines:
          scans_revues: /Users/marie/Archives/Scans
          miniatures: /Volumes/NAS/archives/miniatures
    """

    utilisateur: str = Field(min_length=1)
    racines: dict[str, Path] = Field(default_factory=dict)

    @field_validator("racines")
    @classmethod
    def _cles_non_vides(cls, v: dict[str, Path]) -> dict[str, Path]:
        for nom in v:
            if not nom.strip():
                raise ValueError("Nom de racine vide interdit.")
        return v

    @model_validator(mode="after")
    def _racines_sont_des_dossiers(self) -> ConfigLocale:
        for nom, chemin in self.racines.items():
            if not chemin.is_dir():
                raise ValueError(
                    f"Racine {nom!r} : {chemin} n'existe pas ou n'est pas un dossier."
                )
        return self


def charger_config(chemin: Path) -> ConfigLocale:
    """Lit un YAML UTF-8 et retourne une `ConfigLocale` validée."""
    with chemin.open("r", encoding="utf-8") as f:
        donnees = yaml.safe_load(f) or {}
    if not isinstance(donnees, dict):
        raise ValueError(f"Le fichier {chemin} doit contenir un mapping YAML.")
    return ConfigLocale.model_validate(donnees)
