"""Service de recherche full-text via SQLite FTS5 (V0.9.x).

Cherche dans les tables virtuelles `item_fts`, `fonds_fts`,
`collection_fts` (créées par migration `m1q2r3s4t5u6_fts5_recherche`
+ `db.assurer_tables_fts` pour les tests).

Scope (limite géographique) :
- `ToutLOutil` : cross-fonds, défaut
- `DansLeFonds(fonds_id)` : limite aux items/collections de ce fonds
- `DansLaCollection(collection_id)` : limite aux items de cette
  collection (et la collection elle-même)

Types (filtre les résultats) : `{"item", "fonds", "collection"}` —
si vide, retourne les trois.

Le ranking utilise `bm25(item_fts)` natif FTS5 (plus pertinent que
le rank par défaut). Score plus petit = meilleur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

TypeEntite = Literal["item", "fonds", "collection"]


@dataclass(frozen=True)
class Scope:
    """Limite géographique de la recherche."""

    # `None, None` = tout l'outil. Sinon, soit fonds_id soit collection_id
    # est posé.
    fonds_id: int | None = None
    collection_id: int | None = None

    @property
    def est_global(self) -> bool:
        return self.fonds_id is None and self.collection_id is None


@dataclass(frozen=True)
class ResultatRecherche:
    """Un résultat de recherche unifié (item, fonds, ou collection).

    `snippet` contient le texte autour du match avec balises `<mark>`
    sur les mots trouvés (HTML safe, généré par snippet() FTS5).

    `extras` donne le contexte pour rendre le résultat (cote du fonds
    pour un item, etc.).
    """

    type_entite: TypeEntite
    id: int
    cote: str
    titre: str
    snippet: str  # peut contenir des <mark>
    score: float  # bm25, plus bas = meilleur
    extras: dict[str, str | int | None] = field(default_factory=dict)


# Caractères réservés FTS5 à échapper. Voir
# https://www.sqlite.org/fts5.html#full_text_query_syntax
_FTS_RESERVED = re.compile(r'[":\-\(\)\^\*\+]')


def _preparer_requete_fts(q: str) -> str | None:
    """Convertit une requête utilisateur libre en query FTS5 sûre.

    - Strip + dédoublonne les espaces
    - Échappe les caractères réservés FTS5 en quotant chaque token
    - Joint les tokens en AND (par défaut FTS5 fait OR — on veut
      « tous les mots ») via espace (qui en FTS5 = AND)
    - Ajoute `*` pour matcher les préfixes (utile sur les cotes
      partielles comme `PF-0` qui matche `PF-001`, `PF-002`…)

    Retourne `None` si la requête est vide ou ne contient que des
    caractères réservés.
    """
    propre = q.strip()
    if not propre:
        return None
    # Découpe sur espaces (FTS5 tokenise lui-même les mots, mais on
    # gère le quoting/escaping nous-mêmes pour éviter les injections
    # de syntaxe).
    tokens: list[str] = []
    for raw in propre.split():
        # Garde les chiffres, lettres, accents, tirets internes — exclut
        # les caractères réservés FTS5.
        clean = _FTS_RESERVED.sub(" ", raw).strip()
        for sub in clean.split():
            if not sub:
                continue
            # Quote tout token contenant un caractère non-ASCII ou
            # avec une longueur < 2 (FTS5 réserve les tokens courts).
            # Ajoute `*` pour matcher les préfixes (recherche partielle
            # ergonomique sur les cotes).
            tokens.append(f'"{sub}"*')
    if not tokens:
        return None
    return " ".join(tokens)


def rechercher(
    db: Session,
    q: str,
    *,
    scope: Scope | None = None,
    types: set[TypeEntite] | None = None,
    limite_par_type: int = 50,
) -> list[ResultatRecherche]:
    """Recherche full-text dans item/fonds/collection.

    Args:
        db : session SQLAlchemy
        q : requête utilisateur libre (mots séparés par espaces)
        scope : limite géographique (cf. dataclass `Scope`).
            None = tout l'outil.
        types : set d'entités à inclure (`item`, `fonds`, `collection`).
            None = les trois.
        limite_par_type : nombre max de résultats retournés PAR TYPE.

    Retourne une liste plate, triée par score (bm25 ascendant — meilleur
    en premier). Si la requête est invalide ou vide, retourne `[]`.
    """
    requete_fts = _preparer_requete_fts(q)
    if requete_fts is None:
        return []

    scope = scope or Scope()
    types = types or {"item", "fonds", "collection"}
    resultats: list[ResultatRecherche] = []

    if "item" in types:
        resultats.extend(_rechercher_items(db, requete_fts, scope, limite_par_type))
    if "fonds" in types:
        resultats.extend(_rechercher_fonds(db, requete_fts, scope, limite_par_type))
    if "collection" in types:
        resultats.extend(
            _rechercher_collections(db, requete_fts, scope, limite_par_type)
        )

    # Tri global par score (bm25 ASC = meilleur en premier).
    resultats.sort(key=lambda r: r.score)
    return resultats


def _rechercher_items(
    db: Session, requete_fts: str, scope: Scope, limite: int
) -> list[ResultatRecherche]:
    """Items matchés, avec snippet sur les colonnes textuelles.

    `snippet(item_fts, -1, '<mark>', '</mark>', '…', 30)` : -1 = toutes
    colonnes considérées, 30 tokens de contexte.
    """
    where_supp = ""
    params: dict = {"q": requete_fts, "limite": limite}
    if scope.fonds_id is not None:
        where_supp = " AND item.fonds_id = :fonds_id"
        params["fonds_id"] = scope.fonds_id
    elif scope.collection_id is not None:
        where_supp = (
            " AND item.id IN ("
            "SELECT item_id FROM item_collection "
            "WHERE collection_id = :collection_id)"
        )
        params["collection_id"] = scope.collection_id

    sql = text(
        f"""
        SELECT
            item.id AS id,
            item.cote AS cote,
            item.titre AS titre,
            item.fonds_id AS fonds_id,
            fonds.cote AS fonds_cote,
            snippet(item_fts, -1, '<mark>', '</mark>', '…', 30) AS snippet,
            bm25(item_fts) AS score
        FROM item_fts
        JOIN item ON item.id = item_fts.rowid
        JOIN fonds ON fonds.id = item.fonds_id
        WHERE item_fts MATCH :q{where_supp}
        ORDER BY bm25(item_fts)
        LIMIT :limite
        """
    )
    rows = db.execute(sql, params).all()
    return [
        ResultatRecherche(
            type_entite="item",
            id=row.id,
            cote=row.cote,
            titre=row.titre or "",
            snippet=row.snippet or "",
            score=float(row.score),
            extras={
                "fonds_id": row.fonds_id,
                "fonds_cote": row.fonds_cote,
            },
        )
        for row in rows
    ]


def _rechercher_fonds(
    db: Session, requete_fts: str, scope: Scope, limite: int
) -> list[ResultatRecherche]:
    """Fonds matchés. Le scope `fonds_id` limite au fonds courant,
    `collection_id` exclut tous les fonds (le scope est plus étroit
    que la collection)."""
    where_supp = ""
    params: dict = {"q": requete_fts, "limite": limite}
    if scope.fonds_id is not None:
        where_supp = " AND fonds.id = :fonds_id"
        params["fonds_id"] = scope.fonds_id
    elif scope.collection_id is not None:
        # Recherche dans une collection : on n'inclut pas les fonds
        # (l'utilisateur veut le contenu de la collection, pas le
        # fonds parent).
        return []

    sql = text(
        f"""
        SELECT
            fonds.id AS id,
            fonds.cote AS cote,
            fonds.titre AS titre,
            snippet(fonds_fts, -1, '<mark>', '</mark>', '…', 30) AS snippet,
            bm25(fonds_fts) AS score
        FROM fonds_fts
        JOIN fonds ON fonds.id = fonds_fts.rowid
        WHERE fonds_fts MATCH :q{where_supp}
        ORDER BY bm25(fonds_fts)
        LIMIT :limite
        """
    )
    rows = db.execute(sql, params).all()
    return [
        ResultatRecherche(
            type_entite="fonds",
            id=row.id,
            cote=row.cote,
            titre=row.titre or "",
            snippet=row.snippet or "",
            score=float(row.score),
        )
        for row in rows
    ]


def _rechercher_collections(
    db: Session, requete_fts: str, scope: Scope, limite: int
) -> list[ResultatRecherche]:
    """Collections matchées. `scope.fonds_id` limite aux collections
    du fonds (miroir + libres rattachées). `scope.collection_id`
    exclut les autres collections (un seul résultat possible)."""
    where_supp = ""
    params: dict = {"q": requete_fts, "limite": limite}
    if scope.fonds_id is not None:
        where_supp = " AND collection.fonds_id = :fonds_id"
        params["fonds_id"] = scope.fonds_id
    elif scope.collection_id is not None:
        where_supp = " AND collection.id = :collection_id"
        params["collection_id"] = scope.collection_id

    sql = text(
        f"""
        SELECT
            collection.id AS id,
            collection.cote AS cote,
            collection.titre AS titre,
            collection.fonds_id AS fonds_id,
            fonds.cote AS fonds_cote,
            collection.type_collection AS type_collection,
            snippet(collection_fts, -1, '<mark>', '</mark>', '…', 30) AS snippet,
            bm25(collection_fts) AS score
        FROM collection_fts
        JOIN collection ON collection.id = collection_fts.rowid
        LEFT JOIN fonds ON fonds.id = collection.fonds_id
        WHERE collection_fts MATCH :q{where_supp}
        ORDER BY bm25(collection_fts)
        LIMIT :limite
        """
    )
    rows = db.execute(sql, params).all()
    return [
        ResultatRecherche(
            type_entite="collection",
            id=row.id,
            cote=row.cote,
            titre=row.titre or "",
            snippet=row.snippet or "",
            score=float(row.score),
            extras={
                "fonds_id": row.fonds_id,
                "fonds_cote": row.fonds_cote,
                "type_collection": row.type_collection,
            },
        )
        for row in rows
    ]
