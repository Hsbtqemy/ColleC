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
from archives_tool.api.services.items import ItemIntrouvable
from sqlalchemy import select as sa_select
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
)
from archives_tool.config import ConfigLocale, charger_config
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

    if verbose:
        if rapport.warnings:
            typer.echo("\nWarnings :")
            for w in rapport.warnings:
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
            supprimer_collection_libre(session, col.id)
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


def main() -> None:
    _forcer_utf8_stdout()
    app()


if __name__ == "__main__":
    main()
