"""Création d'une collection vide depuis l'UI web (V0.7).

Logique de validation et création centralisée — la CLI peut s'y
brancher si besoin (V0.8 : commande `archives-tool collection nouvelle`
ou équivalent). Pas de duplication entre UI et CLI.

Validation côté serveur uniquement : le navigateur peut envoyer ce
qu'il veut, on ne lui fait pas confiance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import Collection, PhaseChantier

# Cote : alphanumérique + tiret + souligné. Pas d'espaces, pas
# d'accents (pour la portabilité fichier et URL). Voir CLAUDE.md.
PATTERN_COTE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class FormulaireCollection:
    """État de saisie pour la page « Nouvelle collection vide ».

    Tous les champs optionnels sont à `""` (input vide en HTML) plutôt
    qu'à `None` pour faciliter la propagation au template en cas
    d'erreur de validation.
    """

    cote: str = ""
    titre: str = ""
    description: str = ""
    description_interne: str = ""
    editeur: str = ""
    lieu_edition: str = ""
    auteur_principal: str = ""
    date_debut: str = ""
    date_fin: str = ""
    phase: str = PhaseChantier.CATALOGAGE.value
    parent_cote: str = ""
    doi_nakala: str = ""


@dataclass
class ResultatValidation:
    erreurs: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.erreurs


_PHASES_VALIDES: frozenset[str] = frozenset(p.value for p in PhaseChantier)


def valider_formulaire(
    db: Session, formulaire: FormulaireCollection
) -> ResultatValidation:
    """Valide un formulaire de création. Erreurs inscrites par champ."""
    res = ResultatValidation()

    cote = formulaire.cote.strip()
    if not cote:
        res.erreurs["cote"] = "La cote est obligatoire."
    elif not PATTERN_COTE.match(cote):
        res.erreurs["cote"] = (
            "Caractères autorisés : lettres, chiffres, tiret, souligné."
        )
    elif (
        db.scalar(select(Collection).where(Collection.cote_collection == cote))
        is not None
    ):
        res.erreurs["cote"] = f"La cote {cote!r} existe déjà."

    if not formulaire.titre.strip():
        res.erreurs["titre"] = "Le titre est obligatoire."

    if formulaire.phase and formulaire.phase not in _PHASES_VALIDES:
        res.erreurs["phase"] = "Phase inconnue."

    parent_cote = formulaire.parent_cote.strip()
    if parent_cote:
        parent = db.scalar(
            select(Collection).where(Collection.cote_collection == parent_cote)
        )
        if parent is None:
            res.erreurs["parent_cote"] = (
                f"Aucune collection parente avec la cote {parent_cote!r}."
            )

    if formulaire.doi_nakala:
        existant = db.scalar(
            select(Collection).where(Collection.doi_nakala == formulaire.doi_nakala)
        )
        if existant is not None:
            res.erreurs["doi_nakala"] = (
                f"Le DOI Nakala est déjà associé à la collection "
                f"{existant.cote_collection!r}."
            )

    return res


def creer_collection(
    db: Session, formulaire: FormulaireCollection, *, cree_par: str
) -> Collection:
    """Crée la collection en base. Suppose que `valider_formulaire` est
    déjà passé — la validation n'est pas re-faite ici.

    `cree_par` alimente `cree_par`/`modifie_par` (TracabiliteMixin).
    """
    parent_id: int | None = None
    parent_cote = formulaire.parent_cote.strip()
    if parent_cote:
        parent = db.scalar(
            select(Collection).where(Collection.cote_collection == parent_cote)
        )
        parent_id = parent.id if parent else None

    col = Collection(
        cote_collection=formulaire.cote.strip(),
        titre=formulaire.titre.strip(),
        description=(formulaire.description or None) or None,
        description_interne=formulaire.description_interne or None,
        editeur=formulaire.editeur or None,
        lieu_edition=formulaire.lieu_edition or None,
        auteur_principal=formulaire.auteur_principal or None,
        date_debut=formulaire.date_debut or None,
        date_fin=formulaire.date_fin or None,
        doi_nakala=formulaire.doi_nakala or None,
        phase=formulaire.phase or PhaseChantier.CATALOGAGE.value,
        parent_id=parent_id,
        cree_par=cree_par,
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    return col
