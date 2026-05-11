"""Préférences de colonnes par utilisateur+collection+vue.

V0.6.3 — onglet `items` uniquement. Les autres vues (fichiers,
sous-collections) restent sur les colonnes par défaut. Le schéma
de la table `PreferencesAffichage` est en place depuis V0.5.

Validation côté serveur : la liste reçue par POST est filtrée
contre la whitelist (colonnes dédiées + métadonnées disponibles
pour la collection). Une colonne hors whitelist est silencieusement
écartée. `cote` est obligatoire — automatiquement réinjectée si
absente.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archives_tool.models import Item, ItemCollection, PreferencesAffichage

# V0.6.3 — seul `items` est câblé. Les autres vues seront ajoutées
# avec leur propre persistance V0.7+ ; on n'élargit pas le Literal
# tant qu'aucun chemin de code ne les consomme.
Vue = Literal["items"]


# ---------------------------------------------------------------------------
# Catalogue des colonnes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColonneDisponible:
    """Métadonnées d'une colonne sélectionnable."""

    nom: str  # identifiant technique (clé de tri, attribut Python)
    label: str  # nom affiché en en-tête
    categorie: Literal["dediee", "metadonnee"]
    type_donnee: Literal["texte", "entier", "date", "etat", "liste", "calcule"]
    obligatoire: bool = False  # True pour `cote` — non décochable


COLONNES_DEFAUT_ITEMS: tuple[str, ...] = (
    "cote",
    "titre",
    "type",
    "date",
    "etat",
    "fichiers",
    "modifie",
)

COLONNES_DEDIEES_ITEMS: tuple[ColonneDisponible, ...] = (
    ColonneDisponible("cote", "Cote", "dediee", "texte", obligatoire=True),
    ColonneDisponible("titre", "Titre", "dediee", "texte"),
    ColonneDisponible("type", "Type", "dediee", "texte"),
    ColonneDisponible("date", "Date", "dediee", "date"),
    ColonneDisponible("annee", "Année", "dediee", "entier"),
    ColonneDisponible("langue", "Langue", "dediee", "texte"),
    ColonneDisponible("etat", "État", "dediee", "etat"),
    ColonneDisponible("description", "Description", "dediee", "texte"),
    ColonneDisponible("doi_nakala", "DOI Nakala", "dediee", "texte"),
    ColonneDisponible("doi_collection_nakala", "DOI collection", "dediee", "texte"),
    ColonneDisponible("fichiers", "Fichiers", "dediee", "calcule"),
    ColonneDisponible("modifie", "Modifié", "dediee", "calcule"),
)

_DEDIEES_PAR_NOM: dict[str, ColonneDisponible] = {
    c.nom: c for c in COLONNES_DEDIEES_ITEMS
}


# ---------------------------------------------------------------------------
# Préférences (lecture / écriture / reset)
# ---------------------------------------------------------------------------


@dataclass
class PreferencesColonnes:
    colonnes_ordonnees: list[str]
    par_defaut: bool  # True si rien en base, on retombe sur le défaut


def lire_preferences_colonnes(
    db: Session,
    utilisateur: str,
    collection_id: int,
    vue: Vue = "items",
) -> PreferencesColonnes:
    """Retourne les préférences sauvegardées ou les défauts."""
    row = db.scalar(
        select(PreferencesAffichage).where(
            PreferencesAffichage.utilisateur == utilisateur,
            PreferencesAffichage.collection_id == collection_id,
            PreferencesAffichage.vue == vue,
        )
    )
    if row is None:
        return PreferencesColonnes(
            colonnes_ordonnees=list(COLONNES_DEFAUT_ITEMS), par_defaut=True
        )
    return PreferencesColonnes(
        colonnes_ordonnees=list(row.colonnes_ordonnees), par_defaut=False
    )


def sauvegarder_preferences_colonnes(
    db: Session,
    utilisateur: str,
    collection_id: int,
    vue: Vue,
    colonnes: Sequence[str],
    *,
    metas_valides: set[str] | None = None,
) -> list[str]:
    """Upsert des préférences. Filtre la liste contre la whitelist.

    `metas_valides` est l'ensemble des noms de champs métadonnées
    actuellement présents dans la collection (calculés par
    `champs_metadonnees_disponibles`). Si fourni, chaque clé hors
    dédiées doit y figurer pour être conservée.

    `cote` est réinjectée en tête si absente (colonne obligatoire).
    Une liste qui ne retient rien après filtrage déclenche un retour
    aux défauts (ValueError).

    Retourne la liste effectivement sauvegardée.
    """
    autorisees: set[str] = set(_DEDIEES_PAR_NOM.keys())
    if metas_valides:
        autorisees |= metas_valides
    retenues = [c for c in colonnes if c in autorisees]
    if "cote" not in retenues:
        retenues.insert(0, "cote")
    # On dédoublonne en préservant l'ordre.
    vues: set[str] = set()
    deduped: list[str] = []
    for c in retenues:
        if c not in vues:
            vues.add(c)
            deduped.append(c)
    if not deduped:
        raise ValueError("La liste de colonnes après filtrage est vide.")

    existante = db.scalar(
        select(PreferencesAffichage).where(
            PreferencesAffichage.utilisateur == utilisateur,
            PreferencesAffichage.collection_id == collection_id,
            PreferencesAffichage.vue == vue,
        )
    )
    if existante is None:
        db.add(
            PreferencesAffichage(
                utilisateur=utilisateur,
                collection_id=collection_id,
                vue=vue,
                colonnes_ordonnees=deduped,
            )
        )
    else:
        existante.colonnes_ordonnees = deduped
    db.commit()
    return deduped


def reinitialiser_preferences_colonnes(
    db: Session,
    utilisateur: str,
    collection_id: int,
    vue: Vue = "items",
) -> None:
    """Supprime la ligne PreferencesAffichage. Le prochain `lire`
    retournera les défauts.
    """
    db.execute(
        delete(PreferencesAffichage).where(
            PreferencesAffichage.utilisateur == utilisateur,
            PreferencesAffichage.collection_id == collection_id,
            PreferencesAffichage.vue == vue,
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Catalogue dynamique (champs métadonnées présents dans la collection)
# ---------------------------------------------------------------------------


def champs_metadonnees_disponibles(
    db: Session, collection_id: int, *, limite: int = 50
) -> list[ColonneDisponible]:
    """Champs JSON `metadonnees` présents dans les items, par fréquence.

    Compte par clé non vide (les valeurs `None` ou `""` ne reflètent
    pas un champ « rempli »). Approche Python : acceptable jusqu'à
    quelques milliers d'items (~5000 × N champs ≈ ms). Au-delà,
    basculer sur SQLite JSON1 (`json_each`) — différé pour Aínsa-scale.
    """
    # `Item.metadonnees` est de type SQLAlchemy `JSON` : auto-décodé
    # en dict à la lecture (jamais de chaîne brute à parser ici).
    rows = db.execute(
        select(Item.metadonnees)
        .join(ItemCollection, ItemCollection.item_id == Item.id)
        .where(ItemCollection.collection_id == collection_id)
    ).all()
    compteurs: dict[str, int] = {}
    for (md,) in rows:
        if not isinstance(md, dict):
            continue
        for cle, valeur in md.items():
            if valeur in (None, ""):
                continue
            compteurs[cle] = compteurs.get(cle, 0) + 1
    plus_frequents = sorted(compteurs.items(), key=lambda kv: (-kv[1], kv[0]))[:limite]
    return [
        ColonneDisponible(
            nom=cle,
            label=cle,
            categorie="metadonnee",
            type_donnee="texte",
        )
        for cle, _freq in plus_frequents
    ]


def colonnes_disponibles_items(
    db: Session,
    collection_id: int,
    *,
    avec_metadonnees: bool = True,
) -> dict[str, list[ColonneDisponible]]:
    """`{'dediees': [...], 'metadonnees': [...]}` pour le panneau.

    `avec_metadonnees=False` court-circuite le scan de `Item.metadonnees`
    quand on sait que les préférences en cours ne contiennent que des
    colonnes dédiées (cas par défaut). Le panneau de configuration
    a, lui, toujours besoin de la liste complète pour proposer les
    métadonnées disponibles.
    """
    return {
        "dediees": list(COLONNES_DEDIEES_ITEMS),
        "metadonnees": (
            champs_metadonnees_disponibles(db, collection_id)
            if avec_metadonnees
            else []
        ),
    }


# ---------------------------------------------------------------------------
# Résolution : noms ordonnés → ColonneDisponible enrichies
# ---------------------------------------------------------------------------


def resoudre_colonnes_actives(
    noms_ordonnees: Sequence[str],
    disponibles: dict[str, list[ColonneDisponible]],
) -> list[ColonneDisponible]:
    """Combine la liste ordonnée des préférences avec les métadonnées
    complètes (label, type) pour produire la liste de
    `ColonneDisponible` dans l'ordre demandé.

    Ignore silencieusement les noms qui ne sont plus disponibles
    (ex. champ métadonnée disparu après un nouvel import).
    """
    par_nom: dict[str, ColonneDisponible] = {}
    for c in disponibles.get("dediees", []):
        par_nom[c.nom] = c
    for c in disponibles.get("metadonnees", []):
        # Si une dédiée porte le même nom qu'une méta (très improbable),
        # la dédiée gagne — déjà inscrite avant.
        par_nom.setdefault(c.nom, c)
    return [par_nom[nom] for nom in noms_ordonnees if nom in par_nom]


def metas_valides_pour(disponibles: dict[str, list[ColonneDisponible]]) -> set[str]:
    """Set des noms de champs métadonnées valides pour la collection."""
    return {c.nom for c in disponibles.get("metadonnees", [])}


@dataclass
class ColonnesActivesResolues:
    """Résultat de `charger_colonnes_actives` — actives + dispo bruts.

    Le champ `disponibles` est conservé pour permettre aux callers de
    réutiliser le scan déjà effectué (modale colonnes notamment).
    """

    actives: list[ColonneDisponible]
    disponibles: dict[str, list[ColonneDisponible]]


def charger_colonnes_actives(
    db: Session,
    utilisateur: str,
    collection_id: int,
    vue: Vue = "items",
) -> ColonnesActivesResolues:
    """Lit les préférences, charge les colonnes disponibles, et résout
    la liste active. Court-circuite le scan de `Item.metadonnees` quand
    les préférences ne référencent que des colonnes dédiées.
    """
    prefs = lire_preferences_colonnes(db, utilisateur, collection_id, vue)
    avec_metas = any(nom not in _DEDIEES_PAR_NOM for nom in prefs.colonnes_ordonnees)
    disponibles = colonnes_disponibles_items(
        db, collection_id, avec_metadonnees=avec_metas
    )
    actives = resoudre_colonnes_actives(prefs.colonnes_ordonnees, disponibles)
    return ColonnesActivesResolues(actives=actives, disponibles=disponibles)
