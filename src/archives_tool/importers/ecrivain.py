"""Écrivain d'import : du profil validé aux données en base.

Orchestration :
1. Résout ou crée la Collection cible (et son parent si déclaré).
2. Pour chaque ligne du tableur :
   - lire + transformer → ItemPrepare ;
   - résoudre les fichiers sur disque → list[FichierPrepare].
3. Si granularite_source == "fichier", regroupe les lignes par cote
   avant l'étape d'écriture.
4. Applique les créations/mises à jour en une seule transaction
   (rollback sur erreur en mode réel). En dry-run, le rapport est
   complet mais rien n'est écrit.

Comportement :
- Dry-run par défaut. Hash SHA-256 non calculés en dry-run (rapide).
- En mode réel : hash calculés, batch_id généré (UUID), entrée
  OperationImport journalisée.
- Ré-import : mise à jour par (collection_id, cote). Item inchangé
  si aucun champ mappé n'a bougé.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.config import ConfigLocale
from archives_tool.importers.lecteur_tableur import lire_tableur
from archives_tool.importers.resolveur_fichiers import (
    FichierPrepare,
    resoudre_fichiers_pour_item,
)
from archives_tool.importers.transformateur import ItemPrepare, transformer_ligne
from archives_tool.models import (
    Collection,
    Fichier,
    Item,
    OperationImport,
)
from archives_tool.profils.schema import Profil


@dataclass
class RapportImport:
    dry_run: bool
    batch_id: str | None = None
    collection_creee: bool = False
    collection_id: int | None = None
    items_crees: int = 0
    items_mis_a_jour: int = 0
    items_inchanges: int = 0
    fichiers_ajoutes: int = 0
    fichiers_deja_connus: int = 0
    fichiers_orphelins: list[str] = field(default_factory=list)
    lignes_ignorees: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)
    duree_secondes: float = 0.0


def _resoudre_ou_creer_collection(
    profil: Profil,
    session: Session,
    cree_par: str | None,
    rapport: RapportImport,
) -> Collection:
    col_profil = profil.collection

    # Parent éventuel : doit exister.
    parent: Collection | None = None
    if col_profil.parent_cote:
        parent = session.scalar(
            select(Collection).where(
                Collection.cote_collection == col_profil.parent_cote
            )
        )
        if parent is None:
            raise ValueError(
                f"Collection parent {col_profil.parent_cote!r} déclarée dans "
                "le profil mais introuvable en base."
            )

    existante = session.scalar(
        select(Collection).where(Collection.cote_collection == col_profil.cote)
    )
    if existante is not None:
        # Signaler les divergences de métadonnées sans bloquer l'import.
        for champ, val_prof in col_profil.model_dump(
            exclude={"cote", "parent_cote"}
        ).items():
            val_base = getattr(existante, champ, None)
            if val_prof is not None and val_base != val_prof:
                rapport.warnings.append(
                    f"Collection {col_profil.cote}: {champ} diverge "
                    f"(base={val_base!r}, profil={val_prof!r}). Base conservée."
                )
        return existante

    nouvelle = Collection(
        cote_collection=col_profil.cote,
        titre=col_profil.titre,
        titre_secondaire=col_profil.titre_secondaire,
        editeur=col_profil.editeur,
        lieu_edition=col_profil.lieu_edition,
        periodicite=col_profil.periodicite,
        date_debut=col_profil.date_debut,
        date_fin=col_profil.date_fin,
        issn=col_profil.issn,
        doi_nakala=col_profil.doi_nakala,
        description=col_profil.description,
        description_interne=col_profil.description_interne,
        auteur_principal=col_profil.auteur_principal,
        parent=parent,
        cree_par=cree_par,
    )
    session.add(nouvelle)
    session.flush()  # pour obtenir l'id
    rapport.collection_creee = True
    return nouvelle


def _grouper_par_cote(
    items_prep: list[tuple[ItemPrepare, list[FichierPrepare]]],
    rapport: RapportImport,
) -> list[tuple[ItemPrepare, list[FichierPrepare]]]:
    """Fusionne les lignes partageant la même cote (granularité fichier).

    Première valeur non-None retenue par champ ; divergences → warning.
    Fichiers concaténés dans l'ordre d'apparition.
    """
    groupes: dict[str, tuple[ItemPrepare, list[FichierPrepare]]] = {}
    for item, fichiers in items_prep:
        if item.cote in groupes:
            base, fichiers_base = groupes[item.cote]
            for cle, val in item.champs_colonne.items():
                if val is None:
                    continue
                ancienne = base.champs_colonne.get(cle)
                if ancienne is None:
                    base.champs_colonne[cle] = val
                elif ancienne != val:
                    rapport.warnings.append(
                        f"Cote {item.cote}: divergence sur {cle!r} entre "
                        f"lignes (garde {ancienne!r}, ignore {val!r})."
                    )
            for cle, val in item.metadonnees.items():
                if val is None:
                    continue
                ancienne = base.metadonnees.get(cle)
                if ancienne is None:
                    base.metadonnees[cle] = val
                elif ancienne != val:
                    rapport.warnings.append(
                        f"Cote {item.cote}: divergence sur metadonnees.{cle} "
                        f"(garde {ancienne!r}, ignore {val!r})."
                    )
            fichiers_base.extend(fichiers)
        else:
            groupes[item.cote] = (item, list(fichiers))
    # Réindexer l'ordre des fichiers après fusion, par groupe.
    resultats = []
    for cote, (item, fichiers) in groupes.items():
        for i, f in enumerate(fichiers):
            f.ordre = i + 1
        resultats.append((item, fichiers))
    return resultats


def _valeurs_equivalentes(a: Any, b: Any) -> bool:
    """Comparaison tolérante entre une valeur lue en base et une
    valeur produite par le transformateur.

    pandas lit toutes les cellules en `dtype=str` ; les colonnes
    typées (Integer) stockent la valeur coercée par SQLite. Il faut
    donc accepter 1960 == "1960", sinon chaque ré-import marque
    artificiellement à jour les items avec un champ numérique.
    """
    if a == b:
        return True
    if a is None or b is None:
        return False
    return str(a) == str(b)


def _champs_item_a_jour(item: Item, prep: ItemPrepare) -> dict[str, Any]:
    """Retourne le dict des champs à mettre à jour (valeur différente)."""
    diff: dict[str, Any] = {}
    for cle, val in prep.champs_colonne.items():
        if cle == "cote":
            continue  # cote identifie l'item, pas à mettre à jour ici
        if hasattr(item, cle) and not _valeurs_equivalentes(getattr(item, cle), val):
            diff[cle] = val
    # metadonnees complètes remplacées par le nouveau dict (avec
    # injection de hierarchie/typologie si présentes).
    nouvelles_meta = dict(prep.metadonnees)
    if prep.hierarchie:
        nouvelles_meta["hierarchie"] = prep.hierarchie
    if prep.typologie:
        nouvelles_meta["typologie"] = prep.typologie
    if (item.metadonnees or {}) != nouvelles_meta:
        diff["metadonnees"] = nouvelles_meta
    return diff


def _ecrire_item(
    prep: ItemPrepare,
    collection: Collection,
    session: Session,
    cree_par: str | None,
    rapport: RapportImport,
) -> Item:
    existant = session.scalar(
        select(Item).where(
            (Item.collection_id == collection.id) & (Item.cote == prep.cote)
        )
    )
    meta = dict(prep.metadonnees)
    if prep.hierarchie:
        meta["hierarchie"] = prep.hierarchie
    if prep.typologie:
        meta["typologie"] = prep.typologie

    if existant is None:
        item = Item(
            collection_id=collection.id,
            cote=prep.cote,
            metadonnees=meta or None,
            cree_par=cree_par,
        )
        for cle, val in prep.champs_colonne.items():
            if cle == "cote":
                continue
            if hasattr(item, cle):
                setattr(item, cle, val)
        session.add(item)
        session.flush()
        rapport.items_crees += 1
        return item

    diff = _champs_item_a_jour(existant, prep)
    if not diff:
        rapport.items_inchanges += 1
        return existant
    for cle, val in diff.items():
        setattr(existant, cle, val)
    existant.modifie_par = cree_par
    session.flush()
    rapport.items_mis_a_jour += 1
    return existant


def _ecrire_fichiers(
    item: Item,
    fichiers_prep: list[FichierPrepare],
    session: Session,
    rapport: RapportImport,
) -> None:
    if not fichiers_prep:
        return
    existants_par_chemin = {(f.racine, f.chemin_relatif): f for f in item.fichiers}
    ordres_utilises = {f.ordre for f in item.fichiers}
    prochain_ordre = max(ordres_utilises, default=0) + 1

    for prep in fichiers_prep:
        cle = (prep.racine, prep.chemin_relatif)
        if cle in existants_par_chemin:
            rapport.fichiers_deja_connus += 1
            continue
        ordre = prep.ordre if prep.ordre not in ordres_utilises else prochain_ordre
        ordres_utilises.add(ordre)
        if ordre >= prochain_ordre:
            prochain_ordre = ordre + 1
        fichier = Fichier(
            item_id=item.id,
            racine=prep.racine,
            chemin_relatif=prep.chemin_relatif,
            nom_fichier=prep.nom_fichier,
            hash_sha256=prep.hash_sha256,
            taille_octets=prep.taille_octets,
            format=prep.format,
            ordre=ordre,
        )
        session.add(fichier)
        rapport.fichiers_ajoutes += 1


def importer(
    profil: Profil,
    chemin_profil: Path,
    session: Session,
    config: ConfigLocale,
    dry_run: bool = True,
    cree_par: str | None = None,
) -> RapportImport:
    """Exécute l'import complet et retourne un `RapportImport`."""
    debut = time.monotonic()
    rapport = RapportImport(dry_run=dry_run)

    try:
        # 1. Collection cible.
        collection = _resoudre_ou_creer_collection(profil, session, cree_par, rapport)
        rapport.collection_id = collection.id

        # 2. Lecture + transformation + résolution fichiers.
        lignes = lire_tableur(profil, chemin_profil)
        items_et_fichiers: list[tuple[ItemPrepare, list[FichierPrepare]]] = []
        for idx, ligne in enumerate(lignes):
            numero_ligne = (
                idx + profil.tableur.ligne_entete + 1
            )  # 1-indexé, après l'entête
            try:
                prep = transformer_ligne(ligne, numero_ligne, profil)
            except ValueError as e:
                rapport.erreurs.append(f"Ligne {numero_ligne}: {e}")
                continue
            if prep is None:
                rapport.lignes_ignorees.append((numero_ligne, "ligne entièrement vide"))
                continue
            try:
                fichiers = resoudre_fichiers_pour_item(
                    prep, profil, config, avec_hash=not dry_run
                )
            except Exception as e:
                rapport.erreurs.append(
                    f"Ligne {numero_ligne}: résolution fichiers : {e}"
                )
                continue
            items_et_fichiers.append((prep, fichiers))

        # 3. Regroupement granularité fichier.
        if profil.granularite_source == "fichier":
            items_et_fichiers = _grouper_par_cote(items_et_fichiers, rapport)

        # 4. Si erreurs avant écriture et mode réel : arrêter net.
        if rapport.erreurs and not dry_run:
            session.rollback()
            rapport.duree_secondes = time.monotonic() - debut
            return rapport

        # 5. Écritures (en session ; commit ou rollback plus loin).
        for prep, fichiers in items_et_fichiers:
            item = _ecrire_item(prep, collection, session, cree_par, rapport)
            _ecrire_fichiers(item, fichiers, session, rapport)

        if dry_run:
            session.rollback()
        else:
            rapport.batch_id = str(uuid.uuid4())
            journal = OperationImport(
                batch_id=rapport.batch_id,
                profil_chemin=str(chemin_profil),
                collection_id=collection.id,
                items_crees=rapport.items_crees,
                items_mis_a_jour=rapport.items_mis_a_jour,
                items_inchanges=rapport.items_inchanges,
                fichiers_ajoutes=rapport.fichiers_ajoutes,
                execute_par=cree_par,
                rapport_json=json.dumps(asdict(rapport), ensure_ascii=False),
            )
            session.add(journal)
            session.commit()
    except Exception as e:
        session.rollback()
        rapport.erreurs.append(f"Erreur fatale : {e}")

    rapport.duree_secondes = time.monotonic() - debut
    return rapport
