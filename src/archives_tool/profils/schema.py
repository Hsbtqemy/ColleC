"""Schéma Pydantic d'un profil d'import.

Un profil décrit comment lire un tableur existant et une arborescence
de scans pour amorcer une collection en base. Ce n'est pas une
configuration permanente : une fois l'import fait, la base est la
source de vérité.

Règles transversales :
- Validation stricte : `extra="forbid"` sur tous les modèles. Toute
  clé inconnue est une erreur.
- Versioning obligatoire : le champ `version_profil` sert à gérer
  l'évolution du format sans casser les profils existants.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from archives_tool.models.enums import PhaseChantier

TypeTransformation = Literal["slug", "upper", "lower", "strip", "strip_accents"]
"""Transformations applicables à une valeur mappée.

- `slug` : lower + non-alphanum remplacés par tirets + collapse.
- `upper` / `lower` : changement de casse.
- `strip` : suppression des espaces en bordure.
- `strip_accents` : suppression des diacritiques (NFD + filtrage + NFC).

Le câblage effectif est dans `archives_tool.importers.transformateur`.
"""


class _ProfilBase(BaseModel):
    """Configuration commune à tous les sous-modèles du profil."""

    model_config = ConfigDict(extra="forbid")


class FondsProfil(_ProfilBase):
    """Métadonnées du fonds cible créé par l'import.

    Le fonds est l'**entité racine** : un corpus brut (revue, fonds
    personnel, ensemble de correspondance). À sa création, sa
    collection miroir est créée automatiquement (invariant 1).

    Tous les items importés sont rattachés à ce fonds (`fonds_id`)
    et ajoutés à sa miroir (invariant 6, géré par `creer_item`).
    """

    cote: str
    titre: str
    description: str | None = None
    description_publique: str | None = None
    description_interne: str | None = None
    personnalite_associee: str | None = None
    responsable_archives: str | None = None
    editeur: str | None = None
    lieu_edition: str | None = None
    periodicite: str | None = None
    issn: str | None = None
    date_debut: str | None = None
    date_fin: str | None = None


class CollectionMiroirProfil(_ProfilBase):
    """Personnalisations optionnelles de la collection miroir.

    Section facultative : si absente, la miroir hérite du fonds
    (cote = fonds.cote, titre = fonds.titre, descriptions = None,
    phase = catalogage). Si présente, seuls les champs renseignés
    écrasent ces valeurs héritées.
    """

    cote: str | None = None
    titre: str | None = None
    description: str | None = None
    description_publique: str | None = None
    description_interne: str | None = None
    # Typer en `PhaseChantier` plutôt que `str` : Pydantic rejette
    # automatiquement les valeurs hors enum à la validation YAML, avec
    # un message qui liste les phases acceptées.
    phase: PhaseChantier | None = None
    doi_nakala: str | None = None
    doi_collection_nakala_parent: str | None = None
    personnalite_associee: str | None = None
    responsable_archives: str | None = None


class TableurSource(_ProfilBase):
    """Description du fichier tableur (xlsx ou csv) à lire."""

    chemin: str
    feuille: str | None = None
    ligne_entete: int = 1
    lignes_ignorer_apres_entete: int = 0
    valeurs_nulles: list[str] = Field(
        default_factory=lambda: ["none", "n/a", "s.d.", "NaN", ""]
    )
    separateur_csv: str = ";"
    encodage: str = "utf-8"


class MappingSimple(_ProfilBase):
    """Forme 1 : une colonne source, pas de transformation.

    Forme interne après parsing. Dans le YAML, cette forme s'écrit
    directement sous forme de chaîne : `cote: "Cote"`.
    """

    source: str


class MappingTransforme(_ProfilBase):
    """Forme 2 : une colonne source, avec séparateur et/ou transformation."""

    source: str
    separateur: str | list[str] | None = None
    transformation: TypeTransformation | None = None


class MappingAgrege(_ProfilBase):
    """Forme 3 : plusieurs colonnes agrégées en une valeur unique."""

    sources: list[str] = Field(min_length=1)
    separateur_sortie: str = " | "
    transformation: TypeTransformation | None = None


MappingChamp = Union[MappingSimple, MappingTransforme, MappingAgrege]
"""Un mapping peut prendre trois formes, discriminées par leurs clés.

Dans le YAML :
- chaîne simple → `MappingSimple(source=<chaîne>)`
- objet avec `source` → `MappingSimple` ou `MappingTransforme`
- objet avec `sources` → `MappingAgrege`
"""


def _parse_mapping_champ(valeur: Any) -> MappingChamp:
    """Détecte la forme d'un mapping et renvoie le modèle adéquat."""
    if isinstance(valeur, str):
        return MappingSimple(source=valeur)
    if isinstance(valeur, dict):
        if "sources" in valeur:
            return MappingAgrege.model_validate(valeur)
        if "source" in valeur:
            # MappingTransforme si l'un des champs de transformation est là,
            # sinon MappingSimple — les deux modèles sont équivalents si
            # pas de séparateur ni de transformation, mais Transforme
            # accepte des clés supplémentaires.
            if "separateur" in valeur or "transformation" in valeur:
                return MappingTransforme.model_validate(valeur)
            return MappingSimple.model_validate(valeur)
        raise ValueError(
            "Mapping objet : doit contenir 'source' (une colonne) ou "
            "'sources' (plusieurs colonnes)."
        )
    raise ValueError(
        f"Mapping invalide : attendu une chaîne ou un objet, reçu {type(valeur).__name__}."
    )


class MappingProfil(_ProfilBase):
    """Conteneur du dictionnaire champ cible → mapping source.

    Clés : nom du champ en base (`cote`, `titre`, `date`...) ou clé
    étendue préfixée `metadonnees.` (ex. `metadonnees.auteurs`).

    Les clés du dict `champs` sont arbitraires. Mais la strictness
    `extra="forbid"` héritée de `_ProfilBase` s'applique au niveau du
    modèle : après l'absorber qui wrappe le YAML flat en
    `{champs: {...}}`, aucune clé supplémentaire à `champs` n'est
    tolérée.
    """

    champs: dict[str, MappingChamp]

    @model_validator(mode="before")
    @classmethod
    def _absorber_dict_en_champs(cls, data: Any) -> Any:
        """Permet d'écrire `mapping:` directement comme un dict sans clé
        intermédiaire `champs`."""
        if isinstance(data, dict) and "champs" not in data:
            return {"champs": data}
        return data

    @field_validator("champs", mode="before")
    @classmethod
    def _parser_chaque_mapping(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            raise ValueError("mapping doit être un dictionnaire.")
        return {cle: _parse_mapping_champ(val) for cle, val in v.items()}


class ResolutionFichiers(_ProfilBase):
    """Description de l'arborescence des scans à rapprocher des items."""

    racine: str
    motif_chemin: str
    type_motif: Literal["template", "regex"] = "template"
    recursif: bool = True
    extensions: list[str] = Field(
        default_factory=lambda: [".tif", ".tiff", ".jpg", ".jpeg", ".png", ".pdf"]
    )
    template_nommage_canonique: str | None = None

    @field_validator("motif_chemin")
    @classmethod
    def _non_vide(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("motif_chemin ne peut pas être vide.")
        return v

    @model_validator(mode="after")
    def _valider_regex_si_type_regex(self) -> ResolutionFichiers:
        if self.type_motif == "regex":
            try:
                re.compile(self.motif_chemin)
            except re.error as e:
                raise ValueError(
                    f"motif_chemin (type_motif=regex) ne compile pas : {e}"
                ) from e
        return self


class DecompositionCote(_ProfilBase):
    """Décomposition d'une cote item en sous-parties via regex nommée."""

    regex: str
    stockage: str = "hierarchie"

    @field_validator("regex")
    @classmethod
    def _regex_compile(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"decomposition_cote.regex invalide : {e}") from e
        return v


class DecompositionType(_ProfilBase):
    """Décomposition d'une colonne « Type » à séparateurs en niveaux."""

    colonne: str
    separateur: str = " | "
    niveaux: list[str] = Field(min_length=1)
    stockage: str = "typologie"


class Profil(_ProfilBase):
    """Racine du schéma de profil d'import (v2).

    Le format v2 sépare explicitement les concepts de **fonds** (corpus
    brut) et de **collection miroir** (sa première vue, créée auto).
    Les profils v1 (avec section `collection:` racine) sont rejetés
    par le loader avec un message de migration manuelle.
    """

    version_profil: Literal[2]
    fonds: FondsProfil
    collection_miroir: CollectionMiroirProfil | None = None
    tableur: TableurSource
    granularite_source: Literal["item", "fichier"] = "item"
    mapping: MappingProfil
    fichiers: ResolutionFichiers | None = None
    valeurs_par_defaut: dict[str, Any] = Field(default_factory=dict)
    decomposition_cote: DecompositionCote | None = None
    decomposition_type: DecompositionType | None = None
    # Tolérance : une ligne sans cote est normalement une erreur
    # bloquante. Mis à True, ces lignes sont simplement ignorées —
    # utile quand un tableur d'inventaire contient des lignes de
    # documentation / légende en pied de fichier (non catalographiques).
    ignorer_lignes_sans_cote: bool = False
    # Regex appliquée à `Fichier.nom_fichier` pour extraire l'ordre
    # (numéro de page) de chaque scan. Le groupe 1 doit être un entier.
    # Utile quand le tableur n'a pas de colonne « ordre » mais que le
    # nom de fichier porte un suffixe `_001`, `_002`, etc.
    # Si toutes les valeurs extraites sont uniques et entières, elles
    # remplacent l'ordre séquentiel par défaut.
    ordre_depuis_nom: str | None = None

    @model_validator(mode="after")
    def _cote_requise_si_granularite_fichier(self) -> Profil:
        if self.granularite_source == "fichier" and "cote" not in self.mapping.champs:
            raise ValueError(
                "granularite_source='fichier' : le mapping doit inclure une "
                "clé 'cote' (utilisée pour regrouper les lignes en items)."
            )
        return self

    @field_validator("ordre_depuis_nom")
    @classmethod
    def _valider_regex_ordre(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            compile_ = re.compile(v)
        except re.error as e:
            raise ValueError(f"ordre_depuis_nom : regex invalide : {e}") from e
        if compile_.groups < 1:
            raise ValueError(
                "ordre_depuis_nom : la regex doit contenir au moins un "
                "groupe de capture (le numéro de page)."
            )
        return v
