"""Données factices pour la démo de l'interface.

Crée des collections (FA, HK, PF, RDM, LE), une hiérarchie pour FA,
quelques dizaines d'items par collection, des fichiers, et une poignée
d'événements de journal pour avoir une activité récente non vide. Pas
d'écriture sur disque pour les fichiers : `derive_genere=False`,
hash factices ; les contrôles de cohérence détecteront naturellement
quelques anomalies (orphelins, doublons).
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import (
    Base,
    Collection,
    EtatCatalogage,
    Fichier,
    Item,
    ModificationItem,
    OperationFichier,
    OperationImport,
    PhaseChantier,
    StatutOperation,
    TypeOperationFichier,
)


@dataclass
class RapportDemo:
    chemin_db: Path
    nb_collections: int
    nb_collections_racines: int
    nb_items: int
    nb_fichiers: int
    nb_anomalies: int


_COLLECTIONS_RACINES = [
    {
        "cote": "FA",
        "titre": "Fonds Aínsa",
        "phase": PhaseChantier.CATALOGAGE,
        "editeur": None,
        "items_titres": [
            "Carta de don Pedro",
            "Memoria del año 1923",
            "Inventario de bienes",
            "Cuaderno de campo",
            "Correspondencia oficial",
        ],
    },
    {
        "cote": "HK",
        "titre": "Hara-Kiri",
        "phase": PhaseChantier.REVISION,
        "editeur": "Cavanna",
        "items_titres": [
            "Numéro inaugural",
            "Le scandale du jour",
            "Sommaire de l'été",
            "Planche centrale",
            "Édition spéciale",
        ],
    },
    {
        "cote": "PF",
        "titre": "Por Favor",
        "phase": PhaseChantier.NUMERISATION,
        "editeur": "Equipo Por Favor",
        "items_titres": [
            "Editorial de portada",
            "Crónica política",
            "Reportaje fotográfico",
            "Sección humor",
            "Cartas al director",
        ],
    },
    {
        "cote": "RDM",
        "titre": "Revue des Deux Mondes",
        "phase": PhaseChantier.FINALISATION,
        "editeur": "Buloz",
        "items_titres": [
            "Chronique littéraire",
            "Notes de voyage",
            "Histoire contemporaine",
            "Critique d'art",
            "Économie politique",
        ],
    },
    {
        "cote": "LE",
        "titre": "Lois sur l'engagement",
        "phase": PhaseChantier.ARCHIVEE,
        "editeur": None,
        "items_titres": [
            "Décret 1915-04",
            "Annexe au registre",
            "Délibération communale",
            "Avis préfectoral",
        ],
    },
]

_SOUS_COLLECTIONS_FA = [
    ("FA-AA", "Œuvres", PhaseChantier.CATALOGAGE),
    ("FA-AB", "Correspondance", PhaseChantier.REVISION),
    ("FA-AC", "Documentation", PhaseChantier.CATALOGAGE),
    ("FA-AD", "Photographies", PhaseChantier.NUMERISATION),
]

_ETATS_DISTRIBUTION = [
    EtatCatalogage.VALIDE,
    EtatCatalogage.VALIDE,
    EtatCatalogage.VERIFIE,
    EtatCatalogage.A_VERIFIER,
    EtatCatalogage.BROUILLON,
    EtatCatalogage.A_CORRIGER,
]


def _hash_factice(seed: str) -> str:
    return (
        uuid.uuid5(uuid.NAMESPACE_OID, seed).hex
        + uuid.uuid5(uuid.NAMESPACE_OID, seed[::-1]).hex[:32]
    )


def _creer_collection(
    session: Session,
    cote: str,
    titre: str,
    phase: PhaseChantier,
    alea: random.Random,
    *,
    parent: Collection | None = None,
    editeur: str | None = None,
) -> Collection:
    col = Collection(
        cote_collection=cote,
        titre=titre,
        editeur=editeur,
        phase=phase.value,
        parent=parent,
        cree_par="Marie",
        modifie_par="Marie",
        modifie_le=datetime.now() - timedelta(days=alea.randint(0, 5)),
    )
    session.add(col)
    session.flush()
    return col


def _creer_items(
    session: Session,
    collection: Collection,
    titres: list[str],
    alea: random.Random,
    *,
    nb_min: int = 30,
    nb_max: int = 50,
) -> list[Item]:
    nb = alea.randint(nb_min, nb_max)
    items: list[Item] = []
    for i in range(1, nb + 1):
        titre_base = alea.choice(titres)
        item = Item(
            collection_id=collection.id,
            cote=f"{collection.cote_collection}-{i:03d}",
            titre=f"{titre_base} #{i}",
            annee=alea.randint(1890, 1985),
            etat_catalogage=alea.choice(_ETATS_DISTRIBUTION).value,
            cree_par="Marie",
            modifie_par="Marie",
            modifie_le=datetime.now() - timedelta(hours=alea.randint(0, 200)),
        )
        session.add(item)
        items.append(item)
    session.flush()
    return items


def _creer_fichiers(
    session: Session,
    item: Item,
    alea: random.Random,
    *,
    racine: str = "scans_revues",
) -> list[Fichier]:
    nb = alea.randint(5, 15)
    fichiers: list[Fichier] = []
    for ordre in range(1, nb + 1):
        nom = f"{item.cote}-{ordre:02d}.png"
        fichier = Fichier(
            item_id=item.id,
            racine=racine,
            chemin_relatif=f"{item.cote}/{nom}",
            nom_fichier=nom,
            ordre=ordre,
            hash_sha256=_hash_factice(f"{item.id}-{ordre}"),
            taille_octets=alea.randint(500_000, 5_000_000),
            largeur_px=alea.randint(1500, 4000),
            hauteur_px=alea.randint(2000, 5000),
            format="png",
            ajoute_par="Marie",
        )
        session.add(fichier)
        fichiers.append(fichier)
    session.flush()
    return fichiers


def _creer_journaux(session: Session, items: list[Item], alea: random.Random) -> None:
    """Quelques entrées récentes pour peupler l'activité du dashboard."""
    if not items:
        return

    batch_renommage = str(uuid.uuid4())
    for item in alea.sample(items, k=min(3, len(items))):
        if not item.fichiers:
            continue
        f = item.fichiers[0]
        session.add(
            OperationFichier(
                batch_id=batch_renommage,
                fichier_id=f.id,
                type_operation=TypeOperationFichier.RENAME.value,
                racine_avant=f.racine,
                chemin_avant=f.chemin_relatif,
                racine_apres=f.racine,
                chemin_apres=f.chemin_relatif,
                statut=StatutOperation.REUSSIE.value,
                execute_par="Marie",
                execute_le=datetime.now() - timedelta(hours=alea.randint(1, 12)),
            )
        )

    for item in alea.sample(items, k=min(4, len(items))):
        session.add(
            ModificationItem(
                item_id=item.id,
                champ="titre",
                valeur_avant=None,
                valeur_apres=item.titre,
                modifie_par="Marie",
                modifie_le=datetime.now() - timedelta(hours=alea.randint(1, 24)),
            )
        )

    session.add(
        OperationImport(
            batch_id=str(uuid.uuid4()),
            profil_chemin="profiles/demo.yaml",
            collection_id=items[0].collection_id,
            items_crees=len(items),
            fichiers_ajoutes=sum(len(i.fichiers) for i in items),
            execute_par="Marie",
            execute_le=datetime.now() - timedelta(days=2),
        )
    )


def _injecter_doublons(items: list[Item]) -> int:
    """Force deux fichiers à partager un même hash pour le contrôle qa."""
    if len(items) < 2 or not items[0].fichiers or not items[1].fichiers:
        return 0
    items[1].fichiers[0].hash_sha256 = items[0].fichiers[0].hash_sha256
    return 1


def peupler_base(chemin_db: Path, *, seed: int = 42) -> RapportDemo:
    """Construit la base de démonstration (création + remplissage).

    `seed` permet de rejouer la même base (pour les tests) ou d'en
    générer une variante. Le RNG est local : appeler deux fois la
    fonction sur le même seed produit deux bases identiques, alors
    qu'un RNG module-level ferait dériver l'état entre appels.
    """
    alea = random.Random(seed)
    chemin_db.parent.mkdir(parents=True, exist_ok=True)
    engine = creer_engine(chemin_db)
    Base.metadata.create_all(engine)

    factory = creer_session_factory(engine)
    nb_items_total = 0
    nb_fichiers_total = 0
    anomalies = 0

    with factory() as session:
        racines: dict[str, Collection] = {}
        for cfg in _COLLECTIONS_RACINES:
            col = _creer_collection(
                session,
                cfg["cote"],
                cfg["titre"],
                cfg["phase"],
                alea,
                editeur=cfg.get("editeur"),
            )
            racines[col.cote_collection] = col
            items = _creer_items(session, col, cfg["items_titres"], alea)
            for item in items:
                _creer_fichiers(session, item, alea)
            nb_items_total += len(items)
            nb_fichiers_total += sum(len(it.fichiers) for it in items)
            anomalies += _injecter_doublons(items)
            _creer_journaux(session, items, alea)

        for cote, titre, phase in _SOUS_COLLECTIONS_FA:
            sous = _creer_collection(
                session, cote, titre, phase, alea, parent=racines["FA"]
            )
            items = _creer_items(session, sous, ["Pièce", "Document", "Notice"], alea)
            for item in items:
                _creer_fichiers(session, item, alea)
            nb_items_total += len(items)
            nb_fichiers_total += sum(len(it.fichiers) for it in items)

        # Anomalie supplémentaire : un item sans fichier dans HK.
        hk = racines["HK"]
        item_vide = Item(
            collection_id=hk.id,
            cote=f"{hk.cote_collection}-VIDE",
            titre="Numéro disparu",
            cree_par="Marie",
        )
        session.add(item_vide)
        anomalies += 1
        nb_items_total += 1

        session.commit()

    engine.dispose()
    return RapportDemo(
        chemin_db=chemin_db,
        nb_collections=len(_COLLECTIONS_RACINES) + len(_SOUS_COLLECTIONS_FA),
        nb_collections_racines=len(_COLLECTIONS_RACINES),
        nb_items=nb_items_total,
        nb_fichiers=nb_fichiers_total,
        nb_anomalies=anomalies,
    )
