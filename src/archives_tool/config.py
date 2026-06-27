"""Chargement et validation du `config_local.yaml` par utilisateur.

Ce fichier est hors dépôt : il contient l'identité locale et les chemins
physiques des racines logiques. Jamais versionné, jamais partagé.
"""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

_logger = logging.getLogger(__name__)

#: Hôtes Nakala légitimes par défaut (prod + apitest, variante à tiret
#: incluse). Surchargeable via `nakala.hotes_autorises` pour un proxy ou
#: une instance Nakala tierce.
_HOTES_NAKALA_DEFAUT = ("api.nakala.fr", "apitest.nakala.fr", "api-test.nakala.fr")


def _valider_url_anti_ssrf(
    base_url: str,
    hotes_autorises: list[str],
    *,
    etiquette: str,
    indice_allowlist: str,
) -> str:
    """Valide / normalise une `base_url` distante (anti-SSRF + HTTPS). Lève
    `ValueError` (capté par Pydantic). HTTPS exigé (les secrets circulent en
    header / en Basic auth → jamais sur du HTTP en clair), pas d'identifiants
    dans l'URL, hôte dans l'allowlist, pas d'IP interne. Renvoie l'URL sans
    `/` final.

    Helper commun à Nakala et ShareDocs : avant, ShareDocs ne vérifiait que
    le préfixe `https://` (ni allowlist, ni userinfo, ni IP interne) — une
    `base_url` interne ou hors allowlist passait la config (revue sécurité
    F2). Le client ShareDocs re-validait au runtime, mais la défense en
    profondeur manquait au niveau config.
    """
    base_url = (base_url or "").strip().rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme != "https":
        raise ValueError(
            f"{etiquette} : HTTPS requis (schéma reçu : {parts.scheme or '∅'!r})."
        )
    if parts.username or parts.password:
        raise ValueError(f"{etiquette} : pas d'identifiants dans l'URL.")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"{etiquette} : hôte manquant.")
    autorises = {h.lower() for h in hotes_autorises}
    if host not in autorises:
        raise ValueError(
            f"{etiquette} : hôte non autorisé {host!r}. "
            f"Autorisé(s) : {', '.join(sorted(autorises)) or '(aucun)'} "
            f"({indice_allowlist})."
        )
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass  # nom de domaine, pas une IP → OK
    else:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"{etiquette} : adresse IP interne interdite.")
    return base_url


def _valider_url_nakala(base_url: str, hotes_autorises: list[str]) -> str:
    """Valide une `base_url` Nakala (anti-SSRF + HTTPS). Cf.
    `_valider_url_anti_ssrf`."""
    return _valider_url_anti_ssrf(
        base_url,
        hotes_autorises,
        etiquette="nakala.base_url",
        indice_allowlist="ajouter à nakala.hotes_autorises si légitime",
    )


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
    # `repr=False` : la clé API ne doit jamais apparaître dans un repr/log
    # d'un NakalaConfig (doctrine « secrets jamais loggés »).
    api_key: str | None = Field(default=None, repr=False)
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

    @model_validator(mode="after")
    def _valider_base_url(self) -> ShareDocsConfig:
        # Allowlist effective : `hotes_autorises` vide → on retombe sur le
        # défaut du client (import paresseux = source unique, pas de cycle au
        # chargement de config). Le client `ClientShareDocs` reste l'autorité
        # qui re-valide au runtime ; cette validation est la défense en
        # profondeur côté config (F2), à parité avec Nakala.
        from archives_tool.external.sharedocs.client import HOTES_AUTORISES_DEFAUT

        effectifs = self.hotes_autorises or sorted(HOTES_AUTORISES_DEFAUT)
        self.base_url = _valider_url_anti_ssrf(
            self.base_url,
            list(effectifs),
            etiquette="sharedocs.base_url",
            indice_allowlist="ajouter à sharedocs.hotes_autorises si légitime",
        )
        return self


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

    @field_validator("nakala", "sharedocs", mode="before")
    @classmethod
    def _tolerer_section_distante_invalide(cls, v, info):  # noqa: ANN001
        """Une section optionnelle d'accès distant (`nakala`/`sharedocs`)
        invalide est **désactivée** (→ None) avec un avertissement, plutôt
        que de faire échouer TOUTE la `ConfigLocale`.

        Sans ça (backlog revue R2), un `nakala.base_url` invalide — cas
        élargi par le durcissement SSRF — ferait tomber la config entière
        aux défauts : perte silencieuse de `lecture_seule` (mode sûreté),
        des `racines` (images/dérivés) et de l'identité. Une feature
        distante mal configurée ne doit casser qu'elle-même.
        """
        if v is None:
            return None
        modele = NakalaConfig if info.field_name == "nakala" else ShareDocsConfig
        try:
            # Tolère tout type invalide (dict mal formé, scalaire, liste) :
            # n'importe quelle entrée invalide → section désactivée, jamais un
            # effondrement de toute la config.
            return modele.model_validate(v)
        except ValidationError as e:
            # NE PAS logger `e` brut : son repr Pydantic inclut `input_value`
            # (donc l'api_key Nakala ou un mot de passe d'URL) — doctrine
            # « secrets jamais loggés ». On ne garde que loc + msg, sans input.
            details = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or '<racine>'}: {err['msg']}"
                for err in e.errors(include_input=False, include_url=False)
            )
            _logger.warning(
                "Section '%s' du config_local ignorée (invalide) : %s",
                info.field_name,
                details,
            )
            return None

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
