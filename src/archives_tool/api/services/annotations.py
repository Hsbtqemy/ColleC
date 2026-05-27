"""Service annotations W3C / IIIF (V0.9.7).

CRUD `AnnotationRegion` + sérialisation au format W3C Web Annotation
Data Model à la volée. La forme W3C n'est jamais stockée — on stocke
SQL plat (jointures rapides) et on sérialise au moment du GET.

Voir `docs/developpeurs/annotations-image-future.md`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

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
