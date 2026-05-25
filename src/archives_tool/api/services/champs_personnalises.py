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
from sqlalchemy.exc import IntegrityError
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
    TypeCollection,
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

    ``valeurs_controlees_id`` (V0.9.4 lot 3b) : id du Vocabulaire à
    associer pour les types ``liste`` / ``liste_multiple``. None
    pour pas de vocabulaire (saisie libre). Si renseigné mais le
    type ne le supporte pas, ignoré (pas d'erreur — l'utilisateur
    peut changer le type sans perdre l'association).
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    cle: str = Field(default="")
    libelle: str = Field(default="")
    type: str = Field(default=TypeChamp.TEXTE.value)
    obligatoire: bool = False
    ordre: int = 0
    aide: str = Field(default="")
    description_interne: str = Field(default="")
    valeurs_controlees_id: int | None = None

    @field_validator("type")
    @classmethod
    def _type_valide(cls, v: str) -> str:
        if v and v not in {t.value for t in TypeChamp}:
            raise ValueError(f"Type de champ inconnu : {v!r}")
        return v or TypeChamp.TEXTE.value

    @field_validator("valeurs_controlees_id", mode="before")
    @classmethod
    def _vocab_id_normaliser(cls, v: object) -> int | None:
        """Form HTML envoie "" (chaîne vide) quand l'utilisateur
        choisit « — aucun — ». On le convertit en None pour que
        Pydantic ne plante pas sur la validation int."""
        if v in (None, "", "None"):
            return None
        if isinstance(v, str):
            return int(v)
        return v  # type: ignore[return-value]


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
        valeurs_controlees_id=champ.valeurs_controlees_id,
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


def lister_champs_actifs_pour_item(
    db: Session, item_id: int
) -> list[ChampPersonnalise]:
    """Champs personnalisés actifs visibles pour un item, mutualisés
    sur toutes les collections d'appartenance.

    Identique à la requête utilisée par :func:`composer_page_item` :
    filtre ``actif=True``, eager-load du vocabulaire + valeurs. Trié
    par (ordre, cle). Utilisé aussi par la page item modifier
    (V0.9.5) pour exposer un champ de saisie par ChampPersonnalise.
    """
    from sqlalchemy.orm import selectinload
    from archives_tool.models import ItemCollection, Vocabulaire

    return list(
        db.scalars(
            select(ChampPersonnalise)
            .options(
                selectinload(ChampPersonnalise.vocabulaire).selectinload(
                    Vocabulaire.valeurs
                )
            )
            .join(
                ItemCollection,
                ItemCollection.collection_id == ChampPersonnalise.collection_id,
            )
            .where(ItemCollection.item_id == item_id)
            .where(ChampPersonnalise.actif.is_(True))
            .order_by(ChampPersonnalise.ordre, ChampPersonnalise.cle)
        ).all()
    )


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
        valeurs_controlees_id=formulaire.valeurs_controlees_id,
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
    champ.valeurs_controlees_id = formulaire.valeurs_controlees_id
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


class CleNonPromouvable(FormulaireInvalide):
    """La clé libre ne peut pas être promue en ChampPersonnalise
    (clé absente, slug invalide, item sans miroir candidat).

    Sous-classe de ``FormulaireInvalide`` pour cohérence des routes
    qui catch via le type parent."""


def promouvoir_cle_libre_en_champ(
    db: Session,
    item: Item,
    cle: str,
) -> tuple[ChampPersonnalise, Collection]:
    """Formalise une clé libre de ``item.metadonnees`` en
    ``ChampPersonnalise`` sur la miroir du fonds de l'item.

    Workflow attendu : l'utilisateur voit dans le cartouche une clé
    libre (rendue par le fallback Bug C V0.9.2-import) et clique
    « Formaliser ». On crée le champ avec le libellé synthétisé
    (`_libelle_depuis_cle` côté composer) et l'ordre 0. L'utilisateur
    raffine ensuite via la page de gestion des champs.

    Idempotent : si un ``ChampPersonnalise`` avec cette clé existe
    déjà sur la miroir (actif ou déprécié), on le retourne tel quel
    sans erreur — le bouton « Formaliser » peut donc être cliqué
    deux fois sans casser, et un champ déprécié n'est pas
    automatiquement réactivé (l'utilisateur conserve le contrôle).

    Retourne ``(champ, miroir)`` pour permettre au caller de rediriger
    vers la page de gestion ``/collection/<miroir.cote>/champs``.

    Lève :class:`CleNonPromouvable` si :
    - la clé n'est pas dans ``item.metadonnees`` ;
    - la clé n'est pas un slug valide (PATTERN_CLE) ;
    - l'item n'a pas de fonds (cas pathologique ; tous les items en
      ont un en V0.9.0+).
    """
    # Lazy import : `_libelle_depuis_cle` vit dans dashboard.py qui
    # importe déjà champs_personnalises.PATTERN_CLE (via la closure
    # de composer_metadonnees_par_section, lui-même lazy). Un import
    # top-level créerait une boucle au chargement du module.
    from archives_tool.api.services.dashboard import _libelle_depuis_cle

    cle_strip = cle.strip()
    if not cle_strip:
        raise CleNonPromouvable({"cle": "La clé est obligatoire."})
    if not PATTERN_CLE.match(cle_strip):
        raise CleNonPromouvable(
            {"cle": (
                "Cette clé n'est pas un slug valide — la promouvoir "
                "exige des minuscules / chiffres / underscores. "
                "Renommer la clé en amont (édition métadonnées) avant "
                "de réessayer."
            )}
        )
    meta = item.metadonnees or {}
    if cle_strip not in meta:
        raise CleNonPromouvable(
            {"cle": f"La clé {cle_strip!r} n'est pas dans les métadonnées de cet item."}
        )
    if item.fonds_id is None:
        raise CleNonPromouvable(
            {"cle": "Item sans fonds — pas de miroir candidate pour la promotion."}
        )

    # Miroir du fonds : invariant V0.9.0 garantit qu'il en existe
    # exactement une.
    miroir = db.scalar(
        select(Collection).where(
            Collection.fonds_id == item.fonds_id,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )
    if miroir is None:
        raise CleNonPromouvable(
            {"cle": (
                f"Aucune collection miroir trouvée pour le fonds {item.fonds_id} "
                "— état incohérent."
            )}
        )

    # Idempotence : si un champ existe déjà avec cette clé (actif ou
    # déprécié), on le retourne tel quel.
    existant = db.scalar(
        select(ChampPersonnalise).where(
            ChampPersonnalise.collection_id == miroir.id,
            ChampPersonnalise.cle == cle_strip,
        )
    )
    if existant is not None:
        return existant, miroir

    champ = ChampPersonnalise(
        collection_id=miroir.id,
        cle=cle_strip,
        libelle=_libelle_depuis_cle(cle_strip),
        type=TypeChamp.TEXTE.value,
        obligatoire=False,
        ordre=0,
        actif=True,
    )
    db.add(champ)
    try:
        db.commit()
    except IntegrityError:
        # Race : un autre transaction a insere le meme (collection_id,
        # cle) entre notre SELECT et notre INSERT. On rollback et on
        # retourne le champ gagnant — coherent avec l'idempotence
        # documentee.
        db.rollback()
        existant = db.scalar(
            select(ChampPersonnalise).where(
                ChampPersonnalise.collection_id == miroir.id,
                ChampPersonnalise.cle == cle_strip,
            )
        )
        if existant is None:
            # IntegrityError sans champ correspondant : contrainte non
            # liee a notre cle. Re-leve.
            raise
        return existant, miroir
    db.refresh(champ)
    return champ, miroir


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
