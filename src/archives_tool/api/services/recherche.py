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

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from archives_tool.api.services._filtres_communs import (
    clamper_annee,
    csv_to_liste,
)

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
class FiltresRecherche:
    """Filtres appliqués aux ITEMS uniquement (les fonds/collections
    passent à travers — c'est le choix d'UX V0.9.x).

    `q_dans_resultats` est une exception : c'est un raffinement de la
    query principale, appliqué aux 3 types (FTS5 le concatène à `q`
    avec AND implicite — équivalent à taper les 2 mots dans la barre).
    """

    etats: tuple[str, ...] = ()
    langues: tuple[str, ...] = ()
    types_coar: tuple[str, ...] = ()
    annee_min: int | None = None
    annee_max: int | None = None
    q_dans_resultats: str = ""

    @property
    def actifs(self) -> bool:
        """Au moins un filtre est posé (utile pour décider d'afficher
        les pastilles)."""
        return bool(
            self.etats
            or self.langues
            or self.types_coar
            or self.annee_min is not None
            or self.annee_max is not None
            or self.q_dans_resultats.strip()
        )

    @property
    def affecte_items_seulement(self) -> bool:
        """True si au moins un filtre item-specific est actif (hors
        `q_dans_resultats` qui s'applique aux 3 types)."""
        return bool(
            self.etats
            or self.langues
            or self.types_coar
            or self.annee_min is not None
            or self.annee_max is not None
        )

    @property
    def nb_filtres_actifs(self) -> int:
        """Nombre de dimensions filtrantes actives (période compte
        pour 1 même si annee_min ET annee_max sont posés). Utilisé
        pour afficher `· N actif(s)` dans le summary du template
        sans dupliquer la formule de calcul."""
        n = (
            (1 if self.etats else 0)
            + (1 if self.langues else 0)
            + (1 if self.types_coar else 0)
            + (1 if self.q_dans_resultats.strip() else 0)
        )
        if self.annee_min is not None or self.annee_max is not None:
            n += 1
        return n


@dataclass(frozen=True)
class OptionsFiltresRecherche:
    """Valeurs distinctes présentes dans la base (scope-aware) pour
    peupler les `<select multiple>` côté template. Calculées via
    `calculer_options_filtres(db, scope)`."""

    etats: tuple[str, ...] = ()
    langues: tuple[str, ...] = ()
    types_coar: tuple[str, ...] = ()
    annee_min_base: int | None = None
    annee_max_base: int | None = None


@dataclass(frozen=True)
class ResultatsRecherche:
    """Réponse de `rechercher` : liste tronquée + totaux exacts.

    Distinguer le nombre AFFICHÉ (`len(resultats)`, tronqué à
    `limite_par_type` × types) du nombre TROUVÉ (`total_par_type`,
    compte exact via COUNT FTS5 sans limit). Permet d'afficher
    « 173 résultats trouvés, 100 affichés » plutôt que de masquer
    silencieusement les matchs après la limite.
    """

    resultats: list[ResultatRecherche]  # tronqués
    total_par_type: dict[TypeEntite, int]  # comptes exacts

    def __iter__(self):
        """Itère les résultats (compat code qui faisait `for r in
        rechercher(...)` quand l'API retournait list[Resultat])."""
        return iter(self.resultats)

    def __len__(self) -> int:
        """Nombre AFFICHÉ (tronqué). Pour le total exact, voir
        `.total` ou `.total_par_type`."""
        return len(self.resultats)

    @property
    def total(self) -> int:
        """Total tous types confondus (exact, non tronqué)."""
        return sum(self.total_par_type.values())

    @property
    def tronques(self) -> set[TypeEntite]:
        """Types qui ont plus de résultats qu'affichés (= types pour
        lesquels la limite a été atteinte)."""
        affiches_par_type: dict[TypeEntite, int] = {}
        for r in self.resultats:
            affiches_par_type[r.type_entite] = affiches_par_type.get(r.type_entite, 0) + 1
        return {
            t for t, n in self.total_par_type.items()
            if n > affiches_par_type.get(t, 0)
        }


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
    filtres: FiltresRecherche | None = None,
    limite_par_type: int = 100,
) -> ResultatsRecherche:
    """Recherche full-text dans item/fonds/collection.

    Args:
        db : session SQLAlchemy
        q : requête utilisateur libre (mots séparés par espaces)
        scope : limite géographique (cf. dataclass `Scope`).
            None = tout l'outil.
        types : set d'entités à inclure (`item`, `fonds`, `collection`).
            None = les trois.
        filtres : filtres avancés (cf. `FiltresRecherche`). Les filtres
            état/langue/type_coar/année ne s'appliquent qu'aux items
            (les fonds/collections passent à travers — choix d'UX
            V0.9.x). `q_dans_resultats` s'applique aux 3 types via
            concaténation FTS5 (AND implicite).
        limite_par_type : nombre max de résultats AFFICHÉS par type.
            Le total exact (non-tronqué) est aussi retourné via
            `ResultatsRecherche.total_par_type`.

    Retourne `ResultatsRecherche` avec la liste plate triée par
    score (bm25 ASC — meilleur en premier) ET le compte exact par
    type. Si la requête est invalide ou vide, retourne un objet
    vide (resultats=[], total_par_type={...: 0}).
    """
    filtres = filtres or FiltresRecherche()
    # `q_dans_resultats` est un raffinement : concaténer à `q` avec
    # un espace donne un AND implicite en FTS5 (équivaut à taper les
    # 2 dans la barre).
    q_combinee = q
    if filtres.q_dans_resultats.strip():
        q_combinee = f"{q} {filtres.q_dans_resultats}".strip()
    requete_fts = _preparer_requete_fts(q_combinee)
    types_eff: set[TypeEntite] = types or {"item", "fonds", "collection"}
    if requete_fts is None:
        return ResultatsRecherche(
            resultats=[],
            total_par_type={t: 0 for t in types_eff},
        )

    scope = scope or Scope()
    resultats: list[ResultatRecherche] = []
    totaux: dict[TypeEntite, int] = {}

    if "item" in types_eff:
        resultats.extend(
            _rechercher_items(db, requete_fts, scope, filtres, limite_par_type)
        )
        totaux["item"] = _compter_items(db, requete_fts, scope, filtres)
    if "fonds" in types_eff:
        resultats.extend(_rechercher_fonds(db, requete_fts, scope, limite_par_type))
        totaux["fonds"] = _compter_fonds(db, requete_fts, scope)
    if "collection" in types_eff:
        resultats.extend(
            _rechercher_collections(db, requete_fts, scope, limite_par_type)
        )
        totaux["collection"] = _compter_collections(db, requete_fts, scope)

    resultats.sort(key=lambda r: r.score)
    return ResultatsRecherche(resultats=resultats, total_par_type=totaux)


def _clause_filtres_items(filtres: FiltresRecherche) -> tuple[str, dict]:
    """Construit le fragment SQL `AND ...` et les params nommés pour
    appliquer les filtres item-specific (état, langue, type COAR,
    année) à un SELECT/COUNT sur `item`. Retourne `("", {})` si
    aucun filtre n'est posé."""
    fragments: list[str] = []
    params: dict = {}
    if filtres.etats:
        # WHERE item.etat_catalogage IN (:etat_0, :etat_1, ...)
        cles = [f"etat_{i}" for i in range(len(filtres.etats))]
        fragments.append(f"item.etat_catalogage IN ({', '.join(':' + c for c in cles)})")
        params.update({c: v for c, v in zip(cles, filtres.etats, strict=True)})
    if filtres.langues:
        cles = [f"lang_{i}" for i in range(len(filtres.langues))]
        fragments.append(f"item.langue IN ({', '.join(':' + c for c in cles)})")
        params.update({c: v for c, v in zip(cles, filtres.langues, strict=True)})
    if filtres.types_coar:
        cles = [f"tcoar_{i}" for i in range(len(filtres.types_coar))]
        fragments.append(f"item.type_coar IN ({', '.join(':' + c for c in cles)})")
        params.update({c: v for c, v in zip(cles, filtres.types_coar, strict=True)})
    if filtres.annee_min is not None:
        fragments.append("item.annee >= :annee_min")
        params["annee_min"] = filtres.annee_min
    if filtres.annee_max is not None:
        fragments.append("item.annee <= :annee_max")
        params["annee_max"] = filtres.annee_max
    if not fragments:
        return "", {}
    return " AND " + " AND ".join(fragments), params


def _compter_items(
    db: Session,
    requete_fts: str,
    scope: Scope,
    filtres: FiltresRecherche | None = None,
) -> int:
    """COUNT(*) sans LIMIT pour avoir le total exact item_fts."""
    where_supp = ""
    params: dict = {"q": requete_fts}
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
    if filtres is not None:
        frag_filtres, params_filtres = _clause_filtres_items(filtres)
        where_supp += frag_filtres
        params.update(params_filtres)
    sql = text(
        f"""
        SELECT COUNT(*) FROM item_fts
        JOIN item ON item.id = item_fts.rowid
        WHERE item_fts MATCH :q{where_supp}
        """
    )
    return int(db.execute(sql, params).scalar_one() or 0)


def _compter_fonds(db: Session, requete_fts: str, scope: Scope) -> int:
    if scope.collection_id is not None:
        return 0  # collection scope exclut les fonds
    where_supp = ""
    params: dict = {"q": requete_fts}
    if scope.fonds_id is not None:
        where_supp = " AND fonds.id = :fonds_id"
        params["fonds_id"] = scope.fonds_id
    sql = text(
        f"""
        SELECT COUNT(*) FROM fonds_fts
        JOIN fonds ON fonds.id = fonds_fts.rowid
        WHERE fonds_fts MATCH :q{where_supp}
        """
    )
    return int(db.execute(sql, params).scalar_one() or 0)


def _compter_collections(db: Session, requete_fts: str, scope: Scope) -> int:
    where_supp = ""
    params: dict = {"q": requete_fts}
    if scope.fonds_id is not None:
        where_supp = " AND collection.fonds_id = :fonds_id"
        params["fonds_id"] = scope.fonds_id
    elif scope.collection_id is not None:
        where_supp = " AND collection.id = :collection_id"
        params["collection_id"] = scope.collection_id
    sql = text(
        f"""
        SELECT COUNT(*) FROM collection_fts
        JOIN collection ON collection.id = collection_fts.rowid
        WHERE collection_fts MATCH :q{where_supp}
        """
    )
    return int(db.execute(sql, params).scalar_one() or 0)


def _rechercher_items(
    db: Session,
    requete_fts: str,
    scope: Scope,
    filtres: FiltresRecherche | None,
    limite: int,
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
    if filtres is not None:
        frag_filtres, params_filtres = _clause_filtres_items(filtres)
        where_supp += frag_filtres
        params.update(params_filtres)

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


# ---------------------------------------------------------------------------
# Options dynamiques + parsing des filtres avancés
# ---------------------------------------------------------------------------


def calculer_options_filtres_recherche(
    db: Session, scope: Scope | None = None
) -> OptionsFiltresRecherche:
    """Récupère les valeurs distinctes d'état, langue, type COAR et
    les bornes d'année présentes parmi les items (scope-aware).

    Pour un scope global : passe sur toute la base. Pour un scope
    fonds/collection : restreint au périmètre — l'utilisateur ne
    voit que les filtres effectivement applicables. Réutilise le
    pattern de `dashboard.composer_page_collection` (une seule
    requête par dimension, résultats petits)."""
    from archives_tool.models import Item, ItemCollection

    scope = scope or Scope()
    requete = select(
        Item.etat_catalogage, Item.langue, Item.type_coar, Item.annee
    )
    if scope.fonds_id is not None:
        requete = requete.where(Item.fonds_id == scope.fonds_id)
    elif scope.collection_id is not None:
        requete = requete.join(
            ItemCollection, ItemCollection.item_id == Item.id
        ).where(ItemCollection.collection_id == scope.collection_id)

    etats_set: set[str] = set()
    langues_set: set[str] = set()
    types_set: set[str] = set()
    annee_min: int | None = None
    annee_max: int | None = None
    for etat, langue, type_coar, annee in db.execute(requete).all():
        if etat:
            etats_set.add(etat)
        if langue:
            langues_set.add(langue)
        if type_coar:
            types_set.add(type_coar)
        if annee is not None:
            annee_min = annee if annee_min is None else min(annee_min, annee)
            annee_max = annee if annee_max is None else max(annee_max, annee)
    return OptionsFiltresRecherche(
        etats=tuple(sorted(etats_set)),
        langues=tuple(sorted(langues_set)),
        types_coar=tuple(sorted(types_set)),
        annee_min_base=annee_min,
        annee_max_base=annee_max,
    )


def parser_filtres_recherche(
    *,
    etat: str | list[str] | None,
    langue: str | list[str] | None,
    type_coar: str | list[str] | None,
    annee_min: int | None,
    annee_max: int | None,
    q_dans_resultats: str | None,
    options: OptionsFiltresRecherche,
) -> FiltresRecherche:
    """Parse les filtres reçus en query string + valide contre les
    options dynamiques. Les valeurs hors whitelist sont silencieusement
    ignorées (jamais de 400 sur paramètre invalide — cohérent avec
    `parser_filtres_collection`).

    Note : etat est validé contre `options.etats` (états réellement
    présents dans le périmètre), pas contre l'enum global — pour ne
    pas accepter `?etat=brouillon` quand aucun item du périmètre n'est
    en brouillon (la pastille apparaîtrait sans effet).
    """
    etats = tuple(e for e in csv_to_liste(etat) if e in options.etats)
    langues = tuple(lang for lang in csv_to_liste(langue) if lang in options.langues)
    types_coar = tuple(t for t in csv_to_liste(type_coar) if t in options.types_coar)

    a_min = clamper_annee(
        annee_min, options.annee_min_base, options.annee_max_base
    )
    a_max = clamper_annee(
        annee_max, options.annee_min_base, options.annee_max_base
    )
    if a_min is not None and a_max is not None and a_min > a_max:
        a_min, a_max = a_max, a_min

    return FiltresRecherche(
        etats=etats,
        langues=langues,
        types_coar=types_coar,
        annee_min=a_min,
        annee_max=a_max,
        q_dans_resultats=(q_dans_resultats or "").strip(),
    )
