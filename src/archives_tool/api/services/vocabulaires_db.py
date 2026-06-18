"""CRUD des vocabulaires personnalisés en base (V0.9.4 lot 3a).

Distinct de :mod:`vocabulaires` qui héberge les options **hardcoded**
(LANGUES, TYPES_COAR, ETATS) — fondamentaux du domaine, structurels
pour les champs item système, jamais modifiables depuis l'UI.

Ce module gère les ``Vocabulaire`` et leurs ``ValeurControlee`` en
base, pour les utilisateurs qui veulent référencer un vocabulaire
custom depuis un ``ChampPersonnalise`` (cf. lot 3b). Sépare clairement
les deux sources :

- **Hardcoded** (`vocabulaires.OPTIONS_PAR_CHAMP`) : enum stable du
  domaine, partagé par tous les fonds. Ne nécessite pas d'UI.
- **DB** (ce module) : vocabulaires propres au chantier de
  l'utilisateur. Créés, renommés, étendus au fil du temps.

Sémantique « déprécier vs supprimer » alignée sur :mod:`champs_personnalises` :

- une **valeur** se déprécie via ``actif=False`` (champ déjà présent
  sur :class:`models.ValeurControlee`) — les items qui la portent
  ne perdent pas leur valeur, elle ne sort juste plus du
  dropdown ;
- la **suppression du vocabulaire entier** est interdite tant qu'un
  ``ChampPersonnalise`` y fait référence (FK).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
    OperationInterdite,
)
from archives_tool.models import ChampPersonnalise, ValeurControlee, Vocabulaire


# Slug d'un code de vocabulaire ou valeur : on autorise les majuscules
# (langues ISO 639-3 sont en minuscules par convention mais COAR
# utilise des slugs comme `c_18cf`) et les chiffres. Aucun espace,
# accent ou ponctuation autre que `-` et `_` (compatible URL, FTS et
# JSON keys).
PATTERN_CODE_VOCAB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

_MSG_CODE_FORMAT = (
    "Le code doit être alphanumérique avec tirets ou underscores "
    "(ex. : tag_personnage, c_18cf, fra)."
)


class VocabulaireIntrouvable(EntiteIntrouvable):
    """Le vocabulaire demandé n'existe pas."""


class ValeurIntrouvable(EntiteIntrouvable):
    """La valeur contrôlée demandée n'existe pas."""


class VocabulaireInvalide(FormulaireInvalide):
    """Saisie invalide (code, libellé, doublon)."""


class ValeurInvalide(FormulaireInvalide):
    """Saisie invalide pour une valeur contrôlée."""


class VocabulaireReference(OperationInterdite):
    """Tentative de supprimer un vocabulaire encore référencé par un
    ``ChampPersonnalise``. La FK ``valeurs_controlees_id`` empêcherait
    la suppression côté SQL (`RESTRICT` par défaut) mais le service
    lève cette exception explicite avec la liste des champs en cause
    pour que la route puisse l'afficher proprement."""

    def __init__(self, champs_referents: list[str]) -> None:
        self.champs_referents = champs_referents
        super().__init__(
            f"Vocabulaire référencé par {len(champs_referents)} "
            f"champ(s) personnalisé(s) : {', '.join(champs_referents)}."
        )


class FormulaireVocabulaire(BaseModel):
    """Formulaire de création / modification d'un vocabulaire."""

    model_config = ConfigDict(str_strip_whitespace=False)

    code: str = Field(default="")
    libelle: str = Field(default="")
    description: str = Field(default="")
    description_interne: str = Field(default="")
    uri_base: str = Field(default="")


class FormulaireValeur(BaseModel):
    """Formulaire de création / modification d'une valeur contrôlée."""

    model_config = ConfigDict(str_strip_whitespace=False)

    code: str = Field(default="")
    libelle: str = Field(default="")
    uri: str = Field(default="")
    description_interne: str = Field(default="")
    ordre: int = 0


# ---------------------------------------------------------------------------
# Vocabulaire CRUD
# ---------------------------------------------------------------------------


def lister_vocabulaires(db: Session) -> list[Vocabulaire]:
    """Tous les vocabulaires, triés par libellé. Eager loading des
    valeurs (compteur de valeurs) et des fonds rattachés (badge
    `global` / `N fonds` sur la page liste — sans N+1)."""
    return list(
        db.scalars(
            select(Vocabulaire)
            .options(
                selectinload(Vocabulaire.valeurs),
                selectinload(Vocabulaire.fonds_rattaches),
            )
            .order_by(Vocabulaire.libelle)
        ).all()
    )


def vocabulaire_par_id(db: Session, vocab_id: int) -> Vocabulaire:
    """Charge un vocabulaire par id ou lève :class:`VocabulaireIntrouvable`.
    Eager loading des valeurs (la page détail itère dessus) et des
    fonds rattachés (section rattachement T3)."""
    vocab = db.scalar(
        select(Vocabulaire)
        .options(
            selectinload(Vocabulaire.valeurs),
            selectinload(Vocabulaire.fonds_rattaches),
        )
        .where(Vocabulaire.id == vocab_id)
    )
    if vocab is None:
        raise VocabulaireIntrouvable(f"Vocabulaire {vocab_id} introuvable.")
    return vocab


def _valider_vocabulaire(
    db: Session,
    formulaire: FormulaireVocabulaire,
    *,
    ignorer_id: int | None = None,
) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    code = formulaire.code.strip()
    if not code:
        erreurs["code"] = "Le code est obligatoire."
    elif not PATTERN_CODE_VOCAB.match(code):
        erreurs["code"] = _MSG_CODE_FORMAT
    else:
        stmt = select(Vocabulaire.id).where(Vocabulaire.code == code)
        if ignorer_id is not None:
            stmt = stmt.where(Vocabulaire.id != ignorer_id)
        if db.scalar(stmt) is not None:
            erreurs["code"] = f"Le code {code!r} existe déjà."
    if not formulaire.libelle.strip():
        erreurs["libelle"] = "Le libellé est obligatoire."
    return erreurs


def creer_vocabulaire(db: Session, formulaire: FormulaireVocabulaire) -> Vocabulaire:
    """Crée un vocabulaire vide. Les valeurs s'ajoutent ensuite via
    :func:`ajouter_valeur`."""
    erreurs = _valider_vocabulaire(db, formulaire)
    if erreurs:
        raise VocabulaireInvalide(erreurs)
    vocab = Vocabulaire(
        code=formulaire.code.strip(),
        libelle=formulaire.libelle.strip(),
        description=formulaire.description.strip() or None,
        description_interne=formulaire.description_interne.strip() or None,
        uri_base=formulaire.uri_base.strip() or None,
    )
    db.add(vocab)
    db.commit()
    db.refresh(vocab)
    return vocab


def modifier_vocabulaire(
    db: Session, vocab_id: int, formulaire: FormulaireVocabulaire
) -> Vocabulaire:
    """Modifie un vocabulaire existant."""
    vocab = vocabulaire_par_id(db, vocab_id)
    erreurs = _valider_vocabulaire(db, formulaire, ignorer_id=vocab_id)
    if erreurs:
        raise VocabulaireInvalide(erreurs)
    vocab.code = formulaire.code.strip()
    vocab.libelle = formulaire.libelle.strip()
    vocab.description = formulaire.description.strip() or None
    vocab.description_interne = formulaire.description_interne.strip() or None
    vocab.uri_base = formulaire.uri_base.strip() or None
    db.commit()
    db.refresh(vocab)
    return vocab


def supprimer_vocabulaire(db: Session, vocab_id: int) -> None:
    """Suppression définitive. Lève :class:`VocabulaireReference` si
    le vocabulaire est encore référencé par un ``ChampPersonnalise``.

    La cascade ORM ``all, delete-orphan`` sur ``Vocabulaire.valeurs``
    supprime les valeurs associées automatiquement.
    """
    vocab = vocabulaire_par_id(db, vocab_id)
    referents = list(
        db.scalars(
            select(ChampPersonnalise.cle).where(
                ChampPersonnalise.valeurs_controlees_id == vocab_id
            )
        ).all()
    )
    if referents:
        raise VocabulaireReference(referents)
    db.delete(vocab)
    db.commit()


# ---------------------------------------------------------------------------
# ValeurControlee CRUD
# ---------------------------------------------------------------------------


def valeur_par_id(db: Session, valeur_id: int) -> ValeurControlee:
    valeur = db.get(ValeurControlee, valeur_id)
    if valeur is None:
        raise ValeurIntrouvable(f"Valeur {valeur_id} introuvable.")
    return valeur


def _valider_valeur(
    db: Session,
    vocabulaire_id: int,
    formulaire: FormulaireValeur,
    *,
    ignorer_id: int | None = None,
) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    code = formulaire.code.strip()
    if not code:
        erreurs["code"] = "Le code est obligatoire."
    elif not PATTERN_CODE_VOCAB.match(code):
        erreurs["code"] = _MSG_CODE_FORMAT
    else:
        stmt = select(ValeurControlee.id).where(
            ValeurControlee.vocabulaire_id == vocabulaire_id,
            ValeurControlee.code == code,
        )
        if ignorer_id is not None:
            stmt = stmt.where(ValeurControlee.id != ignorer_id)
        if db.scalar(stmt) is not None:
            erreurs["code"] = f"Le code {code!r} existe déjà dans ce vocabulaire."
    if not formulaire.libelle.strip():
        erreurs["libelle"] = "Le libellé est obligatoire."
    return erreurs


def ajouter_valeur(
    db: Session, vocabulaire_id: int, formulaire: FormulaireValeur
) -> ValeurControlee:
    """Ajoute une valeur à un vocabulaire.

    Garantit la cohérence du cache ORM : on assigne via la relation
    (``vocab.valeurs.append``) plutôt que la FK seule — sinon
    ``vocab.valeurs`` resterait stale dans la même session (SQLAlchemy
    ne back-populate que sur assignation via la relation, pas via la
    FK). Sans ça, le composer cartouche qui résout les libellés
    humains dans la même requête manquerait les nouvelles valeurs.
    """
    # Charge le vocab pour append côté relation (vs FK seule).
    vocab = vocabulaire_par_id(db, vocabulaire_id)
    erreurs = _valider_valeur(db, vocabulaire_id, formulaire)
    if erreurs:
        raise ValeurInvalide(erreurs)
    # Ordre par défaut : max+1 (ajoute en fin de liste).
    if formulaire.ordre == 0:
        max_ordre = db.scalar(
            select(func.max(ValeurControlee.ordre)).where(
                ValeurControlee.vocabulaire_id == vocabulaire_id
            )
        )
        ordre = (max_ordre or 0) + 1
    else:
        ordre = formulaire.ordre
    valeur = ValeurControlee(
        code=formulaire.code.strip(),
        libelle=formulaire.libelle.strip(),
        uri=formulaire.uri.strip() or None,
        description_interne=formulaire.description_interne.strip() or None,
        ordre=ordre,
        actif=True,
    )
    vocab.valeurs.append(valeur)
    db.commit()
    db.refresh(valeur)
    return valeur


def modifier_valeur(
    db: Session, valeur_id: int, formulaire: FormulaireValeur
) -> ValeurControlee:
    """Modifie une valeur existante. ``code`` peut changer — pas de
    propagation aux items (contrairement au rename d'un champ), parce
    qu'un ``code`` de valeur n'est pas stocké dans ``Item.metadonnees``
    en clé mais en *valeur* : la responsabilité de re-mapper est
    laissée à l'utilisateur (qui peut faire un export/réimport)."""
    valeur = valeur_par_id(db, valeur_id)
    erreurs = _valider_valeur(
        db, valeur.vocabulaire_id, formulaire, ignorer_id=valeur_id
    )
    if erreurs:
        raise ValeurInvalide(erreurs)
    valeur.code = formulaire.code.strip()
    valeur.libelle = formulaire.libelle.strip()
    valeur.uri = formulaire.uri.strip() or None
    valeur.description_interne = formulaire.description_interne.strip() or None
    valeur.ordre = formulaire.ordre or valeur.ordre
    db.commit()
    db.refresh(valeur)
    return valeur


def deprecier_valeur(db: Session, valeur_id: int) -> ValeurControlee:
    """Toggle ``actif=False``. Idempotent. La valeur reste en base
    (les items qui la portent en metadonnees gardent leur valeur),
    elle ne sort plus du dropdown."""
    valeur = valeur_par_id(db, valeur_id)
    if valeur.actif:
        valeur.actif = False
        db.commit()
        db.refresh(valeur)
    return valeur


def reactiver_valeur(db: Session, valeur_id: int) -> ValeurControlee:
    """Toggle ``actif=True``. Idempotent."""
    valeur = valeur_par_id(db, valeur_id)
    if not valeur.actif:
        valeur.actif = True
        db.commit()
        db.refresh(valeur)
    return valeur


def supprimer_valeur(db: Session, valeur_id: int) -> None:
    """Suppression définitive. Pas de check de référence (ce sont
    des valeurs JSON dans ``Item.metadonnees`` — pas une FK)."""
    valeur = valeur_par_id(db, valeur_id)
    db.delete(valeur)
    db.commit()


# ---------------------------------------------------------------------------
# Scoping vocabulaire ↔ fonds (V0.9.x — T1 ticket scoping)
#
# Permet de restreindre un vocabulaire à un sous-ensemble de fonds.
# Un vocab sans aucun rattachement reste visible globalement (défaut).
# Voir `docs/developpeurs/vocabulaire-scoping-future.md`.
# ---------------------------------------------------------------------------


def attacher_vocabulaire_au_fonds(
    db: Session, vocab_id: int, fonds_id: int
) -> Vocabulaire:
    """Rattache un vocabulaire à un fonds. Idempotent : si le lien
    existe déjà, no-op silencieux. Lève `VocabulaireIntrouvable` ou
    `EntiteIntrouvable` (sur Fonds) si l'une des deux entités manque.
    """
    from archives_tool.models import Fonds

    vocab = vocabulaire_par_id(db, vocab_id)
    fonds = db.get(Fonds, fonds_id)
    if fonds is None:
        raise EntiteIntrouvable(f"Fonds {fonds_id} introuvable.")
    if fonds not in vocab.fonds_rattaches:
        vocab.fonds_rattaches.append(fonds)
        db.commit()
        db.refresh(vocab)
    return vocab


def detacher_vocabulaire_du_fonds(
    db: Session, vocab_id: int, fonds_id: int
) -> Vocabulaire:
    """Retire le rattachement vocab ↔ fonds. Idempotent : si le lien
    n'existe pas, no-op. Lève `VocabulaireIntrouvable` /
    `EntiteIntrouvable` si l'une des deux entités manque.

    Note : le vocabulaire n'est pas supprimé — seul le lien disparait.
    Si on détache du seul fonds rattaché, le vocab redevient global.
    """
    from archives_tool.models import Fonds

    vocab = vocabulaire_par_id(db, vocab_id)
    fonds = db.get(Fonds, fonds_id)
    if fonds is None:
        raise EntiteIntrouvable(f"Fonds {fonds_id} introuvable.")
    if fonds in vocab.fonds_rattaches:
        vocab.fonds_rattaches.remove(fonds)
        db.commit()
        db.refresh(vocab)
    return vocab


# ---------------------------------------------------------------------------
# Helpers d'usage côté composer / cartouche
# ---------------------------------------------------------------------------


def options_depuis_vocabulaire(
    vocab: Vocabulaire, *, inclure_deprecies: bool = False
) -> tuple[tuple[str, str], ...]:
    """Convertit un ``Vocabulaire`` chargé en :data:`OPTIONS_PAR_CHAMP`-
    compatible tuple. Trié par (ordre, code).

    Format identique à `vocabulaires.LANGUES_OPTIONS` etc. — permet
    au composer et à l'édition inline de traiter les deux sources
    uniformément. Par défaut, exclut les valeurs dépréciées.
    """
    valeurs = sorted(vocab.valeurs, key=lambda v: (v.ordre or 0, v.code))
    if not inclure_deprecies:
        valeurs = [v for v in valeurs if v.actif]
    return tuple((v.code, v.libelle) for v in valeurs)
