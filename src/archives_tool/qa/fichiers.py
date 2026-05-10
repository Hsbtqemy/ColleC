"""Famille 2 — cohérence des fichiers.

Tous les contrôles supposent que les racines de la config locale sont
fournies pour les vérifications disque. Si elles sont absentes,
FILE-MISSING saute les contrôles disque (compte 0 mais avertissement
remonté en `references`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.files.paths import (
    chemin_existe_nfc_ou_nfd,
    valider_chemin_relatif,
)
from archives_tool.models import EtatFichier, Fichier, Item, ItemCollection
from archives_tool.qa._commun import (
    Exemple,
    PerimetreControle,
    ResultatControle,
    Severite,
    borner_exemples,
    construire_resultat,
    restreindre_aux_fichiers,
)

FAMILLE = "fichiers"


def controler_file_missing(
    db: Session,
    perimetre: PerimetreControle,
    *,
    racines: Mapping[str, Path] | None = None,
) -> ResultatControle:
    """FILE-MISSING : fichier référencé en base mais absent du disque.

    Avertissement (pas erreur) car la base demo et les bases de test
    n'ont pas leurs fichiers physiquement. Si `racines` est vide ou
    None, on remonte juste un avertissement de configuration.
    """
    racines = racines or {}
    stmt = restreindre_aux_fichiers(
        select(Fichier.id, Fichier.racine, Fichier.chemin_relatif).where(
            Fichier.etat == EtatFichier.ACTIF.value,
            Fichier.chemin_relatif.is_not(None),
        ),
        perimetre,
    ).order_by(Fichier.racine, Fichier.chemin_relatif)
    rows = db.execute(stmt).all()

    problemes: list[Exemple] = []
    for fid, racine, chemin_rel in rows:
        if racine not in racines:
            problemes.append(
                Exemple(
                    message=f"Racine {racine!r} non configurée pour {chemin_rel}",
                    references={"fichier_id": fid, "racine": racine},
                )
            )
            continue
        try:
            valider_chemin_relatif(chemin_rel)
        except ValueError:
            problemes.append(
                Exemple(
                    message=f"Chemin relatif invalide : {chemin_rel}",
                    references={"fichier_id": fid, "chemin_relatif": chemin_rel},
                )
            )
            continue
        if not chemin_existe_nfc_ou_nfd(racines[racine], chemin_rel):
            problemes.append(
                Exemple(
                    message=f"Fichier absent du disque : {racine}/{chemin_rel}",
                    references={
                        "fichier_id": fid,
                        "racine": racine,
                        "chemin_relatif": chemin_rel,
                    },
                )
            )

    return construire_resultat(
        id="FILE-MISSING",
        famille=FAMILLE,
        severite=Severite.AVERTISSEMENT,
        libelle="Fichier référencé en base mais absent du disque",
        total=len(rows),
        problemes=problemes,
    )


def controler_file_item_vide(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """FILE-ITEM-VIDE : item sans fichier rattaché (info)."""
    items_stmt = select(Item.id, Item.cote)
    if perimetre.fonds_id is not None:
        items_stmt = items_stmt.where(Item.fonds_id == perimetre.fonds_id)
    elif perimetre.collection_id is not None:
        items_stmt = items_stmt.where(
            Item.id.in_(
                select(ItemCollection.item_id).where(
                    ItemCollection.collection_id == perimetre.collection_id
                )
            )
        )
    items = db.execute(items_stmt.order_by(Item.cote)).all()

    item_ids_avec_fichiers = {
        iid
        for (iid,) in db.execute(
            restreindre_aux_fichiers(
                select(Fichier.item_id)
                .where(Fichier.etat == EtatFichier.ACTIF.value)
                .distinct(),
                perimetre,
            )
        ).all()
    }

    problemes = [
        Exemple(
            message=f"Item {cote} sans fichier",
            references={"item_cote": cote, "item_id": iid},
        )
        for iid, cote in items
        if iid not in item_ids_avec_fichiers
    ]
    return construire_resultat(
        id="FILE-ITEM-VIDE",
        famille=FAMILLE,
        severite=Severite.INFO,
        libelle="Item avec au moins un fichier",
        total=len(items),
        problemes=problemes,
    )


def controler_file_hash_duplique(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """FILE-HASH-DUPLIQUE : plusieurs fichiers ACTIF avec même hash.

    Saute les fichiers dont le hash n'est pas calculé (cas demo).
    Agrégation SQL — pas de boucle Python sur tous les fichiers.
    """
    stmt = (
        restreindre_aux_fichiers(
            select(
                Fichier.hash_sha256,
                func.count(Fichier.id).label("nb"),
            ).where(
                Fichier.etat == EtatFichier.ACTIF.value,
                Fichier.hash_sha256.is_not(None),
            ),
            perimetre,
        )
        .group_by(Fichier.hash_sha256)
        .having(func.count(Fichier.id) > 1)
        .order_by(Fichier.hash_sha256)
    )
    duplicats = db.execute(stmt).all()
    nb_total = (
        db.scalar(
            restreindre_aux_fichiers(
                select(func.count(Fichier.id)).where(
                    Fichier.etat == EtatFichier.ACTIF.value,
                    Fichier.hash_sha256.is_not(None),
                ),
                perimetre,
            )
        )
        or 0
    )

    problemes: list[Exemple] = []
    for hash_, nb in duplicats:
        cotes = db.execute(
            select(Item.cote, Fichier.nom_fichier)
            .join(Item, Item.id == Fichier.item_id)
            .where(Fichier.hash_sha256 == hash_)
            .order_by(Item.cote, Fichier.nom_fichier)
            .limit(3)
        ).all()
        descriptifs = ", ".join(f"{c}/{n}" for c, n in cotes)
        problemes.append(
            Exemple(
                message=f"{nb} fichiers avec hash {hash_[:8]}… : {descriptifs}",
                references={"hash_sha256": hash_, "nb": nb},
            )
        )

    # Compte particulier : on remonte le total des fichiers concernés
    # par les groupes de doublons (pas le nombre de groupes).
    return ResultatControle(
        id="FILE-HASH-DUPLIQUE",
        famille=FAMILLE,
        severite=Severite.AVERTISSEMENT,
        libelle="Doublons de fichiers par hash SHA-256",
        passe=not problemes,
        compte_total=nb_total,
        compte_problemes=sum(nb for _, nb in duplicats),
        exemples=borner_exemples(problemes),
    )


def controler_file_hash_manquant(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """FILE-HASH-MANQUANT : fichier ACTIF sans hash calculé (info).

    Attendu sur la base demo (fichiers fictifs). Sur une base réelle,
    c'est un signal d'import incomplet.
    """
    stmt = restreindre_aux_fichiers(
        select(Fichier.id, Fichier.racine, Fichier.chemin_relatif).where(
            Fichier.etat == EtatFichier.ACTIF.value,
            Fichier.hash_sha256.is_(None),
        ),
        perimetre,
    ).order_by(Fichier.racine, Fichier.chemin_relatif)
    rows = db.execute(stmt).all()
    problemes = [
        Exemple(
            message=f"Hash absent : {racine}/{chemin_rel}",
            references={"fichier_id": fid, "racine": racine},
        )
        for fid, racine, chemin_rel in rows
    ]
    return construire_resultat(
        id="FILE-HASH-MANQUANT",
        famille=FAMILLE,
        severite=Severite.INFO,
        libelle="Fichier avec hash SHA-256 calculé",
        total=perimetre.fichiers_count,
        problemes=problemes,
    )
