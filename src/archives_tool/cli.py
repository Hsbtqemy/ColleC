"""Interface en ligne de commande."""

from __future__ import annotations

from pathlib import Path

import typer

from archives_tool.config import ConfigLocale, charger_config
from archives_tool.db import creer_engine, creer_session_factory
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
