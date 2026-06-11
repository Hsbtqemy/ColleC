"""Écriture d'un :class:`TableurNakala` en CSV ou xlsx (Lot 1, T1.3).

Séparé de l'aplatissement (`tableur.py`, pur) : ici on touche le disque.

- CSV : `utf-8-sig` (Excel FR lit le BOM), séparateur `;` par défaut
  (préférence projet), `csv.DictWriter` qui quote automatiquement les
  champs contenant le séparateur.
- xlsx : openpyxl en mode `write_only` (les collections Nakala montent à
  plusieurs milliers de lignes — Aínsa ≈ 6000 données, davantage de
  fichiers — le mode classique chargerait tout en mémoire). Un bandeau
  « Collection : … » en première ligne, les entêtes en gras ensuite.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from archives_tool.external.nakala.tableur import TableurNakala

#: Caractères interdits par Excel dans un nom de feuille + longueur max.
_INTERDITS_FEUILLE = set('[]:*?/\\')
_TITRE_FEUILLE_MAX = 31

#: Types MIME pour servir les tableurs en téléchargement (route web).
MIME_CSV = "text/csv; charset=utf-8"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def vers_csv_bytes(tableur: TableurNakala, *, sep: str = ";") -> bytes:
    """Sérialise le tableur en CSV (`utf-8-sig`, séparateur `sep`) → octets.

    Variante mémoire de :func:`ecrire_csv`, réutilisée par la route web de
    téléchargement (pas de fichier temporaire). Le BOM `utf-8-sig` permet à
    Excel FR de lire les accents directement.
    """
    tampon = io.StringIO(newline="")
    writer = csv.DictWriter(
        tampon, fieldnames=tableur.colonnes, delimiter=sep, extrasaction="ignore"
    )
    writer.writeheader()
    for ligne in tableur.lignes:
        writer.writerow(ligne)
    return tampon.getvalue().encode("utf-8-sig")


def ecrire_csv(tableur: TableurNakala, chemin: Path, *, sep: str = ";") -> None:
    """Écrit le tableur en CSV (`utf-8-sig`, séparateur `sep`)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(vers_csv_bytes(tableur, sep=sep))


def _slug_feuille(titre: str) -> str:
    nettoye = "".join(c for c in (titre or "") if c not in _INTERDITS_FEUILLE)
    return nettoye[:_TITRE_FEUILLE_MAX] or "Nakala"


def _composer_classeur(
    tableur: TableurNakala, *, titre_collection: str | None
) -> Workbook:
    """Construit le classeur openpyxl (`write_only`, entêtes en gras)."""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title=_slug_feuille(titre_collection or "Nakala"))

    # Bandeau titre collection (1re ligne), entêtes en gras (2e ligne).
    bandeau = WriteOnlyCell(ws, value=f"Collection : {titre_collection or '—'}")
    bandeau.font = Font(bold=True, size=14)
    ws.append([bandeau])

    entetes = []
    for nom in tableur.colonnes:
        cell = WriteOnlyCell(ws, value=nom)
        cell.font = Font(bold=True)
        entetes.append(cell)
    ws.append(entetes)

    for ligne in tableur.lignes:
        ws.append([ligne.get(col, "") for col in tableur.colonnes])
    return wb


def vers_xlsx_bytes(
    tableur: TableurNakala, *, titre_collection: str | None = None
) -> bytes:
    """Sérialise le tableur en xlsx → octets (variante mémoire de
    :func:`ecrire_xlsx`, pour la route web)."""
    tampon = io.BytesIO()
    _composer_classeur(tableur, titre_collection=titre_collection).save(tampon)
    return tampon.getvalue()


def ecrire_xlsx(
    tableur: TableurNakala, chemin: Path, *, titre_collection: str | None = None
) -> None:
    """Écrit le tableur en xlsx (mode `write_only`, entêtes en gras)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(vers_xlsx_bytes(tableur, titre_collection=titre_collection))
