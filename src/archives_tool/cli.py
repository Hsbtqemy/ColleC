"""Interface en ligne de commande."""

from __future__ import annotations

from pathlib import Path

import typer

from rich.table import Table

import archives_tool.affichage.console as console_mod
from archives_tool.affichage.collections import (
    afficher_collections_arbre,
    afficher_collections_plat,
    afficher_fiche_collection,
)
from archives_tool.affichage.fichiers import afficher_fiche_fichier
from archives_tool.affichage.items import afficher_fiche_item
from archives_tool.affichage.statistiques import afficher_statistiques
from archives_tool.api.services.collections import (
    CollectionIntrouvable,
    CollectionInvalide,
    FormulaireCollection,
    OperationCollectionInterdite,
    creer_collection_libre,
    lire_collection_par_cote,
    supprimer_collection_libre,
)
from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    lire_fonds_par_cote,
)
from archives_tool.config import ConfigLocale, charger_config
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.exporters.dublin_core import exporter_dc_xml
from archives_tool.exporters.excel import exporter_excel
from archives_tool.exporters.nakala import exporter_nakala_csv
from archives_tool.exporters.rapport import RapportExport
from archives_tool.exporters.selection import CritereSelection, SelectionErreur
from archives_tool.importers.ecrivain import RapportImport, importer as importer_profil
from archives_tool.models import Collection, Fonds, PhaseChantier, TypeCollection
from archives_tool.profils import (
    ProfilInvalide,
    ProfilObsoleteV1,
    analyser_tableur,
    charger_profil,
    generer_squelette,
)
from archives_tool.demo import peupler_base
from archives_tool.derivatives import generer_derives, nettoyer_derives
from archives_tool.derivatives.affichage import (
    afficher_rapport as afficher_rapport_derives,
)
from archives_tool.qa.affichage import afficher_rapport_qa
from archives_tool.qa.controles import CODES_CONTROLES, controler_tout
from archives_tool.renamer import (
    annuler_batch,
    construire_plan,
    executer_plan,
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


def _afficher_rapport(rapport: RapportImport, verbose: bool) -> None:
    mode = "DRY-RUN" if rapport.dry_run else "RÉEL"
    typer.echo(f"Import {mode} — durée {rapport.duree_secondes:.2f}s")
    if rapport.fonds_cote:
        verbe = "créé" if rapport.fonds_cree else "existant"
        suffixe = (
            " + miroir personnalisée" if rapport.miroir_personnalisee else ""
        )
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


def _afficher_rapport_export(rapport: RapportExport, verbose: bool) -> None:
    typer.echo(
        f"Export {rapport.format} — {rapport.nb_items_selectionnes} items, "
        f"{rapport.nb_fichiers_selectionnes} fichiers — "
        f"{rapport.duree_secondes:.2f}s"
    )
    if rapport.chemin_sortie:
        typer.echo(f"  Sortie : {rapport.chemin_sortie}")
    if rapport.items_incomplets:
        typer.echo(f"  Items incomplets : {len(rapport.items_incomplets)}", err=True)
        if verbose:
            for cote, manques in rapport.items_incomplets:
                typer.echo(f"    - {cote} : manque {', '.join(manques)}", err=True)
    if rapport.valeurs_non_mappees and verbose:
        typer.echo("  Valeurs non canoniques :")
        for champ, valeur in rapport.valeurs_non_mappees:
            typer.echo(f"    - {champ} = {valeur!r}")
    if rapport.avertissements and verbose:
        typer.echo("  Avertissements :")
        for a in rapport.avertissements:
            typer.echo(f"    - {a}")


@app.command("exporter")
def cmd_exporter(
    format: str = typer.Argument(
        ...,
        metavar="FORMAT",
        help="Un parmi : xlsx, csv, dc-xml, nakala-csv.",
    ),
    collection: str = typer.Option(
        ...,
        "--collection",
        help="Cote de la collection à exporter (obligatoire en V1).",
    ),
    recursif: bool = typer.Option(
        False,
        "--recursif/--non-recursif",
        help="Inclure les sous-collections.",
    ),
    etat: list[str] = typer.Option(
        None,
        "--etat",
        help="Filtrer par état de catalogage (multiple).",
    ),
    granularite: str = typer.Option(
        "item",
        "--granularite",
        help="'item' ou 'fichier' (ignoré pour nakala-csv, forcé à item).",
    ),
    sortie: Path = typer.Option(
        ...,
        "--sortie",
        help="Chemin du fichier (xlsx/csv/nakala-csv, dc-xml agrégé) "
        "ou dossier (dc-xml un-fichier-par-item).",
    ),
    colonnes: str = typer.Option(
        None,
        "--colonnes",
        help="Liste de champs internes séparés par virgule (uniquement xlsx/csv).",
    ),
    mode: str = typer.Option(
        "agrege",
        "--mode",
        help="'agrege' ou 'un-fichier-par-item' (uniquement dc-xml).",
    ),
    licence: str = typer.Option(
        "CC-BY-NC-ND-4.0",
        "--licence",
        help="Licence par défaut (nakala-csv).",
    ),
    statut: str = typer.Option(
        "pending",
        "--statut",
        help="Statut par défaut (nakala-csv).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--no-dry-run",
        help="Calcule le rapport sans écrire le fichier de sortie.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict/--souple",
        help="Exit non-zéro si des items sont incomplets.",
    ),
    verbose: bool = typer.Option(False, "--verbose/--quiet"),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
) -> None:
    """Exporter une sélection d'items vers un format canonique."""
    critere = CritereSelection(
        collection_cote=collection,
        recursif=recursif,
        etats=list(etat) if etat else None,
        granularite="fichier" if granularite == "fichier" else "item",
    )

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    try:
        with factory() as session:
            if format == "xlsx":
                cols = [c.strip() for c in colonnes.split(",")] if colonnes else None
                rapport = exporter_excel(
                    session,
                    critere,
                    sortie,
                    format="xlsx",
                    colonnes=cols,
                    dry_run=dry_run,
                )
            elif format == "csv":
                cols = [c.strip() for c in colonnes.split(",")] if colonnes else None
                rapport = exporter_excel(
                    session,
                    critere,
                    sortie,
                    format="csv",
                    colonnes=cols,
                    dry_run=dry_run,
                )
            elif format == "dc-xml":
                mode_norm = (
                    "un_fichier_par_item" if mode == "un-fichier-par-item" else "agrege"
                )
                rapport = exporter_dc_xml(
                    session,
                    critere,
                    sortie,
                    mode=mode_norm,
                    dry_run=dry_run,
                )
            elif format == "nakala-csv":
                # Nakala : granularité forcée à item.
                critere.granularite = "item"
                rapport = exporter_nakala_csv(
                    session,
                    critere,
                    sortie,
                    licence_defaut=licence,
                    statut_defaut=statut,
                    dry_run=dry_run,
                )
            else:
                typer.echo(
                    f"Format inconnu : {format!r}. Attendu : xlsx, csv, "
                    "dc-xml, nakala-csv.",
                    err=True,
                )
                raise typer.Exit(2)
    except SelectionErreur as e:
        typer.echo(f"Erreur sélection : {e}", err=True)
        raise typer.Exit(2) from None

    _afficher_rapport_export(rapport, verbose)

    if strict and rapport.items_incomplets:
        raise typer.Exit(1)
    raise typer.Exit(0)


# ---------------------------------------------------------------------------
# Sous-groupe `montrer` : commandes de visualisation en lecture seule.
# ---------------------------------------------------------------------------

montrer = typer.Typer(
    help="Visualiser collections, items et fichiers en base.",
    no_args_is_help=True,
)
app.add_typer(montrer, name="montrer")


@montrer.command("statistiques")
def cmd_montrer_statistiques(
    collection: str = typer.Option(
        None,
        "--collection",
        help="Limite les statistiques à une collection (et ses sous-collections).",
    ),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
) -> None:
    """Vue d'ensemble globale ou par collection."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        ok = afficher_statistiques(session, collection_cote=collection)
    if not ok:
        raise typer.Exit(1)


@montrer.command("fichier")
def cmd_montrer_fichier(
    fichier_id: int = typer.Argument(..., help="ID numérique du fichier en base."),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
    config_path: Path = typer.Option(
        Path("config_local.yaml"),
        "--config",
        help="Config locale pour le diagnostic disque (optionnelle).",
    ),
) -> None:
    """Afficher la fiche d'un fichier avec diagnostic disque."""
    config: ConfigLocale | None = None
    try:
        config = charger_config(config_path)
    except Exception:
        # Config absente ou invalide : on continue sans diagnostic disque.
        config = None

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        ok = afficher_fiche_fichier(session, fichier_id, config)
    if not ok:
        raise typer.Exit(1)


@montrer.command("item")
def cmd_montrer_item(
    cote_item: str = typer.Argument(..., help="Cote de l'item."),
    collection: str = typer.Option(
        None,
        "--collection",
        help="Cote de la collection si la cote item n'est pas unique.",
    ),
    metadonnees_completes: bool = typer.Option(
        False,
        "--metadonnees-completes",
        help="Afficher tout le JSON metadonnees (sinon résumé tronqué).",
    ),
    fichiers: bool = typer.Option(True, "--fichiers/--pas-fichiers"),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
) -> None:
    """Afficher la fiche détaillée d'un item."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        ok = afficher_fiche_item(
            session,
            cote_item,
            collection_cote=collection,
            metadonnees_completes=metadonnees_completes,
            fichiers=fichiers,
        )
    if not ok:
        raise typer.Exit(1)


@montrer.command("collection")
def cmd_montrer_collection(
    cote: str = typer.Argument(..., help="Cote de la collection."),
    items: bool = typer.Option(True, "--items/--pas-items"),
    limite: int = typer.Option(
        50,
        "--limite",
        help="Nombre max d'items à afficher (0 = illimité).",
    ),
    tri_par: str = typer.Option(
        "cote",
        "--tri-par",
        help="Tri des items : cote, date, etat, modifie.",
    ),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
) -> None:
    """Afficher la fiche d'une collection avec ses items."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        ok = afficher_fiche_collection(
            session, cote, items=items, limite=limite, tri_par=tri_par
        )
    if not ok:
        raise typer.Exit(1)


@montrer.command("collections")
def cmd_montrer_collections(
    recursif: bool = typer.Option(
        False,
        "--recursif/--pas-recursif",
        help="Affichage en arbre plutôt qu'en tableau plat.",
    ),
    vide: bool = typer.Option(
        True,
        "--vide/--avec-items",
        help="Inclure les collections sans items (mode plat seulement).",
    ),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
) -> None:
    """Lister toutes les collections (plat ou arbre)."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        if recursif:
            afficher_collections_arbre(session)
        else:
            afficher_collections_plat(session, vide=vide)


# ---------------------------------------------------------------------------
# Commande `controler` : contrôles de cohérence base/disque (lecture seule).
# ---------------------------------------------------------------------------


@app.command("controler")
def cmd_controler(
    collection: str = typer.Option(
        None,
        "--collection",
        help="Limite les contrôles à une collection (sinon : toutes).",
    ),
    recursif: bool = typer.Option(
        False,
        "--recursif/--non-recursif",
        help="Inclure les sous-collections lors d'un filtre par collection.",
    ),
    check: list[str] = typer.Option(
        None,
        "--check",
        help=(
            "Restreindre aux contrôles indiqués (multi). Codes : "
            f"{', '.join(CODES_CONTROLES)}."
        ),
    ),
    extensions: str = typer.Option(
        None,
        "--extensions",
        help=(
            "Liste d'extensions (séparées par virgule) pour le contrôle "
            "des orphelins disque. Défaut : png,jpg,jpeg,tif,tiff,pdf."
        ),
    ),
    limite_details: int = typer.Option(
        20,
        "--limite-details",
        help="Nombre max de lignes affichées par contrôle (0 = illimité).",
    ),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
    config_path: Path = typer.Option(
        Path("config_local.yaml"),
        "--config",
        help=(
            "Config locale (racines). Optionnelle : sans elle, le contrôle "
            "des orphelins et des fichiers manquants se contente d'avertir."
        ),
    ),
) -> None:
    """Contrôler la cohérence base ↔ disque (lecture seule)."""
    # Config locale optionnelle : si elle manque, on continue sans
    # racines — les contrôles concernés se déclareront non vérifiables.
    racines: dict[str, Path] = {}
    try:
        config = charger_config(config_path)
        racines = dict(config.racines)
    except FileNotFoundError:
        typer.echo(
            f"Config absente ({config_path}) : contrôles disque ignorés.",
            err=True,
        )
    except Exception as e:
        typer.echo(f"Config invalide : {e}", err=True)
        raise typer.Exit(2) from None

    exts: set[str] | None = None
    if extensions is not None:
        exts = {e.strip() for e in extensions.split(",") if e.strip()}

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    try:
        with factory() as session:
            rapport = controler_tout(
                session,
                racines=racines,
                collection_cote=collection,
                recursif=recursif,
                checks=check or None,
                extensions_orphelins=exts,
            )
    except ValueError as e:
        typer.echo(f"Erreur : {e}", err=True)
        raise typer.Exit(2) from None

    afficher_rapport_qa(rapport, limite_details=limite_details)
    raise typer.Exit(1 if rapport.nb_anomalies > 0 else 0)


# ---------------------------------------------------------------------------
# Sous-groupe `deriver` : génération de vignettes et aperçus.
# ---------------------------------------------------------------------------

deriver = typer.Typer(
    help="Générer ou nettoyer les dérivés (vignettes, aperçus).",
    no_args_is_help=True,
)
app.add_typer(deriver, name="deriver")


def _options_perimetre_deriver(
    collection: str | None,
    item: str | None,
    fichier_id: list[int] | None,
) -> None:
    n = sum(x is not None and x != [] for x in (collection, item, fichier_id))
    if n == 0:
        typer.echo("Erreur : précisez --collection, --item ou --fichier-id.", err=True)
        raise typer.Exit(2)


@deriver.command("appliquer")
def cmd_deriver_appliquer(
    collection: str = typer.Option(None, "--collection"),
    item: str = typer.Option(None, "--item"),
    fichier_id: list[int] = typer.Option(None, "--fichier-id"),
    recursif: bool = typer.Option(False, "--recursif/--non-recursif"),
    force: bool = typer.Option(
        False, "--force", help="Régénérer même si derive_genere est déjà True."
    ),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run"),
    racine_cible: str = typer.Option(
        "miniatures",
        "--racine-cible",
        help="Racine logique où écrire les dérivés.",
    ),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
    config_path: Path = typer.Option(Path("config_local.yaml"), "--config"),
) -> None:
    """Générer les dérivés des fichiers ciblés."""
    _options_perimetre_deriver(collection, item, fichier_id)
    config = _charger_config_ou_sortie(config_path)

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    try:
        with factory() as session:
            rapport = generer_derives(
                session,
                racines=dict(config.racines),
                racine_cible=racine_cible,
                collection_cote=collection,
                item_cote=item,
                fichier_ids=list(fichier_id) if fichier_id else None,
                recursif=recursif,
                force=force,
                dry_run=dry_run,
            )
    except ValueError as e:
        typer.echo(f"Erreur : {e}", err=True)
        raise typer.Exit(2) from None

    afficher_rapport_derives(rapport)
    raise typer.Exit(1 if rapport.nb_erreurs else 0)


@deriver.command("nettoyer")
def cmd_deriver_nettoyer(
    collection: str = typer.Option(None, "--collection"),
    item: str = typer.Option(None, "--item"),
    fichier_id: list[int] = typer.Option(None, "--fichier-id"),
    recursif: bool = typer.Option(False, "--recursif/--non-recursif"),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run"),
    racine_cible: str = typer.Option("miniatures", "--racine-cible"),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
    config_path: Path = typer.Option(Path("config_local.yaml"), "--config"),
) -> None:
    """Supprimer les dérivés des fichiers ciblés."""
    _options_perimetre_deriver(collection, item, fichier_id)
    config = _charger_config_ou_sortie(config_path)

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    try:
        with factory() as session:
            rapport = nettoyer_derives(
                session,
                racines=dict(config.racines),
                racine_cible=racine_cible,
                collection_cote=collection,
                item_cote=item,
                fichier_ids=list(fichier_id) if fichier_id else None,
                recursif=recursif,
                dry_run=dry_run,
            )
    except ValueError as e:
        typer.echo(f"Erreur : {e}", err=True)
        raise typer.Exit(2) from None

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
    collection: str = typer.Option(None, "--collection"),
    item: str = typer.Option(
        None, "--item", help="Cote de l'item à cibler (alternative à --collection)."
    ),
    fichier_id: list[int] = typer.Option(
        None,
        "--fichier-id",
        help="ID(s) de fichier à cibler (option répétable).",
    ),
    recursif: bool = typer.Option(
        False, "--recursif/--non-recursif", help="Inclure les sous-collections."
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
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
    config_path: Path = typer.Option(Path("config_local.yaml"), "--config"),
) -> None:
    """Construire un plan de renommage et l'appliquer (dry-run par défaut)."""
    config = _charger_config_ou_sortie(config_path)
    nom = utilisateur if utilisateur is not None else config.utilisateur
    racines = dict(config.racines)

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    try:
        with factory() as session:
            plan = construire_plan(
                session,
                template=template,
                racines=racines,
                collection_cote=collection,
                item_cote=item,
                fichier_ids=list(fichier_id) if fichier_id else None,
                recursif=recursif,
            )
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
            afficher_execution(rap)
            raise typer.Exit(1 if rap.erreurs else 0)
    except ValueError as e:
        typer.echo(f"Erreur : {e}", err=True)
        raise typer.Exit(2) from None


@renommer.command("annuler")
def cmd_renommer_annuler(
    batch_id: str = typer.Option(..., "--batch-id", help="UUID du batch à annuler."),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    utilisateur: str = typer.Option(None, "--utilisateur"),
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
    afficher_annulation(rap)
    raise typer.Exit(1 if rap.erreurs else 0)


@renommer.command("historique")
def cmd_renommer_historique(
    limite: int = typer.Option(50, "--limite", help="Nombre de batchs à afficher."),
    db_path: Path = typer.Option(Path("data/archives.db"), "--db-path"),
) -> None:
    """Afficher les derniers batchs de renommage."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as session:
        entrees = lister_batchs(session, limite=limite)

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
        f"  {rapport.nb_collections} collections "
        "(miroirs + libres + transversale)"
    )
    console_mod.console.print(f"  {rapport.nb_items} items rattachés")
    console_mod.console.print(f"  {rapport.nb_fichiers} fichiers référencés")
    console_mod.console.print(
        "Pour lancer l'interface sur cette base :\n"
        f"  ARCHIVES_DB={rapport.chemin_db} "
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


def _ouvrir_session_existante(db_path: Path):
    """Ouvre une session sur une base SQLite **existante** (Exit 2 si
    le fichier est absent). Les commandes `collections` exigent une
    base déjà créée — pas d'auto-création ici (différent de
    `archives-tool importer` qui peut créer la base à la volée)."""
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
    from sqlalchemy import select as sa_select

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
            type_str = (
                "[miroir]"
                if col.type_collection == TypeCollection.MIROIR.value
                else "[libre]"
            )
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

        if col.type_collection == TypeCollection.MIROIR.value:
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
