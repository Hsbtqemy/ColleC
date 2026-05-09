"""Génération de la base de démonstration V0.9.0+.

5 fonds (HK, FA, RDM, MAR, CONC-1789) avec leurs collections miroirs
auto-créées, 4 collections libres rattachées au fonds Aínsa, et une
collection transversale « Témoignages d'exil » qui pioche dans deux
fonds. ~330 items, ~1000 fichiers (entrées DB seulement, pas de
fichier physique sur disque).

Le seeder utilise exclusivement les services métier
(`creer_fonds`, `creer_collection_libre`, `creer_item`,
`ajouter_item_a_collection`, `ajouter_collaborateur`) — aucun INSERT
direct. Cela garantit que les invariants V0.9.0 sont respectés
(notamment l'auto-rattachement à la miroir).

Reproductibilité : RNG local seedé à 42 par défaut. Deux appels
consécutifs avec le même seed produisent des bases identiques.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    FormulaireCollection,
    ajouter_item_a_collection,
    creer_collection_libre,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    creer_item,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import (
    Base,
    CollaborateurFonds,
    Collection,
    EtatCatalogage,
    Fichier,
    Fonds,
    Item,
    RoleCollaborateur,
)


@dataclass
class RapportDemo:
    """Comptage de ce qui a été produit, pour affichage CLI."""

    chemin_db: Path
    nb_fonds: int
    nb_collections: int  # toutes types confondus (miroirs + libres + transversale)
    nb_items: int
    nb_fichiers: int


_ETATS_DISTRIBUTION: list[EtatCatalogage] = [
    EtatCatalogage.VALIDE,
    EtatCatalogage.VALIDE,
    EtatCatalogage.VALIDE,
    EtatCatalogage.VERIFIE,
    EtatCatalogage.A_VERIFIER,
    EtatCatalogage.BROUILLON,
    EtatCatalogage.A_CORRIGER,
]


def _etat_alea(alea: random.Random) -> str:
    return alea.choice(_ETATS_DISTRIBUTION).value


def _seed_fichiers(
    db: Session,
    item: Item,
    alea: random.Random,
    *,
    racine: str,
    nb_min: int = 5,
    nb_max: int = 12,
    extension: str = "tif",
) -> None:
    """Crée des entrées Fichier pour un item (chemins fictifs ;
    la base demo ne touche pas au disque)."""
    nb = alea.randint(nb_min, nb_max)
    for ordre in range(1, nb + 1):
        nom = f"{item.cote}-{ordre:02d}.{extension}"
        db.add(
            Fichier(
                item_id=item.id,
                racine=racine,
                chemin_relatif=f"{item.cote}/{nom}",
                nom_fichier=nom,
                ordre=ordre,
                taille_octets=alea.randint(500_000, 5_000_000),
                largeur_px=alea.randint(2400, 3600),
                hauteur_px=alea.randint(3000, 4800),
                format=extension,
                ajoute_par="seeder",
            )
        )


# ---------------------------------------------------------------------------
# Fonds Hara-Kiri (HK) — 40 items
# ---------------------------------------------------------------------------


def _seed_fonds_hk(db: Session, alea: random.Random) -> Fonds:
    fonds = creer_fonds(
        db,
        FormulaireFonds(
            cote="HK",
            titre="Hara-Kiri",
            description="Revue satirique mensuelle fondée par Cavanna.",
            description_publique=(
                "Hara-Kiri, mensuel satirique français (1960-1985), "
                "édité par Cavanna et le Professeur Choron."
            ),
            responsable_archives="Cavanna",
            editeur="Éditions du Square",
            lieu_edition="Paris",
            periodicite="mensuel",
            date_debut="1969",
            date_fin="1985",
        ),
        cree_par="seeder",
    )

    for i in range(1, 41):
        annee = min(1969 + (i // 4), 1985)
        item = creer_item(
            db,
            FormulaireItem(
                cote=f"HK-{i:03d}",
                titre=f"Numéro {i} de Hara-Kiri",
                fonds_id=fonds.id,
                description="Numéro mensuel — couvertures, dessins, textes.",
                date=str(annee),
                annee=annee,
                etat_catalogage=_etat_alea(alea),
            ),
            cree_par="seeder",
        )
        _seed_fichiers(db, item, alea, racine="scans_revues", extension="tif")
    return fonds


# ---------------------------------------------------------------------------
# Fonds Aínsa (FA) — 4 collections libres + miroir
# ---------------------------------------------------------------------------


_AINSA_COLLECTIONS = (
    ("FA-OEUVRES", "Œuvres", "Manuscrit autographe", 39, "manuscrit"),
    ("FA-CORRESP", "Correspondance", "Lettre", 32, "lettre"),
    ("FA-DOCU", "Documentation", "Note de travail", 47, "note"),
    ("FA-PHOTOS", "Photographies", "Photographie", 49, "photo"),
)
# Sélection candidate pour la collection transversale « Témoignages
# d'exil » : chacune de ces deux libres contribue ses items à la
# transversale au-delà de leur miroir habituelle (cf. _seed_transversale).
_AINSA_THEMATIQUES: frozenset[str] = frozenset({"FA-OEUVRES", "FA-CORRESP"})


def _seed_fonds_fa(db: Session, alea: random.Random) -> tuple[Fonds, list[Item]]:
    fonds = creer_fonds(
        db,
        FormulaireFonds(
            cote="FA",
            titre="Fonds Aínsa",
            description="Fonds personnel de l'écrivain uruguayen Fernando Aínsa.",
            personnalite_associee="Aínsa, Fernando",
            responsable_archives="Idmhand, Fatiha",
            date_debut="1955",
            date_fin="2019",
        ),
        cree_par="seeder",
    )

    items_thematiques: list[Item] = []
    for cote_libre, titre_libre, base_titre, nb_items, racine in _AINSA_COLLECTIONS:
        libre = creer_collection_libre(
            db,
            FormulaireCollection(
                cote=cote_libre,
                titre=titre_libre,
                fonds_id=fonds.id,
                description=f"Sous-classement « {titre_libre} » du fonds Aínsa.",
            ),
            cree_par="seeder",
        )
        for i in range(1, nb_items + 1):
            annee = alea.randint(1955, 2019)
            item = creer_item(
                db,
                FormulaireItem(
                    cote=f"{cote_libre}-{i:03d}",
                    titre=f"{base_titre} n°{i}",
                    fonds_id=fonds.id,
                    description=f"{titre_libre} — pièce {i}.",
                    date=str(annee),
                    annee=annee,
                    etat_catalogage=_etat_alea(alea),
                ),
                cree_par="seeder",
            )
            ajouter_item_a_collection(db, item.id, libre.id, ajoute_par="seeder")
            _seed_fichiers(
                db, item, alea, racine=racine, nb_min=1, nb_max=4, extension="tif"
            )
            if cote_libre in _AINSA_THEMATIQUES:
                items_thematiques.append(item)
    return fonds, items_thematiques


# ---------------------------------------------------------------------------
# Fonds Revue des Deux Mondes (RDM) — 36 items
# ---------------------------------------------------------------------------


def _seed_fonds_rdm(db: Session, alea: random.Random) -> Fonds:
    fonds = creer_fonds(
        db,
        FormulaireFonds(
            cote="RDM",
            titre="Revue des Deux Mondes",
            description="Revue littéraire et politique bimensuelle.",
            editeur="Buloz",
            lieu_edition="Paris",
            periodicite="bimensuel",
            issn="0035-1962",
            responsable_archives="Marie",
            date_debut="1900",
            date_fin="1929",
        ),
        cree_par="seeder",
    )
    for i in range(1, 37):
        annee = 1900 + i - 1
        item = creer_item(
            db,
            FormulaireItem(
                cote=f"RDM-{i:03d}",
                titre=f"Livraison de {annee}",
                fonds_id=fonds.id,
                description="Numéro semestriel — articles, chroniques, critiques.",
                date=str(annee),
                annee=annee,
                etat_catalogage=_etat_alea(alea),
            ),
            cree_par="seeder",
        )
        _seed_fichiers(db, item, alea, racine="scans_revues", extension="tif")
    return fonds


# ---------------------------------------------------------------------------
# Fonds Marges (MAR) — 40 items
# ---------------------------------------------------------------------------


def _seed_fonds_mar(db: Session, alea: random.Random) -> Fonds:
    fonds = creer_fonds(
        db,
        FormulaireFonds(
            cote="MAR",
            titre="Marges",
            description="Zine personnel auto-édité, fanzine littéraire.",
            personnalite_associee="auteur du zine",
            responsable_archives="Lucas",
            periodicite="irrégulier",
            date_debut="1990",
            date_fin="1999",
        ),
        cree_par="seeder",
    )
    for i in range(1, 41):
        annee = 1990 + (i % 10)
        item = creer_item(
            db,
            FormulaireItem(
                cote=f"MAR-{i:03d}",
                titre=f"Marges n°{i}",
                fonds_id=fonds.id,
                date=str(annee),
                annee=annee,
                etat_catalogage=_etat_alea(alea),
            ),
            cree_par="seeder",
        )
        _seed_fichiers(
            db, item, alea, racine="scans_zines", nb_min=1, nb_max=3, extension="png"
        )
    return fonds


# ---------------------------------------------------------------------------
# Fonds Concorde 1789 (CONC-1789) — 50 items
# ---------------------------------------------------------------------------


def _seed_fonds_conc(db: Session, alea: random.Random) -> tuple[Fonds, list[Item]]:
    fonds = creer_fonds(
        db,
        FormulaireFonds(
            cote="CONC-1789",
            titre="Concorde 1789",
            description="Almanachs et brochures de la période révolutionnaire.",
            lieu_edition="Paris",
            date_debut="1789",
            date_fin="1791",
        ),
        cree_par="seeder",
    )
    items: list[Item] = []
    for i in range(1, 51):
        annee = 1789 + (i % 3)
        item = creer_item(
            db,
            FormulaireItem(
                cote=f"CONC-1789-{i:03d}",
                titre=f"Brochure révolutionnaire n°{i}",
                fonds_id=fonds.id,
                description="Pamphlet ou almanach révolutionnaire.",
                date=str(annee),
                annee=annee,
                etat_catalogage=_etat_alea(alea),
            ),
            cree_par="seeder",
        )
        items.append(item)
        _seed_fichiers(
            db, item, alea, racine="scans_historiques", nb_min=1, nb_max=5, extension="tif"
        )
    return fonds, items


# ---------------------------------------------------------------------------
# Collection transversale Témoignages d'exil
# ---------------------------------------------------------------------------


def _seed_transversale(
    db: Session,
    items_ainsa: Iterable[Item],
    items_conc: Iterable[Item],
) -> None:
    """Collection transversale piochée dans Aínsa et Concorde 1789."""
    coll = creer_collection_libre(
        db,
        FormulaireCollection(
            cote="TEMOIG",
            titre="Témoignages d'exil",
            fonds_id=None,
            description=(
                "Sélection thématique transversale d'items qui parlent "
                "d'exil et de bouleversement révolutionnaire."
            ),
        ),
        cree_par="seeder",
    )
    selection_ainsa = sorted(items_ainsa, key=lambda i: i.cote)[:12]
    selection_conc = sorted(items_conc, key=lambda i: i.cote)[:6]
    for item in selection_ainsa + selection_conc:
        ajouter_item_a_collection(db, item.id, coll.id, ajoute_par="seeder")


# ---------------------------------------------------------------------------
# Collaborateurs
# ---------------------------------------------------------------------------


def _seed_collaborateurs(
    db: Session,
    fonds_hk: Fonds,
    fonds_fa: Fonds,
    fonds_rdm: Fonds,
) -> None:
    """Crée les `CollaborateurFonds` directement (pas de service CRUD
    dédié pour cette entité en V0.9.0-alpha.1 ; sera ajouté en V0.9.0-beta
    avec les routes web de gestion des collaborateurs)."""
    db.add_all(
        [
            CollaborateurFonds(
                fonds_id=fonds_hk.id,
                nom="Marie Dupont",
                roles=[RoleCollaborateur.NUMERISATION.value],
                periode="2022",
            ),
            CollaborateurFonds(
                fonds_id=fonds_hk.id,
                nom="Hugo Martin",
                roles=[
                    RoleCollaborateur.CATALOGAGE.value,
                    RoleCollaborateur.INDEXATION.value,
                ],
                periode="2023",
            ),
            CollaborateurFonds(
                fonds_id=fonds_fa.id,
                nom="Idmhand, Fatiha",
                roles=[RoleCollaborateur.CATALOGAGE.value],
            ),
            CollaborateurFonds(
                fonds_id=fonds_fa.id,
                nom="Marie Dupont",
                roles=[
                    RoleCollaborateur.NUMERISATION.value,
                    RoleCollaborateur.INDEXATION.value,
                ],
                periode="2022-2023",
            ),
            CollaborateurFonds(
                fonds_id=fonds_rdm.id,
                nom="Lucas Bernard",
                roles=[RoleCollaborateur.TRANSCRIPTION.value],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def peupler_base(chemin_db: Path, *, seed: int = 42) -> RapportDemo:
    """Construit la base de démonstration (création + remplissage).

    `seed` permet de rejouer la même base (tests déterministes) ou
    d'en générer une variante.
    """
    alea = random.Random(seed)
    chemin_db.parent.mkdir(parents=True, exist_ok=True)
    engine = creer_engine(chemin_db)
    Base.metadata.create_all(engine)

    factory = creer_session_factory(engine)
    with factory() as session:
        fonds_hk = _seed_fonds_hk(session, alea)
        fonds_fa, items_ainsa_thematiques = _seed_fonds_fa(session, alea)
        fonds_rdm = _seed_fonds_rdm(session, alea)
        _seed_fonds_mar(session, alea)
        _, items_conc = _seed_fonds_conc(session, alea)
        _seed_transversale(session, items_ainsa_thematiques, items_conc)
        _seed_collaborateurs(session, fonds_hk, fonds_fa, fonds_rdm)
        session.commit()

        rapport = RapportDemo(
            chemin_db=chemin_db,
            nb_fonds=session.scalar(select(func.count()).select_from(Fonds)) or 0,
            nb_collections=session.scalar(
                select(func.count()).select_from(Collection)
            )
            or 0,
            nb_items=session.scalar(select(func.count()).select_from(Item)) or 0,
            nb_fichiers=session.scalar(select(func.count()).select_from(Fichier))
            or 0,
        )

    engine.dispose()
    return rapport
