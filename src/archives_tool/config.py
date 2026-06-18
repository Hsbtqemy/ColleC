"""Chargement et validation du `config_local.yaml` par utilisateur.

Ce fichier est hors dépôt : il contient l'identité locale et les chemins
physiques des racines logiques. Jamais versionné, jamais partagé.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

#: Hôtes Nakala légitimes par défaut (prod + apitest, variante à tiret
#: incluse). Surchargeable via `nakala.hotes_autorises` pour un proxy ou
#: une instance Nakala tierce.
_HOTES_NAKALA_DEFAUT = ("api.nakala.fr", "apitest.nakala.fr", "api-test.nakala.fr")


def _valider_url_nakala(base_url: str, hotes_autorises: list[str]) -> str:
    """Valide / normalise une `base_url` Nakala (anti-SSRF + HTTPS). Lève
    `ValueError` (capté par Pydantic). Parité avec le client ShareDocs :
    HTTPS exigé (la clé API circule en header `X-API-KEY` → jamais sur du
    HTTP en clair), pas d'identifiants dans l'URL, hôte dans l'allowlist,
    pas d'IP interne. Renvoie l'URL sans `/` final."""
    base_url = (base_url or "").strip().rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme != "https":
        raise ValueError(
            f"nakala.base_url : HTTPS requis (schéma reçu : {parts.scheme or '∅'!r})."
        )
    if parts.username or parts.password:
        raise ValueError("nakala.base_url : pas d'identifiants dans l'URL.")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("nakala.base_url : hôte manquant.")
    autorises = {h.lower() for h in hotes_autorises}
    if host not in autorises:
        raise ValueError(
            f"nakala.base_url : hôte non autorisé {host!r}. "
            f"Autorisé(s) : {', '.join(sorted(autorises)) or '(aucun)'} "
            "(ajouter à nakala.hotes_autorises si légitime)."
        )
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass  # nom de domaine, pas une IP → OK
    else:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("nakala.base_url : adresse IP interne interdite.")
    return base_url


class NakalaConfig(BaseModel):
    """Configuration d'accès Nakala (lecture, V0.9.x P1).

    Optionnelle : présente uniquement si l'utilisateur veut tirer des
    dépôts depuis Nakala. Clé API facultative — les dépôts publics sont
    lisibles anonymement ; la clé est requise pour les dépôts privés /
    en attente / sous embargo.

    Exemple :
        nakala:
          base_url: https://apitest.nakala.fr
          api_key: "33170cfe-..."
    """

    # Prod par défaut ; mettre `https://apitest.nakala.fr` pour les tests.
    base_url: str = "https://api.nakala.fr"
    api_key: str | None = None
    verify_ssl: bool = True
    timeout: float = 30.0
    hotes_autorises: list[str] = Field(
        default_factory=lambda: list(_HOTES_NAKALA_DEFAUT)
    )

    @model_validator(mode="after")
    def _valider_base_url(self) -> NakalaConfig:
        # base_url Nakala vient toujours de la config (pas d'override web) →
        # la valider ici suffit (anti-SSRF complet, cf. `_valider_url_nakala`).
        self.base_url = _valider_url_nakala(self.base_url, self.hotes_autorises)
        return self


class ShareDocsConfig(BaseModel):
    """Accès ShareDocs (WebDAV Huma-Num) en lecture (Chantier 1).

    Optionnelle : présente si l'utilisateur veut ingérer des fichiers
    depuis ShareDocs sans monter le partage. **Les identifiants n'y
    figurent JAMAIS** — ils sont fournis en RAM (web) ou par variables
    d'environnement (CLI). On ne stocke que l'URL racine et, en option,
    l'allowlist d'hôtes (anti-SSRF ; vide → défaut du client).

    Exemple :
        sharedocs:
          base_url: https://sharedocs.huma-num.fr/dav/projets/colleC
    """

    base_url: str
    hotes_autorises: list[str] = Field(default_factory=list)

    @field_validator("base_url")
    @classmethod
    def _base_url_https(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith("https://"):
            raise ValueError("sharedocs.base_url doit commencer par https://")
        return v


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
    # `lecture_seule: true` bloque toute mutation HTTP (POST/PUT/PATCH/
    # DELETE) avec un code 423. Sert à exposer ColleC à un consultant
    # occasionnel sans risque d'édition accidentelle — ce n'est pas
    # une mesure de sécurité (l'utilisateur peut éditer le YAML).
    lecture_seule: bool = False
    # Accès Nakala en lecture (P1) — None si non configuré.
    nakala: NakalaConfig | None = None
    # Accès ShareDocs WebDAV (Chantier 1) — None si non configuré.
    sharedocs: ShareDocsConfig | None = None

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
