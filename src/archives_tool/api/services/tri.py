"""Tri et pagination des listings côté service.

Whitelist par tableau : aucun `order_by` dynamique construit depuis une
chaîne client. Le mapping `{nom_public: clause_sqlalchemy}` est la
source de vérité — toute valeur hors mapping retombe sur le tri par
défaut sans erreur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from sqlalchemy import Select

Ordre = Literal["asc", "desc"]
T = TypeVar("T")

# Whitelists des clés de tri publiques par tableau.
TRIS_COLLECTIONS = ("cote", "titre", "items", "fichiers", "modifie")
TRIS_ITEMS = ("cote", "titre", "type", "date", "etat", "fichiers", "modifie")
TRIS_FICHIERS = ("item", "nom", "ordre", "type", "taille", "etat")


def appliquer_tri(
    stmt: Select[T],
    mapping: dict[str, object],
    tri: str | None,
    ordre: Ordre,
    *,
    defaut: tuple[str, Ordre],
) -> tuple[Select[T], str, Ordre]:
    """Applique un `order_by` whitelisté à une SELECT.

    Retourne `(stmt, tri_effectif, ordre_effectif)` : si `tri` n'est
    pas dans le mapping, on retombe sur `defaut`. L'ordre est
    normalisé à 'asc'/'desc' ; toute autre valeur → 'asc'.
    """
    cle = tri if tri in mapping else defaut[0]
    sens: Ordre = ordre if ordre in ("asc", "desc") else defaut[1]
    colonne = mapping[cle]
    expr = colonne.desc() if sens == "desc" else colonne.asc()
    return stmt.order_by(expr), cle, sens


U = TypeVar("U")


@dataclass
class Listage(Generic[U]):
    """Résultat d'un listing : items + métadonnées de tri/pagination/filtres.

    Quand `par_page == 0`, il n'y a pas de pagination (la liste est
    complète). Sinon `total` est le compte global avant pagination
    et `pages` se déduit.
    """

    items: list[U]
    tri: str
    ordre: Ordre
    page: int = 1
    par_page: int = 0
    total: int = 0
    filtres: dict[str, object] = field(default_factory=dict)

    @property
    def pages(self) -> int:
        if self.par_page <= 0:
            return 1
        return max(1, (self.total + self.par_page - 1) // self.par_page)

    @property
    def nb_filtres_actifs(self) -> int:
        # `filtres` ne contient que les clés effectivement appliquées
        # par les helpers `appliquer_filtres_*` (ils n'y inscrivent rien
        # quand le filtre est ignoré). Compter sur la clé évite de
        # sous-estimer pour `annee_debut=0` (falsy mais filtre actif).
        return len(self.filtres)
