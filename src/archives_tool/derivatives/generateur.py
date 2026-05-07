"""Génération et nettoyage des dérivés.

Lecture via Pillow (formats raster) ou PyMuPDF (PDF, première page).
Sortie : JPEG qualité 85, recadré au côté long demandé via
`Image.thumbnail` (préserve le ratio).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.files.paths import resoudre_chemin
from archives_tool.models import Collection, EtatFichier, Fichier, Item

from .chemins import chemin_derive
from .rapport import RapportDerivation, ResultatDerive, StatutDerive

TAILLES_PAR_DEFAUT: dict[str, int] = {"vignette": 300, "apercu": 1200}
QUALITE_JPEG = 85
DPI_PDF = 200


def _ouvrir_image(chemin: Path) -> Image.Image:
    """Ouvre un fichier image et retourne un objet Pillow.

    Pour les PDF, rend la première page via PyMuPDF. Les autres
    formats passent directement par Pillow ; les TIFF multi-pages
    présentent leur première frame par défaut.
    """
    if chemin.suffix.lower() == ".pdf":
        import fitz  # PyMuPDF — import paresseux (gros module).

        with fitz.open(chemin) as doc:
            if doc.page_count == 0:
                raise ValueError("PDF sans page.")
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=DPI_PDF)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return Image.open(chemin)


def _convertir_rgb(img: Image.Image) -> Image.Image:
    """Garantit un mode RGB pour la sauvegarde JPEG.

    RGBA est composé sur fond blanc (préserve l'apparence visuelle
    plutôt que d'écraser la transparence en noir). Les autres modes
    (L, P, CMYK, …) passent par `convert('RGB')`.
    """
    if img.mode == "RGB":
        return img
    if img.mode == "RGBA":
        fond = Image.new("RGB", img.size, (255, 255, 255))
        fond.paste(img, mask=img.split()[-1])
        return fond
    return img.convert("RGB")


def generer_derives_pour_fichier(
    fichier: Fichier,
    racines: Mapping[str, Path],
    *,
    racine_cible: str,
    tailles: Mapping[str, int] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> ResultatDerive:
    """Génère les dérivés pour un fichier. Idempotent."""
    if not force and fichier.derive_genere:
        return ResultatDerive(fichier_id=fichier.id, statut=StatutDerive.DEJA_GENERE)

    if racine_cible not in racines:
        return ResultatDerive(
            fichier_id=fichier.id,
            statut=StatutDerive.ERREUR,
            message=f"Racine cible {racine_cible!r} non configurée.",
        )

    try:
        chemin_source = resoudre_chemin(racines, fichier.racine, fichier.chemin_relatif)
    except (KeyError, ValueError) as e:
        return ResultatDerive(
            fichier_id=fichier.id,
            statut=StatutDerive.ERREUR,
            message=str(e),
        )
    if not chemin_source.exists():
        return ResultatDerive(
            fichier_id=fichier.id,
            statut=StatutDerive.ERREUR,
            message=f"Source absente : {chemin_source}",
        )

    try:
        img_src = _ouvrir_image(chemin_source)
    except Exception as e:
        return ResultatDerive(
            fichier_id=fichier.id,
            statut=StatutDerive.ERREUR,
            message=f"Échec ouverture : {e}",
        )

    img = _convertir_rgb(img_src)
    res = ResultatDerive(
        fichier_id=fichier.id,
        statut=StatutDerive.GENERE,
        largeur_originale=img.width,
        hauteur_originale=img.height,
    )

    base_cible = racines[racine_cible]
    tailles_a_generer = tailles or TAILLES_PAR_DEFAUT
    for nom_taille, taille_max in tailles_a_generer.items():
        chemin_rel_cible = chemin_derive(fichier.chemin_relatif, nom_taille)
        chemin_abs = base_cible.joinpath(*chemin_rel_cible.split("/"))
        if not dry_run:
            chemin_abs.parent.mkdir(parents=True, exist_ok=True)
            copie = img.copy()
            copie.thumbnail((taille_max, taille_max), Image.Resampling.LANCZOS)
            copie.save(chemin_abs, "JPEG", quality=QUALITE_JPEG)
        res.derives_crees[nom_taille] = chemin_rel_cible

    if not dry_run:
        fichier.derive_genere = True
        if fichier.largeur_px is None:
            fichier.largeur_px = res.largeur_originale
        if fichier.hauteur_px is None:
            fichier.hauteur_px = res.hauteur_originale

    return res


def _ids_arbre(racine: Collection) -> list[int]:
    ids = [racine.id]
    a_visiter = list(racine.enfants)
    while a_visiter:
        n = a_visiter.pop(0)
        ids.append(n.id)
        a_visiter.extend(n.enfants)
    return ids


def _selectionner_fichiers(
    session: Session,
    *,
    collection_cote: str | None,
    item_cote: str | None,
    fichier_ids: list[int] | None,
    recursif: bool,
) -> list[Fichier]:
    stmt = select(Fichier).where(Fichier.etat == EtatFichier.ACTIF.value)

    if fichier_ids is not None:
        stmt = stmt.where(Fichier.id.in_(fichier_ids))
    elif item_cote is not None:
        stmt = stmt.join(Item, Fichier.item_id == Item.id).where(Item.cote == item_cote)
    elif collection_cote is not None:
        col = session.scalar(
            select(Collection).where(Collection.cote_collection == collection_cote)
        )
        if col is None:
            raise ValueError(f"Collection {collection_cote!r} introuvable.")
        ids = _ids_arbre(col) if recursif else [col.id]
        stmt = stmt.join(Item, Fichier.item_id == Item.id).where(
            Item.collection_id.in_(ids)
        )
    else:
        raise ValueError(
            "Aucun périmètre fourni : précisez collection_cote, item_cote ou fichier_ids."
        )
    stmt = stmt.order_by(Fichier.id)
    return list(session.scalars(stmt).all())


def generer_derives(
    session: Session,
    *,
    racines: Mapping[str, Path],
    racine_cible: str = "miniatures",
    collection_cote: str | None = None,
    item_cote: str | None = None,
    fichier_ids: list[int] | None = None,
    recursif: bool = False,
    force: bool = False,
    dry_run: bool = False,
    tailles: Mapping[str, int] | None = None,
) -> RapportDerivation:
    """Sélectionne les fichiers et génère leurs dérivés."""
    debut = time.perf_counter()
    rapport = RapportDerivation(dry_run=dry_run, racine_cible=racine_cible)

    fichiers = _selectionner_fichiers(
        session,
        collection_cote=collection_cote,
        item_cote=item_cote,
        fichier_ids=fichier_ids,
        recursif=recursif,
    )

    for fichier in fichiers:
        res = generer_derives_pour_fichier(
            fichier,
            racines,
            racine_cible=racine_cible,
            tailles=tailles,
            force=force,
            dry_run=dry_run,
        )
        rapport.comptabiliser(res)

    if not dry_run and rapport.nb_generes > 0:
        session.commit()
    rapport.duree_secondes = time.perf_counter() - debut
    return rapport


def nettoyer_derives(
    session: Session,
    *,
    racines: Mapping[str, Path],
    racine_cible: str = "miniatures",
    collection_cote: str | None = None,
    item_cote: str | None = None,
    fichier_ids: list[int] | None = None,
    recursif: bool = False,
    tailles: Mapping[str, int] | None = None,
    dry_run: bool = False,
) -> RapportDerivation:
    """Supprime les dérivés des fichiers ciblés et remet `derive_genere=False`."""
    debut = time.perf_counter()
    rapport = RapportDerivation(dry_run=dry_run, racine_cible=racine_cible)

    if racine_cible not in racines:
        raise ValueError(f"Racine cible {racine_cible!r} non configurée.")
    base_cible = racines[racine_cible]
    tailles_eff = tailles or TAILLES_PAR_DEFAUT

    fichiers = _selectionner_fichiers(
        session,
        collection_cote=collection_cote,
        item_cote=item_cote,
        fichier_ids=fichier_ids,
        recursif=recursif,
    )

    for fichier in fichiers:
        res = ResultatDerive(fichier_id=fichier.id, statut=StatutDerive.NETTOYE)
        for nom_taille in tailles_eff:
            chemin_rel = chemin_derive(fichier.chemin_relatif, nom_taille)
            chemin_abs = base_cible.joinpath(*chemin_rel.split("/"))
            if chemin_abs.exists():
                if not dry_run:
                    chemin_abs.unlink()
                res.derives_crees[nom_taille] = chemin_rel
        if not dry_run:
            fichier.derive_genere = False
        rapport.comptabiliser(res)

    if not dry_run and rapport.nb_nettoyes > 0:
        session.commit()
    rapport.duree_secondes = time.perf_counter() - debut
    return rapport
