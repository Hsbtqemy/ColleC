"""CRUD des champs personnalisés d'une collection (V0.9.4).

Permet de formaliser les clés libres de ``Item.metadonnees`` en champs
structurés avec libellé, type et ordre d'affichage :

- :func:`creer_champ` : ajouter un nouveau champ sur une collection ;
- :func:`modifier_champ` : libellé, type, ordre, aide, description
  interne (la ``cle`` reste figée — passer par :func:`renommer_champ`) ;
- :func:`renommer_champ` : changer la ``cle`` ET propager dans
  ``Item.metadonnees`` de tous les items de la collection ;
- :func:`deprecier_champ` / :func:`reactiver_champ` : toggle
  ``actif`` — un champ déprécié n'apparaît plus dans la section
  « Champs personnalisés » formels du cartouche, mais ses valeurs
  restent en JSON (fallback clé libre du composer) ;
- :func:`supprimer_champ` : hard delete réservé aux faux départs.

Pas de verrou optimiste sur ``ChampPersonnalise`` lui-même (admin op,
contention faible). Le rename propage néanmoins ``modifie_le`` /
``version`` sur chaque item touché — un éditeur inline concurrent
sera donc rejeté avec un conflit propre.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
)
from archives_tool.models import (
    ChampPersonnalise,
    Collection,
    Item,
    ItemCollection,
    TypeChamp,
)


# Clé d'une métadonnée : slug minuscule, démarre par une lettre, puis
# lettres / chiffres / underscores. Plus strict que `PATTERN_COTE`
# (qui autorise majuscules et tirets) parce que ces clés finissent en
# clés JSON exportées vers Dublin Core et indexées par FTS — moins de
# variantes = moins de surprises. Si le tableur d'import a une
# colonne « Date de parution », elle sera slugifiée en
# `date_de_parution` automatiquement par l'importer.
PATTERN_CLE = re.compile(r"^[a-z][a-z0-9_]*$")

_MSG_CLE_FORMAT = (
    "La clé doit commencer par une lettre minuscule et ne contenir que "
    "des lettres minuscules, chiffres et underscores (ex. : auteur_principal)."
)


class ChampIntrouvable(EntiteIntrouvable):
    """Le ChampPersonnalise demandé n'existe pas."""


class ChampInvalide(FormulaireInvalide):
    """Saisie de champ personnalisé invalide (clé, type, libellé vide…)."""


class FormulaireChamp(BaseModel):
    """Formulaire de création / modification d'un champ personnalisé.

    À la création, ``cle`` est obligatoire et validée par
    :data:`PATTERN_CLE`. À la modification standard, ``cle`` est
    ignorée — utiliser :func:`renommer_champ` pour la changer.
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    cle: str = Field(default="")
    libelle: str = Field(default="")
    type: str = Field(default=TypeChamp.TEXTE.value)
    obligatoire: bool = False
    ordre: int = 0
    aide: str = Field(default="")
    description_interne: str = Field(default="")

    @field_validator("type")
    @classmethod
    def _type_valide(cls, v: str) -> str:
        if v and v not in {t.value for t in TypeChamp}:
            raise ValueError(f"Type de champ inconnu : {v!r}")
        return v or TypeChamp.TEXTE.value


def formulaire_depuis_champ(champ: ChampPersonnalise) -> FormulaireChamp:
    """Pré-remplit un FormulaireChamp depuis un ChampPersonnalise."""
    return FormulaireChamp(
        cle=champ.cle,
        libelle=champ.libelle,
        type=champ.type,
        obligatoire=champ.obligatoire,
        ordre=champ.ordre,
        aide=champ.aide or "",
        description_interne=champ.description_interne or "",
    )


def lister_champs(
    db: Session,
    collection_id: int,
    *,
    inclure_deprecies: bool = True,
) -> list[ChampPersonnalise]:
    """Retourne les champs d'une collection, triés par (ordre, cle).

    Par défaut, inclut les champs dépréciés (la page de gestion les
    affiche en grisé avec un bouton « Réactiver »). Passer
    ``inclure_deprecies=False`` pour ne récupérer que les actifs (ce
    que le composer du cartouche fera).
    """
    stmt = select(ChampPersonnalise).where(
        ChampPersonnalise.collection_id == collection_id
    )
    if not inclure_deprecies:
        stmt = stmt.where(ChampPersonnalise.actif.is_(True))
    stmt = stmt.order_by(ChampPersonnalise.ordre, ChampPersonnalise.cle)
    return list(db.scalars(stmt).all())


def champ_par_id(db: Session, champ_id: int) -> ChampPersonnalise:
    """Charge un champ par id ou lève :class:`ChampIntrouvable`."""
    champ = db.get(ChampPersonnalise, champ_id)
    if champ is None:
        raise ChampIntrouvable(f"ChampPersonnalise {champ_id} introuvable.")
    return champ


def _valider_formulaire(
    db: Session,
    collection_id: int,
    formulaire: FormulaireChamp,
    *,
    exiger_cle: bool,
) -> dict[str, str]:
    """Validation des champs du formulaire (cle si exigée, libellé).

    ``exiger_cle=False`` est utilisé par :func:`modifier_champ` qui
    ignore la cle du formulaire (la modifier passe par
    :func:`renommer_champ`). Le rename a sa propre validation
    inline pour ne pas dépendre d'un drapeau supplémentaire ici.
    """
    erreurs: dict[str, str] = {}
    if exiger_cle:
        cle = formulaire.cle.strip()
        if not cle:
            erreurs["cle"] = "La clé est obligatoire."
        elif not PATTERN_CLE.match(cle):
            erreurs["cle"] = _MSG_CLE_FORMAT
        else:
            stmt = select(ChampPersonnalise.id).where(
                ChampPersonnalise.collection_id == collection_id,
                ChampPersonnalise.cle == cle,
            )
            if db.scalar(stmt) is not None:
                erreurs["cle"] = f"La clé {cle!r} existe déjà sur cette collection."
    if not formulaire.libelle.strip():
        erreurs["libelle"] = "Le libellé est obligatoire."
    return erreurs


def creer_champ(
    db: Session,
    collection_id: int,
    formulaire: FormulaireChamp,
) -> ChampPersonnalise:
    """Crée un nouveau champ sur une collection.

    Lève :class:`ChampInvalide` si la saisie est invalide (clé absente,
    mal formée, déjà utilisée ; libellé vide).
    """
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise EntiteIntrouvable(f"Collection {collection_id} introuvable.")
    erreurs = _valider_formulaire(
        db, collection_id, formulaire, exiger_cle=True
    )
    if erreurs:
        raise ChampInvalide(erreurs)
    champ = ChampPersonnalise(
        collection_id=collection_id,
        cle=formulaire.cle.strip(),
        libelle=formulaire.libelle.strip(),
        type=formulaire.type,
        obligatoire=formulaire.obligatoire,
        ordre=formulaire.ordre,
        aide=formulaire.aide.strip() or None,
        description_interne=formulaire.description_interne.strip() or None,
        actif=True,
    )
    db.add(champ)
    db.commit()
    db.refresh(champ)
    return champ


def modifier_champ(
    db: Session,
    champ_id: int,
    formulaire: FormulaireChamp,
) -> ChampPersonnalise:
    """Modifie un champ (libellé, type, ordre, aide, description_interne).

    La ``cle`` est **ignorée** : passer par :func:`renommer_champ`
    pour la changer (afin de garantir la propagation aux items).
    """
    champ = champ_par_id(db, champ_id)
    erreurs = _valider_formulaire(
        db, champ.collection_id or 0, formulaire,
        exiger_cle=False,
    )
    if erreurs:
        raise ChampInvalide(erreurs)
    champ.libelle = formulaire.libelle.strip()
    champ.type = formulaire.type
    champ.obligatoire = formulaire.obligatoire
    champ.ordre = formulaire.ordre
    champ.aide = formulaire.aide.strip() or None
    champ.description_interne = formulaire.description_interne.strip() or None
    db.commit()
    db.refresh(champ)
    return champ


def renommer_champ(
    db: Session,
    champ_id: int,
    nouvelle_cle: str,
    *,
    modifie_par: str | None = None,
) -> tuple[ChampPersonnalise, int]:
    """Renomme la ``cle`` d'un champ et propage dans ``Item.metadonnees``.

    Pour chaque item de la collection qui a une valeur sous l'ancienne
    clé, la valeur est déplacée sous la nouvelle. Bump
    ``Item.modifie_le`` / ``version`` pour invalider les éditeurs
    inline concurrents.

    Retourne ``(champ_modifié, nb_items_propagés)``.
    """
    champ = champ_par_id(db, champ_id)
    nouvelle = nouvelle_cle.strip()
    if not nouvelle:
        raise ChampInvalide({"cle": "La clé est obligatoire."})
    if not PATTERN_CLE.match(nouvelle):
        raise ChampInvalide({"cle": _MSG_CLE_FORMAT})
    if nouvelle == champ.cle:
        return champ, 0
    # Unicité (collection_id, cle)
    existant = db.scalar(
        select(ChampPersonnalise.id).where(
            ChampPersonnalise.collection_id == champ.collection_id,
            ChampPersonnalise.cle == nouvelle,
            ChampPersonnalise.id != champ.id,
        )
    )
    if existant is not None:
        raise ChampInvalide(
            {"cle": f"La clé {nouvelle!r} existe déjà sur cette collection."}
        )

    ancienne = champ.cle
    # Propagation : items de la collection avec la clé en metadonnees.
    items = list(
        db.scalars(
            select(Item)
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == champ.collection_id)
        ).all()
    )
    propages = 0
    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)
    for item in items:
        meta = item.metadonnees
        if not isinstance(meta, dict) or ancienne not in meta:
            continue
        # Si la nouvelle clé existe déjà en libre sur cet item (cas
        # rare : un champ structurel `auteurs` renommé en `auteur`
        # alors qu'un import antérieur a aussi dumpé une valeur en
        # `auteur` libre), on SKIP cet item — sans ça, on écraserait
        # silencieusement la valeur libre. L'utilisateur résoudra
        # manuellement via la page item.
        if nouvelle in meta:
            continue
        nouveau_meta = dict(meta)
        nouveau_meta[nouvelle] = nouveau_meta.pop(ancienne)
        item.metadonnees = nouveau_meta
        flag_modified(item, "metadonnees")
        item.modifie_le = maintenant
        if modifie_par:
            item.modifie_par = modifie_par
        # Bump manuel — `version_id_generator=False` sur Item, voir
        # services.conflits.verifier_et_incrementer_version. Sans ça,
        # un éditeur inline concurrent ne verra pas le conflit.
        item.version = (item.version or 1) + 1
        propages += 1
    champ.cle = nouvelle
    db.commit()
    db.refresh(champ)
    return champ, propages


def deprecier_champ(db: Session, champ_id: int) -> ChampPersonnalise:
    """Marque un champ comme inactif. Idempotent."""
    champ = champ_par_id(db, champ_id)
    if champ.actif:
        champ.actif = False
        db.commit()
        db.refresh(champ)
    return champ


def reactiver_champ(db: Session, champ_id: int) -> ChampPersonnalise:
    """Réactive un champ déprécié. Idempotent."""
    champ = champ_par_id(db, champ_id)
    if not champ.actif:
        champ.actif = True
        db.commit()
        db.refresh(champ)
    return champ


def supprimer_champ(db: Session, champ_id: int) -> None:
    """Suppression définitive (hard delete) du ChampPersonnalise.

    À utiliser avec parcimonie : les valeurs dans ``Item.metadonnees``
    ne sont **pas** supprimées (elles retomberont en clé libre du
    composer). Préférer :func:`deprecier_champ` qui garde la trace
    structurelle et permet une réactivation.
    """
    champ = champ_par_id(db, champ_id)
    db.delete(champ)
    db.commit()
