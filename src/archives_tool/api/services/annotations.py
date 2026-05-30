"""Service annotations W3C / IIIF (V0.9.7).

CRUD `AnnotationRegion` + sérialisation au format W3C Web Annotation
Data Model à la volée. La forme W3C n'est jamais stockée — on stocke
SQL plat (jointures rapides) et on sérialise au moment du GET.

Voir `docs/developpeurs/annotations-image-future.md`.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
)
from archives_tool.api.services.conflits import (
    convertir_stale_data,
    verifier_et_incrementer_version,
)
from archives_tool.models import AnnotationRegion, Fichier


#: Motivations W3C autorisées. Liste exhaustive de
#: https://www.w3.org/TR/annotation-model/#motivation-and-purpose.
#: On valide à la création/modification pour ne pas accepter de
#: motivation hors norme (réversibilité W3C compromise sinon).
MOTIVATIONS_W3C: frozenset[str] = frozenset(
    {
        "assessing", "bookmarking", "classifying", "commenting",
        "describing", "editing", "highlighting", "identifying",
        "linking", "moderating", "questioning", "replying",
        "tagging",
    }
)


#: Types de sélecteur supportés. `fragment` (xywh=x,y,w,h) couvre 95%
#: des cas. `svg` pour formes complexes (polygone, ellipse) lisibles
#: par Annotorious et Mirador.
SELECTEURS_AUTORISES: frozenset[str] = frozenset({"fragment", "svg"})


class AnnotationIntrouvable(EntiteIntrouvable):
    """L'ID de l'annotation n'existe pas."""


class AnnotationInvalide(FormulaireInvalide):
    """Données de formulaire d'annotation invalides."""


class FormulaireAnnotation(BaseModel):
    """Formulaire de création/modification d'une annotation.

    `version` ne s'applique qu'à la modification (verrou optimiste).
    À la création, laisser à `None`. À la modification, passer la
    version lue par le GET.

    Le `corps` est validé comme liste de dicts avec au moins un body
    minimal (`{type, purpose}` ou `{type, value}` selon le type). On
    n'impose pas de schéma strict pour préserver l'extensibilité W3C.
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    selecteur: str = Field(default="")
    selecteur_type: str = Field(default="fragment")
    corps: list[dict[str, Any]] = Field(default_factory=list)
    motivation: str = Field(default="tagging")
    version: int | None = None

    @field_validator("selecteur_type")
    @classmethod
    def _valider_selecteur_type(cls, v: str) -> str:
        if v not in SELECTEURS_AUTORISES:
            raise ValueError(
                f"selecteur_type doit être dans {sorted(SELECTEURS_AUTORISES)}, "
                f"reçu {v!r}"
            )
        return v

    @field_validator("motivation")
    @classmethod
    def _valider_motivation(cls, v: str) -> str:
        if v not in MOTIVATIONS_W3C:
            raise ValueError(
                f"motivation doit être une motivation W3C standard "
                f"(reçu {v!r}). Valeurs : {sorted(MOTIVATIONS_W3C)}"
            )
        return v


def _valider(formulaire: FormulaireAnnotation) -> dict[str, str]:
    """Validations qui ne tiennent pas dans les field_validator Pydantic."""
    erreurs: dict[str, str] = {}
    if not formulaire.selecteur.strip():
        erreurs["selecteur"] = "Le sélecteur est obligatoire."
    if not formulaire.corps:
        erreurs["corps"] = (
            "L'annotation doit avoir au moins un body (tag, identification, "
            "commentaire…)."
        )
    else:
        for i, body in enumerate(formulaire.corps):
            if not isinstance(body, dict):
                erreurs[f"corps[{i}]"] = "Chaque body doit être un dict W3C."
                continue
            if "type" not in body:
                erreurs[f"corps[{i}].type"] = "Body sans `type` W3C."
    return erreurs


def serialiser_w3c(annotation: AnnotationRegion, *, base_url: str = "") -> dict[str, Any]:
    """Sérialise une AnnotationRegion en JSON-LD W3C Web Annotation.

    ``base_url`` (ex `"https://colle-c.example"`) préfixe les URIs des
    annotations + cibles. En usage local, on peut laisser vide — les
    URIs deviennent relatives, ce qui est conforme.
    """
    selector: dict[str, Any]
    if annotation.selecteur_type == "svg":
        selector = {"type": "SvgSelector", "value": annotation.selecteur}
    else:
        # `conformsTo` est exigé par Annotorious 2.7 qui appelle
        # `selector.conformsTo.startsWith("http://www.w3.org/TR/media-frags")`
        # quand il ré-ingère un FragmentSelector (cf. crash V0.9.7 β
        # à la première création d'annotation). C'est aussi conforme
        # au spec W3C qui le requiert pour désambiguïser la grammaire
        # de fragment (W3C Web Annotation Data Model §4.2.4).
        selector = {
            "type": "FragmentSelector",
            "conformsTo": "http://www.w3.org/TR/media-frags/",
            "value": annotation.selecteur,
        }

    # W3C spec : les champs optionnels DOIVENT être omis quand absents
    # (pas inclus en `null`). Les serializers stricts (Mirador, etc.)
    # peuvent rejeter `"creator": null`.
    out: dict[str, Any] = {
        "@context": "http://www.w3.org/ns/anno.jsonld",
        "id": f"{base_url}/api/annotations/{annotation.id}",
        "type": "Annotation",
        "motivation": annotation.motivation,
        "target": {
            "source": f"{base_url}/api/fichiers/{annotation.fichier_id}",
            "selector": selector,
        },
        "body": list(annotation.corps),
    }
    if annotation.cree_le is not None:
        out["created"] = annotation.cree_le.isoformat()
    if annotation.cree_par:
        out["creator"] = annotation.cree_par
    if annotation.modifie_le is not None:
        out["modified"] = annotation.modifie_le.isoformat()
    return out


def serialiser_collection_w3c(
    annotations: list[AnnotationRegion],
    *,
    fichier_id: int,
    base_url: str = "",
) -> dict[str, Any]:
    """Sérialise une liste d'annotations en AnnotationPage W3C.

    Pour un fichier donné — équivalent IIIF d'un canvas. Sera embarqué
    dans un AnnotationCollection au moment de l'export Nakala (Lot
    delta de la roadmap).
    """
    return {
        "@context": "http://www.w3.org/ns/anno.jsonld",
        "id": f"{base_url}/api/fichiers/{fichier_id}/annotations",
        "type": "AnnotationPage",
        "items": [serialiser_w3c(a, base_url=base_url) for a in annotations],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def lire_annotation(db: Session, annotation_id: int) -> AnnotationRegion:
    """Lookup par ID. Lève `AnnotationIntrouvable` si absente."""
    a = db.get(AnnotationRegion, annotation_id)
    if a is None:
        raise AnnotationIntrouvable(f"annotation id={annotation_id}")
    return a


def lister_annotations_fichier(
    db: Session, fichier_id: int
) -> tuple[AnnotationRegion, ...]:
    """Liste les annotations d'un fichier, ordonnées par création.

    Pas de pagination — on attend qq dizaines d'annotations par fichier
    typiquement (une page de revue avec 5-20 dessins). Si volume
    pathologique (manuscrit annoté ligne par ligne), pagination
    pourra être ajoutée.
    """
    rows = db.scalars(
        select(AnnotationRegion)
        .where(AnnotationRegion.fichier_id == fichier_id)
        .order_by(AnnotationRegion.cree_le)
    ).all()
    return tuple(rows)


def creer_annotation(
    db: Session,
    fichier_id: int,
    formulaire: FormulaireAnnotation,
    *,
    cree_par: str | None = None,
) -> AnnotationRegion:
    """Crée une annotation sur un fichier.

    Lève `AnnotationInvalide` (validation), `AnnotationIntrouvable`
    (fichier inconnu).
    """
    erreurs = _valider(formulaire)
    if erreurs:
        raise AnnotationInvalide(erreurs)

    fichier = db.get(Fichier, fichier_id)
    if fichier is None:
        raise AnnotationIntrouvable(f"fichier id={fichier_id}")

    annotation = AnnotationRegion(
        fichier_id=fichier_id,
        selecteur=formulaire.selecteur.strip(),
        selecteur_type=formulaire.selecteur_type,
        corps=list(formulaire.corps),
        motivation=formulaire.motivation,
        cree_par=cree_par,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation


def modifier_annotation(
    db: Session,
    annotation_id: int,
    formulaire: FormulaireAnnotation,
    *,
    modifie_par: str | None = None,
) -> AnnotationRegion:
    """Modifie une annotation existante avec verrou optimiste.

    Lève `AnnotationInvalide` (validation), `AnnotationIntrouvable`
    (id inconnu), `ConflitVersion` (version périmée).
    """
    erreurs = _valider(formulaire)
    if erreurs:
        raise AnnotationInvalide(erreurs)

    annotation = lire_annotation(db, annotation_id)
    annotation.selecteur = formulaire.selecteur.strip()
    annotation.selecteur_type = formulaire.selecteur_type
    annotation.corps = list(formulaire.corps)
    annotation.motivation = formulaire.motivation
    annotation.modifie_par = modifie_par
    annotation.modifie_le = datetime.now()
    verifier_et_incrementer_version(annotation, formulaire)

    with convertir_stale_data(formulaire.version):
        db.commit()
    db.refresh(annotation)
    return annotation


def supprimer_annotation(db: Session, annotation_id: int) -> None:
    """Supprime une annotation. Idempotent : pas d'erreur si déjà absente."""
    annotation = db.get(AnnotationRegion, annotation_id)
    if annotation is None:
        return
    db.delete(annotation)
    db.commit()


# ---------------------------------------------------------------------------
# Export Nakala (V0.9.7 δ) — sérialisation AnnotationCollection W3C
# pour dépôt à côté des images d'un item ou d'une collection.
# ---------------------------------------------------------------------------


def lister_annotations_item(
    db: Session, item_id: int
) -> tuple[AnnotationRegion, ...]:
    """Toutes les annotations des fichiers d'un item, triées par
    (fichier_id, cree_le). Pour l'export par item (granularité
    typique Nakala : un AnnotationCollection par numéro de revue)."""
    from archives_tool.models import Fichier

    rows = db.scalars(
        select(AnnotationRegion)
        .join(Fichier, Fichier.id == AnnotationRegion.fichier_id)
        .where(Fichier.item_id == item_id)
        .order_by(AnnotationRegion.fichier_id, AnnotationRegion.cree_le)
    ).all()
    return tuple(rows)


def lister_annotations_collection(
    db: Session, collection_id: int
) -> tuple[AnnotationRegion, ...]:
    """Toutes les annotations de tous les items d'une collection.
    Granularité par collection (= un seul AnnotationCollection JSON)
    pour les corpus moyennement riches. Tri stable (fichier, cree_le)."""
    from archives_tool.models import Fichier, Item, ItemCollection

    rows = db.scalars(
        select(AnnotationRegion)
        .join(Fichier, Fichier.id == AnnotationRegion.fichier_id)
        .join(Item, Item.id == Fichier.item_id)
        .join(ItemCollection, ItemCollection.item_id == Item.id)
        .where(ItemCollection.collection_id == collection_id)
        .order_by(AnnotationRegion.fichier_id, AnnotationRegion.cree_le)
    ).all()
    return tuple(rows)


def serialiser_annotation_collection_w3c(
    annotations: list[AnnotationRegion],
    *,
    label: str,
    collection_id_uri: str,
    base_url: str = "",
) -> dict[str, Any]:
    """Sérialise un ensemble d'annotations en W3C `AnnotationCollection`.

    Format pour dépôt à côté des images sur Nakala (référencé dans le
    manifeste IIIF de l'item). Spec W3C Web Annotation §6.3
    (https://www.w3.org/TR/annotation-model/#annotation-collection).

    Un seul `AnnotationPage` pour la simplicité (acceptable jusqu'à
    quelques milliers d'annotations dans un seul fichier ; au-delà,
    paginer par canvas). Annotations triées dans l'ordre du listing
    (par fichier puis par création).

    ``label`` : libellé humain du corpus (« Annotations de Por Favor
    n°2 »). ``collection_id_uri`` : identifiant URI canonique du
    AnnotationCollection — typiquement le DOI Nakala de l'item /
    collection une fois publiée.
    """
    items = [serialiser_w3c(a, base_url=base_url) for a in annotations]
    page_id = f"{collection_id_uri}/page/1" if collection_id_uri else ""
    return {
        "@context": "http://www.w3.org/ns/anno.jsonld",
        "id": collection_id_uri,
        "type": "AnnotationCollection",
        "label": label,
        "total": len(items),
        "first": {
            "id": page_id,
            "type": "AnnotationPage",
            "partOf": collection_id_uri,
            "next": None,
            "items": items,
        },
    }


# ---------------------------------------------------------------------------
# Enrichissement rétroactif (V0.9.8 — T4 du scoping vocabulaires)
# ---------------------------------------------------------------------------
#
# Scénario : un vocab a été rattaché à un fonds APRÈS que ce fonds a été
# annoté. Les annotations existantes sont restées en `TextualBody value=
# "Copi"` parce que l'autocomplete ne proposait pas encore les entrées
# vocab. On veut maintenant propager les URIs Wikidata/VIAF du vocab vers
# ces annotations « pauvres » → les transformer en `SpecificResource
# source={id, label}` qui transportent le pivot d'autorité.
#
# Voir `docs/developpeurs/vocabulaire-scoping-future.md` T4 pour les
# choix de design (figé en base plutôt que résolu à la lecture, replace
# plutôt qu'ajouter, idempotent, dry-run par défaut).


def _normaliser_pour_match(s: str) -> str:
    """NFD + suppression diacritiques + lowercase + strip.

    Permet de matcher « Copi » == « COPI » == « Côpi » (un même libellé
    peut être saisi à la main avec une faute d'accent ou de casse). On
    préserve les non-ASCII non-diacritiques (CJK, arabe, hébreu…) en
    filtrant uniquement la catégorie Unicode « Mn » (Mark, Nonspacing).
    """
    nfd = unicodedata.normalize("NFD", s)
    sans_accents = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return sans_accents.lower().strip()


@dataclass(frozen=True)
class MatchEnrichissement:
    """Un body candidat à l'enrichissement (TextualBody → SpecificResource).

    Préview du diff sans modification de la base. Sert au dry-run + à
    la modale UI qui montre l'avant/après.
    """

    annotation_id: int
    fichier_id: int
    body_index: int  # position du body dans `corps`
    libelle_libre: str  # tel que tapé dans l'annotation (TextualBody.value)
    valeur_id: int  # ValeurControlee.id qui matche
    valeur_libelle: str  # libellé canonique du vocab (peut différer en casse/accents)
    valeur_uri: str  # URI à injecter (Wikidata Q…, VIAF, etc.)


@dataclass(frozen=True)
class RapportEnrichissement:
    """Résumé d'une passe d'enrichissement (dry-run ou appliqué).

    - ``matches`` : liste des transformations candidates / effectuées.
    - ``deja_enrichies`` : nb de bodies qui étaient déjà SpecificResource
      avec une URI cible du vocab (skip silencieux, idempotence).
    - ``annotations_modifiees`` : nb d'annotations distinctes qui ont
      ≥1 body transformé. Différent de ``len(matches)`` quand une même
      annotation a plusieurs tags qui matchent.
    - ``dry_run`` : True = aucune écriture en base, False = appliqué.
    """

    matches: tuple[MatchEnrichissement, ...]
    deja_enrichies: int
    annotations_modifiees: int
    dry_run: bool

    @property
    def nb_matches(self) -> int:
        return len(self.matches)


def _est_specific_resource_avec_uri(body: dict[str, Any], uri: str) -> bool:
    """Le body est-il déjà un SpecificResource pointant sur cette URI ?

    Accepte les deux formes que produit Annotorious 2.7 :
    - ``source: "<uri>"`` (string directe)
    - ``source: {"id": "<uri>", "label": "..."}`` (objet avec label).
    """
    if body.get("type") != "SpecificResource":
        return False
    source = body.get("source")
    if isinstance(source, str):
        return source == uri
    if isinstance(source, dict):
        return source.get("id") == uri
    return False


def _lister_annotations_fonds(
    db: Session, fonds_id: int
) -> tuple[AnnotationRegion, ...]:
    """Toutes les annotations des fichiers des items du fonds.

    Pas dans l'API publique des « listers par périmètre » (item /
    collection) parce que l'enrichissement est l'unique usage pour
    l'instant. Si un autre besoin émerge, le promouvoir.
    """
    from archives_tool.models import Item

    rows = db.scalars(
        select(AnnotationRegion)
        .join(Fichier, Fichier.id == AnnotationRegion.fichier_id)
        .join(Item, Item.id == Fichier.item_id)
        .where(Item.fonds_id == fonds_id)
        .order_by(AnnotationRegion.fichier_id, AnnotationRegion.cree_le)
    ).all()
    return tuple(rows)


def enrichir_annotations_par_vocab(
    db: Session,
    vocabulaire_id: int,
    fonds_id: int,
    *,
    dry_run: bool = True,
    modifie_par: str | None = None,
) -> RapportEnrichissement:
    """Enrichit les annotations d'un fonds avec les URIs d'un vocabulaire.

    Parcourt les ``AnnotationRegion`` des fichiers du fonds, matche les
    bodies ``TextualBody`` (purpose=tagging par défaut, sinon n'importe)
    contre les ``ValeurControlee`` actives du vocabulaire ayant une URI,
    et remplace chaque match par un ``SpecificResource purpose=tagging
    source={id, label}``.

    Matching : normalisation NFD + suppression diacritiques + lowercase
    + strip. « Copi » == « COPI » == « Côpi » → match.

    Idempotent : si un body est déjà ``SpecificResource`` avec l'URI
    cible, il est compté dans ``deja_enrichies`` et pas re-touché.

    ``dry_run=True`` : aucune écriture, juste le rapport (preview).
    ``dry_run=False`` : applique en base, bump version + traçabilité
    via ``TracabiliteMixin``.

    Lève ``EntiteIntrouvable`` si le vocab ou le fonds n'existent pas.
    """
    from archives_tool.models import Fonds
    from archives_tool.models.profil import ValeurControlee, Vocabulaire

    vocab = db.get(
        Vocabulaire, vocabulaire_id,
        options=[selectinload(Vocabulaire.valeurs)],
    )
    if vocab is None:
        raise EntiteIntrouvable(f"vocabulaire id={vocabulaire_id}")
    fonds = db.get(Fonds, fonds_id)
    if fonds is None:
        raise EntiteIntrouvable(f"fonds id={fonds_id}")

    # Construit l'index libellé_normalisé → (id, libellé canonique, URI).
    # On ne considère que les valeurs actives ET ayant une URI (sans URI,
    # il n'y a rien à propager — le matching libre resterait un libellé
    # libre).
    index: dict[str, tuple[int, str, str]] = {}
    for v in vocab.valeurs:
        if not v.actif or not v.uri:
            continue
        cle = _normaliser_pour_match(v.libelle)
        if not cle:
            continue
        # En cas de collision (deux valeurs avec libellé normalisé
        # identique), première gagne. Cas marginal — un vocab bien tenu
        # n'a pas de doublons.
        index.setdefault(cle, (v.id, v.libelle, v.uri))

    matches: list[MatchEnrichissement] = []
    deja_enrichies = 0
    annotations_a_modifier: list[AnnotationRegion] = []

    if not index:
        # Vocab sans valeur exploitable : rapport vide, pas de scan.
        return RapportEnrichissement(
            matches=(), deja_enrichies=0,
            annotations_modifiees=0, dry_run=dry_run,
        )

    annotations = _lister_annotations_fonds(db, fonds_id)

    for ann in annotations:
        nouveau_corps: list[dict[str, Any]] = []
        ann_a_change = False
        for idx, body in enumerate(ann.corps or []):
            # Skip rapide : pas un TextualBody → on garde tel quel, on
            # compte le « déjà enrichi » seulement si SpecificResource
            # pointe sur une URI connue du vocab (sinon c'est un body
            # qu'on n'aurait jamais touché).
            if body.get("type") != "TextualBody":
                # Cas « déjà enrichi par un passage précédent » :
                # SpecificResource avec une URI qu'on aurait produite.
                if body.get("type") == "SpecificResource":
                    source = body.get("source")
                    uri_courante = (
                        source if isinstance(source, str)
                        else (source.get("id") if isinstance(source, dict) else None)
                    )
                    if uri_courante and any(
                        u == uri_courante for _, _, u in index.values()
                    ):
                        deja_enrichies += 1
                nouveau_corps.append(body)
                continue

            valeur = body.get("value")
            if not isinstance(valeur, str) or not valeur.strip():
                nouveau_corps.append(body)
                continue

            cle = _normaliser_pour_match(valeur)
            cible = index.get(cle)
            if cible is None:
                nouveau_corps.append(body)
                continue

            vid, vlibelle, vuri = cible
            # Si malgré le type TextualBody le body référence déjà la
            # bonne URI (cas hybride bizarre), skip.
            if _est_specific_resource_avec_uri(body, vuri):
                deja_enrichies += 1
                nouveau_corps.append(body)
                continue

            matches.append(MatchEnrichissement(
                annotation_id=ann.id,
                fichier_id=ann.fichier_id,
                body_index=idx,
                libelle_libre=valeur,
                valeur_id=vid,
                valeur_libelle=vlibelle,
                valeur_uri=vuri,
            ))
            # On préserve la purpose initiale (tagging par défaut, mais
            # un body peut avoir purpose=describing par ex).
            purpose = body.get("purpose", "tagging")
            nouveau_corps.append({
                "type": "SpecificResource",
                "purpose": purpose,
                "source": {"id": vuri, "label": vlibelle},
            })
            ann_a_change = True

        if ann_a_change:
            if not dry_run:
                ann.corps = nouveau_corps
                ann.modifie_par = modifie_par
                ann.modifie_le = datetime.now()
                # AnnotationRegion n'a pas de `version_id_col` (le verrou
                # optimiste cross-process est sur Fonds/Collection/Item).
                # On bump quand même `version` à la main pour signaler à
                # un éventuel consommateur qu'un événement de
                # modification a eu lieu, et pour rester cohérent avec
                # `modifier_annotation` qui bump aussi.
                ann.version = (ann.version or 1) + 1
            annotations_a_modifier.append(ann)

    if not dry_run and annotations_a_modifier:
        db.commit()
        for ann in annotations_a_modifier:
            db.refresh(ann)

    return RapportEnrichissement(
        matches=tuple(matches),
        deja_enrichies=deja_enrichies,
        annotations_modifiees=len(annotations_a_modifier),
        dry_run=dry_run,
    )
