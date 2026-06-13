"""Interface en ligne de commande."""

from __future__ import annotations

import enum
from pathlib import Path

import typer

from rich.table import Table

import archives_tool.affichage.console as console_mod
from archives_tool.affichage.montrer import (
    rendu_json_collection_detail,
    rendu_json_collection_liste,
    rendu_json_fichier_detail,
    rendu_json_fonds_detail,
    rendu_json_fonds_liste,
    rendu_json_item_detail,
    rendu_text_collection_detail,
    rendu_text_collection_liste,
    rendu_text_fichier_detail,
    rendu_text_fonds_detail,
    rendu_text_fonds_liste,
    rendu_text_item_detail,
)
from archives_tool.api.services.dashboard import (
    composer_page_collection,
    composer_page_fonds,
    composer_page_item,
)
from archives_tool.api.services.fonds import lister_fonds
from archives_tool.api.services.items import (
    ItemIntrouvable,
    ItemInvalide,
    creer_items_en_serie,
    lire_item_par_cote,
    supprimer_item,
)
from sqlalchemy import func as sa_func, select as sa_select
from sqlalchemy.orm import selectinload

from archives_tool.api.services.collections import (
    CollectionIntrouvable,
    CollectionInvalide,
    FormulaireCollection,
    OperationCollectionInterdite,
    creer_collection_libre,
    lire_collection_par_cote,
    lister_collections,
    supprimer_collection_libre,
)
from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    lire_fonds_par_cote,
    supprimer_fonds,
)
from archives_tool.api.services.operations_entite import lister_suppressions
from archives_tool.api.services.nakala import (
    RafraichissementImpossible,
    RapatriementInvalide,
    rafraichir,
    rafraichir_collection,
    rapatrier,
    rapatrier_collection,
    titre_collection_nakala,
)
from archives_tool.api.services.nakala_depot import (
    DepotImpossible,
    deposer_collection,
    deposer_item,
    pousser_collection,
    pousser_item,
    publier_collection,
    publier_item,
)
from archives_tool.api.services.nakala_fichiers import (
    ComparaisonImpossible,
    comparer_fichiers_item,
)
from archives_tool.external.nakala.depot_mapper import MetaInvalide
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.config import ConfigLocale, charger_config
from archives_tool.external.nakala.client import (
    ClientLectureNakala,
    ErreurNakala,
    NakalaAccesInterdit,
    NakalaAuthRefusee,
    NakalaInjoignable,
    NakalaIntrouvable,
    normaliser_identifiant_nakala,
)
from archives_tool.external.nakala.collection import iterer_donnees_collection
from archives_tool.external.nakala.mapper import mapper_depot
from archives_tool.external.nakala.tableur import (
    lignes_niveau_donnee,
    lignes_niveau_fichier,
)
from archives_tool.external.nakala.tableur_io import ecrire_csv, ecrire_xlsx
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.exporters.dublin_core import exporter_dublin_core
from archives_tool.exporters.excel import exporter_excel
from archives_tool.exporters.nakala import exporter_nakala_csv
from archives_tool.exporters.rapport import RapportExport
from archives_tool.importers.ecrivain import RapportImport, importer as importer_profil
from archives_tool.models import (
    Collection,
    Fichier,
    Fonds,
    Item,
    PhaseChantier,
)
from archives_tool.profils import (
    ProfilInvalide,
    ProfilObsoleteV1,
    analyser_tableur,
    charger_profil,
    generer_squelette,
)
from archives_tool.demo import peupler_base
from archives_tool.derivatives import (
    RACINE_CIBLE_DEFAUT,
    generer_derives,
    nettoyer_derives,
)
from archives_tool.derivatives.affichage import (
    afficher_rapport as afficher_rapport_derives,
)
from archives_tool.qa import (
    composer_perimetre,
    executer_controles,
    formatter_rapport_json,
    formatter_rapport_text,
)
from archives_tool.renamer import (
    Perimetre,
    annuler_batch,
    construire_plan,
    executer_plan,
    formatter_annulation_json,
    formatter_execution_json,
    formatter_historique_json,
    formatter_plan_json,
)
from archives_tool.renamer.affichage import (
    afficher_annulation,
    afficher_execution,
    afficher_plan,
)
from archives_tool.renamer.historique import lister_batchs

app = typer.Typer(
    help="Outil de gestion de collections numérisées.",
    no_args_is_help=True,
)


@app.callback()
def _callback() -> None:
    """Callback racine (sans option), nécessaire à Typer pour préserver
    l'aide en arborescence et la structure en sous-commandes (`importer`,
    `exporter`, `montrer ...`). Ne pas retirer même quand plusieurs
    commandes coexistent au niveau racine — il garantit que Typer
    rend le help de manière cohérente."""


def _charger_config_ou_sortie(chemin: Path) -> ConfigLocale:
    try:
        return charger_config(chemin)
    except FileNotFoundError as e:
        typer.echo(f"Erreur : config introuvable ({chemin}) : {e}", err=True)
        raise typer.Exit(2) from None
    except Exception as e:
        typer.echo(f"Erreur config : {e}", err=True)
        raise typer.Exit(2) from None


# ---------------------------------------------------------------------------
# Helpers partagés par les sous-groupes `exporter` et `collections`.
# Hissés ici pour être disponibles avant la déclaration des commandes
# (les `typer.Option(default=_DB_PATH_OPTION)` sont évalués à la
# définition, pas à l'appel).
# ---------------------------------------------------------------------------


def _ouvrir_session_existante(db_path: Path):
    """Ouvre une session sur une base SQLite **existante** (Exit 2 si
    le fichier est absent). À utiliser pour les commandes lecture/
    export ou mutations qui supposent que la base existe — différent
    de `archives-tool importer` qui peut créer la base à la volée."""
    if not db_path.is_file():
        typer.echo(f"Erreur : base introuvable ({db_path}).", err=True)
        raise typer.Exit(2)
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    return factory()


def _resoudre_fonds_ou_sortie(session, cote: str | None) -> Fonds | None:
    """Résout `--fonds COTE` en `Fonds` (ou None si cote absente).
    Sortie code 1 + message stderr si la cote est inconnue."""
    if cote is None:
        return None
    try:
        return lire_fonds_par_cote(session, cote)
    except FondsIntrouvable:
        typer.echo(f"Erreur : fonds {cote!r} introuvable.", err=True)
        raise typer.Exit(1) from None


_DB_PATH_OPTION = typer.Option(
    Path("data/archives.db"), "--db-path", help="Chemin de la base SQLite."
)


class _FormatRapport(str, enum.Enum):
    """Formats de sortie partagés par `controler` et `montrer`. Typer
    reconnaît les `Enum(str, ...)` et génère un Choice automatiquement."""

    TEXT = "text"
    JSON = "json"


def _afficher_rapport(rapport: RapportImport, verbose: bool) -> None:
    mode = "DRY-RUN" if rapport.dry_run else "RÉEL"
    typer.echo(f"Import {mode} — durée {rapport.duree_secondes:.2f}s")
    if rapport.fonds_cote:
        verbe = "créé" if rapport.fonds_cree else "existant"
        suffixe = " + miroir personnalisée" if rapport.miroir_personnalisee else ""
        typer.echo(f"  Fonds {rapport.fonds_cote} ({verbe}){suffixe}")
    typer.echo(f"  Items créés : {rapport.items_crees}")
    typer.echo(f"  Fichiers ajoutés : {rapport.fichiers_ajoutes}")
    if rapport.batch_id:
        typer.echo(f"  batch_id : {rapport.batch_id}")

    if rapport.erreurs:
        typer.echo("\nErreurs :", err=True)
        for e in rapport.erreurs:
            typer.echo(f"  - {e}", err=True)

    # Affichage agrégé des divergences (V0.9.2-import T6) — toujours
    # visible (même sans --verbose), c'est un signal utile pour
    # corriger le mapping. La flat list `warnings` reste réservée au
    # mode verbose pour les autres avertissements.
    if rapport.divergences_aggregees:
        typer.echo(
            f"\n{len(rapport.divergences_aggregees)} colonne(s) à reclasser "
            "(valeurs ignorées à la fusion par cote) :"
        )
        for d in rapport.divergences_aggregees:
            prefixe = "metadonnees." if d.niveau == "metadonnees" else ""
            exemples = ", ".join(d.exemples_valeurs[:3])
            typer.echo(
                f"  - {prefixe}{d.champ} : {d.nb_cotes_affectees} cote(s) "
                f"affectée(s), {d.nb_divergences} valeur(s) ignorée(s)"
                f"{' (ex. ' + exemples + ')' if exemples else ''}"
            )

    if verbose:
        # Warnings non-divergences (fichiers orphelins, ordre_depuis_nom
        # qui ne matche pas, etc.). Filtrer les divergences déjà
        # résumées au-dessus pour éviter le bruit. Marqueur partagé
        # avec le producteur dans `importers.ecrivain`.
        from archives_tool.importers.ecrivain import (
            MARQUEUR_WARNING_DIVERGENCE,
        )

        autres = [
            w for w in rapport.warnings
            if MARQUEUR_WARNING_DIVERGENCE not in w
        ]
        if autres:
            typer.echo("\nWarnings :")
            for w in autres:
                typer.echo(f"  - {w}")
        if rapport.lignes_ignorees:
            typer.echo("\nLignes ignorées :")
            for n, raison in rapport.lignes_ignorees:
                typer.echo(f"  - ligne {n}: {raison}")
        if rapport.fichiers_orphelins:
            typer.echo("\nFichiers orphelins (sur disque, pas référencés) :")
            for f in rapport.fichiers_orphelins:
                typer.echo(f"  - {f}")


@app.command("importer")
def cmd_importer(
    chemin_profil: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Chemin du profil YAML à importer.",
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Dry-run par défaut : aucune écriture, rapport simulé.",
    ),
    utilisateur: str = typer.Option(
        None,
        "--utilisateur",
        help="Nom à inscrire en cree_par. Sinon lu dans la config locale.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose/--quiet",
        help="Affiche warnings, lignes ignorées et fichiers orphelins.",
    ),
    db_path: Path = typer.Option(
        Path("data/archives.db"),
        "--db-path",
        help="Chemin de la base SQLite.",
    ),
    config_path: Path = typer.Option(
        Path("config_local.yaml"),
        "--config",
        help="Chemin de la config locale (racines + identité).",
    ),
) -> None:
    """Importer un profil YAML v2 en base (dry-run par défaut).

    Les profils v1 (avec section `collection:` racine) sont rejetés
    avec un message de migration vers v2 et exit code 2.
    """
    config = _charger_config_ou_sortie(config_path)

    try:
        profil = charger_profil(chemin_profil)
    except ProfilObsoleteV1 as e:
        # Exit code 2 distinct pour signaler explicitement le format
        # obsolète (vs. erreur de validation v2 qui exit aussi avec 2).
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from None
    except ProfilInvalide as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from None

    nom = utilisateur if utilisateur is not None else config.utilisateur

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        rapport = importer_profil(
            profil,
            chemin_profil,
            session,
            config,
            dry_run=dry_run,
            cree_par=nom,
        )

    _afficher_rapport(rapport, verbose)
    raise typer.Exit(1 if rapport.erreurs else 0)


# ---------------------------------------------------------------------------
# Commande `reindexer` : rebuild des tables FTS5 de recherche
# ---------------------------------------------------------------------------


@app.command("reindexer")
def cmd_reindexer(
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Reconstruit les tables FTS5 (`item_fts`, `fonds_fts`, `collection_fts`).

    Utile principalement pour :
    - Une base ancienne (pré-V0.9.3) qui n'avait pas encore l'index FTS.
    - Une base restaurée depuis une sauvegarde sans les tables FTS.
    - Diagnostic d'un index potentiellement désynchronisé.

    Idempotent : peut être relancé sans risque (vide puis repeuple).
    Le coût est ~1 seconde pour ~10 000 items. L'index est ensuite
    maintenu automatiquement par les triggers SQL — pas besoin de
    relancer après chaque modification.
    """
    from archives_tool.db import assurer_tables_fts, reindexer_fts

    if not db_path.is_file():
        typer.echo(f"Erreur : base introuvable ({db_path}).", err=True)
        raise typer.Exit(2)
    engine = creer_engine(db_path)
    assurer_tables_fts(engine)  # crée si absentes
    counts = reindexer_fts(engine)
    engine.dispose()
    typer.echo(
        f"Réindexation terminée : "
        f"{counts.get('item', 0)} items, "
        f"{counts.get('fonds', 0)} fonds, "
        f"{counts.get('collection', 0)} collections."
    )


# ---------------------------------------------------------------------------
# Commande `exporter`
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Sous-groupe `exporter` : Dublin Core / Nakala / xlsx.
# Granularité = la collection (miroir, libre rattachée, transversale).
# ---------------------------------------------------------------------------

exporter_app = typer.Typer(
    help="Exporter une collection vers un format externe.",
    no_args_is_help=True,
)
app.add_typer(exporter_app, name="exporter")


def _resoudre_collection_pour_export(
    session, cote: str, fonds_cote: str | None
) -> Collection:
    """Charge une collection par cote, avec désambiguïsation `--fonds COTE`.
    Sortie code 1 + message stderr si la collection est inconnue ou
    ambiguë."""
    fonds_obj = _resoudre_fonds_ou_sortie(session, fonds_cote)
    fonds_id = fonds_obj.id if fonds_obj else None
    try:
        return lire_collection_par_cote(session, cote, fonds_id=fonds_id)
    except CollectionIntrouvable:
        typer.echo(f"Erreur : collection {cote!r} introuvable.", err=True)
        raise typer.Exit(1) from None


def _afficher_rapport_export(rapport: RapportExport, verbose: bool) -> None:
    """Affiche le résumé d'un export sur stdout (incomplets sur stderr).
    `verbose=True` détaille les items incomplets ligne par ligne."""
    typer.echo(
        f"Export {rapport.format} — {rapport.nb_items_selectionnes} items, "
        f"{rapport.nb_fichiers_selectionnes} fichiers — "
        f"{rapport.duree_secondes:.2f}s"
    )
    if rapport.chemin_sortie:
        typer.echo(f"  Sortie : {rapport.chemin_sortie}")
    if rapport.items_incomplets:
        typer.echo(f"  ⚠ Items incomplets : {len(rapport.items_incomplets)}", err=True)
        if verbose:
            for cote, manques in rapport.items_incomplets:
                typer.echo(f"    - {cote} : manque {', '.join(manques)}", err=True)


@exporter_app.command("dublin-core")
def cmd_exporter_dublin_core(
    cote: str = typer.Argument(..., help="Cote de la collection à exporter."),
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help="Cote du fonds parent (pour désambiguïser une cote partagée).",
    ),
    sortie: Path | None = typer.Option(
        None,
        "--sortie",
        "-o",
        help="Chemin du fichier XML (défaut : <cote>_dc.xml dans le cwd).",
    ),
    verbose: bool = typer.Option(False, "--verbose/--quiet"),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Exporte une collection en Dublin Core XML (un fichier agrégé)."""
    chemin = sortie or Path.cwd() / f"{cote}_dc.xml"
    with _ouvrir_session_existante(db_path) as session:
        collection = _resoudre_collection_pour_export(session, cote, fonds)
        rapport = exporter_dublin_core(session, collection, chemin)
    _afficher_rapport_export(rapport, verbose)


@exporter_app.command("nakala")
def cmd_exporter_nakala(
    cote: str = typer.Argument(..., help="Cote de la collection à exporter."),
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help="Cote du fonds parent (pour désambiguïser une cote partagée).",
    ),
    sortie: Path | None = typer.Option(
        None,
        "--sortie",
        "-o",
        help="Chemin du fichier CSV (défaut : <cote>_nakala.csv dans le cwd).",
    ),
    licence: str = typer.Option(
        "CC-BY-NC-ND-4.0", "--licence", help="Licence par défaut."
    ),
    statut: str = typer.Option("pending", "--statut", help="Statut par défaut."),
    verbose: bool = typer.Option(False, "--verbose/--quiet"),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Exporte une collection en CSV de dépôt bulk Nakala."""
    chemin = sortie or Path.cwd() / f"{cote}_nakala.csv"
    with _ouvrir_session_existante(db_path) as session:
        collection = _resoudre_collection_pour_export(session, cote, fonds)
        rapport = exporter_nakala_csv(
            session,
            collection,
            chemin,
            licence_defaut=licence,
            statut_defaut=statut,
        )
    _afficher_rapport_export(rapport, verbose)


@exporter_app.command("xlsx")
def cmd_exporter_xlsx(
    cote: str = typer.Argument(..., help="Cote de la collection à exporter."),
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help="Cote du fonds parent (pour désambiguïser une cote partagée).",
    ),
    sortie: Path | None = typer.Option(
        None,
        "--sortie",
        "-o",
        help="Chemin du fichier xlsx (défaut : <cote>.xlsx dans le cwd).",
    ),
    verbose: bool = typer.Option(False, "--verbose/--quiet"),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Exporte une collection en xlsx pour catalogage manuel."""
    chemin = sortie or Path.cwd() / f"{cote}.xlsx"
    with _ouvrir_session_existante(db_path) as session:
        collection = _resoudre_collection_pour_export(session, cote, fonds)
        rapport = exporter_excel(session, collection, chemin)
    _afficher_rapport_export(rapport, verbose)


@exporter_app.command("annotations")
def cmd_exporter_annotations(
    cote: str = typer.Argument(..., help="Cote de la collection à exporter."),
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help="Cote du fonds parent (pour désambiguïser une cote partagée).",
    ),
    sortie: Path | None = typer.Option(
        None,
        "--sortie",
        "-o",
        help=(
            "Chemin du fichier JSON-LD W3C (défaut : "
            "<cote>_annotations.json dans le cwd)."
        ),
    ),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Exporte les annotations IIIF d'une collection en W3C
    AnnotationCollection JSON-LD (V0.9.7 δ).

    Format conforme à la spec W3C Web Annotation Data Model et à
    IIIF Presentation API 3. Fichier à déposer à côté des images
    sur Nakala et à référencer dans le manifeste IIIF de l'item /
    collection. Réversible vers Mirador, Recogito ou tout autre
    viewer standard.

    Un seul AnnotationPage (acceptable jusqu'à qq milliers
    d'annotations). Au-delà, paginer par canvas (lot futur).
    """
    import json

    from archives_tool.api.services.annotations import (
        lister_annotations_collection,
        serialiser_annotation_collection_w3c,
    )

    chemin = sortie or Path.cwd() / f"{cote}_annotations.json"
    with _ouvrir_session_existante(db_path) as session:
        collection = _resoudre_collection_pour_export(session, cote, fonds)
        annotations = lister_annotations_collection(session, collection.id)
        # URI canonique : DOI Nakala si publié, sinon URI relative locale.
        # Une fois Nakala dépôt fait, on peut re-générer le JSON avec
        # le vrai DOI à la place — le fichier d'export reflète la
        # réalité au moment de l'export.
        collection_id_uri = (
            collection.doi_nakala
            if collection.doi_nakala
            else f"/api/collections/{collection.cote}/annotations"
        )
        payload = serialiser_annotation_collection_w3c(
            list(annotations),
            label=f"Annotations de {collection.titre}",
            collection_id_uri=collection_id_uri,
        )
    chemin.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    typer.echo(
        f"✓ {len(annotations)} annotation(s) exportée(s) vers {chemin}"
    )


# ---------------------------------------------------------------------------
# Sous-groupe `montrer` : commandes de visualisation en lecture seule.
# ---------------------------------------------------------------------------

montrer = typer.Typer(
    help="Visualiser collections, items et fichiers en base.",
    no_args_is_help=True,
)
app.add_typer(montrer, name="montrer")


@montrer.command("fonds")
def cmd_montrer_fonds(
    cote: str | None = typer.Option(
        None, "--cote", "-c", help="Cote du fonds. Sans cote : liste tous les fonds."
    ),
    format_sortie: _FormatRapport = typer.Option(_FormatRapport.TEXT, "--format"),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Afficher un fonds (liste sans --cote, détail avec --cote)."""
    with _ouvrir_session_existante(db_path) as session:
        if cote is None:
            fonds_list = lister_fonds(session)
            sortie = (
                rendu_json_fonds_liste(fonds_list)
                if format_sortie is _FormatRapport.JSON
                else rendu_text_fonds_liste(fonds_list)
            )
        else:
            try:
                detail = composer_page_fonds(session, cote)
            except FondsIntrouvable:
                typer.echo(f"Erreur : fonds {cote!r} introuvable.", err=True)
                raise typer.Exit(1) from None
            sortie = (
                rendu_json_fonds_detail(detail)
                if format_sortie is _FormatRapport.JSON
                else rendu_text_fonds_detail(detail)
            )
    typer.echo(sortie)


@montrer.command("collection")
def cmd_montrer_collection(
    cote: str | None = typer.Option(
        None, "--cote", "-c", help="Cote de la collection. Sans cote : liste."
    ),
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help="Cote du fonds (filtre la liste, ou désambiguïse une cote partagée).",
    ),
    format_sortie: _FormatRapport = typer.Option(_FormatRapport.TEXT, "--format"),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Afficher les collections (liste ou détail)."""
    with _ouvrir_session_existante(db_path) as session:
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        fonds_id = fonds_obj.id if fonds_obj else None
        if cote is None:
            collections = lister_collections(session, fonds_id=fonds_id)
            sortie = (
                rendu_json_collection_liste(collections)
                if format_sortie is _FormatRapport.JSON
                else rendu_text_collection_liste(collections)
            )
        else:
            try:
                col = lire_collection_par_cote(session, cote, fonds_id=fonds_id)
            except CollectionIntrouvable:
                typer.echo(f"Erreur : collection {cote!r} introuvable.", err=True)
                raise typer.Exit(1) from None
            detail = composer_page_collection(session, col)
            sortie = (
                rendu_json_collection_detail(detail)
                if format_sortie is _FormatRapport.JSON
                else rendu_text_collection_detail(detail)
            )
    typer.echo(sortie)


@montrer.command("item")
def cmd_montrer_item(
    cote_item: str = typer.Argument(..., help="Cote de l'item."),
    fonds: str = typer.Option(
        ...,
        "--fonds",
        "-f",
        help="Cote du fonds (obligatoire — la cote item n'est unique que par fonds).",
    ),
    format_sortie: _FormatRapport = typer.Option(_FormatRapport.TEXT, "--format"),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Afficher la fiche détaillée d'un item."""
    with _ouvrir_session_existante(db_path) as session:
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        try:
            detail = composer_page_item(session, cote_item, fonds_obj)
        except ItemIntrouvable:
            typer.echo(
                f"Erreur : item {cote_item!r} introuvable dans le fonds {fonds}.",
                err=True,
            )
            raise typer.Exit(1) from None
        sortie = (
            rendu_json_item_detail(detail)
            if format_sortie is _FormatRapport.JSON
            else rendu_text_item_detail(detail)
        )
    typer.echo(sortie)


@montrer.command("fichier")
def cmd_montrer_fichier(
    fichier_id: int = typer.Argument(..., help="ID numérique du fichier."),
    format_sortie: _FormatRapport = typer.Option(_FormatRapport.TEXT, "--format"),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Afficher la fiche détaillée d'un fichier (par id global)."""
    with _ouvrir_session_existante(db_path) as session:
        # Eager loading explicite : le rendu lit `fichier.item.fonds`
        # et `fichier.operations`. Sans ces options, 3 SELECT lazy
        # supplémentaires seraient émis pendant le rendu.
        fichier = session.scalar(
            sa_select(Fichier)
            .options(
                selectinload(Fichier.item).selectinload(Item.fonds),
                selectinload(Fichier.operations),
            )
            .where(Fichier.id == fichier_id)
        )
        if fichier is None:
            typer.echo(f"Erreur : fichier id={fichier_id} introuvable.", err=True)
            raise typer.Exit(1)
        sortie = (
            rendu_json_fichier_detail(fichier)
            if format_sortie is _FormatRapport.JSON
            else rendu_text_fichier_detail(fichier)
        )
    typer.echo(sortie)


def _resume_cascade_court(type_entite: str, cascade: dict) -> str:
    """Résumé d'une ligne pour la colonne Cascade du tableau text."""
    if type_entite == "fonds":
        return (
            f"{cascade.get('items', 0)} items, "
            f"{cascade.get('fichiers', 0)} fic., "
            f"{cascade.get('collections_detachees', 0)} libre(s) détachée(s)"
        )
    if type_entite == "collection":
        return f"{cascade.get('junctions', 0)} lien(s)"
    if type_entite == "item":
        return (
            f"{cascade.get('fichiers', 0)} fic., "
            f"{cascade.get('annotations', 0)} annot."
        )
    return ""


@montrer.command("suppressions")
def cmd_montrer_suppressions(
    type_entite: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filtrer : fonds | collection | item (sinon : tout).",
    ),
    limite: int = typer.Option(
        100, "--limite", "-n", help="Nombre maximum de lignes."
    ),
    format_sortie: _FormatRapport = typer.Option(_FormatRapport.TEXT, "--format"),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Lister les suppressions d'entités journalisées (les plus récentes
    d'abord). Lecture seule."""
    import json

    valides = {"fonds", "collection", "item"}
    if type_entite is not None and type_entite not in valides:
        typer.echo(
            f"Erreur : --type doit valoir {', '.join(sorted(valides))}.", err=True
        )
        raise typer.Exit(2)

    with _ouvrir_session_existante(db_path) as session:
        ops = lister_suppressions(session, type_entite=type_entite, limite=limite)

        if format_sortie is _FormatRapport.JSON:
            charge = [
                {
                    "id": o.id,
                    "type_entite": o.type_entite,
                    "entite_id": o.entite_id,
                    "cote": o.cote,
                    "fonds_cote": o.fonds_cote,
                    "titre": o.titre,
                    "execute_le": o.execute_le.isoformat() if o.execute_le else None,
                    "execute_par": o.execute_par,
                    "cascade": json.loads(o.cascade_resume)
                    if o.cascade_resume
                    else None,
                }
                for o in ops
            ]
            typer.echo(json.dumps(charge, ensure_ascii=False, indent=2))
            return

        if not ops:
            typer.echo("Aucune suppression journalisée.")
            return

        table = Table(title="Suppressions journalisées")
        table.add_column("Date")
        table.add_column("Type")
        table.add_column("Cote")
        table.add_column("Fonds")
        table.add_column("Par")
        table.add_column("Cascade")
        for o in ops:
            cascade = json.loads(o.cascade_resume) if o.cascade_resume else {}
            table.add_row(
                o.execute_le.strftime("%Y-%m-%d %H:%M") if o.execute_le else "—",
                o.type_entite,
                o.cote or "—",
                o.fonds_cote or "—",
                o.execute_par or "—",
                _resume_cascade_court(o.type_entite, cascade),
            )
        console_mod.console.print(table)


# ---------------------------------------------------------------------------
# Commande `controler` : contrôles de cohérence base/disque (lecture seule).
# ---------------------------------------------------------------------------


@app.command("controler")
def cmd_controler(
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help="Cote du fonds à contrôler (sinon : base entière).",
    ),
    collection: str | None = typer.Option(
        None,
        "--collection",
        "-c",
        help="Cote de la collection à contrôler (sinon : base entière).",
    ),
    format_sortie: _FormatRapport = typer.Option(
        _FormatRapport.TEXT,
        "--format",
        help="Format de sortie.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit 1 dès qu'il y a un problème (avertissement compris).",
    ),
    max_exemples: int = typer.Option(
        5,
        "--max-exemples",
        help="Nombre maximum d'exemples affichés par contrôle (text).",
    ),
    db_path: Path = _DB_PATH_OPTION,
    config_path: Path = typer.Option(
        Path("config_local.yaml"),
        "--config",
        help=(
            "Config locale (racines). Optionnelle : sans elle, "
            "FILE-MISSING signale les racines comme non configurées."
        ),
    ),
) -> None:
    """Contrôler la cohérence d'une base archives-tool (lecture seule)."""
    if fonds and collection:
        typer.echo(
            "Erreur : --fonds et --collection sont mutuellement exclusifs.",
            err=True,
        )
        raise typer.Exit(2)

    racines: dict[str, Path] = {}
    try:
        config = charger_config(config_path)
        racines = dict(config.racines)
    except FileNotFoundError:
        if format_sortie is _FormatRapport.TEXT:
            typer.echo(
                f"Config absente ({config_path}) : "
                "FILE-MISSING signalera les racines non configurées.",
                err=True,
            )
    except Exception as e:
        typer.echo(f"Config invalide : {e}", err=True)
        raise typer.Exit(2) from None

    with _ouvrir_session_existante(db_path) as session:
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        fonds_id = fonds_obj.id if fonds_obj else None
        collection_id: int | None = None
        if collection:
            try:
                col = lire_collection_par_cote(session, collection, fonds_id=fonds_id)
            except CollectionIntrouvable:
                typer.echo(
                    f"Erreur : collection {collection!r} introuvable.",
                    err=True,
                )
                raise typer.Exit(1) from None
            collection_id = col.id
            fonds_id = None  # collection prend le pas

        perimetre = composer_perimetre(
            session, fonds_id=fonds_id, collection_id=collection_id
        )
        rapport = executer_controles(session, perimetre, racines=racines)

    if format_sortie is _FormatRapport.JSON:
        typer.echo(formatter_rapport_json(rapport))
    else:
        typer.echo(formatter_rapport_text(rapport, max_exemples=max_exemples))

    if rapport.nb_erreurs > 0:
        raise typer.Exit(1)
    if strict and (rapport.nb_avertissements > 0 or rapport.nb_infos > 0):
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Sous-groupe `deriver` : génération de vignettes et aperçus.
# ---------------------------------------------------------------------------

deriver = typer.Typer(
    help="Générer ou nettoyer les dérivés (vignettes, aperçus).",
    no_args_is_help=True,
)
app.add_typer(deriver, name="deriver")


def _construire_perimetre_cli(
    fonds: str | None,
    collection: str | None,
    item: str | None,
    fichier_id: list[int] | None,
) -> Perimetre:
    """Construit un `Perimetre` à partir des 4 options CLI mutuellement
    exclusives partagées par `archives-tool renommer` et `deriver`.
    Sortie code 2 si la combinaison est invalide.

    Convention : --fonds (seul) cible tous les fichiers d'un fonds ;
    --fonds combiné à --collection ou --item désambiguïse une cote
    partagée entre fonds.
    """
    fonds_seul = (
        fonds if collection is None and item is None and not fichier_id else None
    )
    try:
        return Perimetre(
            fonds_cote=fonds_seul,
            collection_cote=collection,
            collection_fonds_cote=fonds if collection is not None else None,
            item_cote=item,
            item_fonds_cote=fonds if item is not None else None,
            fichier_ids=tuple(fichier_id) if fichier_id else (),
        )
    except ValueError as e:
        typer.echo(f"Erreur : {e}", err=True)
        raise typer.Exit(2) from None


@deriver.command("appliquer")
def cmd_deriver_appliquer(
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help=(
            "Cote du fonds. Avec --collection ou --item : désambiguïse "
            "la cote partagée. Seul : couvre tous les fichiers du fonds."
        ),
    ),
    collection: str | None = typer.Option(
        None, "--collection", "-c", help="Cote de la collection à cibler."
    ),
    item: str | None = typer.Option(
        None, "--item", "-i", help="Cote de l'item à cibler."
    ),
    fichier_id: list[int] = typer.Option(
        None, "--fichier-id", help="ID(s) de fichier à cibler (option répétable)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Régénérer même si derive_genere est déjà True."
    ),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run"),
    racine_cible: str = typer.Option(
        RACINE_CIBLE_DEFAUT,
        "--racine-cible",
        help="Racine logique où écrire les dérivés.",
    ),
    db_path: Path = _DB_PATH_OPTION,
    config_path: Path = typer.Option(Path("config_local.yaml"), "--config"),
) -> None:
    """Générer les dérivés des fichiers ciblés.

    Périmètre : exactement un de --fonds (seul), --collection, --item
    ou --fichier-id (multiple).
    """
    perimetre = _construire_perimetre_cli(fonds, collection, item, fichier_id)
    config = _charger_config_ou_sortie(config_path)

    with _ouvrir_session_existante(db_path) as session:
        try:
            rapport = generer_derives(
                session,
                perimetre=perimetre,
                racines=dict(config.racines),
                racine_cible=racine_cible,
                force=force,
                dry_run=dry_run,
            )
        except (FondsIntrouvable, CollectionIntrouvable) as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None

    afficher_rapport_derives(rapport)
    raise typer.Exit(1 if rapport.nb_erreurs else 0)


@deriver.command("nettoyer")
def cmd_deriver_nettoyer(
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help=(
            "Cote du fonds. Avec --collection ou --item : désambiguïse "
            "la cote partagée. Seul : couvre tous les fichiers du fonds."
        ),
    ),
    collection: str | None = typer.Option(
        None, "--collection", "-c", help="Cote de la collection à cibler."
    ),
    item: str | None = typer.Option(
        None, "--item", "-i", help="Cote de l'item à cibler."
    ),
    fichier_id: list[int] = typer.Option(
        None, "--fichier-id", help="ID(s) de fichier à cibler (option répétable)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run"),
    racine_cible: str = typer.Option(RACINE_CIBLE_DEFAUT, "--racine-cible"),
    db_path: Path = _DB_PATH_OPTION,
    config_path: Path = typer.Option(Path("config_local.yaml"), "--config"),
) -> None:
    """Supprimer les dérivés des fichiers ciblés.

    Périmètre : exactement un de --fonds (seul), --collection, --item
    ou --fichier-id (multiple).
    """
    perimetre = _construire_perimetre_cli(fonds, collection, item, fichier_id)
    config = _charger_config_ou_sortie(config_path)

    with _ouvrir_session_existante(db_path) as session:
        try:
            rapport = nettoyer_derives(
                session,
                perimetre=perimetre,
                racines=dict(config.racines),
                racine_cible=racine_cible,
                dry_run=dry_run,
            )
        except (FondsIntrouvable, CollectionIntrouvable) as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None

    afficher_rapport_derives(rapport)


# ---------------------------------------------------------------------------
# Sous-groupe `renommer` : renommage transactionnel.
# ---------------------------------------------------------------------------

renommer = typer.Typer(
    help="Renommer des fichiers, annuler un batch, voir l'historique.",
    no_args_is_help=True,
)
app.add_typer(renommer, name="renommer")


@renommer.command("appliquer")
def cmd_renommer_appliquer(
    template: str = typer.Option(
        ...,
        "--template",
        help='Template au format Python (ex. "{cote}-{ordre:02d}.{ext}").',
    ),
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help=(
            "Cote du fonds. Avec --collection ou --item : désambiguïse "
            "la cote partagée. Seul : renomme tous les fichiers du fonds."
        ),
    ),
    collection: str | None = typer.Option(
        None,
        "--collection",
        "-c",
        help="Cote de la collection à cibler.",
    ),
    item: str | None = typer.Option(
        None,
        "--item",
        "-i",
        help="Cote de l'item à cibler.",
    ),
    fichier_id: list[int] = typer.Option(
        None,
        "--fichier-id",
        help="ID(s) de fichier à cibler (option répétable).",
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Dry-run par défaut : aperçu sans toucher aux fichiers.",
    ),
    utilisateur: str = typer.Option(
        None,
        "--utilisateur",
        help="Nom à inscrire en execute_par. Sinon lu dans la config locale.",
    ),
    limite: int = typer.Option(
        50, "--limite", help="Lignes max affichées (0 = illimité)."
    ),
    format_sortie: _FormatRapport = typer.Option(
        _FormatRapport.TEXT,
        "--format",
        help="Format de sortie : 'text' (Rich) ou 'json'.",
    ),
    db_path: Path = _DB_PATH_OPTION,
    config_path: Path = typer.Option(Path("config_local.yaml"), "--config"),
) -> None:
    """Construire un plan de renommage et l'appliquer (dry-run par défaut).

    Périmètre : exactement un de --fonds (seul), --collection,
    --item, ou --fichier-id (multiple). Pour les cotes de collection
    ou d'item partagées entre fonds, --fonds peut accompagner
    --collection ou --item pour désambiguïser.
    """
    perimetre = _construire_perimetre_cli(fonds, collection, item, fichier_id)
    config = _charger_config_ou_sortie(config_path)
    nom = utilisateur if utilisateur is not None else config.utilisateur
    racines = dict(config.racines)

    with _ouvrir_session_existante(db_path) as session:
        try:
            plan = construire_plan(
                session,
                template=template,
                racines=racines,
                perimetre=perimetre,
            )
        except (FondsIntrouvable, CollectionIntrouvable) as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None

        if format_sortie is _FormatRapport.JSON:
            typer.echo(formatter_plan_json(plan))
        else:
            afficher_plan(plan, limite=limite)
        if not plan.applicable:
            raise typer.Exit(1)
        if plan.nb_renommages == 0:
            raise typer.Exit(0)

        rap = executer_plan(
            session,
            plan,
            racines=racines,
            dry_run=dry_run,
            execute_par=nom,
        )
        if format_sortie is _FormatRapport.JSON:
            typer.echo(formatter_execution_json(rap))
        else:
            afficher_execution(rap)
        raise typer.Exit(1 if rap.erreurs else 0)


@renommer.command("annuler")
def cmd_renommer_annuler(
    batch_id: str = typer.Option(..., "--batch-id", help="UUID du batch à annuler."),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    utilisateur: str = typer.Option(None, "--utilisateur"),
    format_sortie: _FormatRapport = typer.Option(
        _FormatRapport.TEXT,
        "--format",
        help="Format de sortie : 'text' (Rich) ou 'json'.",
    ),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
    config_path: Path = typer.Option(Path("config_local.yaml"), "--config"),
) -> None:
    """Annuler un batch de renommage déjà appliqué."""
    config = _charger_config_ou_sortie(config_path)
    nom = utilisateur if utilisateur is not None else config.utilisateur
    racines = dict(config.racines)

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        rap = annuler_batch(
            session, batch_id, racines=racines, dry_run=dry_run, execute_par=nom
        )
    if format_sortie is _FormatRapport.JSON:
        typer.echo(formatter_annulation_json(rap))
    else:
        afficher_annulation(rap)
    raise typer.Exit(1 if rap.erreurs else 0)


@renommer.command("historique")
def cmd_renommer_historique(
    limite: int = typer.Option(50, "--limite", help="Nombre de batchs à afficher."),
    format_sortie: _FormatRapport = typer.Option(
        _FormatRapport.TEXT,
        "--format",
        help="Format de sortie : 'text' (Rich) ou 'json'.",
    ),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
) -> None:
    """Afficher les derniers batchs de renommage."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        entrees = lister_batchs(session, limite=limite)

    if format_sortie is _FormatRapport.JSON:
        typer.echo(formatter_historique_json(entrees))
        return

    if not entrees:
        console_mod.console.print(
            "[avertissement]Aucun batch dans l'historique.[/avertissement]"
        )
        return

    table = Table(show_header=True, header_style="sous_titre", expand=False)
    table.add_column("Batch")
    table.add_column("Date")
    table.add_column("Par")
    table.add_column("Ops")
    table.add_column("Types")
    table.add_column("Annulé")
    for e in entrees:
        date_str = (
            e.execute_le_premier.strftime("%Y-%m-%d %H:%M")
            if e.execute_le_premier
            else "—"
        )
        annule = (
            f"[avertissement]oui ({e.annule_par_batch_id[:8]}…)[/avertissement]"
            if e.annule and e.annule_par_batch_id
            else ""
        )
        table.add_row(
            e.batch_id,
            date_str,
            e.execute_par or "—",
            str(e.nb_operations),
            ", ".join(e.types_operations),
            annule,
        )
    console_mod.console.print(table)


# ---------------------------------------------------------------------------
# Sous-groupe `profil` : aide à la création de profils d'import.
# ---------------------------------------------------------------------------

profil_app = typer.Typer(
    help="Créer ou analyser un profil d'import YAML.",
    no_args_is_help=True,
)
app.add_typer(profil_app, name="profil")


def _refuser_ecrasement(chemin: Path, force: bool) -> None:
    """Quitte avec un code 1 si `chemin` existe et que `force` est faux."""
    if chemin.exists() and not force:
        typer.echo(
            f"Erreur : {chemin} existe déjà. Utilisez --force pour écraser.",
            err=True,
        )
        raise typer.Exit(1)


def _ecrire_profil(contenu: str, sortie: Path, force: bool, vers_stdout: bool) -> None:
    if vers_stdout:
        typer.echo(contenu, nl=False)
        return
    _refuser_ecrasement(sortie, force)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(contenu, encoding="utf-8")


@profil_app.command("init")
def cmd_profil_init(
    cote: str = typer.Option(..., "--cote", help="Cote de la collection."),
    titre: str = typer.Option(..., "--titre", help="Titre de la collection."),
    tableur: str = typer.Option(
        ...,
        "--tableur",
        help="Chemin du tableur (relatif au futur profil ou absolu).",
    ),
    granularite: str = typer.Option(
        "item", "--granularite", help="'item' ou 'fichier'."
    ),
    sortie: Path = typer.Option(
        Path("profil.yaml"),
        "--sortie",
        help="Chemin du profil à générer.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Écraser le fichier sortie s'il existe."
    ),
    stdout: bool = typer.Option(
        False, "--stdout", help="Écrire sur la sortie standard au lieu du fichier."
    ),
) -> None:
    """Générer un squelette de profil YAML à compléter manuellement."""
    if granularite not in ("item", "fichier"):
        typer.echo(
            f"Erreur : --granularite doit valoir 'item' ou 'fichier' (reçu : {granularite!r}).",
            err=True,
        )
        raise typer.Exit(2)
    contenu = generer_squelette(
        cote_collection=cote,
        titre_collection=titre,
        chemin_tableur=tableur,
        granularite=granularite,  # type: ignore[arg-type]
    )
    _ecrire_profil(contenu, sortie, force, stdout)
    if not stdout:
        typer.echo(f"✓ Profil créé : {sortie}")
        typer.echo("Prochaines étapes :")
        typer.echo(
            f"  1. Éditez {sortie} pour compléter le mapping (placeholder "
            '"A_REMPLACER" → nom réel de la colonne cote).'
        )
        typer.echo("  2. Lancez un import en dry-run pour vérifier :")
        typer.echo(f"     archives-tool importer {sortie}")


@profil_app.command("analyser")
def cmd_profil_analyser(
    chemin_tableur: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Chemin du tableur à analyser.",
    ),
    feuille: str = typer.Option(
        None,
        "--feuille",
        help="Feuille Excel à lire (défaut : première feuille).",
    ),
    cote: str = typer.Option(
        None,
        "--cote",
        help="Cote de la collection (défaut : 'A_COMPLETER').",
    ),
    titre: str = typer.Option(
        None,
        "--titre",
        help="Titre de la collection (défaut : 'À compléter').",
    ),
    sortie: Path = typer.Option(
        Path("profil.yaml"),
        "--sortie",
        help="Chemin du profil à générer.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Écraser le fichier sortie s'il existe."
    ),
    stdout: bool = typer.Option(
        False, "--stdout", help="Écrire sur la sortie standard au lieu du fichier."
    ),
) -> None:
    """Analyser un tableur et générer un profil pré-rempli."""
    try:
        contenu = analyser_tableur(
            chemin_tableur,
            feuille=feuille,
            cote_collection=cote,
            titre_collection=titre,
        )
    except FileNotFoundError as e:
        typer.echo(f"Erreur : {e}", err=True)
        raise typer.Exit(2) from None
    except ValueError as e:
        typer.echo(f"Erreur : {e}", err=True)
        raise typer.Exit(2) from None

    # Compteurs pour le résumé.
    nb_detectes = contenu.count("  # détecté")
    nb_meta = contenu.count("\n  metadonnees.")
    nb_total = nb_detectes + nb_meta

    _ecrire_profil(contenu, sortie, force, stdout)
    if not stdout:
        typer.echo(f"✓ Tableur analysé : {chemin_tableur}")
        typer.echo(f"  {nb_total} colonnes détectées")
        typer.echo(f"  {nb_detectes} mappées automatiquement vers des champs dédiés")
        typer.echo(f"  {nb_meta} mappées vers metadonnees.<slug>")
        typer.echo(f"✓ Profil créé : {sortie}")
        typer.echo("Prochaines étapes :")
        typer.echo(f"  1. Ouvrez {sortie} dans votre éditeur.")
        typer.echo(
            '  2. Vérifiez les mappings signalés "# détecté" — corrigez '
            "si l'heuristique a fait une erreur."
        )
        typer.echo(
            "  3. Ajustez les colonnes metadonnees (séparateurs multivaleurs, "
            "agrégations, suppression des colonnes inutiles)."
        )
        typer.echo("  4. Complétez les métadonnées de la collection.")
        typer.echo("  5. Lancez un import en dry-run :")
        typer.echo(f"     archives-tool importer {sortie}")


# ---------------------------------------------------------------------------
# Sous-groupe `demo` : génération d'une base de démonstration.
# ---------------------------------------------------------------------------

demo = typer.Typer(
    help="Outils autour de la base de démonstration.",
    no_args_is_help=True,
)
app.add_typer(demo, name="demo")


@demo.command("init")
def cmd_demo_init(
    sortie: Path = typer.Option(
        Path("data/demo.db"),
        "--sortie",
        help="Chemin du fichier .db à créer.",
    ),
    force: bool = typer.Option(False, "--force", help="Écraser un fichier existant."),
) -> None:
    """Créer une base SQLite peuplée pour explorer l'interface."""
    _refuser_ecrasement(sortie, force)
    if sortie.exists():
        sortie.unlink()

    rapport = peupler_base(sortie)
    console_mod.console.print(
        f"[succes]✓[/succes] Base de démonstration créée : "
        f"[valeur]{rapport.chemin_db}[/valeur]"
    )
    console_mod.console.print(f"  {rapport.nb_fonds} fonds")
    console_mod.console.print(
        f"  {rapport.nb_collections} collections (miroirs + libres + transversale)"
    )
    console_mod.console.print(f"  {rapport.nb_items} items rattachés")
    console_mod.console.print(f"  {rapport.nb_fichiers} fichiers référencés")
    if rapport.chemin_derives:
        console_mod.console.print(
            f"  Placeholders JPEG : [valeur]{rapport.chemin_derives}[/valeur]"
        )
    if rapport.chemin_config:
        console_mod.console.print(
            f"  Config locale démo : [valeur]{rapport.chemin_config}[/valeur]"
        )
    console_mod.console.print(
        "\nPour lancer l'interface sur cette base :\n"
        f"  ARCHIVES_DB={rapport.chemin_db} "
        f"ARCHIVES_CONFIG={rapport.chemin_config} "
        "uv run uvicorn archives_tool.api.main:app --reload"
    )


# ---------------------------------------------------------------------------
# Sous-groupe `collections` : gestion des collections libres en CLI
# (pendant CLI de l'UI V0.9.0-beta.2.1).
# ---------------------------------------------------------------------------

collections_app = typer.Typer(
    help="Gestion des collections libres (création, listage, suppression).",
    no_args_is_help=True,
)
app.add_typer(collections_app, name="collections")


@collections_app.command("creer-libre")
def cmd_collections_creer_libre(
    cote: str = typer.Argument(..., help="Cote de la nouvelle collection."),
    titre: str = typer.Argument(..., help="Titre de la nouvelle collection."),
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help="Cote du fonds parent. Omettre pour une collection transversale.",
    ),
    description: str | None = typer.Option(
        None, "--description", "-d", help="Description courte (libre)."
    ),
    description_publique: str | None = typer.Option(
        None,
        "--description-publique",
        help="Description publique (exports DC / Nakala).",
    ),
    phase: PhaseChantier = typer.Option(
        PhaseChantier.CATALOGAGE,
        "--phase",
        help="Phase de chantier.",
    ),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Créer une collection libre, transversale (sans --fonds) ou
    rattachée (avec --fonds COTE).
    """
    with _ouvrir_session_existante(db_path) as session:
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        fonds_id = fonds_obj.id if fonds_obj else None

        formulaire = FormulaireCollection(
            cote=cote,
            titre=titre,
            description=description or "",
            description_publique=description_publique or "",
            phase=phase.value,
            fonds_id=fonds_id,
        )
        try:
            col = creer_collection_libre(session, formulaire)
        except CollectionInvalide as e:
            typer.echo(f"Erreur : {e.erreurs}", err=True)
            raise typer.Exit(1) from None

        rattachement = (
            f"rattachée au fonds {fonds}"
            if fonds_id is not None
            else "transversale (sans fonds)"
        )
        typer.echo(f"✓ Collection libre créée : {col.cote} — {col.titre}")
        typer.echo(f"  {rattachement}")


@collections_app.command("lister")
def cmd_collections_lister(
    fonds: str | None = typer.Option(
        None, "--fonds", "-f", help="Limiter aux collections du fonds COTE."
    ),
    transversales: bool = typer.Option(
        False,
        "--transversales",
        "-t",
        help="N'afficher que les collections transversales (sans fonds).",
    ),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Lister les collections (toutes, par fonds, ou transversales)."""
    with _ouvrir_session_existante(db_path) as session:
        stmt = sa_select(Collection, Fonds.cote.label("fonds_cote")).join(
            Fonds, Fonds.id == Collection.fonds_id, isouter=True
        )
        if transversales:
            stmt = stmt.where(Collection.fonds_id.is_(None))
        elif fonds:
            fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
            stmt = stmt.where(Collection.fonds_id == fonds_obj.id)
        stmt = stmt.order_by(Collection.cote)

        rows = session.execute(stmt).all()
        if not rows:
            typer.echo("Aucune collection trouvée.")
            return

        for col, fonds_cote in rows:
            type_str = "[miroir]" if col.est_miroir else "[libre]"
            rattachement = f"— {fonds_cote}" if fonds_cote else "— transversale"
            typer.echo(
                f"  {col.cote:20} {col.titre[:40]:40} {type_str:10}{rattachement}"
            )


@collections_app.command("supprimer")
def cmd_collections_supprimer(
    cote: str = typer.Argument(..., help="Cote de la collection à supprimer."),
    fonds: str | None = typer.Option(
        None,
        "--fonds",
        "-f",
        help="Cote du fonds (pour désambiguïser une cote partagée).",
    ),
    confirme: bool = typer.Option(
        False, "--yes", "-y", help="Sauter la confirmation interactive."
    ),
    utilisateur: str | None = typer.Option(
        None, "--utilisateur", "-u", help="Nom journalisé dans la traçabilité."
    ),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Supprimer une collection libre. Refuse les miroirs (gérées par
    leur fonds parent — utiliser `archives-tool fonds supprimer`)."""
    with _ouvrir_session_existante(db_path) as session:
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        fonds_id = fonds_obj.id if fonds_obj else None

        try:
            col = lire_collection_par_cote(session, cote, fonds_id=fonds_id)
        except CollectionIntrouvable as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None

        if col.est_miroir:
            typer.echo(
                f"Erreur : la collection {cote} est une miroir, "
                f"elle est gérée par son fonds.",
                err=True,
            )
            raise typer.Exit(1)

        if not confirme:
            typer.echo(f"Supprimer la collection {col.cote} — {col.titre} ?")
            if not typer.confirm("Confirmer ?", default=False):
                raise typer.Abort()

        try:
            supprimer_collection_libre(session, col.id, execute_par=utilisateur)
        except OperationCollectionInterdite as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None
        typer.echo(f"✓ Collection {cote} supprimée.")


def _forcer_utf8_stdout() -> None:
    """Force stdout/stderr en UTF-8 si l'encodage par défaut ne l'est
    pas (cas typique : PowerShell sous Windows qui utilise cp1252).

    Sans ça, `controler` et `montrer` plantent en `UnicodeEncodeError`
    sur les symboles Rich (✓ ⚠ etc.). `errors="replace"` est défensif
    pour les chars qui resteraient inencodables — on n'interrompt
    jamais une commande à cause d'un glyphe.
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (stream.encoding or "").lower()
        except AttributeError:
            continue
        if enc and enc != "utf-8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                # Stream redirigé / wrappé : pas de reconfigure dispo.
                pass


items_app = typer.Typer(
    help="Gestion des items (création en série, …).",
    no_args_is_help=True,
)
app.add_typer(items_app, name="items")


@items_app.command("creer-serie")
def cmd_items_creer_serie(
    fonds: str = typer.Option(
        ...,
        "--fonds",
        "-f",
        help="Cote du fonds dans lequel créer les items.",
    ),
    pattern: str = typer.Option(
        ...,
        "--pattern",
        "-p",
        help=(
            "Pattern de cote avec variable `{n}` (ou `{n:03d}` pour "
            "zéro-padding). Ex : `PF-{n:03d}` produit `PF-001`, `PF-002`, ..."
        ),
    ),
    de_n: int = typer.Option(
        1, "--de", help="Numéro de départ (inclus). Défaut 1.",
    ),
    a_n: int = typer.Option(
        ..., "--a", help="Numéro de fin (inclus).",
    ),
    titre: str = typer.Option(
        "",
        "--titre",
        help="Template du titre (variable `{n}`). Vide = titre vide.",
    ),
    collection: str | None = typer.Option(
        None,
        "--collection",
        "-c",
        help=(
            "Cote de la collection cible. Omettre pour utiliser la "
            "miroir du fonds."
        ),
    ),
    etat: str = typer.Option(
        "brouillon",
        "--etat",
        help=(
            "État de catalogage initial. Valeurs : brouillon, a_verifier, "
            "verifie, valide, a_corriger."
        ),
    ),
    type_coar: str | None = typer.Option(
        None,
        "--type-coar",
        help="URI COAR appliqué à tous les items créés.",
    ),
    langue: str | None = typer.Option(
        None,
        "--langue",
        help="Code langue (ISO 639-3 ou 639-1) appliqué à tous les items.",
    ),
    ignorer_existants: bool = typer.Option(
        False,
        "--ignorer-existants",
        help=(
            "Ignorer silencieusement les cotes déjà présentes au lieu "
            "de refuser la série entière."
        ),
    ),
    utilisateur: str | None = typer.Option(
        None,
        "--utilisateur",
        "-u",
        help="Nom à inscrire dans `cree_par`. Défaut : config locale.",
    ),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Créer une série d'items dans un fonds en une transaction.

    Cas d'usage : préparer 60 fiches d'items d'une revue avant
    numérisation, pour pouvoir rattacher les scans au fil.

    Exemple :

    \b
        archives-tool items creer-serie \\
            --fonds PF --pattern "PF-{n:03d}" \\
            --de 1 --a 60 \\
            --titre "Por Favor n°{n}" \\
            --etat brouillon
    """
    # `cree_par` est passé directement via --utilisateur (None
    # accepté côté service → cree_par reste NULL en base, l'item
    # est tracé sans nom d'utilisateur).
    nom_utilisateur = utilisateur

    with _ouvrir_session_existante(db_path) as session:
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)

        # Résolution optionnelle de la collection cible.
        collection_id: int | None = None
        if collection:
            try:
                col = lire_collection_par_cote(
                    session, collection, fonds_id=fonds_obj.id
                )
            except CollectionIntrouvable:
                # Tentative en transversale si pas trouvée dans le fonds.
                try:
                    col = lire_collection_par_cote(session, collection)
                except CollectionIntrouvable:
                    typer.echo(
                        f"Erreur : collection {collection!r} introuvable.",
                        err=True,
                    )
                    raise typer.Exit(1) from None
            collection_id = col.id

        try:
            rapport = creer_items_en_serie(
                session,
                fonds_id=fonds_obj.id,
                pattern_cote=pattern,
                de_n=de_n,
                a_n=a_n,
                titre_template=titre,
                collection_id=collection_id,
                etat=etat,
                type_coar=type_coar,
                langue=langue,
                ignorer_existants=ignorer_existants,
                cree_par=nom_utilisateur,
            )
        except ItemInvalide as e:
            typer.echo("Erreur de validation :", err=True)
            for champ, msg in e.erreurs.items():
                typer.echo(f"  • {champ} : {msg}", err=True)
            raise typer.Exit(1) from None

        typer.echo(
            f"✓ {rapport.nb_crees} item(s) créé(s) dans le fonds "
            f"{fonds_obj.cote!r}."
        )
        if rapport.nb_crees > 0:
            premiere = rapport.crees[0].cote
            derniere = rapport.crees[-1].cote
            typer.echo(f"  Plage : {premiere} → {derniere}")
        if rapport.nb_ignores > 0:
            typer.echo(
                f"  {rapport.nb_ignores} cote(s) ignorée(s) (déjà existante(s))."
            )


@items_app.command("supprimer")
def cmd_items_supprimer(
    cote: str = typer.Argument(..., help="Cote de l'item à supprimer."),
    fonds: str = typer.Option(
        ...,
        "--fonds",
        "-f",
        help="Cote du fonds (obligatoire — les cotes d'item sont uniques par fonds).",
    ),
    confirme: bool = typer.Option(
        False, "--yes", "-y", help="Sauter la confirmation interactive."
    ),
    utilisateur: str | None = typer.Option(
        None, "--utilisateur", "-u", help="Nom journalisé dans la traçabilité."
    ),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Supprimer un item et tous ses fichiers + annotations en cascade."""
    with _ouvrir_session_existante(db_path) as session:
        # `--fonds` est requis (Typer enforce ...) donc `_resoudre_fonds_ou_sortie`
        # ne retourne jamais None ici — soit elle résout, soit elle a déjà
        # appelé `typer.Exit(1)`.
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        assert fonds_obj is not None
        try:
            item = lire_item_par_cote(session, cote, fonds_id=fonds_obj.id)
        except ItemIntrouvable as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None

        nb_fichiers = len(item.fichiers)
        nb_collections = len(item.collections)
        if not confirme:
            typer.echo(
                f"Supprimer l'item {item.cote} (fonds {fonds_obj.cote}) — "
                f"{item.titre or '(sans titre)'} ?"
            )
            typer.echo(
                f"  {nb_fichiers} fichier(s) + leurs annotations seront "
                f"supprimés en cascade. L'item sera retiré de "
                f"{nb_collections} collection(s)."
            )
            if not typer.confirm("Confirmer ?", default=False):
                raise typer.Abort()

        supprimer_item(session, item.id, execute_par=utilisateur)
        typer.echo(f"✓ Item {item.cote} supprimé.")


fonds_app = typer.Typer(
    help="Gestion des fonds (suppression, …).",
    no_args_is_help=True,
)
app.add_typer(fonds_app, name="fonds")


@fonds_app.command("supprimer")
def cmd_fonds_supprimer(
    cote: str = typer.Argument(..., help="Cote du fonds à supprimer."),
    confirme: bool = typer.Option(
        False, "--yes", "-y", help="Sauter la confirmation interactive."
    ),
    utilisateur: str | None = typer.Option(
        None, "--utilisateur", "-u", help="Nom journalisé dans la traçabilité."
    ),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Supprimer un fonds et toute sa descendance (items + miroir +
    collaborateurs). Les collections libres rattachées deviennent
    transversales (FK ON DELETE SET NULL). Cascade irréversible."""
    with _ouvrir_session_existante(db_path) as session:
        try:
            fonds_obj = lire_fonds_par_cote(session, cote)
        except FondsIntrouvable as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None

        # Compteurs pour le récap : un seul SELECT COUNT par dimension
        # pour éviter le N+1 sur `fonds.items` × `item.fichiers` (visible
        # sur les gros fonds : PF = 173 items × 38 fichiers = 174 requêtes).
        nb_items = session.scalar(
            sa_select(sa_func.count(Item.id)).where(Item.fonds_id == fonds_obj.id)
        )
        nb_fichiers = session.scalar(
            sa_select(sa_func.count(Fichier.id))
            .join(Item, Fichier.item_id == Item.id)
            .where(Item.fonds_id == fonds_obj.id)
        )
        # Collections : miroir + libres rattachées. Les libres deviendront
        # transversales, on les compte séparément pour le récap.
        miroir = fonds_obj.collection_miroir
        libres = [c for c in fonds_obj.collections if c is not miroir]

        if not confirme:
            typer.echo(
                f"Supprimer le fonds {fonds_obj.cote} — "
                f"{fonds_obj.titre or '(sans titre)'} ?"
            )
            typer.echo(
                f"  {nb_items} item(s) + {nb_fichiers} fichier(s) + "
                f"annotations seront supprimés."
            )
            if miroir is not None:
                typer.echo(f"  La miroir {miroir.cote!r} sera supprimée.")
            if libres:
                typer.echo(
                    f"  {len(libres)} collection(s) libre(s) rattachée(s) "
                    f"deviendront transversales (préservées) : "
                    f"{', '.join(c.cote for c in libres)}"
                )
            if not typer.confirm("Confirmer ?", default=False):
                raise typer.Abort()

        supprimer_fonds(session, fonds_obj.id, execute_par=utilisateur)
        typer.echo(f"✓ Fonds {cote} supprimé.")


annotations_app = typer.Typer(
    help="Opérations groupées sur les annotations IIIF (enrichissement…).",
    no_args_is_help=True,
)
app.add_typer(annotations_app, name="annotations")


@annotations_app.command("enrichir")
def cmd_annotations_enrichir(
    vocabulaire_code: str = typer.Option(
        ..., "--vocabulaire", "-v",
        help="Code du vocabulaire dont on propage les URIs.",
    ),
    fonds_cote: str = typer.Option(
        ..., "--fonds", "-f",
        help="Cote du fonds dont les annotations seront enrichies.",
    ),
    appliquer: bool = typer.Option(
        False, "--appliquer",
        help=(
            "Appliquer les modifications. Par défaut, dry-run (preview "
            "des matches sans toucher à la base)."
        ),
    ),
    utilisateur: str | None = typer.Option(
        None, "--utilisateur", "-u",
        help="Nom à poser dans `modifie_par` (défaut : config locale).",
    ),
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Enrichir rétroactivement les annotations d'un fonds avec les URIs
    d'un vocabulaire (T4 du scoping vocabulaires).

    Parcourt les annotations W3C du fonds, matche les `TextualBody` de
    tag (insensible accents/casse) contre les `ValeurControlee` actives
    du vocabulaire ayant une URI, et les remplace par des
    `SpecificResource source={id, label}` qui transportent le pivot
    Wikidata/VIAF.

    Cas d'usage : un vocab a été rattaché à un fonds APRÈS que ce fonds
    a été annoté. Les annotations existantes sont restées en tag libre.
    On veut maintenant propager les URIs sans les ré-éditer une à une.

    Idempotent — replay = no-op. Dry-run par défaut, `--appliquer` pour
    écrire en base.
    """
    from sqlalchemy import select as sa_select_

    from archives_tool.api.services._erreurs import EntiteIntrouvable
    from archives_tool.api.services.annotations import (
        enrichir_annotations_par_vocab,
    )
    from archives_tool.models.profil import Vocabulaire

    # Résolution du vocab par code (le service prend des ids, pas des
    # codes — plus pratique en CLI de passer un code humain).
    with _ouvrir_session_existante(db_path) as session:
        vocab = session.scalar(
            sa_select_(Vocabulaire).where(Vocabulaire.code == vocabulaire_code)
        )
        if vocab is None:
            typer.echo(
                f"Erreur : vocabulaire {vocabulaire_code!r} introuvable.",
                err=True,
            )
            raise typer.Exit(1)

        try:
            fonds_obj = lire_fonds_par_cote(session, fonds_cote)
        except FondsIntrouvable as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None

        # `utilisateur` est libre : si pas fourni, modifie_par reste
        # `None`. La traçabilité explicite (« qui a lancé l'enrichissement »)
        # passe par `--utilisateur` — pas de fallback auto sur la config
        # locale (qui peut ne pas exister dans les contextes batch/CI).
        modifie_par = utilisateur

        try:
            rapport = enrichir_annotations_par_vocab(
                session, vocab.id, fonds_obj.id,
                dry_run=not appliquer,
                modifie_par=modifie_par if appliquer else None,
            )
        except EntiteIntrouvable as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None

        mode = "APPLIQUÉ" if appliquer else "DRY-RUN (aucune écriture)"
        typer.echo(
            f"Enrichissement {mode} — vocab {vocab.code!r} sur fonds "
            f"{fonds_obj.cote!r}"
        )
        typer.echo(
            f"  {rapport.nb_matches} match(es) "
            f"sur {rapport.annotations_modifiees} annotation(s)"
        )
        if rapport.deja_enrichies:
            typer.echo(
                f"  {rapport.deja_enrichies} body(s) déjà enrichi(s) "
                "(idempotence)"
            )
        if rapport.matches:
            typer.echo("\nMatches :")
            for m in rapport.matches:
                typer.echo(
                    f"  annotation #{m.annotation_id} (fichier #{m.fichier_id})"
                    f" : « {m.libelle_libre} » → {m.valeur_uri}"
                )
        if not appliquer and rapport.matches:
            typer.echo(
                "\nRelancez avec --appliquer pour figer en base.",
            )


# ---------------------------------------------------------------------------
# Commande `nakala` : pull (lecture / rapatriement / rafraîchissement).
# ---------------------------------------------------------------------------

nakala_app = typer.Typer(
    help="Pull Nakala : inspecter, rapatrier, rafraîchir des dépôts.",
    no_args_is_help=True,
)
app.add_typer(nakala_app, name="nakala")

_CONFIG_OPTION_NAKALA = typer.Option(
    Path("config_local.yaml"),
    "--config",
    help="Config locale (section `nakala:` requise : base_url + clé API).",
)


def _client_nakala_ou_sortie(config: ConfigLocale) -> ClientLectureNakala:
    if config.nakala is None:
        typer.echo(
            "Erreur : aucune section `nakala:` dans le config_local.yaml "
            "(base_url + api_key).",
            err=True,
        )
        raise typer.Exit(2)
    n = config.nakala
    return ClientLectureNakala(
        n.base_url, n.api_key, timeout=n.timeout, verify_ssl=n.verify_ssl
    )


def _lire_depot_ou_sortie(client: ClientLectureNakala, doi: str) -> dict:
    try:
        return client.lire_depot(doi)
    except NakalaIntrouvable:
        typer.echo(f"Erreur : dépôt {doi!r} introuvable sur Nakala.", err=True)
        raise typer.Exit(1) from None
    except NakalaAuthRefusee:
        typer.echo(
            f"Erreur : accès refusé à {doi!r} — clé API manquante/invalide "
            "(dépôt privé/embargo ?).",
            err=True,
        )
        raise typer.Exit(1) from None
    except NakalaInjoignable as e:
        typer.echo(f"Erreur : Nakala injoignable ({e}).", err=True)
        raise typer.Exit(1) from None
    except ErreurNakala as e:
        typer.echo(f"Erreur Nakala : {e}", err=True)
        raise typer.Exit(1) from None


@nakala_app.command("montrer")
def cmd_nakala_montrer(
    doi: str = typer.Argument(..., help="DOI/identifiant Nakala (10.34847/nkl.…)."),
    format_sortie: _FormatRapport = typer.Option(_FormatRapport.TEXT, "--format"),
    config_path: Path = _CONFIG_OPTION_NAKALA,
) -> None:
    """Lire et afficher un dépôt Nakala (lecture seule, sans toucher la base)."""
    doi = normaliser_identifiant_nakala(doi)
    config = _charger_config_ou_sortie(config_path)
    with _client_nakala_ou_sortie(config) as client:
        brut = _lire_depot_ou_sortie(client, doi)
    depot = mapper_depot(brut)

    if format_sortie is _FormatRapport.JSON:
        import json

        typer.echo(json.dumps(
            {
                "identifiant": depot.identifiant,
                "statut": depot.statut,
                "titre": depot.titre,
                "createurs": depot.createurs,
                "date": depot.date,
                "type_coar": depot.type_coar,
                "langues": depot.langues,
                "description": depot.description,
                "sujets": depot.sujets,
                "licence": depot.licence,
                "nb_fichiers": len(depot.fichiers),
                "metadonnees": depot.metadonnees,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return

    typer.echo(f"Dépôt {depot.identifiant} [{depot.statut or '?'}]")
    typer.echo(f"  Titre      : {depot.titre or '—'}")
    typer.echo(f"  Créateurs  : {', '.join(depot.createurs) or '—'}")
    typer.echo(f"  Date       : {depot.date or '—'}")
    typer.echo(f"  Type COAR  : {depot.type_coar or '—'}")
    typer.echo(f"  Langues    : {', '.join(depot.langues) or '—'}")
    typer.echo(f"  Licence    : {depot.licence or '—'}")
    typer.echo(f"  Sujets     : {', '.join(depot.sujets) or '—'}")
    typer.echo(f"  Fichiers   : {len(depot.fichiers)}")
    if depot.metadonnees:
        typer.echo(f"  Métadonnées: {', '.join(sorted(depot.metadonnees))}")


@nakala_app.command("rapatrier")
def cmd_nakala_rapatrier(
    doi: str = typer.Argument(..., help="DOI/identifiant Nakala à rapatrier."),
    fonds: str = typer.Option(..., "--fonds", "-f", help="Cote du fonds cible."),
    cote: str | None = typer.Option(
        None, "--cote", help="Cote de l'item (sinon dérivée du DOI)."
    ),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Créer réellement (sinon : aperçu)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Créer un item ColleC depuis un dépôt Nakala (dry-run par défaut)."""
    doi = normaliser_identifiant_nakala(doi)
    config = _charger_config_ou_sortie(config_path)
    with _client_nakala_ou_sortie(config) as client:
        brut = _lire_depot_ou_sortie(client, doi)
        base_url = client.base_url
    depot = mapper_depot(brut)

    with _ouvrir_session_existante(db_path) as session:
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        assert fonds_obj is not None
        try:
            rapport = rapatrier(
                session, depot, brut, fonds_id=fonds_obj.id, cote=cote,
                cree_par=config.utilisateur, dry_run=not no_dry_run,
                base_url=base_url,
            )
        except RapatriementInvalide as e:
            typer.echo(f"Erreur : {e.erreurs}", err=True)
            raise typer.Exit(2) from None
        except ItemInvalide as e:
            # Ex. cote dérivée en collision avec un autre item du fonds.
            typer.echo(
                f"Erreur : item invalide ({e.erreurs}). "
                "Fournir une cote explicite via --cote ?",
                err=True,
            )
            raise typer.Exit(1) from None

    mode = "RÉEL" if no_dry_run else "DRY-RUN"
    if rapport.deja_existant:
        typer.echo(
            f"[{mode}] Dépôt déjà rapatrié → item {rapport.cote!r} "
            f"(id={rapport.item_id}). Utiliser `nakala rafraichir` pour mettre à jour."
        )
    elif no_dry_run:
        typer.echo(
            f"✓ Item {rapport.cote!r} créé (id={rapport.item_id}) dans le fonds {fonds} "
            f"— {rapport.nb_fichiers} fichier(s) Nakala."
        )
    else:
        typer.echo(
            f"[DRY-RUN] Créerait l'item {rapport.cote!r} dans le fonds {fonds}. "
            "Relancer avec --no-dry-run pour créer."
        )


@nakala_app.command("rafraichir")
def cmd_nakala_rafraichir(
    doi: str = typer.Argument(..., help="DOI d'un dépôt déjà rapatrié."),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Appliquer l'overwrite (sinon : diff seul)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Re-tirer un dépôt et le comparer / réappliquer sur l'item lié
    (diff par défaut, overwrite avec --no-dry-run)."""
    doi = normaliser_identifiant_nakala(doi)
    config = _charger_config_ou_sortie(config_path)
    with _client_nakala_ou_sortie(config) as client:
        brut = _lire_depot_ou_sortie(client, doi)
    depot = mapper_depot(brut)

    with _ouvrir_session_existante(db_path) as session:
        try:
            rapport = rafraichir(
                session, depot, brut,
                modifie_par=config.utilisateur, dry_run=not no_dry_run,
            )
        except RafraichissementImpossible as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None
        except ItemInvalide as e:
            # Ex. dépôt sans titre → l'overwrite serait invalide.
            typer.echo(f"Erreur : overwrite invalide ({e.erreurs}).", err=True)
            raise typer.Exit(1) from None

    if not rapport.a_des_changements:
        typer.echo(f"Item {rapport.item_cote!r} déjà à jour (aucun changement).")
        return
    typer.echo(f"Item {rapport.item_cote!r} — changements :")
    for d in rapport.diffs:
        typer.echo(f"  {d.champ:12} : {d.avant or '—'}  →  {d.apres or '—'}")
    if rapport.metadonnees_modifiees:
        typer.echo("  métadonnées  : (mises à jour Nakala)")
    if rapport.applique:
        typer.echo("✓ Overwrite appliqué.")
    else:
        typer.echo("[DRY-RUN] Relancer avec --no-dry-run pour appliquer.")


class _GranulariteTableur(str, enum.Enum):
    DONNEE = "donnee"
    FICHIER = "fichier"


class _FormatTableur(str, enum.Enum):
    CSV = "csv"
    XLSX = "xlsx"


def _lire_collection_ou_sortie(client: ClientLectureNakala, doi: str) -> dict:
    """Comme `_lire_depot_ou_sortie` mais pour une collection."""
    try:
        return client.lire_collection(doi)
    except NakalaIntrouvable:
        typer.echo(f"Erreur : collection {doi!r} introuvable sur Nakala.", err=True)
        raise typer.Exit(1) from None
    except NakalaAuthRefusee:
        typer.echo(
            f"Erreur : accès refusé à {doi!r} — clé API manquante/invalide.",
            err=True,
        )
        raise typer.Exit(1) from None
    except NakalaInjoignable as e:
        typer.echo(f"Erreur : Nakala injoignable ({e}).", err=True)
        raise typer.Exit(1) from None
    except ErreurNakala as e:
        typer.echo(f"Erreur Nakala : {e}", err=True)
        raise typer.Exit(1) from None


@nakala_app.command("exporter-tableur")
def cmd_nakala_exporter_tableur(
    doi: str = typer.Argument(..., help="DOI/identifiant de la collection Nakala."),
    granularite: _GranulariteTableur = typer.Option(
        _GranulariteTableur.DONNEE,
        "--granularite",
        help="donnee = 1 ligne/donnée ; fichier = 1 ligne/fichier (+ colonnes techniques).",
    ),
    format_sortie: _FormatTableur = typer.Option(
        _FormatTableur.CSV, "--format", help="csv ou xlsx."
    ),
    sep: str = typer.Option(";", "--sep", help="Séparateur CSV (ignoré en xlsx)."),
    sortie: Path | None = typer.Option(
        None, "--sortie", help="Chemin de sortie (défaut : <doi>_<granularite>.<ext> dans le cwd)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
) -> None:
    """Exporter une collection Nakala en tableur (lecture seule, sans base).

    Au choix : niveau **donnée** (toutes les métadonnées en colonnes) ou
    niveau **fichier** (métadonnées de la donnée recopiées + colonnes
    techniques du fichier : nom, sha1, mime, taille, embargo…).
    """
    doi = normaliser_identifiant_nakala(doi)
    config = _charger_config_ou_sortie(config_path)
    with _client_nakala_ou_sortie(config) as client:
        meta = _lire_collection_ou_sortie(client, doi)
        titre = titre_collection_nakala(meta)
        donnees = list(iterer_donnees_collection(client, doi))

    if granularite is _GranulariteTableur.FICHIER:
        tableur = lignes_niveau_fichier(donnees)
    else:
        tableur = lignes_niveau_donnee(donnees)

    ext = format_sortie.value
    if sortie is None:
        slug = doi.replace("/", "_").replace(".", "_")
        sortie = Path.cwd() / f"{slug}_{granularite.value}.{ext}"

    if format_sortie is _FormatTableur.XLSX:
        ecrire_xlsx(tableur, sortie, titre_collection=titre)
    else:
        ecrire_csv(tableur, sortie, sep=sep)

    typer.echo(
        f"✓ {len(donnees)} donnée(s) → {len(tableur.lignes)} ligne(s) "
        f"({granularite.value}, {ext}) : {sortie}"
    )


@nakala_app.command("rapatrier-collection")
def cmd_nakala_rapatrier_collection(
    doi: str = typer.Argument(..., help="DOI/identifiant de la collection Nakala."),
    fonds: str | None = typer.Option(
        None, "--fonds", "-f",
        help="Cote du fonds cible (sinon un fonds est créé depuis la collection).",
    ),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Rapatrier réellement (sinon : aperçu)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Rapatrier toute une collection Nakala (Fonds + N Items, dry-run par défaut).

    Une donnée → un Item (granularité native du modèle). Les fichiers Nakala
    ne sont pas matérialisés en `Fichier` (le JSON brut est caché).
    """
    doi = normaliser_identifiant_nakala(doi)
    config = _charger_config_ou_sortie(config_path)
    with _client_nakala_ou_sortie(config) as client:
        with _ouvrir_session_existante(db_path) as session:
            try:
                rapport = rapatrier_collection(
                    session, client, doi, fonds_cote=fonds,
                    cree_par=config.utilisateur, dry_run=not no_dry_run,
                )
            except FondsIntrouvable:
                typer.echo(f"Erreur : fonds {fonds!r} introuvable.", err=True)
                raise typer.Exit(1) from None
            except NakalaIntrouvable:
                typer.echo(f"Erreur : collection {doi!r} introuvable sur Nakala.", err=True)
                raise typer.Exit(1) from None
            except NakalaAuthRefusee:
                typer.echo(
                    f"Erreur : accès refusé à {doi!r} — clé API manquante/invalide.",
                    err=True,
                )
                raise typer.Exit(1) from None
            except NakalaInjoignable as e:
                typer.echo(f"Erreur : Nakala injoignable ({e}).", err=True)
                raise typer.Exit(1) from None
            except ErreurNakala as e:
                typer.echo(f"Erreur Nakala : {e}", err=True)
                raise typer.Exit(1) from None

    mode = "RÉEL" if no_dry_run else "DRY-RUN"
    cible = (
        f"fonds {rapport.fonds_cote!r}"
        + (" (créé)" if rapport.fonds_cree else "")
    )
    suffixe_fichiers = (
        f", {rapport.fichiers_crees} fichier(s)" if rapport.fichiers_crees else ""
    )
    typer.echo(
        f"[{mode}] Collection {doi} → {cible} : "
        f"{len(rapport.crees)} créé(s){suffixe_fichiers}, "
        f"{len(rapport.deja_existants)} déjà présent(s), {len(rapport.erreurs)} erreur(s)."
    )
    for doi_err, detail in rapport.erreurs:
        typer.echo(f"  ✗ {doi_err} : {detail}", err=True)
    if not no_dry_run:
        typer.echo("Relancer avec --no-dry-run pour rapatrier réellement.")


#: Plafond d'items détaillés listés dans l'aperçu de rafraichir-collection.
_MAX_DETAIL_RAFRAICHIR = 50


@nakala_app.command("rafraichir-collection")
def cmd_nakala_rafraichir_collection(
    doi: str = typer.Argument(..., help="DOI/identifiant de la collection Nakala."),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Appliquer les overwrites (sinon : diff seul)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Re-tirer une collection Nakala et comparer/réappliquer sur les items liés.

    Diff par défaut (dry-run) ; `--no-dry-run` applique les overwrites. Les
    données de la collection sans item ColleC sont signalées (à rapatrier).
    Les fichiers ne sont pas re-synchronisés (champs documentaires seulement).
    """
    doi = normaliser_identifiant_nakala(doi)
    config = _charger_config_ou_sortie(config_path)
    with _client_nakala_ou_sortie(config) as client:
        with _ouvrir_session_existante(db_path) as session:
            try:
                rapport = rafraichir_collection(
                    session, client, doi,
                    modifie_par=config.utilisateur, dry_run=not no_dry_run,
                )
            except NakalaIntrouvable:
                typer.echo(f"Erreur : collection {doi!r} introuvable sur Nakala.", err=True)
                raise typer.Exit(1) from None
            except NakalaAuthRefusee:
                typer.echo(
                    f"Erreur : accès refusé à {doi!r} — clé API manquante/invalide.",
                    err=True,
                )
                raise typer.Exit(1) from None
            except NakalaInjoignable as e:
                typer.echo(f"Erreur : Nakala injoignable ({e}).", err=True)
                raise typer.Exit(1) from None
            except ErreurNakala as e:
                typer.echo(f"Erreur Nakala : {e}", err=True)
                raise typer.Exit(1) from None

    mode = "RÉEL" if no_dry_run else "DRY-RUN"
    modifies = rapport.modifies
    verbe = "modifié(s)" if no_dry_run else "à modifier"
    typer.echo(
        f"[{mode}] Collection {doi} : {len(modifies)} {verbe}, "
        f"{len(rapport.inchanges)} inchangé(s), {len(rapport.non_lies)} non lié(s), "
        f"{len(rapport.erreurs)} erreur(s)."
    )
    for r in modifies[:_MAX_DETAIL_RAFRAICHIR]:
        champs = ", ".join(d.champ for d in r.diffs) or "—"
        meta = " + métadonnées" if r.metadonnees_modifiees else ""
        typer.echo(f"  • {r.item_cote} : {champs}{meta}")
    if len(modifies) > _MAX_DETAIL_RAFRAICHIR:
        typer.echo(f"  … et {len(modifies) - _MAX_DETAIL_RAFRAICHIR} autre(s).")
    for doi_err, detail in rapport.erreurs:
        typer.echo(f"  ✗ {doi_err} : {detail}", err=True)
    if not no_dry_run and modifies:
        typer.echo("Relancer avec --no-dry-run pour appliquer les overwrites.")


# ---------------------------------------------------------------------------
# Dépôt (écriture) Nakala — P2
# ---------------------------------------------------------------------------


def _client_ecriture_nakala_ou_sortie(config: ConfigLocale) -> NakalaEcritureClient:
    """Construit un client d'écriture Nakala depuis la config, ou sort (2)."""
    if config.nakala is None:
        typer.echo(
            "Erreur : aucune section `nakala:` dans le config_local.yaml.", err=True
        )
        raise typer.Exit(2)
    n = config.nakala
    if not n.api_key:
        typer.echo(
            "Erreur : `nakala.api_key` est obligatoire pour le dépôt (écriture).",
            err=True,
        )
        raise typer.Exit(2)
    return NakalaEcritureClient(
        n.base_url, n.api_key, timeout=n.timeout, verify_ssl=n.verify_ssl
    )


def _sortie_erreur_nakala_ecriture(exc: ErreurNakala) -> None:
    """Traduit une exception Nakala écriture en message stderr + Exit(1)."""
    if isinstance(exc, NakalaAuthRefusee):
        typer.echo("Erreur : clé API Nakala manquante/invalide (401).", err=True)
    elif isinstance(exc, NakalaAccesInterdit):
        typer.echo(
            "Erreur : la clé n'a pas le droit de dépôt sur cette ressource (403).",
            err=True,
        )
    elif isinstance(exc, NakalaInjoignable):
        typer.echo(f"Erreur : Nakala injoignable ({exc}).", err=True)
    else:  # NakalaSoumissionInvalide (422/4xx) + ErreurNakala (5xx)
        typer.echo(f"Erreur Nakala : {exc}", err=True)
    raise typer.Exit(1) from None


@nakala_app.command("deposer")
def cmd_nakala_deposer(
    cote: str = typer.Argument(..., help="Cote de l'item ColleC à déposer."),
    fonds: str = typer.Option(..., "--fonds", "-f", help="Cote du fonds de l'item."),
    statut: str = typer.Option(
        "pending", "--statut", help="pending (défaut, réversible) ou published."
    ),
    collection: str | None = typer.Option(
        None, "--collection", help="DOI d'une collection Nakala où rattacher."
    ),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Déposer réellement (sinon : aperçu)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Déposer un item ColleC comme nouveau dépôt Nakala (dry-run par défaut).

    Seuls les fichiers locaux de l'item sont téléversés. `pending` (défaut)
    crée un dépôt supprimable sans DOI minté.
    """
    config = _charger_config_ou_sortie(config_path)
    racines = dict(config.racines)
    with _client_ecriture_nakala_ou_sortie(config) as client:
        with _ouvrir_session_existante(db_path) as session:
            fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
            assert fonds_obj is not None
            try:
                item = lire_item_par_cote(session, cote, fonds_id=fonds_obj.id)
            except ItemIntrouvable:
                typer.echo(f"Erreur : item {cote!r} introuvable.", err=True)
                raise typer.Exit(1) from None
            try:
                rapport = deposer_item(
                    session, client, item, racines=racines, statut=statut,
                    collection_doi=collection, cree_par=config.utilisateur,
                    dry_run=not no_dry_run,
                )
            except DepotImpossible as e:
                typer.echo(f"Erreur : {e}", err=True)
                raise typer.Exit(1) from None
            except MetaInvalide as e:
                typer.echo(f"Erreur : métadonnées insuffisantes — {e}", err=True)
                raise typer.Exit(1) from None
            except ErreurNakala as e:
                _sortie_erreur_nakala_ecriture(e)

    if rapport.deja_depose:
        typer.echo(f"Item {rapport.cote!r} déjà déposé → {rapport.doi}.")
    elif no_dry_run:
        typer.echo(
            f"✓ Item {rapport.cote!r} déposé → {rapport.doi} "
            f"({rapport.nb_fichiers} fichier(s), statut {statut})."
        )
    else:
        typer.echo(
            f"[DRY-RUN] Déposerait l'item {rapport.cote!r} : "
            f"{rapport.nb_fichiers} fichier(s), {len(rapport.metas)} métadonnée(s), "
            f"statut {statut}."
        )
    for avert in rapport.avertissements:
        typer.echo(f"  ⚠ {avert}")
    if not no_dry_run and not rapport.deja_depose:
        typer.echo("Relancer avec --no-dry-run pour déposer réellement.")


@nakala_app.command("deposer-collection")
def cmd_nakala_deposer_collection(
    cote: str = typer.Argument(..., help="Cote de la collection ColleC."),
    fonds: str | None = typer.Option(
        None, "--fonds", "-f", help="Cote du fonds (désambiguïse une cote partagée)."
    ),
    statut_donnee: str = typer.Option("pending", "--statut-donnee"),
    statut_collection: str = typer.Option("private", "--statut-collection"),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Déposer réellement (sinon : aperçu)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Créer la collection Nakala + y déposer ses items (dry-run par défaut)."""
    config = _charger_config_ou_sortie(config_path)
    racines = dict(config.racines)
    with _client_ecriture_nakala_ou_sortie(config) as client:
        with _ouvrir_session_existante(db_path) as session:
            collection = _resoudre_collection_pour_export(session, cote, fonds)
            try:
                rapport = deposer_collection(
                    session, client, collection, racines=racines,
                    statut_donnee=statut_donnee, statut_collection=statut_collection,
                    cree_par=config.utilisateur, dry_run=not no_dry_run,
                )
            except ErreurNakala as e:
                _sortie_erreur_nakala_ecriture(e)

    mode = "RÉEL" if no_dry_run else "DRY-RUN"
    cible = rapport.collection_doi or "(à créer)"
    if rapport.collection_creee:
        cible += " (créée)"
    typer.echo(
        f"[{mode}] Collection {collection.cote} → {cible} : "
        f"{len(rapport.deposes)} déposé(s), {len(rapport.sautes)} déjà déposé(s), "
        f"{len(rapport.non_deposables)} sans fichier local, "
        f"{len(rapport.erreurs)} erreur(s)."
    )
    for c, detail in rapport.erreurs:
        typer.echo(f"  ✗ {c} : {detail}", err=True)
    if not no_dry_run:
        typer.echo("Relancer avec --no-dry-run pour déposer réellement.")


# ---------------------------------------------------------------------------
# Round-trip métadonnées — P3
# ---------------------------------------------------------------------------


def _nom_court_propriete(uri: str) -> str:
    """URI propriété → libellé court (`nkl:title`, `dcterms:subject`)."""
    if "#" in uri:
        return "nkl:" + uri.rsplit("#", 1)[-1]
    if "/dc/terms/" in uri:
        return "dcterms:" + uri.rsplit("/", 1)[-1]
    return uri


def _afficher_diff_push(rapport, mode: str, no_dry_run: bool) -> None:
    """Sortie commune des commandes de push (diff + dérive)."""
    if rapport.derive:
        typer.echo(
            "⚠ Le dépôt distant a changé depuis le dernier rapatriement "
            "(dérive) — vérifier avant d'écraser.",
            err=True,
        )
    if not rapport.a_des_changements:
        typer.echo(f"Item {rapport.cote!r} ({rapport.doi}) : aucun changement à pousser.")
        return
    typer.echo(f"[{mode}] Item {rapport.cote!r} ({rapport.doi}) — "
               f"{len(rapport.diffs)} champ(s) à modifier :")
    for d in rapport.diffs:
        avant = " | ".join(d.avant) or "∅"
        apres = " | ".join(d.apres) or "∅"
        typer.echo(f"  • {_nom_court_propriete(d.property_uri)} : {avant}  →  {apres}")
    if rapport.applique:
        typer.echo("✓ Métadonnées poussées sur Nakala.")
    elif not no_dry_run:
        typer.echo("Relancer avec --no-dry-run pour pousser.")


@nakala_app.command("pousser")
def cmd_nakala_pousser(
    cote: str = typer.Argument(..., help="Cote de l'item lié à Nakala."),
    fonds: str = typer.Option(..., "--fonds", "-f", help="Cote du fonds de l'item."),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Pousser réellement (sinon : diff)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Pousser les modifications de métadonnées d'un item vers son dépôt Nakala.

    Diff par défaut (dry-run) ; `--no-dry-run` applique le `PUT` (remplace les
    métadonnées). Signale une dérive si le distant a changé depuis le pull.
    """
    config = _charger_config_ou_sortie(config_path)
    with (
        _client_nakala_ou_sortie(config) as lecture,
        _client_ecriture_nakala_ou_sortie(config) as ecriture,
        _ouvrir_session_existante(db_path) as session,
    ):
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        assert fonds_obj is not None
        try:
            item = lire_item_par_cote(session, cote, fonds_id=fonds_obj.id)
        except ItemIntrouvable:
            typer.echo(f"Erreur : item {cote!r} introuvable.", err=True)
            raise typer.Exit(1) from None
        try:
            rapport = pousser_item(
                session, lecture, ecriture, item,
                dry_run=not no_dry_run, modifie_par=config.utilisateur,
            )
        except DepotImpossible as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None
        except MetaInvalide as e:
            typer.echo(f"Erreur : métadonnées insuffisantes — {e}", err=True)
            raise typer.Exit(1) from None
        except ErreurNakala as e:
            _sortie_erreur_nakala_ecriture(e)

    _afficher_diff_push(rapport, "RÉEL" if no_dry_run else "DRY-RUN", no_dry_run)


@nakala_app.command("publier")
def cmd_nakala_publier(
    cote: str = typer.Argument(..., help="Cote de l'item lié à Nakala."),
    fonds: str = typer.Option(..., "--fonds", "-f", help="Cote du fonds de l'item."),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Publier réellement (IRRÉVERSIBLE)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Publier le dépôt d'un item (`pending → published`).

    **Irréversible** : mint un DOI DataCite définitif. Dry-run par défaut.
    """
    config = _charger_config_ou_sortie(config_path)
    with (
        _client_nakala_ou_sortie(config) as lecture,
        _client_ecriture_nakala_ou_sortie(config) as ecriture,
        _ouvrir_session_existante(db_path) as session,
    ):
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        assert fonds_obj is not None
        try:
            item = lire_item_par_cote(session, cote, fonds_id=fonds_obj.id)
        except ItemIntrouvable:
            typer.echo(f"Erreur : item {cote!r} introuvable.", err=True)
            raise typer.Exit(1) from None
        try:
            rapport = publier_item(
                session, lecture, ecriture, item,
                dry_run=not no_dry_run, modifie_par=config.utilisateur,
            )
        except DepotImpossible as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None
        except MetaInvalide as e:
            typer.echo(f"Erreur : métadonnées insuffisantes — {e}", err=True)
            raise typer.Exit(1) from None
        except ErreurNakala as e:
            _sortie_erreur_nakala_ecriture(e)

    if rapport.applique:
        typer.echo(f"✓ Dépôt {rapport.doi} publié (DOI minté — irréversible).")
    else:
        typer.echo(
            f"[DRY-RUN] Publierait le dépôt {rapport.doi} (item {rapport.cote!r}). "
            "Relancer avec --no-dry-run — IRRÉVERSIBLE."
        )


@nakala_app.command("pousser-collection")
def cmd_nakala_pousser_collection(
    cote: str = typer.Argument(..., help="Cote de la collection ColleC."),
    fonds: str | None = typer.Option(
        None, "--fonds", "-f", help="Cote du fonds (désambiguïse une cote partagée)."
    ),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Pousser réellement (sinon : diff)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Pousser les métadonnées de la collection puis de ses items liés."""
    config = _charger_config_ou_sortie(config_path)
    with (
        _client_nakala_ou_sortie(config) as lecture,
        _client_ecriture_nakala_ou_sortie(config) as ecriture,
        _ouvrir_session_existante(db_path) as session,
    ):
        collection = _resoudre_collection_pour_export(session, cote, fonds)
        try:
            rapport = pousser_collection(
                session, lecture, ecriture, collection,
                dry_run=not no_dry_run, modifie_par=config.utilisateur,
            )
        except ErreurNakala as e:
            _sortie_erreur_nakala_ecriture(e)

    mode = "RÉEL" if no_dry_run else "DRY-RUN"
    # Entité collection (titre/description) d'abord.
    mc = rapport.meta_collection
    if mc is None:
        typer.echo(
            f"Collection {collection.cote} : pas de DOI Nakala — "
            "métadonnées de collection non poussées (items uniquement)."
        )
    elif not mc.a_des_changements:
        typer.echo(f"Métadonnées de collection ({mc.doi}) : aucun changement.")
    else:
        etat = "poussées" if mc.applique else "à pousser"
        typer.echo(
            f"Métadonnées de collection ({mc.doi}) — {len(mc.diffs)} champ(s) {etat} :"
        )
        for d in mc.diffs:
            avant = " | ".join(d.avant) or "∅"
            apres = " | ".join(d.apres) or "∅"
            typer.echo(f"  • {_nom_court_propriete(d.property_uri)} : {avant}  →  {apres}")

    # Puis les items.
    verbe = "poussé(s)" if no_dry_run else "à pousser"
    typer.echo(
        f"[{mode}] Items de {collection.cote} : {len(rapport.pousses)} {verbe}, "
        f"{len(rapport.inchanges)} inchangé(s), {len(rapport.non_lies)} non lié(s), "
        f"{len(rapport.erreurs)} erreur(s)."
    )
    for r in rapport.pousses:
        typer.echo(f"  • {r.cote} : {len(r.diffs)} champ(s)")
    for c, detail in rapport.erreurs:
        typer.echo(f"  ✗ {c} : {detail}", err=True)
    if not no_dry_run and (rapport.pousses or (mc and mc.a_des_changements)):
        typer.echo("Relancer avec --no-dry-run pour pousser.")


@nakala_app.command("publier-collection")
def cmd_nakala_publier_collection(
    cote: str = typer.Argument(..., help="Cote de la collection ColleC."),
    fonds: str | None = typer.Option(
        None, "--fonds", "-f", help="Cote du fonds (désambiguïse une cote partagée)."
    ),
    no_dry_run: bool = typer.Option(
        False, "--no-dry-run", help="Publier réellement (IRRÉVERSIBLE)."
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Publier tous les items liés d'une collection (`pending → published`).

    **Irréversible** : mint un DOI DataCite par item. Dry-run par défaut.
    """
    config = _charger_config_ou_sortie(config_path)
    with (
        _client_nakala_ou_sortie(config) as lecture,
        _client_ecriture_nakala_ou_sortie(config) as ecriture,
        _ouvrir_session_existante(db_path) as session,
    ):
        collection = _resoudre_collection_pour_export(session, cote, fonds)
        try:
            rapport = publier_collection(
                session, lecture, ecriture, collection,
                dry_run=not no_dry_run, modifie_par=config.utilisateur,
            )
        except ErreurNakala as e:
            _sortie_erreur_nakala_ecriture(e)

    mode = "RÉEL" if no_dry_run else "DRY-RUN"
    verbe = "publié(s)" if no_dry_run else "à publier"
    typer.echo(
        f"[{mode}] Collection {collection.cote} : {len(rapport.publies)} {verbe}, "
        f"{len(rapport.non_lies)} non lié(s), {len(rapport.erreurs)} erreur(s)."
    )
    for c, detail in rapport.erreurs:
        typer.echo(f"  ✗ {c} : {detail}", err=True)
    if not no_dry_run and rapport.publies:
        typer.echo("Relancer avec --no-dry-run pour publier — IRRÉVERSIBLE.")


@nakala_app.command("comparer-fichiers")
def cmd_nakala_comparer_fichiers(
    cote: str = typer.Argument(..., help="Cote de l'item lié à Nakala."),
    fonds: str = typer.Option(..., "--fonds", "-f", help="Cote du fonds de l'item."),
    format_sortie: _FormatRapport = typer.Option(
        _FormatRapport.TEXT, "--format",
        help="Format de sortie (text Rich par défaut, json pour scripts).",
    ),
    config_path: Path = _CONFIG_OPTION_NAKALA,
    db_path: Path = _DB_PATH_OPTION,
) -> None:
    """Comparer les fichiers d'un item ColleC vs son dépôt Nakala (P3+b).

    Lecture seule, **aucune écriture**. Recalcule le SHA-1 des binaires
    locaux et confronte aux fichiers distants. Classifie en :

    - **nouveaux** : à uploader au push (binaire local jamais déposé).
    - **modifiés** : à ré-uploader (binaire local changé).
    - **inchangés** : à conserver tels quels.
    - **Nakala-only sans local** : pas de binaire local résolvable — au
      push, **danger** s'ils ne sont pas préservés explicitement.
    - **orphelins distants** : sur Nakala mais plus en local — au push,
      ils seraient supprimés côté Nakala.

    Le palier P3+c (push effectif) refusera par défaut s'il y a des
    orphelins distants ou des Nakala-only sans local. Cette commande
    sert d'aperçu humain avant de décider.
    """
    config = _charger_config_ou_sortie(config_path)
    racines = dict(config.racines)
    with (
        _client_nakala_ou_sortie(config) as lecture,
        _ouvrir_session_existante(db_path) as session,
    ):
        fonds_obj = _resoudre_fonds_ou_sortie(session, fonds)
        assert fonds_obj is not None
        try:
            item = lire_item_par_cote(session, cote, fonds_id=fonds_obj.id)
        except ItemIntrouvable:
            typer.echo(f"Erreur : item {cote!r} introuvable.", err=True)
            raise typer.Exit(1) from None
        try:
            rapport = comparer_fichiers_item(
                session, lecture, item, racines=racines,
            )
        except ComparaisonImpossible as e:
            typer.echo(f"Erreur : {e}", err=True)
            raise typer.Exit(1) from None
        except ErreurNakala as e:
            typer.echo(f"Erreur Nakala : {e}", err=True)
            raise typer.Exit(1) from None

    if format_sortie is _FormatRapport.JSON:
        import json

        typer.echo(json.dumps({
            "cote_item": rapport.cote_item,
            "doi": rapport.doi,
            "aucun_changement": rapport.aucun_changement,
            "nouveaux": [
                {"ordre": fc.ordre, "nom_fichier": fc.nom_fichier,
                 "sha1_local": fc.sha1_local}
                for fc in rapport.nouveaux
            ],
            "modifies": [
                {"ordre": fc.ordre, "nom_fichier": fc.nom_fichier,
                 "sha1_local": fc.sha1_local, "sha1_distant": fc.sha1_distant}
                for fc in rapport.modifies
            ],
            "inchanges": [
                {"ordre": fc.ordre, "nom_fichier": fc.nom_fichier,
                 "sha1": fc.sha1_local}
                for fc in rapport.inchanges
            ],
            "nakala_only_sans_local": [
                {"ordre": fc.ordre, "nom_fichier": fc.nom_fichier,
                 "sha1_distant": fc.sha1_distant}
                for fc in rapport.nakala_only_sans_local
            ],
            "orphelins_distants": [
                {"sha1": fo.sha1, "nom_fichier": fo.nom_fichier}
                for fo in rapport.orphelins_distants
            ],
        }, ensure_ascii=False, indent=2))
        return

    typer.echo(f"Item {rapport.cote_item} ↔ dépôt {rapport.doi}")
    typer.echo(
        f"  Inchangés : {len(rapport.inchanges)}"
        f" · Modifiés : {len(rapport.modifies)}"
        f" · Nouveaux : {len(rapport.nouveaux)}"
        f" · Orphelins distants : {len(rapport.orphelins_distants)}"
        f" · Nakala-only sans local : {len(rapport.nakala_only_sans_local)}"
    )
    if rapport.aucun_changement and not rapport.nakala_only_sans_local:
        typer.echo("  ✓ Aucun changement à pousser.")
        return
    if rapport.aucun_changement:
        typer.echo(
            "  ⚠ Aucun changement à pousser mais des Nakala-only sans local "
            "sont signalés — vérifier au push."
        )

    def _detail_liste(titre: str, items: list, formatter) -> None:
        if not items:
            return
        typer.echo(f"  {titre} :")
        for i in items:
            typer.echo(f"    • {formatter(i)}")

    _detail_liste(
        "Nouveaux (à uploader)",
        rapport.nouveaux,
        lambda fc: f"[{fc.ordre:02d}] {fc.nom_fichier} (sha1 local: {fc.sha1_local[:12]}…)",
    )
    _detail_liste(
        "Modifiés (sha1 a changé)",
        rapport.modifies,
        lambda fc: (
            f"[{fc.ordre:02d}] {fc.nom_fichier} "
            f"({fc.sha1_distant[:12]}… → {fc.sha1_local[:12]}…)"
        ),
    )
    _detail_liste(
        "Nakala-only sans binaire local",
        rapport.nakala_only_sans_local,
        lambda fc: (
            f"[{fc.ordre:02d}] {fc.nom_fichier}"
            + (f" (sha1 distant: {fc.sha1_distant[:12]}…)" if fc.sha1_distant else "")
        ),
    )
    _detail_liste(
        "Orphelins distants (présents Nakala, absents locaux)",
        rapport.orphelins_distants,
        lambda fo: f"{fo.nom_fichier or '(sans nom)'} (sha1: {fo.sha1[:12]}…)",
    )


def main() -> None:
    _forcer_utf8_stdout()
    app()


if __name__ == "__main__":
    main()
