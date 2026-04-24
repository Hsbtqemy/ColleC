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


class _ProfilBase(BaseModel):
    """Configuration commune à tous les sous-modèles du profil."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class CollectionProfil(_ProfilBase):
    """Métadonnées de la collection cible créée / complétée par l'import."""

    cote: str
    titre: str
    parent_cote: str | None = None
    titre_secondaire: str | None = None
    editeur: str | None = None
    lieu_edition: str | None = None
    periodicite: str | None = None
    date_debut: str | None = None
    date_fin: str | None = None
    issn: str | None = None
    doi_nakala: str | None = None
    description: str | None = None
    description_interne: str | None = None
    auteur_principal: str | None = None


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
    transformation: str | None = None


class MappingAgrege(_ProfilBase):
    """Forme 3 : plusieurs colonnes agrégées en une valeur unique."""

    sources: list[str] = Field(min_length=1)
    separateur_sortie: str = " | "
    transformation: str | None = None


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
    """

    # `extra="allow"` ici est intentionnel : on veut permettre des clés
    # arbitraires, on les validera au niveau du dict parent.
    model_config = ConfigDict(extra="allow")

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
    """Racine du schéma de profil d'import."""

    version_profil: Literal[1]
    collection: CollectionProfil
    tableur: TableurSource
    granularite_source: Literal["item", "fichier"] = "item"
    mapping: MappingProfil
    fichiers: ResolutionFichiers | None = None
    valeurs_par_defaut: dict[str, Any] = Field(default_factory=dict)
    decomposition_cote: DecompositionCote | None = None
    decomposition_type: DecompositionType | None = None

    @model_validator(mode="after")
    def _cote_requise_si_granularite_fichier(self) -> Profil:
        if self.granularite_source == "fichier" and "cote" not in self.mapping.champs:
            raise ValueError(
                "granularite_source='fichier' : le mapping doit inclure une "
                "clé 'cote' (utilisée pour regrouper les lignes en items)."
            )
        return self
