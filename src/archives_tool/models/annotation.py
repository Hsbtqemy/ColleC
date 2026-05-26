"""Modèle d'annotation d'image (V0.9.7).

Conforme à la spécification W3C Web Annotation Data Model, qui est
aussi le format d'annotation natif d'IIIF Presentation API 3.

Stockage SQL plat (champs scalaires pour les jointures rapides + un
champ JSON pour le `corps`) ; sérialisation au format W3C à la volée
dans le service `services/annotations.py`. Le choix W3C garantit la
réversibilité totale vers Recogito, Mirador et tout viewer standard.

Voir `docs/developpeurs/annotations-image-future.md` pour les
décisions structurantes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TracabiliteMixin

if TYPE_CHECKING:
    from .fichier import Fichier


class AnnotationRegion(Base, TracabiliteMixin):
    """Annotation W3C ciblant une région d'un fichier image.

    Cas d'usage typiques (chantier Por Favor) :
    - Identifier les dessinateurs (Copi, Forges) au sein d'une page
      avec plusieurs auteurs.
    - Marquer les caricatures représentant une personnalité (Franco,
      Carrillo) avec un lien Wikidata/VIAF.
    - Signaler des éléments iconographiques récurrents.

    Le sélecteur W3C indique la région ciblée :
    - ``selecteur_type="fragment"`` : ``selecteur`` au format
      ``xywh=x,y,w,h`` pour un rectangle. Le plus courant.
    - ``selecteur_type="svg"`` : ``selecteur`` au format SVG path pour
      formes complexes (polygone, ellipse).

    Le corps (``corps``) est une liste de bodies W3C — chaque body
    porte une `purpose` (`tagging`, `identifying`, `commenting`) et
    soit une valeur textuelle (`TextualBody`), soit un URI source
    (`SpecificResource`). Forme JSON-LD canonique :

    ```json
    [
      { "type": "TextualBody", "purpose": "tagging", "value": "Copi" },
      { "type": "SpecificResource", "purpose": "identifying",
        "source": "https://www.wikidata.org/entity/Q733678" }
    ]
    ```

    La sérialisation au format W3C complet est faite au moment du GET
    par `services/annotations.py` — pas stockée telle quelle pour ne
    pas redonder les champs SQL (cree_par, version, fichier_id).
    """

    __tablename__ = "annotation_region"

    id: Mapped[int] = mapped_column(primary_key=True)

    fichier_id: Mapped[int] = mapped_column(
        ForeignKey("fichier.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fichier: Mapped["Fichier"] = relationship(
        "Fichier",
        back_populates="annotations",
    )

    selecteur: Mapped[str] = mapped_column(Text, nullable=False)
    selecteur_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="fragment"
    )
    # Bodies W3C — liste de dicts. Voir docstring de la classe.
    # Type explicite JSON (le type_annotation_map de Base ne matche
    # pas le générique `list[dict[str, Any]]` paramétré).
    corps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    # Motivation W3C : tagging | identifying | commenting | describing |
    # classifying | linking | bookmarking | highlighting | …
    # Pas d'enum strict côté SQL pour préserver l'extensibilité W3C
    # (champ texte avec validation côté service).
    motivation: Mapped[str] = mapped_column(
        String(32), nullable=False, default="tagging"
    )

    __table_args__ = (
        # Index secondaire pour les requêtes « toutes les annotations
        # d'un fichier triées chronologiquement ».
        Index(
            "ix_annotation_region_fichier_cree",
            "fichier_id",
            "cree_le",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<AnnotationRegion id={self.id} fichier_id={self.fichier_id} "
            f"motivation={self.motivation!r}>"
        )
