"""Interface en ligne de commande."""

from __future__ import annotations

from pathlib import Path

import typer

from archives_tool.affichage.collections import (
    afficher_collections_arbre,
    afficher_collections_plat,
    afficher_fiche_collection,
)
from archives_tool.affichage.fichiers import afficher_fiche_fichier
from archives_tool.affichage.items import afficher_fiche_item
from archives_tool.affichage.statistiques import afficher_statistiques
from archives_tool.config import ConfigLocale, charger_config
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.exporters.dublin_core import exporter_dc_xml
from archives_tool.exporters.excel import exporter_excel
from archives_tool.exporters.nakala import exporter_nakala_csv
from archives_tool.exporters.rapport import RapportExport
from archives_tool.exporters.selection import CritereSelection, SelectionErreur
from archives_tool.importers.ecrivain import RapportImport, importer as importer_profil
from archives_tool.profils import ProfilInvalide, charger_profil

app = typer.Typer(
    help="Outil de gestion de collections numérisées.",
    no_args_is_help=True,
)


@app.callback()
def _callback() -> None:
    """Force la structure en sous-commandes (sinon Typer promeut la
    commande unique au niveau racine et masque le nom `importer`)."""


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
    if rapport.collection_id is not None:
        verbe = "créée" if rapport.collection_creee else "existante"
        typer.echo(f"  Collection #{rapport.collection_id} ({verbe})")
    typer.echo(
        f"  Items : {rapport.items_crees} créés, "
        f"{rapport.items_mis_a_jour} mis à jour, "
        f"{rapport.items_inchanges} inchangés"
    )
    typer.echo(
        f"  Fichiers : {rapport.fichiers_ajoutes} ajoutés, "
        f"{rapport.fichiers_deja_connus} déjà connus"
    )
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
    """Importer un profil YAML en base (dry-run par défaut)."""
    config = _charger_config_ou_sortie(config_path)

    try:
        profil = charger_profil(chemin_profil)
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
