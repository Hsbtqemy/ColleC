"""Chargement et validation d'un profil YAML."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .schema import Profil


class ProfilInvalide(Exception):
    """Erreur de chargement ou de validation d'un profil YAML."""

    def __init__(self, chemin: Path, erreurs: list[str]) -> None:
        self.chemin = chemin
        self.erreurs = erreurs
        super().__init__(self._format())

    def _format(self) -> str:
        entete = f"Profil invalide : {self.chemin}"
        lignes = [entete] + [f"  - {e}" for e in self.erreurs]
        return "\n".join(lignes)


class ProfilObsoleteV1(ProfilInvalide):
    """Profil au format v1 — non supporté depuis V0.9.0-gamma.1.

    Le format v1 décrit une `collection:` racine ; le format v2 sépare
    `fonds:` (corpus brut, racine) et `collection_miroir:` (overrides
    optionnels de la miroir auto-créée).

    Pas de migration automatique : la situation v1 → v2 est ambiguë
    (la « collection » devient-elle un fonds ou une collection libre ?
    qu'en est-il de `parent_cote` ?). Mieux vaut rejeter clairement
    et laisser l'utilisateur choisir.
    """

    MESSAGE_MIGRATION = (
        "Profil au format v1 — non supporté depuis V0.9.0-gamma.1.\n"
        "Le format v2 sépare les concepts de fonds et de collection :\n"
        "  - renommer la section `collection:` en `fonds:`\n"
        "  - changer `version_profil: 1` en `version_profil: 2`\n"
        "  - retirer `parent_cote` (la hiérarchie a disparu)\n"
        "  - optionnel : ajouter une section `collection_miroir:` pour\n"
        "    personnaliser le titre / la description / la phase de la\n"
        "    miroir auto-créée à partir du fonds.\n"
        "Voir docs/profils.md pour le guide complet."
    )

    def __init__(self, chemin: Path) -> None:
        super().__init__(chemin, [self.MESSAGE_MIGRATION])


def _normaliser_nfc_recursif(valeur: Any) -> Any:
    """Normalise en NFC toutes les chaînes contenues dans une structure
    imbriquée (dicts, listes). Laisse les autres types inchangés."""
    if isinstance(valeur, str):
        return unicodedata.normalize("NFC", valeur)
    if isinstance(valeur, dict):
        return {cle: _normaliser_nfc_recursif(v) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_normaliser_nfc_recursif(v) for v in valeur]
    return valeur


def _formater_erreurs_pydantic(exc: ValidationError) -> list[str]:
    """Transforme les erreurs Pydantic en lignes lisibles « chemin : message »."""
    lignes = []
    for err in exc.errors():
        chemin = ".".join(str(e) for e in err["loc"]) or "<racine>"
        msg = err["msg"]
        lignes.append(f"{chemin} : {msg}")
    return lignes


def charger_profil(chemin: Path) -> Profil:
    """Lit, parse, valide et renvoie un `Profil`.

    - Résout le chemin relatif du tableur par rapport au dossier
      contenant le profil YAML (pas au cwd).
    - Normalise toutes les chaînes en Unicode NFC avant validation.
    - Traduit les `ValidationError` Pydantic en `ProfilInvalide` avec
      des erreurs localisées.
    """
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ProfilInvalide(chemin, [f"Fichier introuvable : {chemin}"])

    try:
        texte = chemin.read_text(encoding="utf-8")
    except OSError as e:
        raise ProfilInvalide(chemin, [f"Lecture impossible : {e}"]) from e

    try:
        donnees = yaml.safe_load(texte)
    except yaml.YAMLError as e:
        raise ProfilInvalide(chemin, [f"YAML invalide : {e}"]) from e

    if not isinstance(donnees, dict):
        raise ProfilInvalide(
            chemin,
            [f"Le profil doit être un mapping YAML (reçu : {type(donnees).__name__})."],
        )

    donnees = _normaliser_nfc_recursif(donnees)

    # Détection précoce des profils v1 : version=1, ou présence de la
    # section `collection:` racine (forme v1) avec absence de `fonds:`.
    # Le message d'erreur est plus utile que les erreurs Pydantic
    # cryptiques sur des clés manquantes/inconnues.
    version = donnees.get("version_profil")
    if version == 1 or ("collection" in donnees and "fonds" not in donnees):
        raise ProfilObsoleteV1(chemin)

    try:
        profil = Profil.model_validate(donnees)
    except ValidationError as e:
        raise ProfilInvalide(chemin, _formater_erreurs_pydantic(e)) from e

    # Résolution du chemin du tableur : si relatif, ancré sur le dossier
    # contenant le profil.
    chemin_tableur = Path(profil.tableur.chemin)
    if not chemin_tableur.is_absolute():
        profil.tableur.chemin = str((chemin.parent / chemin_tableur).resolve())

    return profil
