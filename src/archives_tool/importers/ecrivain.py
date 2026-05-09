"""Écrivain d'import : du profil v2 validé aux données en base.

Orchestration :
1. Crée le fonds + sa miroir auto via `creer_fonds` (service métier).
2. Si la section `collection_miroir:` est présente, applique les
   personnalisations (titre, descriptions, phase, DOI) via
   `modifier_collection`.
3. Pour chaque ligne du tableur :
   - lire + transformer → ItemPrepare ;
   - résoudre les fichiers sur disque → list[FichierPrepare].
4. Si granularite_source == "fichier", regroupe les lignes par cote.
5. Crée les items via `creer_item` (auto-rattachement à la miroir,
   invariant 6).
6. Ajoute les Fichier à la session (couche basse, pas de service
   dédié pour l'instant).

Comportement :
- Dry-run par défaut : aucune écriture en base, rapport simulé.
  Pas d'appel aux services qui commitent ; validation Pydantic + lecture
  tableur + résolution fichiers seulement.
- Mode réel : appel aux services métier (qui commitent à chaque entité).
  En cas d'erreur après création du fonds, le fonds créé reste en base
  (les commits sont déjà passés) — l'utilisateur peut le supprimer
  manuellement.
- Hash SHA-256 calculés en mode réel uniquement (rapide en dry-run).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    FormulaireCollection,
    formulaire_depuis_collection,
    modifier_collection,
)
from archives_tool.api.services.fonds import (
    FondsInvalide,
    FormulaireFonds,
    creer_fonds,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    ItemInvalide,
    creer_item,
)
from archives_tool.config import ConfigLocale
from archives_tool.importers.lecteur_tableur import lire_tableur
from archives_tool.importers.resolveur_fichiers import (
    FichierPrepare,
    resoudre_fichiers_pour_item,
)
from archives_tool.importers.transformateur import ItemPrepare, transformer_ligne
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Item,
    OperationImport,
)
from archives_tool.profils.schema import (
    CollectionMiroirProfil,
    FondsProfil,
    Profil,
)


@dataclass
class RapportImport:
    dry_run: bool
    batch_id: str | None = None
    fonds_cote: str | None = None
    fonds_id: int | None = None
    fonds_cree: bool = False
    miroir_id: int | None = None
    miroir_personnalisee: bool = False
    items_crees: int = 0
    # Champs réservés à la sémantique réimport (V0.9.x post-gamma.1) ;
    # actuellement 0 mais persistés dans OperationImport pour cohérence
    # de schéma à long terme.
    items_inchanges: int = 0
    items_mis_a_jour: int = 0
    fichiers_ajoutes: int = 0
    fichiers_deja_connus: int = 0
    fichiers_orphelins: list[str] = field(default_factory=list)
    lignes_ignorees: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)
    duree_secondes: float = 0.0


def _formulaire_fonds_depuis_profil(prof: FondsProfil) -> FormulaireFonds:
    """Convertit `FondsProfil` (None pour absent) en `FormulaireFonds`
    (chaîne vide pour absent). Les deux modèles ont les mêmes 13 champs ;
    on s'appuie sur model_dump pour rester cohérent en cas d'évolution."""
    data = {k: (v if v is not None else "") for k, v in prof.model_dump().items()}
    return FormulaireFonds.model_validate(data)


def _appliquer_overrides_miroir(
    base: FormulaireCollection, overrides: CollectionMiroirProfil
) -> FormulaireCollection:
    """Applique les champs renseignés du profil sur le formulaire de base.

    `model_validate` re-déclenche les validateurs de `FormulaireCollection`
    (notamment celui de `phase` qui rejette les valeurs hors enum) — pas
    besoin de pré-valider côté importer.
    """
    data = base.model_dump()
    for nom, val in overrides.model_dump().items():
        if val is None:
            continue
        data[nom] = val
    return FormulaireCollection.model_validate(data)


def _personnaliser_miroir(
    db: Session,
    miroir: Collection,
    overrides: CollectionMiroirProfil,
    modifie_par: str | None,
) -> None:
    base = formulaire_depuis_collection(miroir)
    nouveau = _appliquer_overrides_miroir(base, overrides)
    modifier_collection(db, miroir.id, nouveau, modifie_par=modifie_par)


def _construire_formulaire_item(
    prep: ItemPrepare,
    fonds_id: int,
    valeurs_par_defaut: dict[str, Any],
) -> FormulaireItem:
    """Convertit un `ItemPrepare` en `FormulaireItem`.

    `valeurs_par_defaut` complète les colonnes absentes (langue,
    etat_catalogage, etc.) sans écraser ce qui vient du tableur.
    Les métadonnées étendues (clé `metadonnees.X` du mapping) sont
    fusionnées avec hiérarchie/typologie issues des décompositions.
    """
    champs = dict(prep.champs_colonne)
    # Compléter avec les défauts du profil sans écraser les valeurs
    # explicitement renseignées (y compris None, qui peut être une
    # absence intentionnelle si l'utilisateur a mappé une colonne).
    for nom, val in valeurs_par_defaut.items():
        if nom not in champs:
            champs[nom] = val

    metadonnees = dict(prep.metadonnees)
    if prep.hierarchie:
        metadonnees["hierarchie"] = prep.hierarchie
    if prep.typologie:
        metadonnees["typologie"] = prep.typologie

    return FormulaireItem(
        cote=champs.get("cote") or prep.cote,
        titre=champs.get("titre") or "",
        fonds_id=fonds_id,
        description=champs.get("description") or "",
        notes_internes=champs.get("notes_internes") or "",
        type_coar=champs.get("type_coar") or "",
        langue=champs.get("langue") or "",
        date=champs.get("date") or "",
        annee=_int_ou_none(champs.get("annee")),
        numero=champs.get("numero") or "",
        numero_tri=_int_ou_none(champs.get("numero_tri")),
        etat_catalogage=champs.get("etat_catalogage") or EtatCatalogage.BROUILLON.value,
        metadonnees=metadonnees,
        doi_nakala=champs.get("doi_nakala") or "",
        doi_collection_nakala=champs.get("doi_collection_nakala") or "",
    )


def _int_ou_none(valeur: Any) -> int | None:
    """Coerce une valeur lue en str depuis un tableur en int, ou None.
    Les chaînes vides et les valeurs déjà-None deviennent None."""
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, int):
        return valeur
    try:
        return int(str(valeur).strip())
    except (ValueError, TypeError):
        return None


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


def _ecrire_fichiers(
    item: Item,
    fichiers_prep: list[FichierPrepare],
    session: Session,
    rapport: RapportImport,
) -> None:
    """Crée les Fichier rattachés à l'item (couche ORM directe).

    Pas de service `creer_fichier` : le besoin est trop simple (pas
    de validation métier complexe) et le journalisme se fait au niveau
    OperationImport pour l'import.
    """
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


def _preparer_lignes(
    profil: Profil,
    chemin_profil: Path,
    config: ConfigLocale,
    *,
    dry_run: bool,
    rapport: RapportImport,
) -> list[tuple[ItemPrepare, list[FichierPrepare]]]:
    """Lit le tableur et résout les fichiers, sans toucher la base.

    Cette étape est commune à dry-run et mode réel — c'est le point
    où l'on peut détecter les erreurs de mapping ou de motif fichiers
    avant toute écriture.
    """
    lignes = lire_tableur(profil, chemin_profil)
    items_et_fichiers: list[tuple[ItemPrepare, list[FichierPrepare]]] = []
    for idx, ligne in enumerate(lignes):
        numero_ligne = idx + profil.tableur.ligne_entete + 1  # 1-indexé
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
        except Exception as e:  # noqa: BLE001 — résolveur a plusieurs erreurs typées
            rapport.erreurs.append(
                f"Ligne {numero_ligne}: résolution fichiers : {e}"
            )
            continue
        items_et_fichiers.append((prep, fichiers))

    if profil.granularite_source == "fichier":
        items_et_fichiers = _grouper_par_cote(items_et_fichiers, rapport)
    return items_et_fichiers


def _executer_dry_run(
    profil: Profil,
    items_et_fichiers: list[tuple[ItemPrepare, list[FichierPrepare]]],
    rapport: RapportImport,
) -> None:
    """Simule l'import sans écriture en base.

    Valide chaque FormulaireItem produit + compte les fichiers qui
    seraient liés. Le fonds n'est pas réellement créé : on rapporte
    juste sa cote pour information.
    """
    rapport.fonds_cote = profil.fonds.cote
    rapport.fonds_cree = True
    rapport.miroir_personnalisee = profil.collection_miroir is not None

    for prep, fichiers in items_et_fichiers:
        try:
            # fonds_id factice : la validation Pydantic ne le vérifie
            # pas plus loin (le service ferait l'existence check).
            _construire_formulaire_item(
                prep, fonds_id=1, valeurs_par_defaut=profil.valeurs_par_defaut
            )
        except ValueError as e:
            rapport.erreurs.append(f"Item {prep.cote}: {e}")
            continue
        rapport.items_crees += 1
        rapport.fichiers_ajoutes += len(fichiers)


def _executer_reel(
    profil: Profil,
    items_et_fichiers: list[tuple[ItemPrepare, list[FichierPrepare]]],
    session: Session,
    cree_par: str | None,
    rapport: RapportImport,
) -> None:
    """Exécute l'import effectivement en base.

    Note : `creer_fonds` et `creer_item` commitent à chaque appel. Si
    une erreur survient en cours d'import, les entités déjà créées
    restent en base — l'utilisateur peut supprimer le fonds via la
    CLI `collections supprimer` (miroir gérée par le fonds).
    """
    formulaire_fonds = _formulaire_fonds_depuis_profil(profil.fonds)
    fonds = creer_fonds(session, formulaire_fonds, cree_par=cree_par)
    rapport.fonds_id = fonds.id
    rapport.fonds_cote = fonds.cote
    rapport.fonds_cree = True

    miroir = fonds.collection_miroir
    if miroir is None:
        # Anomalie : `creer_fonds` doit toujours créer la miroir.
        rapport.erreurs.append(
            f"Fonds {fonds.cote} créé sans miroir — anomalie d'intégrité."
        )
        return
    rapport.miroir_id = miroir.id

    if profil.collection_miroir is not None:
        try:
            _personnaliser_miroir(session, miroir, profil.collection_miroir, cree_par)
            rapport.miroir_personnalisee = True
        except ValueError as e:
            rapport.erreurs.append(f"Personnalisation miroir : {e}")
            return

    for prep, fichiers in items_et_fichiers:
        try:
            formulaire_item = _construire_formulaire_item(
                prep, fonds_id=fonds.id, valeurs_par_defaut=profil.valeurs_par_defaut
            )
        except ValueError as e:
            rapport.erreurs.append(f"Item {prep.cote}: {e}")
            continue
        try:
            item = creer_item(session, formulaire_item, cree_par=cree_par)
        except ItemInvalide as e:
            rapport.erreurs.append(f"Item {prep.cote} invalide : {e.erreurs}")
            continue
        rapport.items_crees += 1
        _ecrire_fichiers(item, fichiers, session, rapport)


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
        items_et_fichiers = _preparer_lignes(
            profil, chemin_profil, config, dry_run=dry_run, rapport=rapport
        )

        # Si erreurs avant écriture en mode réel, on s'arrête.
        if rapport.erreurs and not dry_run:
            rapport.duree_secondes = time.monotonic() - debut
            return rapport

        if dry_run:
            _executer_dry_run(profil, items_et_fichiers, rapport)
        else:
            _executer_reel(profil, items_et_fichiers, session, cree_par, rapport)
            if not rapport.erreurs:
                rapport.batch_id = str(uuid.uuid4())
                journal = OperationImport(
                    batch_id=rapport.batch_id,
                    profil_chemin=str(chemin_profil),
                    collection_id=rapport.miroir_id,
                    items_crees=rapport.items_crees,
                    items_mis_a_jour=rapport.items_mis_a_jour,
                    items_inchanges=rapport.items_inchanges,
                    fichiers_ajoutes=rapport.fichiers_ajoutes,
                    execute_par=cree_par,
                    rapport_json=json.dumps(asdict(rapport), ensure_ascii=False),
                )
                session.add(journal)
                session.commit()
    except FondsInvalide as e:
        rapport.erreurs.append(f"Fonds invalide : {e.erreurs}")
        session.rollback()
    except Exception as e:  # noqa: BLE001 — fail-safe pour ne pas perdre le rapport
        session.rollback()
        rapport.erreurs.append(f"Erreur fatale : {e}")

    rapport.duree_secondes = time.monotonic() - debut
    return rapport
