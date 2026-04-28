"""Affichage fiche fichier avec diagnostic disque."""

from __future__ import annotations

from sqlalchemy.orm import Session

from archives_tool.affichage import console as cons  # le sous-module
from archives_tool.affichage.formatters import (
    ABSENT,
    formater_date,
    formater_etat,
    formater_taille_octets,
)
from archives_tool.config import ConfigLocale
from archives_tool.files.paths import hash_sha256, resoudre_chemin
from archives_tool.models import Fichier


def afficher_fiche_fichier(
    session: Session,
    fichier_id: int,
    config: ConfigLocale | None = None,
) -> bool:
    """Panneau de diagnostic d'un Fichier (id en base).

    Si `config` est fourni : tente de résoudre la racine et de
    vérifier l'existence et le hash sur disque.
    """
    from rich.panel import Panel

    fichier = session.get(Fichier, fichier_id)
    if fichier is None:
        cons.console.print(
            f"[erreur]Fichier #{fichier_id} introuvable en base.[/erreur]"
        )
        return False

    item = fichier.item
    col = item.collection if item else None
    parent_aff = f"{item.cote} ({col.cote_collection})" if item and col else ABSENT

    dimensions = ABSENT
    if fichier.largeur_px and fichier.hauteur_px:
        dimensions = f"{fichier.largeur_px} × {fichier.hauteur_px} px"

    lignes = [
        ("Item parent", parent_aff),
        ("Ordre", str(fichier.ordre)),
        ("Type de page", fichier.type_page),
        ("Folio", fichier.folio or ABSENT),
        ("Nom", fichier.nom_fichier),
        ("Racine", fichier.racine),
        ("Chemin relatif", fichier.chemin_relatif),
        ("Format", fichier.format or ABSENT),
        ("Taille", formater_taille_octets(fichier.taille_octets)),
        ("Dimensions", dimensions),
        ("Hash SHA-256", fichier.hash_sha256 or ABSENT),
        ("État", formater_etat(fichier.etat)),
        ("Ajouté le", formater_date(fichier.ajoute_le)),
        ("Ajouté par", fichier.ajoute_par or ABSENT),
    ]
    largeur = max(len(c) for c, _ in lignes)
    corps = "\n".join(
        f"[cle]{cle.ljust(largeur)}[/cle] : [valeur]{val}[/valeur]"
        for cle, val in lignes
    )
    cons.console.print(
        Panel(corps, title=f"[titre]Fichier #{fichier.id}[/titre]", expand=False)
    )

    # Diagnostic disque (optionnel — config requise)
    if config is None:
        return True
    if fichier.racine not in config.racines:
        cons.console.print(
            Panel(
                f"[avertissement]Racine logique {fichier.racine!r} non "
                f"configurée dans la config locale — diagnostic disque "
                f"indisponible.[/avertissement]",
                title="[sous_titre]Chemin résolu[/sous_titre]",
                expand=False,
            )
        )
        return True

    try:
        chemin_abs = resoudre_chemin(
            config.racines, fichier.racine, fichier.chemin_relatif
        )
    except Exception as e:
        cons.console.print(f"[erreur]Résolution du chemin : {e}[/erreur]")
        return True

    diagnostic_lignes = [str(chemin_abs)]
    if chemin_abs.is_file():
        diagnostic_lignes.append("[succes]✓ existe sur disque[/succes]")
        if fichier.hash_sha256:
            try:
                hash_actuel = hash_sha256(chemin_abs)
                if hash_actuel == fichier.hash_sha256:
                    diagnostic_lignes.append("[succes]✓ hash inchangé[/succes]")
                else:
                    diagnostic_lignes.append(
                        "[avertissement]⚠ hash modifié depuis l'import[/avertissement]"
                    )
                    diagnostic_lignes.append(f"  base   : {fichier.hash_sha256}")
                    diagnostic_lignes.append(f"  disque : {hash_actuel}")
            except OSError as e:
                diagnostic_lignes.append(f"[erreur]✗ lecture impossible : {e}[/erreur]")
        else:
            diagnostic_lignes.append(
                "[dim]vérification hash impossible (hash absent en base)[/dim]"
            )
    else:
        diagnostic_lignes.append("[erreur]✗ absent sur disque[/erreur]")

    cons.console.print(
        Panel(
            "\n".join(diagnostic_lignes),
            title="[sous_titre]Chemin résolu[/sous_titre]",
            expand=False,
        )
    )
    return True
