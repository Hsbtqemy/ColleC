"""Rendus text (Rich) et JSON pour la CLI `archives-tool montrer`.

Six rendus, un par variante (entité × format) :
- `rendu_text_fonds_liste` / `rendu_json_fonds_liste`
- `rendu_text_fonds_detail` / `rendu_json_fonds_detail`
- `rendu_text_collection_liste` / `rendu_json_collection_liste`
- `rendu_text_collection_detail` / `rendu_json_collection_detail`
- `rendu_text_item_detail` / `rendu_json_item_detail`
- `rendu_text_fichier_detail` / `rendu_json_fichier_detail`

Tous lecture seule. Reuse maximal des helpers `affichage/formatters.py`
et du THEME global.
"""

from __future__ import annotations

import json
from datetime import datetime
from io import StringIO
from typing import Any

from rich.console import Console
from rich.table import Table

from archives_tool.affichage.console import THEME
from archives_tool.affichage.formatters import (
    formater_etat,
    formater_taille_octets,
    temps_relatif,
)
from archives_tool.api.services._erreurs import chaine_ou_none
from archives_tool.api.services.dashboard import (
    CollectionDetail,
    FondsDetail,
    ItemDetail,
)
from archives_tool.api.services.fonds import FondsResume
from archives_tool.models import Collection, Fichier

# Nombre par défaut d'événements de journal (modifications d'item,
# opérations sur fichier) affichés en text. Pas exposé en CLI : si on
# le rend configurable un jour, on remontera l'option ici.
_MAX_EVENEMENTS = 5

_ABSENT = "[dim]~[/dim]"


# ---------------------------------------------------------------------------
# Helpers communs
# ---------------------------------------------------------------------------


def _new_console() -> tuple[Console, StringIO]:
    """Console Rich qui écrit dans un StringIO + theme global. Évite de
    polluer stdout pendant les tests, et garde les couleurs si la CLI
    redirige vers un TTY."""
    buf = StringIO()
    return Console(file=buf, theme=THEME, force_terminal=False, width=120), buf


def _ou_absent(valeur: Any) -> str:
    """`valeur` en str si non vide, sinon marqueur absent. S'aligne sur
    `chaine_ou_none` (services/_erreurs) pour la définition de « vide »."""
    nettoye = chaine_ou_none(valeur) if valeur is None or isinstance(valeur, str) else valeur
    return _ABSENT if nettoye is None else str(nettoye)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _section_tracabilite_text(console: Console, entite: Any, *, verbe: str = "Créé") -> None:
    """Section « Traçabilité » commune à fonds / collection / item / fichier.

    `verbe` permet d'adapter (« Créé » vs « Ajouté » pour les fichiers).
    Lit `cree_le` ou `ajoute_le` selon ce qui existe sur l'entité.
    """
    cree_le = getattr(entite, "cree_le", None) or getattr(entite, "ajoute_le", None)
    cree_par = getattr(entite, "cree_par", None) or getattr(entite, "ajoute_par", None)
    console.print("[bold]Traçabilité[/bold]")
    console.print(
        f"  {verbe} le {_iso(cree_le) or '~'} par {_ou_absent(cree_par)}"
    )
    if entite.modifie_le:
        console.print(
            f"  Modifié {temps_relatif(entite.modifie_le)} "
            f"par {_ou_absent(entite.modifie_par)}"
        )


def _dict_tracabilite(entite: Any) -> dict[str, Any]:
    """Dict JSON commun pour la traçabilité (clés stables : cree_le /
    cree_par / modifie_le / modifie_par). Utile pour fonds / collection /
    item — `Fichier` a son propre schéma (ajoute_le, version)."""
    return {
        "cree_le": _iso(entite.cree_le),
        "cree_par": entite.cree_par,
        "modifie_le": _iso(entite.modifie_le),
        "modifie_par": entite.modifie_par,
    }


# ---------------------------------------------------------------------------
# Fonds
# ---------------------------------------------------------------------------


def rendu_text_fonds_liste(fonds_list: list[FondsResume]) -> str:
    console, buf = _new_console()
    console.print(f"[bold]Fonds ({len(fonds_list)})[/bold]")
    if not fonds_list:
        console.print("[dim]Aucun fonds.[/dim]")
        return buf.getvalue()
    table = Table(show_header=True, header_style="cle", box=None, padding=(0, 2))
    table.add_column("Cote", style="bold")
    table.add_column("Titre")
    table.add_column("Items", justify="right")
    table.add_column("Collections", justify="right")
    table.add_column("Miroir")
    for f in fonds_list:
        table.add_row(
            f.cote,
            f.titre,
            str(f.nb_items),
            str(f.nb_collections),
            f.miroir_cote or "—",
        )
    console.print(table)
    return buf.getvalue()


def rendu_json_fonds_liste(fonds_list: list[FondsResume]) -> str:
    return json.dumps(
        {
            "type": "fonds_liste",
            "fonds": [
                {
                    "cote": f.cote,
                    "titre": f.titre,
                    "description": f.description,
                    "nb_items": f.nb_items,
                    "nb_collections": f.nb_collections,
                    "miroir_cote": f.miroir_cote,
                    "cree_le": f.cree_le.isoformat() if f.cree_le else None,
                }
                for f in fonds_list
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def rendu_text_fonds_detail(detail: FondsDetail) -> str:
    console, buf = _new_console()
    f = detail.fonds
    console.print(f"[bold cyan]Fonds {f.titre}[/bold cyan] ([bold]{f.cote}[/bold])")
    console.print()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cle")
    table.add_column()
    table.add_row("Description", _ou_absent(f.description))
    if f.description_publique:
        table.add_row("Description publique", f.description_publique)
    if f.description_interne:
        table.add_row("Description interne", f.description_interne)
    table.add_row("Responsable archives", _ou_absent(f.responsable_archives))
    table.add_row("Personnalité associée", _ou_absent(f.personnalite_associee))
    if any((f.editeur, f.lieu_edition, f.periodicite, f.issn)):
        table.add_row("Éditeur", _ou_absent(f.editeur))
        table.add_row("Lieu d'édition", _ou_absent(f.lieu_edition))
        table.add_row("Périodicité", _ou_absent(f.periodicite))
        table.add_row("ISSN", _ou_absent(f.issn))
    if f.date_debut or f.date_fin:
        table.add_row("Période", f"{f.date_debut or '?'} — {f.date_fin or '?'}")
    console.print(table)

    console.print()
    console.print(
        f"[bold]Collections ({len(detail.collections_resume)})[/bold]"
    )
    cols = Table(show_header=True, header_style="cle", box=None, padding=(0, 2))
    cols.add_column("Cote")
    cols.add_column("Titre")
    cols.add_column("Type")
    cols.add_column("Items", justify="right")
    for c in detail.collections_resume:
        type_lbl = "miroir" if c.est_miroir else "libre"
        cols.add_row(c.cote, c.titre, type_lbl, str(c.nb_items))
    console.print(cols)

    console.print()
    console.print(
        f"[bold]Items ({detail.nb_items}) — {len(detail.items_recents)} récents[/bold]"
    )
    if detail.items_recents:
        items = Table(show_header=True, header_style="cle", box=None, padding=(0, 2))
        items.add_column("Cote")
        items.add_column("Titre")
        items.add_column("Date")
        items.add_column("État")
        for i in detail.items_recents:
            items.add_row(
                i.cote,
                i.titre or "",
                i.date or "",
                formater_etat(i.etat) if i.etat else "",
            )
        console.print(items)
    if detail.collaborateurs_par_role:
        console.print()
        console.print("[bold]Collaborateurs[/bold]")
        for role, gens in detail.collaborateurs_par_role.items():
            if not gens:
                continue
            console.print(f"  [cle]{role.value}[/cle]")
            for g in gens:
                console.print(f"    - {g.nom}")
    console.print()
    _section_tracabilite_text(console, f)
    return buf.getvalue()


def rendu_json_fonds_detail(detail: FondsDetail) -> str:
    f = detail.fonds
    data = {
        "type": "fonds_detail",
        "fonds": {
            "cote": f.cote,
            "titre": f.titre,
            "description": f.description,
            "description_publique": f.description_publique,
            "description_interne": f.description_interne,
            "responsable_archives": f.responsable_archives,
            "personnalite_associee": f.personnalite_associee,
            "editeur": f.editeur,
            "lieu_edition": f.lieu_edition,
            "periodicite": f.periodicite,
            "issn": f.issn,
            "date_debut": f.date_debut,
            "date_fin": f.date_fin,
            "nb_items": detail.nb_items,
            "collections": [
                {
                    "cote": c.cote,
                    "titre": c.titre,
                    "type_collection": c.type_collection,
                    "nb_items": c.nb_items,
                }
                for c in detail.collections_resume
            ],
            "items_recents": [
                {
                    "cote": i.cote,
                    "titre": i.titre,
                    "date": i.date,
                    "etat": i.etat,
                }
                for i in detail.items_recents
            ],
            "collaborateurs_par_role": {
                role.value: [{"nom": g.nom} for g in gens]
                for role, gens in detail.collaborateurs_par_role.items()
            },
            "tracabilite": _dict_tracabilite(f),
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _libelle_collection(c: Collection) -> str:
    """Libellé text d'une collection selon son type/rattachement.
    Utilise les properties ORM `est_miroir`/`est_transversale` pour
    rester cohérent avec le CHECK et les autres consommateurs."""
    if c.est_miroir:
        return "miroir"
    if c.est_transversale:
        return "transversale"
    return "libre rattachée"


def rendu_text_collection_liste(collections: list[Collection]) -> str:
    console, buf = _new_console()
    console.print(f"[bold]Collections ({len(collections)})[/bold]")
    if not collections:
        console.print("[dim]Aucune collection.[/dim]")
        return buf.getvalue()
    table = Table(show_header=True, header_style="cle", box=None, padding=(0, 2))
    table.add_column("Cote", style="bold")
    table.add_column("Titre")
    table.add_column("Type")
    table.add_column("Fonds")
    table.add_column("Phase")
    for c in collections:
        type_lbl = _libelle_collection(c)
        fonds_lbl = c.fonds.cote if c.fonds_id and c.fonds else "(transversale)"
        table.add_row(c.cote, c.titre, type_lbl, fonds_lbl, c.phase)
    console.print(table)
    return buf.getvalue()


def rendu_json_collection_liste(collections: list[Collection]) -> str:
    return json.dumps(
        {
            "type": "collection_liste",
            "collections": [
                {
                    "cote": c.cote,
                    "titre": c.titre,
                    "type_collection": c.type_collection,
                    "fonds_cote": c.fonds.cote if c.fonds_id and c.fonds else None,
                    "phase": c.phase,
                }
                for c in collections
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def rendu_text_collection_detail(detail: CollectionDetail) -> str:
    console, buf = _new_console()
    c = detail.collection
    type_lbl = _libelle_collection(c)
    console.print(
        f"[bold cyan]Collection {c.titre}[/bold cyan] ([bold]{c.cote}[/bold]) — {type_lbl}"
    )
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cle")
    table.add_column()
    if detail.fonds_parent is not None:
        table.add_row(
            "Fonds parent",
            f"{detail.fonds_parent.titre} ({detail.fonds_parent.cote})",
        )
    table.add_row("Phase", c.phase)
    table.add_row("Description", _ou_absent(c.description))
    if c.description_publique:
        table.add_row("Description publique", c.description_publique)
    table.add_row("DOI Nakala", _ou_absent(c.doi_nakala))
    table.add_row(
        "DOI collection parente", _ou_absent(c.doi_collection_nakala_parent)
    )
    table.add_row("Items", str(detail.nb_items))
    console.print(table)

    if detail.est_transversale and detail.fonds_representes:
        console.print()
        console.print(
            f"[bold]Fonds représentés ({len(detail.fonds_representes)})[/bold]"
        )
        for f in detail.fonds_representes:
            console.print(f"  • {f.titre} ([bold]{f.cote}[/bold])")

    console.print()
    _section_tracabilite_text(console, c)
    return buf.getvalue()


def rendu_json_collection_detail(detail: CollectionDetail) -> str:
    c = detail.collection
    return json.dumps(
        {
            "type": "collection_detail",
            "collection": {
                "cote": c.cote,
                "titre": c.titre,
                "type_collection": c.type_collection,
                "phase": c.phase,
                "description": c.description,
                "description_publique": c.description_publique,
                "doi_nakala": c.doi_nakala,
                "doi_collection_nakala_parent": c.doi_collection_nakala_parent,
                "est_miroir": detail.est_miroir,
                "est_transversale": detail.est_transversale,
                "nb_items": detail.nb_items,
                "fonds_parent": (
                    {
                        "cote": detail.fonds_parent.cote,
                        "titre": detail.fonds_parent.titre,
                    }
                    if detail.fonds_parent
                    else None
                ),
                "fonds_representes": [
                    {"cote": f.cote, "titre": f.titre}
                    for f in detail.fonds_representes
                ],
                "tracabilite": _dict_tracabilite(c),
            },
        },
        indent=2,
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------


def rendu_text_item_detail(
    detail: ItemDetail, *, max_evenements: int = _MAX_EVENEMENTS
) -> str:
    console, buf = _new_console()
    item = detail.item
    fonds = detail.fonds
    console.print(
        f"[bold cyan]Item {item.cote}[/bold cyan] — "
        f"fonds [bold]{fonds.cote}[/bold] ({fonds.titre})"
    )
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cle")
    table.add_column()
    table.add_row("Titre", _ou_absent(item.titre))
    if item.numero or item.numero_tri is not None:
        suffixe = f" (tri : {item.numero_tri})" if item.numero_tri is not None else ""
        table.add_row("Numéro", f"{item.numero or '~'}{suffixe}")
    if item.date or item.annee:
        d = item.date or ""
        a = f" (année {item.annee})" if item.annee else ""
        table.add_row("Date", f"{d}{a}".strip() or "~")
    table.add_row("État", formater_etat(item.etat_catalogage))
    table.add_row("Type COAR", _ou_absent(item.type_coar))
    table.add_row("Langue", _ou_absent(item.langue))
    table.add_row("DOI Nakala", _ou_absent(item.doi_nakala))
    table.add_row("DOI collection Nakala", _ou_absent(item.doi_collection_nakala))
    table.add_row("Description", _ou_absent(item.description))
    if item.notes_internes:
        table.add_row("Notes internes", item.notes_internes)
    console.print(table)

    if item.metadonnees:
        console.print()
        console.print("[bold]Métadonnées custom[/bold]")
        for cle, val in sorted(item.metadonnees.items()):
            if isinstance(val, list):
                val_str = ", ".join(str(v) for v in val)
            elif isinstance(val, dict):
                val_str = json.dumps(val, ensure_ascii=False)
            else:
                val_str = str(val)
            console.print(f"  [cle]{cle}[/cle] : {val_str}")

    console.print()
    console.print(
        f"[bold]Présent dans {len(detail.collections)} collection(s)[/bold]"
    )
    for c in detail.collections:
        type_lbl = "miroir" if c.est_miroir else "libre"
        console.print(f"  • {c.titre} ([bold]{c.cote}[/bold]) [{type_lbl}]")

    console.print()
    console.print(f"[bold]Fichiers ({detail.nb_fichiers})[/bold]")
    if detail.fichiers:
        files_table = Table(show_header=True, header_style="cle", box=None, padding=(0, 2))
        files_table.add_column("#", justify="right")
        files_table.add_column("Nom")
        files_table.add_column("Type")
        files_table.add_column("Taille", justify="right")
        files_table.add_column("Dimensions", justify="right")
        files_table.add_column("Format")
        for f in detail.fichiers:
            files_table.add_row(
                str(f.ordre),
                f.nom_fichier,
                f.type_page,
                formater_taille_octets(f.taille_octets) if f.taille_octets else "—",
                f.dimensions or "—",
                f.format or "—",
            )
        console.print(files_table)

    if item.modifications:
        console.print()
        console.print(
            f"[bold]Dernières modifications ({min(len(item.modifications), max_evenements)})[/bold]"
        )
        recents = sorted(
            item.modifications, key=lambda m: m.modifie_le, reverse=True
        )[:max_evenements]
        for mod in recents:
            ts = mod.modifie_le.isoformat() if mod.modifie_le else "?"
            console.print(
                f"  [dim]{ts}[/dim] — {mod.champ} par {_ou_absent(mod.modifie_par)}"
            )

    console.print()
    _section_tracabilite_text(console, item)
    return buf.getvalue()


def rendu_json_item_detail(detail: ItemDetail) -> str:
    item = detail.item
    fonds = detail.fonds
    return json.dumps(
        {
            "type": "item_detail",
            "item": {
                "cote": item.cote,
                "fonds": {"cote": fonds.cote, "titre": fonds.titre},
                "titre": item.titre,
                "numero": item.numero,
                "numero_tri": item.numero_tri,
                "date": item.date,
                "annee": item.annee,
                "etat_catalogage": item.etat_catalogage,
                "type_coar": item.type_coar,
                "langue": item.langue,
                "doi_nakala": item.doi_nakala,
                "doi_collection_nakala": item.doi_collection_nakala,
                "description": item.description,
                "notes_internes": item.notes_internes,
                "metadonnees": item.metadonnees,
                "collections": [
                    {
                        "cote": c.cote,
                        "titre": c.titre,
                        "type_collection": c.type_collection,
                        "fonds_cote": c.fonds_cote,
                    }
                    for c in detail.collections
                ],
                "fichiers": [
                    {
                        "id": f.id,
                        "ordre": f.ordre,
                        "nom_fichier": f.nom_fichier,
                        "type_page": f.type_page,
                        "format": f.format,
                        "taille_octets": f.taille_octets,
                        "largeur_px": f.largeur_px,
                        "hauteur_px": f.hauteur_px,
                    }
                    for f in detail.fichiers
                ],
                "tracabilite": _dict_tracabilite(item),
            },
        },
        indent=2,
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Fichier
# ---------------------------------------------------------------------------


def rendu_text_fichier_detail(
    fichier: Fichier, *, max_evenements: int = _MAX_EVENEMENTS
) -> str:
    console, buf = _new_console()
    item = fichier.item
    fonds = item.fonds
    console.print(
        f"[bold cyan]Fichier {fichier.nom_fichier}[/bold cyan] "
        f"(id={fichier.id})"
    )
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cle")
    table.add_column()
    table.add_row("Item", f"{item.cote} — {_ou_absent(item.titre)}")
    table.add_row("Fonds", f"{fonds.titre} ({fonds.cote})")
    table.add_row("Ordre", str(fichier.ordre))
    table.add_row("Type page", fichier.type_page)
    table.add_row("Folio", _ou_absent(fichier.folio))
    console.print(table)

    console.print()
    console.print("[bold]Source originale[/bold]")
    src = Table(show_header=False, box=None, padding=(0, 2))
    src.add_column(style="cle")
    src.add_column()
    src.add_row("Racine", _ou_absent(fichier.racine))
    src.add_row("Chemin relatif", _ou_absent(fichier.chemin_relatif))
    src.add_row("URL Nakala (IIIF)", _ou_absent(fichier.iiif_url_nakala))
    console.print(src)

    console.print()
    console.print("[bold]Dérivés[/bold]")
    derives = [
        ("Aperçu", fichier.apercu_chemin),
        ("Vignette", fichier.vignette_chemin),
        ("DZI", fichier.dzi_chemin),
    ]
    for label, val in derives:
        symbole = "[succes]✓[/succes]" if val else "[dim]✗[/dim]"
        console.print(f"  {symbole} [cle]{label}[/cle] : {_ou_absent(val)}")

    console.print()
    console.print("[bold]Métadonnées techniques[/bold]")
    tech = Table(show_header=False, box=None, padding=(0, 2))
    tech.add_column(style="cle")
    tech.add_column()
    tech.add_row("Format", _ou_absent(fichier.format))
    if fichier.taille_octets:
        tech.add_row(
            "Taille",
            f"{formater_taille_octets(fichier.taille_octets)} "
            f"({fichier.taille_octets} octets)",
        )
    if fichier.largeur_px and fichier.hauteur_px:
        tech.add_row("Dimensions", f"{fichier.largeur_px}×{fichier.hauteur_px}")
    tech.add_row("SHA-256", _ou_absent(fichier.hash_sha256))
    tech.add_row("État", fichier.etat)
    tech.add_row("Dérivés générés", "oui" if fichier.derive_genere else "non")
    if fichier.notes_techniques:
        tech.add_row("Notes techniques", fichier.notes_techniques)
    console.print(tech)

    if fichier.operations:
        console.print()
        console.print(
            f"[bold]Dernières opérations "
            f"({min(len(fichier.operations), max_evenements)})[/bold]"
        )
        recents = sorted(
            fichier.operations, key=lambda o: o.execute_le, reverse=True
        )[:max_evenements]
        for op in recents:
            ts = op.execute_le.isoformat() if op.execute_le else "?"
            console.print(
                f"  [dim]{ts}[/dim] — {op.type_operation} "
                f"par {_ou_absent(op.execute_par)}"
            )

    console.print()
    console.print("[bold]Traçabilité[/bold]")
    console.print(
        f"  Ajouté le {fichier.ajoute_le.isoformat() if fichier.ajoute_le else '~'} "
        f"par {_ou_absent(fichier.ajoute_par)}"
    )
    if fichier.modifie_le:
        console.print(
            f"  Modifié le {fichier.modifie_le.isoformat()} (version {fichier.version})"
        )
    return buf.getvalue()


def rendu_json_fichier_detail(fichier: Fichier) -> str:
    item = fichier.item
    fonds = item.fonds
    return json.dumps(
        {
            "type": "fichier_detail",
            "fichier": {
                "id": fichier.id,
                "nom_fichier": fichier.nom_fichier,
                "ordre": fichier.ordre,
                "type_page": fichier.type_page,
                "folio": fichier.folio,
                "item": {"cote": item.cote, "titre": item.titre},
                "fonds": {"cote": fonds.cote, "titre": fonds.titre},
                "source": {
                    "racine": fichier.racine,
                    "chemin_relatif": fichier.chemin_relatif,
                    "iiif_url_nakala": fichier.iiif_url_nakala,
                },
                "derives": {
                    "apercu_chemin": fichier.apercu_chemin,
                    "vignette_chemin": fichier.vignette_chemin,
                    "dzi_chemin": fichier.dzi_chemin,
                    "derive_genere": fichier.derive_genere,
                },
                "technique": {
                    "format": fichier.format,
                    "taille_octets": fichier.taille_octets,
                    "largeur_px": fichier.largeur_px,
                    "hauteur_px": fichier.hauteur_px,
                    "hash_sha256": fichier.hash_sha256,
                    "etat": fichier.etat,
                    "notes_techniques": fichier.notes_techniques,
                },
                "tracabilite": {
                    "ajoute_le": fichier.ajoute_le.isoformat()
                    if fichier.ajoute_le
                    else None,
                    "ajoute_par": fichier.ajoute_par,
                    "modifie_le": fichier.modifie_le.isoformat()
                    if fichier.modifie_le
                    else None,
                    "version": fichier.version,
                },
            },
        },
        indent=2,
        ensure_ascii=False,
    )
