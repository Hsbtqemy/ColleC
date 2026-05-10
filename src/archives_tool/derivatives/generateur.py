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

from archives_tool.api.services.collections import lire_collection_par_cote
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.files.paths import resoudre_chemin
from archives_tool.models import (
    EtatFichier,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
)
from archives_tool.renamer import Perimetre

from .chemins import chemin_derive
from .rapport import RapportDerivation, ResultatDerive, StatutDerive

TAILLES_PAR_DEFAUT: dict[str, int] = {"vignette": 300, "apercu": 1200}
RACINE_CIBLE_DEFAUT = "miniatures"
QUALITE_JPEG = 85
DPI_PDF = 200


def _ouvrir_image(chemin: Path) -> Image.Image:
    """Ouvre l'image et libère immédiatement le handle disque.

    Pillow garde le fichier ouvert jusqu'à `load()` ; le retour ici
    fait `load()` puis `copy()` pour garantir qu'aucun lock ne traîne
    (essentiel sous Windows pour permettre rename/delete ultérieurs).
    Les PDF passent par PyMuPDF, première page rasterisée.
    """
    if chemin.suffix.lower() == ".pdf":
        import fitz  # gros module, import paresseux.

        with fitz.open(chemin) as doc:
            if doc.page_count == 0:
                raise ValueError("PDF sans page.")
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=DPI_PDF)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    with Image.open(chemin) as fichier_ouvert:
        fichier_ouvert.load()
        return fichier_ouvert.copy()


def _convertir_rgb(img: Image.Image) -> Image.Image:
    """RGBA composé sur fond blanc (préserve l'apparence vs écraser
    la transparence en noir) ; autres modes via `convert('RGB')`."""
    if img.mode == "RGB":
        return img
    if img.mode == "RGBA":
        fond = Image.new("RGB", img.size, (255, 255, 255))
        fond.paste(img, mask=img.getchannel("A"))
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
    # Réduction en cascade du plus grand au plus petit : chaque
    # thumbnail repart du résultat précédent plutôt que du
    # full-size, ce qui économise un resample LANCZOS sur les
    # tailles plus petites (gain réel à partir de ~10 MP en source).
    courant = img
    par_taille_decroissante = sorted(tailles_a_generer.items(), key=lambda kv: -kv[1])
    for nom_taille, taille_max in par_taille_decroissante:
        chemin_rel_cible = chemin_derive(fichier.chemin_relatif, nom_taille)
        chemin_abs = base_cible.joinpath(*chemin_rel_cible.split("/"))
        if not dry_run:
            chemin_abs.parent.mkdir(parents=True, exist_ok=True)
            courant = courant.copy()
            courant.thumbnail((taille_max, taille_max), Image.Resampling.LANCZOS)
            courant.save(chemin_abs, "JPEG", quality=QUALITE_JPEG)
        res.derives_crees[nom_taille] = chemin_rel_cible

    if not dry_run:
        fichier.derive_genere = True
        fichier.apercu_chemin = res.derives_crees.get("apercu")
        fichier.vignette_chemin = res.derives_crees.get("vignette")
        if fichier.largeur_px is None:
            fichier.largeur_px = res.largeur_originale
        if fichier.hauteur_px is None:
            fichier.hauteur_px = res.hauteur_originale

    return res


def _selectionner_fichiers(
    session: Session, perimetre: Perimetre
) -> list[Fichier]:
    """Charge les fichiers du périmètre. Les exceptions métier
    (`FondsIntrouvable`, `CollectionIntrouvable`) remontent telles
    quelles — au caller de décider quoi en faire.
    """
    base_stmt = (
        select(Fichier)
        .join(Item, Fichier.item_id == Item.id)
        .join(Fonds, Item.fonds_id == Fonds.id)
        .where(Fichier.etat == EtatFichier.ACTIF.value)
        .order_by(Fichier.id)
    )

    if perimetre.fichier_ids:
        stmt = base_stmt.where(Fichier.id.in_(perimetre.fichier_ids))
    elif perimetre.item_cote is not None:
        stmt = base_stmt.where(Item.cote == perimetre.item_cote)
        if perimetre.item_fonds_cote is not None:
            stmt = stmt.where(Fonds.cote == perimetre.item_fonds_cote)
    elif perimetre.collection_cote is not None:
        fonds_id_filtre = None
        if perimetre.collection_fonds_cote is not None:
            fonds_id_filtre = lire_fonds_par_cote(
                session, perimetre.collection_fonds_cote
            ).id
        col = lire_collection_par_cote(
            session, perimetre.collection_cote, fonds_id=fonds_id_filtre
        )
        stmt = base_stmt.where(
            Item.id.in_(
                select(ItemCollection.item_id).where(
                    ItemCollection.collection_id == col.id
                )
            )
        )
    else:
        stmt = base_stmt.where(Fonds.cote == perimetre.fonds_cote)

    return list(session.scalars(stmt).all())


def generer_derives(
    session: Session,
    *,
    perimetre: Perimetre,
    racines: Mapping[str, Path],
    racine_cible: str = RACINE_CIBLE_DEFAUT,
    force: bool = False,
    dry_run: bool = False,
    tailles: Mapping[str, int] | None = None,
) -> RapportDerivation:
    """Sélectionne les fichiers et génère leurs dérivés."""
    debut = time.perf_counter()
    rapport = RapportDerivation(dry_run=dry_run, racine_cible=racine_cible)

    fichiers = _selectionner_fichiers(session, perimetre)

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
    perimetre: Perimetre,
    racines: Mapping[str, Path],
    racine_cible: str = RACINE_CIBLE_DEFAUT,
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

    fichiers = _selectionner_fichiers(session, perimetre)

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
            fichier.apercu_chemin = None
            fichier.vignette_chemin = None
        rapport.comptabiliser(res)

    if not dry_run and rapport.nb_nettoyes > 0:
        session.commit()
    rapport.duree_secondes = time.perf_counter() - debut
    return rapport
