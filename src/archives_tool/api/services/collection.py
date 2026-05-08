"""Vue collection : détail + listings des trois onglets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from archives_tool.affichage.formatters import (
    LIBELLES_ETAT,
    date_incertaine,
    temps_relatif,
)
from archives_tool.api.services.dashboard import CollectionResume
from archives_tool.api.services.tri import Listage, Ordre, appliquer_tri
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    EtatFichier,
    Fichier,
    Item,
    PhaseChantier,
)


class CollectionIntrouvable(LookupError):
    """La cote demandée n'existe pas en base."""


@dataclass
class CollectionDetail:
    id: int
    cote: str
    titre: str
    titre_secondaire: str | None
    editeur: str | None
    lieu_edition: str | None
    periodicite: str | None
    date_debut: str | None
    date_fin: str | None
    issn: str | None
    doi_nakala: str | None
    description: str | None
    description_interne: str | None
    auteur_principal: str | None
    phase: PhaseChantier
    parent_cote: str | None
    parent_titre: str | None
    nb_sous_collections: int
    nb_items: int
    nb_fichiers: int
    repartition_etats: dict[str, int] = field(default_factory=dict)


# Les sous-collections du même onglet sont rendues par le même
# composant `tableau_collections` que les collections racines du
# dashboard ; elles partagent donc le schéma `CollectionResume`.

SousCollectionResume = CollectionResume


@dataclass
class ItemResume:
    """Schéma aligné sur tableau_items (composant Claude Design).

    `etat` est une chaîne (clé d'EtatCatalogage) car badge_etat
    s'attend à `'valide'` etc., pas à l'enum.

    Les champs optionnels (langue, description, doi_*, etc.) ne sont
    chargés que si la colonne associée est demandée — sinon ils
    restent à leur défaut. `meta` contient les valeurs des champs
    métadonnées sélectionnés.
    """

    cote: str
    titre: str | None
    date: str | None
    annee: int | None
    etat: str
    nb_fichiers: int
    href: str = ""
    type_chaine: str = ""
    type_label: str = ""
    type_coar: str | None = None
    langue: str | None = None
    description: str | None = None
    doi_nakala: str | None = None
    doi_collection_nakala: str | None = None
    date_incertaine: bool = False
    modifie_par: str | None = None
    modifie_le: datetime | None = None
    modifie_depuis: str = ""
    meta: dict[str, str] = field(default_factory=dict)


@dataclass
class FichierResume:
    id: int
    item_cote: str
    nom_fichier: str
    ordre: int
    type_page: str
    folio: str | None
    taille_octets: int | None
    largeur_px: int | None
    hauteur_px: int | None
    derive_genere: bool
    etat: str  # clé EtatFichier ('actif'/'remplace'/'corbeille') pour badge_etat


def _charger_collection(session: Session, cote: str) -> Collection:
    col = session.scalar(select(Collection).where(Collection.cote_collection == cote))
    if col is None:
        raise CollectionIntrouvable(cote)
    return col


def collection_detail(session: Session, cote: str) -> CollectionDetail:
    col = _charger_collection(session, cote)

    repartition: dict[str, int] = {}
    for etat, n in session.execute(
        select(Item.etat_catalogage, func.count(Item.id))
        .where(Item.collection_id == col.id)
        .group_by(Item.etat_catalogage)
    ).all():
        repartition[etat] = n
    nb_items = sum(repartition.values())

    nb_fichiers = (
        session.scalar(
            select(func.count(Fichier.id))
            .join(Item, Fichier.item_id == Item.id)
            .where(Item.collection_id == col.id)
        )
        or 0
    )
    nb_sous_collections = (
        session.scalar(
            select(func.count(Collection.id)).where(Collection.parent_id == col.id)
        )
        or 0
    )

    return CollectionDetail(
        id=col.id,
        cote=col.cote_collection,
        titre=col.titre,
        titre_secondaire=col.titre_secondaire,
        editeur=col.editeur,
        lieu_edition=col.lieu_edition,
        periodicite=col.periodicite,
        date_debut=col.date_debut,
        date_fin=col.date_fin,
        issn=col.issn,
        doi_nakala=col.doi_nakala,
        description=col.description,
        description_interne=col.description_interne,
        auteur_principal=col.auteur_principal,
        phase=PhaseChantier(col.phase),
        parent_cote=col.parent.cote_collection if col.parent else None,
        parent_titre=col.parent.titre if col.parent else None,
        nb_sous_collections=nb_sous_collections,
        nb_items=nb_items,
        nb_fichiers=nb_fichiers,
        repartition_etats=repartition,
    )


def lister_sous_collections(session: Session, cote: str) -> list[SousCollectionResume]:
    col = _charger_collection(session, cote)
    enfants = list(
        session.scalars(
            select(Collection)
            .where(Collection.parent_id == col.id)
            .order_by(Collection.cote_collection)
        ).all()
    )
    if not enfants:
        return []

    ids = [e.id for e in enfants]
    fichiers_par_col = dict(
        session.execute(
            select(Item.collection_id, func.count(Fichier.id))
            .join(Fichier, Fichier.item_id == Item.id)
            .where(Item.collection_id.in_(ids))
            .group_by(Item.collection_id)
        ).all()
    )
    repartition_par_col: dict[int, dict[str, int]] = {}
    for col_id, etat, n in session.execute(
        select(Item.collection_id, Item.etat_catalogage, func.count(Item.id))
        .where(Item.collection_id.in_(ids))
        .group_by(Item.collection_id, Item.etat_catalogage)
    ).all():
        repartition_par_col.setdefault(col_id, {})[etat] = n

    maintenant = datetime.now()
    return [
        SousCollectionResume(
            id=e.id,
            cote=e.cote_collection,
            titre=e.titre,
            phase=PhaseChantier(e.phase),
            href=f"/collection/{e.cote_collection}",
            nb_items=sum(repartition_par_col.get(e.id, {}).values()),
            nb_fichiers=fichiers_par_col.get(e.id, 0),
            repartition=repartition_par_col.get(e.id, {}),
            modifie_par=e.modifie_par,
            modifie_le=e.modifie_le,
            modifie_depuis=temps_relatif(e.modifie_le, maintenant=maintenant),
        )
        for e in enfants
    ]


_ETATS_ITEM = {e.value for e in EtatCatalogage}


def _filtre_multi(
    stmt: Select,
    colonne,
    valeurs: list[str] | None,
    *,
    whitelist: set[str] | None = None,
) -> tuple[Select, list[str] | None]:
    """Applique un filtre `IN` sur `colonne` après whitelist.

    Retourne `(stmt, retenus)` — `retenus` est la liste effectivement
    appliquée, `None` si aucun filtre. Si `whitelist` est fourni, les
    valeurs hors whitelist sont silencieusement écartées.
    """
    if not valeurs:
        return stmt, None
    if whitelist is not None:
        retenus = [v for v in valeurs if v in whitelist]
    else:
        retenus = [v for v in valeurs if v]
    if not retenus:
        return stmt, None
    return stmt.where(colonne.in_(retenus)), retenus


def _filtre_ilike(
    stmt: Select,
    colonne,
    q: str | None,
) -> tuple[Select, str | None]:
    """Applique un `ILIKE %q%` sur `colonne`. Retourne `(stmt, terme_retenu)`."""
    if not q:
        return stmt, None
    terme = q.strip()
    if not terme:
        return stmt, None
    return stmt.where(colonne.ilike(f"%{terme}%")), terme


def appliquer_filtres_items(
    stmt: Select,
    *,
    etat: list[str] | None = None,
    type_coar: list[str] | None = None,
    annee_debut: int | None = None,
    annee_fin: int | None = None,
    q: str | None = None,
) -> tuple[Select, dict[str, object]]:
    """Applique les filtres items sur une SELECT. Whitelist côté Python.

    Retourne `(stmt, filtres_actifs)` — `filtres_actifs` reflète ce qui
    a effectivement été appliqué (les valeurs non valides sont
    silencieusement ignorées).
    """
    actifs: dict[str, object] = {}
    stmt, retenus = _filtre_multi(
        stmt, Item.etat_catalogage, etat, whitelist=_ETATS_ITEM
    )
    if retenus is not None:
        actifs["etat"] = retenus
    stmt, retenus = _filtre_multi(stmt, Item.type_coar, type_coar)
    if retenus is not None:
        actifs["type"] = retenus
    if annee_debut is not None:
        stmt = stmt.where(Item.annee >= annee_debut)
        actifs["annee_debut"] = annee_debut
    if annee_fin is not None:
        stmt = stmt.where(Item.annee <= annee_fin)
        actifs["annee_fin"] = annee_fin
    stmt, terme = _filtre_ilike(stmt, Item.titre, q)
    if terme is not None:
        actifs["q"] = terme
    return stmt, actifs


def _valeurs_distinctes(
    session: Session,
    colonne,
    *,
    where_clauses: list,
) -> list[str]:
    """Liste distincte non vide d'une colonne, sous une série de WHERE.

    Trie alphabétiquement, ignore None et chaînes vides côté Python.
    """
    stmt = select(colonne).distinct().order_by(colonne)
    for clause in where_clauses:
        stmt = stmt.where(clause)
    rows = session.execute(stmt).all()
    return [r[0] for r in rows if r[0]]


def types_coar_disponibles(session: Session, cote: str) -> list[str]:
    col = _charger_collection(session, cote)
    return _valeurs_distinctes(
        session,
        Item.type_coar,
        where_clauses=[Item.collection_id == col.id, Item.type_coar.is_not(None)],
    )


def lister_items(
    session: Session,
    cote: str,
    *,
    tri: str | None = None,
    ordre: Ordre = "asc",
    page: int = 1,
    par_page: int = 50,
    etat: list[str] | None = None,
    type_coar: list[str] | None = None,
    annee_debut: int | None = None,
    annee_fin: int | None = None,
    q: str | None = None,
    colonnes: list[str] | None = None,
) -> Listage[ItemResume]:
    col = _charger_collection(session, cote)
    nb_fichiers_subq = (
        select(func.count(Fichier.id))
        .where(Fichier.item_id == Item.id)
        .correlate(Item)
        .scalar_subquery()
    )

    # Charge `metadonnees` (JSON) seulement si au moins une colonne
    # métadonnée est demandée — sinon on évite la désérialisation par
    # ligne sur les grosses collections.
    colonnes_set = set(colonnes or ())
    _DEDIEES = {
        "cote",
        "titre",
        "type",
        "date",
        "annee",
        "langue",
        "etat",
        "description",
        "doi_nakala",
        "doi_collection_nakala",
        "fichiers",
        "modifie",
    }
    charger_metadonnees = bool(colonnes_set - _DEDIEES)

    selects = [
        Item.cote,
        Item.titre,
        Item.date,
        Item.annee,
        Item.etat_catalogage,
        Item.type_coar,
        Item.langue,
        Item.description,
        Item.doi_nakala,
        Item.doi_collection_nakala,
        Item.modifie_par,
        Item.modifie_le,
        nb_fichiers_subq.label("nb_fichiers"),
    ]
    if charger_metadonnees:
        selects.append(Item.metadonnees)
    base_stmt = select(*selects).where(Item.collection_id == col.id)

    base_stmt, filtres = appliquer_filtres_items(
        base_stmt,
        etat=etat,
        type_coar=type_coar,
        annee_debut=annee_debut,
        annee_fin=annee_fin,
        q=q,
    )

    mapping_tri = {
        "cote": Item.cote,
        "titre": Item.titre,
        "type": Item.type_coar,
        "date": Item.date,
        "etat": Item.etat_catalogage,
        "fichiers": nb_fichiers_subq,
        "modifie": Item.modifie_le,
    }
    stmt, tri_eff, ordre_eff = appliquer_tri(
        base_stmt, mapping_tri, tri, ordre, defaut=("cote", "asc")
    )

    # Le total reflète le filtrage appliqué — la même WHERE clause
    # appliquée sur un COUNT.
    count_stmt = select(func.count(Item.id)).where(Item.collection_id == col.id)
    count_stmt, _ = appliquer_filtres_items(
        count_stmt,
        etat=etat,
        type_coar=type_coar,
        annee_debut=annee_debut,
        annee_fin=annee_fin,
        q=q,
    )
    total = session.scalar(count_stmt) or 0

    page_eff = max(1, page)
    if par_page > 0:
        stmt = stmt.limit(par_page).offset((page_eff - 1) * par_page)

    rows = session.execute(stmt).all()
    maintenant = datetime.now()
    cles_metas = colonnes_set - _DEDIEES
    items: list[ItemResume] = []
    for row in rows:
        meta: dict[str, str] = {}
        if charger_metadonnees and cles_metas:
            md = row.metadonnees
            if isinstance(md, dict):
                for cle in cles_metas:
                    valeur = md.get(cle)
                    if valeur is not None:
                        meta[cle] = (
                            ", ".join(str(v) for v in valeur)
                            if isinstance(valeur, list)
                            else str(valeur)
                        )
        items.append(
            ItemResume(
                cote=row.cote,
                titre=row.titre,
                date=row.date,
                annee=row.annee,
                etat=row.etat_catalogage,
                nb_fichiers=row.nb_fichiers or 0,
                href=f"/item/{row.cote}?collection={cote}",
                type_coar=row.type_coar,
                langue=row.langue,
                description=row.description,
                doi_nakala=row.doi_nakala,
                doi_collection_nakala=row.doi_collection_nakala,
                date_incertaine=date_incertaine(row.date),
                modifie_par=row.modifie_par,
                modifie_le=row.modifie_le,
                modifie_depuis=temps_relatif(row.modifie_le, maintenant=maintenant),
                meta=meta,
            )
        )
    return Listage(
        items=items,
        tri=tri_eff,
        ordre=ordre_eff,
        page=page_eff,
        par_page=par_page,
        total=total,
        filtres=filtres,
    )


_ETATS_FICHIER = {e.value for e in EtatFichier}


def appliquer_filtres_fichiers(
    stmt: Select,
    *,
    etat: list[str] | None = None,
    type_page: list[str] | None = None,
    format: list[str] | None = None,
    q: str | None = None,
) -> tuple[Select, dict[str, object]]:
    """Applique les filtres fichiers sur une SELECT. Whitelist côté Python."""
    actifs: dict[str, object] = {}
    stmt, retenus = _filtre_multi(stmt, Fichier.etat, etat, whitelist=_ETATS_FICHIER)
    if retenus is not None:
        actifs["etat"] = retenus
    stmt, retenus = _filtre_multi(stmt, Fichier.type_page, type_page)
    if retenus is not None:
        actifs["type_page"] = retenus
    stmt, retenus = _filtre_multi(stmt, Fichier.format, format)
    if retenus is not None:
        actifs["format"] = retenus
    stmt, terme = _filtre_ilike(stmt, Fichier.nom_fichier, q)
    if terme is not None:
        actifs["q"] = terme
    return stmt, actifs


def types_page_disponibles(session: Session, cote: str) -> list[str]:
    col = _charger_collection(session, cote)
    # type_page est non-nullable mais on peut filtrer côté Python via
    # _valeurs_distinctes. Le JOIN se fait via une sous-requête.
    return _valeurs_distinctes(
        session,
        Fichier.type_page,
        where_clauses=[
            Fichier.item_id.in_(select(Item.id).where(Item.collection_id == col.id)),
        ],
    )


# Libellés des états — réutilisent le mapping centralisé `LIBELLES_ETAT`
# de `affichage.formatters`. Subset filtré par enum pour éviter la
# duplication du dict.
_LIBELLES_ETAT_ITEM = {
    e.value: LIBELLES_ETAT[e.value] for e in EtatCatalogage if e.value in LIBELLES_ETAT
}
_LIBELLES_ETAT_FICHIER = {
    e.value: LIBELLES_ETAT[e.value] for e in EtatFichier if e.value in LIBELLES_ETAT
}


def sections_filtres_items(
    session: Session, cote: str, filtres: dict[str, object]
) -> list[dict]:
    """Sections du panneau de filtres pour l'onglet items."""
    return [
        {
            "titre": "État",
            "type": "multi",
            "champ": "etat",
            "options": list(_LIBELLES_ETAT_ITEM.keys()),
            "libelles": _LIBELLES_ETAT_ITEM,
            "valeur": filtres.get("etat") or [],
        },
        {
            "titre": "Type",
            "type": "multi",
            "champ": "type",
            "options": types_coar_disponibles(session, cote),
            "valeur": filtres.get("type") or [],
        },
        {
            "titre": "Période",
            "type": "range_annee",
            "valeur_debut": filtres.get("annee_debut"),
            "valeur_fin": filtres.get("annee_fin"),
        },
        {
            "titre": "Recherche dans le titre",
            "type": "text",
            "champ": "q",
            "placeholder": "mots du titre…",
            "valeur": filtres.get("q") or "",
        },
    ]


def sections_filtres_fichiers(
    session: Session, cote: str, filtres: dict[str, object]
) -> list[dict]:
    """Sections du panneau de filtres pour l'onglet fichiers."""
    return [
        {
            "titre": "État",
            "type": "multi",
            "champ": "etat",
            "options": list(_LIBELLES_ETAT_FICHIER.keys()),
            "libelles": _LIBELLES_ETAT_FICHIER,
            "valeur": filtres.get("etat") or [],
        },
        {
            "titre": "Type de page",
            "type": "multi",
            "champ": "type_page",
            "options": types_page_disponibles(session, cote),
            "valeur": filtres.get("type_page") or [],
        },
        {
            "titre": "Format",
            "type": "multi",
            "champ": "format",
            "options": formats_disponibles(session, cote),
            "valeur": filtres.get("format") or [],
        },
        {
            "titre": "Recherche dans le nom",
            "type": "text",
            "champ": "q",
            "placeholder": "nom de fichier…",
            "valeur": filtres.get("q") or "",
        },
    ]


def formats_disponibles(session: Session, cote: str) -> list[str]:
    col = _charger_collection(session, cote)
    return _valeurs_distinctes(
        session,
        Fichier.format,
        where_clauses=[
            Fichier.item_id.in_(select(Item.id).where(Item.collection_id == col.id)),
            Fichier.format.is_not(None),
        ],
    )


def lister_fichiers(
    session: Session,
    cote: str,
    *,
    tri: str | None = None,
    ordre: Ordre = "asc",
    page: int = 1,
    par_page: int = 50,
    etat: list[str] | None = None,
    type_page: list[str] | None = None,
    format: list[str] | None = None,
    q: str | None = None,
) -> Listage[FichierResume]:
    col = _charger_collection(session, cote)
    base_stmt = (
        select(Fichier, Item.cote.label("item_cote"))
        .join(Item, Fichier.item_id == Item.id)
        .where(Item.collection_id == col.id)
    )

    base_stmt, filtres = appliquer_filtres_fichiers(
        base_stmt, etat=etat, type_page=type_page, format=format, q=q
    )

    mapping_tri = {
        "item": Item.cote,
        "nom": Fichier.nom_fichier,
        "ordre": Fichier.ordre,
        "type": Fichier.type_page,
        "taille": Fichier.taille_octets,
        "etat": Fichier.etat,
    }
    stmt, tri_eff, ordre_eff = appliquer_tri(
        base_stmt, mapping_tri, tri, ordre, defaut=("item", "asc")
    )
    # Tri secondaire stable par (item_cote, ordre) pour les rangées
    # avec la même valeur de tri principal.
    if tri_eff != "ordre":
        stmt = stmt.order_by(Item.cote, Fichier.ordre)

    count_stmt = (
        select(func.count(Fichier.id))
        .join(Item, Fichier.item_id == Item.id)
        .where(Item.collection_id == col.id)
    )
    count_stmt, _ = appliquer_filtres_fichiers(
        count_stmt, etat=etat, type_page=type_page, format=format, q=q
    )
    total = session.scalar(count_stmt) or 0

    page_eff = max(1, page)
    if par_page > 0:
        stmt = stmt.limit(par_page).offset((page_eff - 1) * par_page)

    rows = list(session.execute(stmt).all())
    fichiers = [
        FichierResume(
            id=f.id,
            item_cote=item_cote,
            nom_fichier=f.nom_fichier,
            ordre=f.ordre,
            type_page=f.type_page,
            folio=f.folio,
            taille_octets=f.taille_octets,
            largeur_px=f.largeur_px,
            hauteur_px=f.hauteur_px,
            derive_genere=f.derive_genere,
            etat=f.etat,
        )
        for f, item_cote in rows
    ]
    return Listage(
        items=fichiers,
        tri=tri_eff,
        ordre=ordre_eff,
        page=page_eff,
        par_page=par_page,
        filtres=filtres,
        total=total,
    )
