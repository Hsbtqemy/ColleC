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
    personnalite_associee: str = ""
    responsable_archives: str = ""
    date_debut: str = ""
    date_fin: str = ""
    phase: str = PhaseChantier.CATALOGAGE.value
    parent_cote: str = ""
    doi_nakala: str = ""


@dataclass
class ResultatValidation:
    erreurs: dict[str, str] = field(default_factory=dict)
    # Parent résolu pendant la validation — réutilisé par
    # `creer_collection` pour éviter une seconde requête.
    parent_resolu: Collection | None = None

    @property
    def ok(self) -> bool:
        return not self.erreurs


_PHASES_VALIDES: frozenset[str] = frozenset(p.value for p in PhaseChantier)


def lire_collection_par_cote(db: Session, cote: str) -> Collection | None:
    """Lecture par cote — exposé pour les tests et les futures routes
    d'édition. `None` si non trouvée.
    """
    return db.scalar(select(Collection).where(Collection.cote_collection == cote))


def valider_formulaire(
    db: Session, formulaire: FormulaireCollection
) -> ResultatValidation:
    """Valide un formulaire de création. Erreurs inscrites par champ.

    Si la cote parente est valide, la collection résolue est mise à
    disposition via `res.parent_resolu` pour éviter à `creer_collection`
    de la requêter à nouveau.
    """
    res = ResultatValidation()

    cote = formulaire.cote.strip()
    if not cote:
        res.erreurs["cote"] = "La cote est obligatoire."
    elif not PATTERN_COTE.match(cote):
        res.erreurs["cote"] = (
            "Caractères autorisés : lettres, chiffres, tiret, souligné."
        )
    elif lire_collection_par_cote(db, cote) is not None:
        res.erreurs["cote"] = f"La cote {cote!r} existe déjà."

    if not formulaire.titre.strip():
        res.erreurs["titre"] = "Le titre est obligatoire."

    if formulaire.phase and formulaire.phase not in _PHASES_VALIDES:
        res.erreurs["phase"] = "Phase inconnue."

    parent_cote = formulaire.parent_cote.strip()
    if parent_cote:
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
        if existant is not None:
            res.erreurs["doi_nakala"] = (
                f"Le DOI Nakala est déjà associé à la collection "
                f"{existant.cote_collection!r}."
            )

    return res


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

    col = Collection(
        cote_collection=formulaire.cote.strip(),
        titre=formulaire.titre.strip(),
        description=formulaire.description or None,
        description_interne=formulaire.description_interne or None,
        editeur=formulaire.editeur or None,
        lieu_edition=formulaire.lieu_edition or None,
        personnalite_associee=formulaire.personnalite_associee or None,
        responsable_archives=formulaire.responsable_archives or None,
        date_debut=formulaire.date_debut or None,
        date_fin=formulaire.date_fin or None,
        doi_nakala=formulaire.doi_nakala or None,
        phase=formulaire.phase or PhaseChantier.CATALOGAGE.value,
        parent_id=parent.id if parent else None,
        cree_par=cree_par,
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    return col
