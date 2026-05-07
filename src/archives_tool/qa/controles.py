"""Implémentation des quatre contrôles de cohérence V1.

Toutes les fonctions sont en lecture seule : aucune écriture en base,
aucune modification de fichiers sur disque.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.files.paths import chemin_existe_nfc_ou_nfd, normaliser_nfc
from archives_tool.models import Collection, EtatFichier, Fichier, Item

from .rapport import (
    AnomalieFichierManquant,
    AnomalieItemVide,
    AnomalieOrphelinDisque,
    FichierDoublon,
    GroupeDoublons,
    RapportControle,
    RapportQa,
)

# Extensions usuelles d'un fonds numérisé. Le contrôle « orphelins
# disque » ne s'intéresse qu'à ces fichiers : un .txt à côté d'un
# scan n'est pas un orphelin, c'est une note. Surchargeable via
# paramètre.
EXTENSIONS_PAR_DEFAUT: frozenset[str] = frozenset(
    {"png", "jpg", "jpeg", "tif", "tiff", "pdf"}
)


def _collection_par_cote(session: Session, cote: str) -> Collection:
    col = session.scalar(select(Collection).where(Collection.cote_collection == cote))
    if col is None:
        raise ValueError(f"Collection {cote!r} introuvable en base.")
    return col


def _filtre_ids_collections(stmt, ids_collections: list[int] | None):
    if ids_collections is None:
        return stmt
    return stmt.where(Item.collection_id.in_(ids_collections))


def _normaliser_extensions(extensions: Iterable[str] | None) -> frozenset[str]:
    if extensions is None:
        return EXTENSIONS_PAR_DEFAUT
    return frozenset(e.lower().lstrip(".") for e in extensions)


def controler_fichiers_manquants_disque(
    session: Session,
    racines: Mapping[str, Path],
    *,
    ids_collections: list[int] | None = None,
) -> RapportControle:
    """Pour chaque `Fichier` actif, vérifie l'existence physique.

    Les fichiers rattachés à une racine non configurée sont remontés en
    avertissement (on ne sait pas où chercher), pas en anomalie.
    """
    debut = time.perf_counter()
    rap = RapportControle(
        code="fichiers-manquants",
        libelle=LIBELLES["fichiers-manquants"],
    )

    stmt = (
        select(Fichier, Item.cote)
        .join(Item, Fichier.item_id == Item.id)
        .where(Fichier.etat == EtatFichier.ACTIF.value)
        .order_by(Fichier.racine, Fichier.chemin_relatif)
    )
    stmt = _filtre_ids_collections(stmt, ids_collections)

    racines_inconnues_vues: set[str] = set()

    for fichier, cote_item in session.execute(stmt).all():
        if fichier.racine not in racines:
            if fichier.racine not in racines_inconnues_vues:
                rap.avertissements.append(
                    f"Racine {fichier.racine!r} non configurée : "
                    f"fichiers rattachés non vérifiables."
                )
                racines_inconnues_vues.add(fichier.racine)
            continue

        if not chemin_existe_nfc_ou_nfd(
            racines[fichier.racine], fichier.chemin_relatif
        ):
            rap.anomalies.append(
                AnomalieFichierManquant(
                    fichier_id=fichier.id,
                    item_cote=cote_item,
                    racine=fichier.racine,
                    chemin_relatif=fichier.chemin_relatif,
                )
            )

    rap.duree_secondes = time.perf_counter() - debut
    return rap


def controler_orphelins_disque(
    session: Session,
    racines: Mapping[str, Path],
    *,
    ids_collections: list[int] | None = None,
    extensions: Iterable[str] | None = None,
) -> RapportControle:
    """Liste les fichiers présents sous les racines mais non référencés en base.

    Si `ids_collections` est donné, restreint le périmètre aux racines
    *effectivement utilisées* par les fichiers de ces collections (sinon
    on remonterait des fichiers d'autres collections comme orphelins).
    La déduplication se fait sur les chemins en base toutes collections
    confondues : un fichier référencé ailleurs n'est pas un orphelin.
    """
    debut = time.perf_counter()
    rap = RapportControle(
        code="orphelins-disque",
        libelle=LIBELLES["orphelins-disque"],
    )
    exts = _normaliser_extensions(extensions)

    if not racines:
        rap.avertissements.append(
            "Aucune racine configurée : contrôle des orphelins disque ignoré."
        )
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    if ids_collections is not None:
        utilisees = set(
            session.scalars(
                select(Fichier.racine)
                .join(Item, Fichier.item_id == Item.id)
                .where(Item.collection_id.in_(ids_collections))
                .distinct()
            ).all()
        )
        racines_a_scanner = {n: p for n, p in racines.items() if n in utilisees}
        if not racines_a_scanner:
            rap.duree_secondes = time.perf_counter() - debut
            return rap
    else:
        racines_a_scanner = dict(racines)

    references: set[tuple[str, str]] = set()
    for racine, rel in session.execute(
        select(Fichier.racine, Fichier.chemin_relatif).where(
            Fichier.etat == EtatFichier.ACTIF.value
        )
    ).all():
        references.add((racine, normaliser_nfc(rel).casefold()))

    for nom_racine, base in racines_a_scanner.items():
        if not base.exists():
            rap.avertissements.append(f"Racine {nom_racine!r} : {base} n'existe pas.")
            continue
        for chemin in base.rglob("*"):
            if not chemin.is_file():
                continue
            nom = chemin.name
            if nom.startswith("."):
                continue
            ext = chemin.suffix.lstrip(".").lower()
            if ext not in exts:
                continue
            rel = chemin.relative_to(base).as_posix()
            cle = (nom_racine, normaliser_nfc(rel).casefold())
            if cle in references:
                continue
            rap.anomalies.append(
                AnomalieOrphelinDisque(
                    racine=nom_racine,
                    chemin_relatif=normaliser_nfc(rel),
                )
            )

    rap.anomalies.sort(key=lambda a: (a.racine, a.chemin_relatif))
    rap.duree_secondes = time.perf_counter() - debut
    return rap


def controler_items_sans_fichier(
    session: Session,
    *,
    ids_collections: list[int] | None = None,
) -> RapportControle:
    """Items dont aucune ligne `Fichier` (active) n'est rattachée."""
    debut = time.perf_counter()
    rap = RapportControle(
        code="items-vides",
        libelle=LIBELLES["items-vides"],
    )

    sous = (
        select(Fichier.item_id)
        .where(Fichier.etat == EtatFichier.ACTIF.value)
        .distinct()
    )
    stmt = (
        select(Item.id, Item.cote, Collection.cote_collection)
        .join(Collection, Item.collection_id == Collection.id)
        .where(~Item.id.in_(sous))
        .order_by(Collection.cote_collection, Item.cote)
    )
    stmt = _filtre_ids_collections(stmt, ids_collections)

    for item_id, cote_item, cote_col in session.execute(stmt).all():
        rap.anomalies.append(
            AnomalieItemVide(item_id=item_id, cote=cote_item, collection_cote=cote_col)
        )

    rap.duree_secondes = time.perf_counter() - debut
    return rap


def controler_doublons_par_hash(
    session: Session,
    *,
    ids_collections: list[int] | None = None,
) -> RapportControle:
    """Groupes de fichiers ayant le même `hash_sha256` (>= 2 entrées).

    Les fichiers dont `hash_sha256 IS NULL` sont remontés en
    avertissement : le contrôle ne peut rien dire sur eux.

    Stratégie en deux temps : on identifie d'abord les hashes
    dupliqués via un `GROUP BY ... HAVING COUNT > 1`, puis on ne
    charge en mémoire que les fichiers de ces groupes (en pratique
    une fraction infime du fonds).
    """
    debut = time.perf_counter()
    rap = RapportControle(
        code="doublons",
        libelle=LIBELLES["doublons"],
    )

    stmt_null = (
        select(func.count(Fichier.id))
        .join(Item, Fichier.item_id == Item.id)
        .where(Fichier.hash_sha256.is_(None))
        .where(Fichier.etat == EtatFichier.ACTIF.value)
    )
    stmt_null = _filtre_ids_collections(stmt_null, ids_collections)
    nb_sans_hash = session.scalar(stmt_null) or 0
    if nb_sans_hash:
        rap.avertissements.append(
            f"{nb_sans_hash} fichier(s) sans hash : doublons non vérifiables."
        )

    stmt_groupes = (
        select(Fichier.hash_sha256)
        .join(Item, Fichier.item_id == Item.id)
        .where(Fichier.hash_sha256.is_not(None))
        .where(Fichier.etat == EtatFichier.ACTIF.value)
        .group_by(Fichier.hash_sha256)
        .having(func.count(Fichier.id) > 1)
    )
    stmt_groupes = _filtre_ids_collections(stmt_groupes, ids_collections)
    hashes_dup = list(session.scalars(stmt_groupes).all())
    if not hashes_dup:
        rap.duree_secondes = time.perf_counter() - debut
        return rap

    stmt_fichiers = (
        select(Fichier, Item.cote)
        .join(Item, Fichier.item_id == Item.id)
        .where(Fichier.hash_sha256.in_(hashes_dup))
        .where(Fichier.etat == EtatFichier.ACTIF.value)
        .order_by(Fichier.hash_sha256, Fichier.id)
    )
    stmt_fichiers = _filtre_ids_collections(stmt_fichiers, ids_collections)

    groupes: dict[str, GroupeDoublons] = {}
    for fichier, cote_item in session.execute(stmt_fichiers).all():
        h = fichier.hash_sha256
        groupe = groupes.setdefault(h, GroupeDoublons(hash_sha256=h))
        groupe.fichiers.append(
            FichierDoublon(
                fichier_id=fichier.id,
                item_cote=cote_item,
                racine=fichier.racine,
                chemin_relatif=fichier.chemin_relatif,
            )
        )

    rap.anomalies = [g for g in groupes.values() if len(g.fichiers) >= 2]
    rap.duree_secondes = time.perf_counter() - debut
    return rap


@dataclass(frozen=True)
class _DefControle:
    """Définition d'un contrôle : code stable, libellé, fonction et
    arguments supplémentaires acceptés. Source de vérité unique pour
    `controler_tout` et l'affichage."""

    code: str
    libelle: str
    fonction: Callable[..., RapportControle]
    accepte_racines: bool = False
    accepte_extensions: bool = False


_CONTROLES: tuple[_DefControle, ...] = (
    _DefControle(
        "fichiers-manquants",
        "Fichiers référencés mais absents du disque",
        controler_fichiers_manquants_disque,
        accepte_racines=True,
    ),
    _DefControle(
        "orphelins-disque",
        "Fichiers sur disque non référencés en base",
        controler_orphelins_disque,
        accepte_racines=True,
        accepte_extensions=True,
    ),
    _DefControle(
        "items-vides",
        "Items sans fichier rattaché",
        controler_items_sans_fichier,
    ),
    _DefControle(
        "doublons",
        "Doublons potentiels (même hash SHA-256)",
        controler_doublons_par_hash,
    ),
)

CODES_CONTROLES: tuple[str, ...] = tuple(d.code for d in _CONTROLES)
LIBELLES: dict[str, str] = {d.code: d.libelle for d in _CONTROLES}


def controler_tout(
    session: Session,
    *,
    racines: Mapping[str, Path] | None = None,
    collection_cote: str | None = None,
    recursif: bool = False,
    checks: Iterable[str] | None = None,
    extensions_orphelins: Iterable[str] | None = None,
) -> RapportQa:
    """Lance les contrôles demandés et retourne un rapport global.

    `checks=None` lance les quatre. Les codes inconnus lèvent ValueError.
    """
    debut = time.perf_counter()

    codes_demandes = list(checks) if checks is not None else list(CODES_CONTROLES)
    inconnus = [c for c in codes_demandes if c not in LIBELLES]
    if inconnus:
        raise ValueError(
            f"Code(s) de contrôle inconnu(s) : {inconnus!r}. "
            f"Attendu : {list(CODES_CONTROLES)}."
        )

    ids_collections: list[int] | None = None
    portee = "global"
    if collection_cote is not None:
        col = _collection_par_cote(session, collection_cote)
        ids_collections = col.ids_descendants() if recursif else [col.id]
        portee = f"collection {collection_cote}{' (récursif)' if recursif else ''}"

    racines_eff: Mapping[str, Path] = racines or {}
    rapport = RapportQa(portee=portee)

    par_code = {d.code: d for d in _CONTROLES}
    for code in codes_demandes:
        defc = par_code[code]
        kwargs: dict = {"ids_collections": ids_collections}
        if defc.accepte_racines:
            kwargs = {"racines": racines_eff, **kwargs}
        if defc.accepte_extensions:
            kwargs["extensions"] = extensions_orphelins
        rapport.controles.append(defc.fonction(session, **kwargs))

    rapport.duree_secondes = time.perf_counter() - debut
    return rapport
