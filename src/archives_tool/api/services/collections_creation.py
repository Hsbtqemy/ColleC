"""Création / modification d'une collection depuis l'UI web (V0.7+).

Logique de validation et persistance centralisée — la CLI peut s'y
brancher si besoin. Pas de duplication entre UI et CLI.

Validation côté serveur uniquement : le navigateur peut envoyer ce
qu'il veut, on ne lui fait pas confiance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import Collection, PhaseChantier

# Cote : alphanumérique + tiret + souligné. Pas d'espaces, pas
# d'accents (pour la portabilité fichier et URL). Voir CLAUDE.md.
PATTERN_COTE = re.compile(r"^[A-Za-z0-9_-]+$")

_PHASES_VALIDES: frozenset[str] = frozenset(p.value for p in PhaseChantier)


class FormulaireCollection(BaseModel):
    """État de saisie pour les pages création / modification.

    Lié aux Form fields HTML par FastAPI (`Annotated[..., Form()]`).
    Les valeurs vides côté HTML arrivent en `""` plutôt qu'en `None`.
    Le re-rendu en cas d'erreur ré-utilise ce modèle directement.
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    cote: str = Field(default="")
    titre: str = Field(default="")
    description: str = Field(default="")
    description_interne: str = Field(default="")
    editeur: str = Field(default="")
    lieu_edition: str = Field(default="")
    personnalite_associee: str = Field(default="")
    responsable_archives: str = Field(default="")
    date_debut: str = Field(default="")
    date_fin: str = Field(default="")
    phase: str = Field(default=PhaseChantier.CATALOGAGE.value)
    parent_cote: str = Field(default="")
    doi_nakala: str = Field(default="")

    @field_validator("phase")
    @classmethod
    def _phase_valide_ou_defaut(cls, v: str) -> str:
        """Normalise une phase vide ou inconnue en CATALOGAGE.

        La validation stricte (rejet d'une phase inconnue) est faite
        séparément dans `_valider_communs` pour qu'elle puisse
        produire une erreur de formulaire propre plutôt qu'un 422.
        """
        return v or PhaseChantier.CATALOGAGE.value


@dataclass
class ResultatValidation:
    erreurs: dict[str, str] = field(default_factory=dict)
    # Parent résolu pendant la validation — réutilisé par
    # `creer_collection` / `modifier_collection` pour éviter une
    # seconde requête.
    parent_resolu: Collection | None = None

    @property
    def ok(self) -> bool:
        return not self.erreurs


def lire_collection_par_cote(db: Session, cote: str) -> Collection | None:
    """Lecture par cote. `None` si non trouvée."""
    return db.scalar(select(Collection).where(Collection.cote_collection == cote))


def formulaire_depuis_collection(col: Collection) -> "FormulaireCollection":
    """Pré-remplit un `FormulaireCollection` depuis une Collection
    existante (pour la page de modification)."""
    return FormulaireCollection(
        cote=col.cote_collection,
        titre=col.titre,
        description=col.description or "",
        description_interne=col.description_interne or "",
        editeur=col.editeur or "",
        lieu_edition=col.lieu_edition or "",
        personnalite_associee=col.personnalite_associee or "",
        responsable_archives=col.responsable_archives or "",
        date_debut=col.date_debut or "",
        date_fin=col.date_fin or "",
        phase=col.phase or PhaseChantier.CATALOGAGE.value,
        parent_cote=col.parent.cote_collection if col.parent else "",
        doi_nakala=col.doi_nakala or "",
    )


def _valider_communs(
    db: Session,
    formulaire: FormulaireCollection,
    *,
    existante: Collection | None,
) -> ResultatValidation:
    """Validation partagée création / modification.

    `existante` non-None signale une modification : la self-référence
    parentale est rejetée et le DOI ne lève pas d'erreur s'il est
    déjà porté par cette même collection.
    """
    res = ResultatValidation()

    if not formulaire.titre.strip():
        res.erreurs["titre"] = "Le titre est obligatoire."

    if formulaire.phase and formulaire.phase not in _PHASES_VALIDES:
        res.erreurs["phase"] = "Phase inconnue."

    parent_cote = formulaire.parent_cote.strip()
    if parent_cote:
        if existante is not None and parent_cote == existante.cote_collection:
            res.erreurs["parent_cote"] = (
                "Une collection ne peut pas être son propre parent."
            )
        else:
            parent = lire_collection_par_cote(db, parent_cote)
            if parent is None:
                res.erreurs["parent_cote"] = (
                    f"Aucune collection parente avec la cote {parent_cote!r}."
                )
            else:
                res.parent_resolu = parent

    if formulaire.doi_nakala:
        existant = db.scalar(
            select(Collection).where(Collection.doi_nakala == formulaire.doi_nakala)
        )
        if existant is not None and (existante is None or existant.id != existante.id):
            res.erreurs["doi_nakala"] = (
                f"Le DOI Nakala est déjà associé à la collection "
                f"{existant.cote_collection!r}."
            )

    return res


def valider_formulaire(
    db: Session, formulaire: FormulaireCollection
) -> ResultatValidation:
    """Valide un formulaire de création. Erreurs inscrites par champ."""
    res = _valider_communs(db, formulaire, existante=None)

    cote = formulaire.cote.strip()
    if not cote:
        res.erreurs["cote"] = "La cote est obligatoire."
    elif not PATTERN_COTE.match(cote):
        res.erreurs["cote"] = (
            "Caractères autorisés : lettres, chiffres, tiret, souligné."
        )
    elif lire_collection_par_cote(db, cote) is not None:
        res.erreurs["cote"] = f"La cote {cote!r} existe déjà."

    return res


def valider_modification(
    db: Session, col: Collection, formulaire: FormulaireCollection
) -> ResultatValidation:
    """Validation pour la modification. La cote n'est jamais re-validée
    (verrouillée à l'UI). Le DOI n'est rejeté que s'il pointe vers une
    AUTRE collection ; le parent ne peut pas être la collection elle-même."""
    return _valider_communs(db, formulaire, existante=col)


def _appliquer_formulaire(
    col: Collection,
    formulaire: FormulaireCollection,
    parent: Collection | None,
) -> None:
    """Copie les champs éditables du formulaire sur la Collection.
    La cote et la traçabilité sont gérées par les appelants."""
    col.titre = formulaire.titre.strip()
    col.description = formulaire.description or None
    col.description_interne = formulaire.description_interne or None
    col.editeur = formulaire.editeur or None
    col.lieu_edition = formulaire.lieu_edition or None
    col.personnalite_associee = formulaire.personnalite_associee or None
    col.responsable_archives = formulaire.responsable_archives or None
    col.date_debut = formulaire.date_debut or None
    col.date_fin = formulaire.date_fin or None
    col.doi_nakala = formulaire.doi_nakala or None
    col.phase = formulaire.phase or PhaseChantier.CATALOGAGE.value
    col.parent_id = parent.id if parent else None


def creer_collection(
    db: Session,
    formulaire: FormulaireCollection,
    *,
    cree_par: str,
    parent: Collection | None = None,
) -> Collection:
    """Crée la collection en base. Suppose que `valider_formulaire` est
    déjà passé — la validation n'est pas re-faite ici.

    `parent` (résolu par la validation, cf. `ResultatValidation.parent_resolu`)
    évite une seconde requête. Si non fourni mais `formulaire.parent_cote`
    rempli, on retombe sur une lookup.
    """
    if parent is None and formulaire.parent_cote.strip():
        parent = lire_collection_par_cote(db, formulaire.parent_cote.strip())

    col = Collection(cote_collection=formulaire.cote.strip(), cree_par=cree_par)
    _appliquer_formulaire(col, formulaire, parent)
    db.add(col)
    db.commit()
    db.refresh(col)
    return col


def modifier_collection(
    db: Session,
    col: Collection,
    formulaire: FormulaireCollection,
    *,
    modifie_par: str,
    parent: Collection | None = None,
) -> Collection:
    """Met à jour la collection. La cote n'est jamais modifiée."""
    if parent is None and formulaire.parent_cote.strip():
        parent = lire_collection_par_cote(db, formulaire.parent_cote.strip())

    _appliquer_formulaire(col, formulaire, parent)
    col.modifie_par = modifie_par
    col.modifie_le = datetime.now()
    db.commit()
    db.refresh(col)
    return col
