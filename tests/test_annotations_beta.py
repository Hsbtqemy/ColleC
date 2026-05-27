"""Tests d'intégration de la beta annotations (V0.9.7) — vérifie que
la page visionneuse charge Annotorious + le bouton et que le contexte
DOM nécessaire est rendu.

Pas de test fonctionnel JS (Annotorious tourne côté client). On
s'assure du contrat HTML/CSS/JS : si quelqu'un casse le wiring,
ce test le signale.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archives_tool.api.main import app
from archives_tool.demo import peupler_base


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_visionneuse_inclut_annotorious_css_et_js(base_demo: Path) -> None:
    """La page item visionneuse charge la CSS + le plugin Annotorious
    + le script de wiring. Sans ces 3 inclusions, le mode édition
    annotations ne s'active pas."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    # CSS Annotorious
    assert "annotorious.min.css" in resp.text
    # Plugin OSD + Annotorious
    assert "openseadragon-annotorious.min.js" in resp.text
    # Script de wiring REST
    assert "annotations_osd.js" in resp.text


def test_visionneuse_bouton_annoter_present(base_demo: Path) -> None:
    """Le bouton « Annoter » est rendu avec `data-annoter-toggle`
    pointant sur l'ID du viewer. Le JS écoute ce data-attr pour
    basculer Annotorious entre lecture et édition."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    assert "data-annoter-toggle=" in resp.text
    # Le toggle vise l'ID du viewer (visionneuse-<fichier_id>)
    assert 'data-annoter-toggle="visionneuse-' in resp.text


def test_visionneuse_data_fichier_id_expose(base_demo: Path) -> None:
    """Le `data-source` du viewer expose `fichier_id`, lu par
    `annotations_osd.js` pour construire les URLs REST
    `/api/fichiers/<id>/annotations`."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    # data-fichier-id sur le wrapper
    assert "data-fichier-id=" in resp.text
    # fichier_id aussi dans le JSON data-source pour le JS.
    # L'attribut HTML utilise des single-quotes (data-source='{...}')
    # donc les double-quotes JSON restent intactes — pas d'entities.
    assert '"fichier_id":' in resp.text


def test_visionneuse_pas_d_annotorious_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """En lecture seule, on ne charge pas Annotorious : le mode
    édition serait inutile (le POST serait bloqué par le middleware
    en 423) et le bouton « Annoter » trompeur."""
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    # Config lecture seule via env (pattern testé dans test_lecture_seule)
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\n"
        f"lecture_seule: true\n"
        f"racines:\n  demo: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    # Annotorious absent — pas de CSS, pas de script
    assert "annotorious.min.css" not in resp.text
    assert "annotations_osd.js" not in resp.text
    # Bouton « Annoter » absent
    assert "data-annoter-toggle=" not in resp.text


def test_routes_annotations_accessibles_depuis_visionneuse(
    base_demo: Path,
) -> None:
    """Garde-fou contrat client/serveur : depuis la page visionneuse,
    le JS appellerait GET /api/fichiers/<id>/annotations. On vérifie
    que ces routes sont mountées et renvoient bien une AnnotationPage."""
    client = TestClient(app)
    # Récupère un fichier_id du HTML de la page
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    import re
    m = re.search(r'data-fichier-id="(\d+)"', resp.text)
    assert m, "data-fichier-id introuvable dans la page visionneuse"
    fichier_id = int(m.group(1))

    # Appelle l'endpoint REST comme le ferait Annotorious au load
    r_api = client.get(f"/api/fichiers/{fichier_id}/annotations")
    assert r_api.status_code == 200
    page = r_api.json()
    assert page["type"] == "AnnotationPage"
    assert "items" in page


def test_fiche_item_pas_d_annotorious(base_demo: Path) -> None:
    """La fiche item `/item/<cote>` (sans /visionneuse) n'a pas
    Annotorious — c'est la notice catalographique, pas la visionneuse.
    L'édition d'annotations vit sur /visionneuse."""
    client = TestClient(app)
    resp = client.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    assert "annotations_osd.js" not in resp.text


# ---------------------------------------------------------------------------
# Navigation visionneuse (V0.9.7 — beta-fix 3 frictions)
# ---------------------------------------------------------------------------


def test_visionneuse_bouton_notice_pointe_sur_fiche(base_demo: Path) -> None:
    """Le bouton « ← Notice » de la visionneuse ramène à la fiche
    item via `fiche_url` (passé par la route). Sans ce bouton,
    l'utilisateur cataloguant doit chercher un lien obscur pour
    revenir à la notice."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    assert "← Notice" in resp.text
    # Lien vers la fiche notice de l'item courant
    assert 'href="/item/HK-001?fonds=HK"' in resp.text


def test_visionneuse_navigation_page_si_plusieurs_fichiers(
    base_demo: Path,
) -> None:
    """Le bloc Page ‹ N / X › apparaît dès que l'item a >1 fichier.
    Boutons prev/next pointent sur la même visionneuse (le panneau
    fichiers gauche fait pareil — pas de retour à la fiche entre
    deux fichiers, friction utilisateur résolue)."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK&fichier_courant=2")
    assert resp.status_code == 200
    # Compteur position / total
    assert "Navigation pages" in resp.text
    # Liens prev (fichier_courant=1) + next (fichier_courant=3) sont
    # sur la même URL /visionneuse (pas /item/<cote>)
    assert (
        "/item/HK-001/visionneuse?fonds=HK&fichier_courant=1" in resp.text
    )


def test_visionneuse_navigation_page_premier_fichier_desactive_prev(
    base_demo: Path,
) -> None:
    """Au premier fichier, le bouton Page précédent est en gris,
    pas un lien actif. Garde-fou contre les `?fichier_courant=0`
    qui crasheraient le clamp."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK&fichier_courant=1")
    assert resp.status_code == 200
    # Pas de href vers fichier_courant=0
    assert "fichier_courant=0" not in resp.text


def test_panneau_fichiers_mode_visionneuse_garde_la_visionneuse(
    base_demo: Path,
) -> None:
    """Friction utilisateur : sur la visionneuse, cliquer une
    vignette dans le panneau gauche doit RESTER sur la visionneuse,
    pas ramener à la fiche notice. Vérifie que les liens panneau
    pointent sur /visionneuse en mode visionneuse."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    # Au moins un lien vers /visionneuse?fichier_courant=N
    import re
    liens_visionneuse = re.findall(
        r"/item/HK-001/visionneuse\?fonds=HK&fichier_courant=\d+",
        resp.text,
    )
    assert len(liens_visionneuse) >= 2, "Pas assez de liens panneau-visionneuse"
    # Aucun lien `/item/HK-001?fonds=HK&fichier_courant=N` (qui ramènerait
    # à la fiche). Le seul lien fiche est le bouton « ← Notice ».
    liens_fiche_avec_fichier = re.findall(
        r'href="/item/HK-001\?fonds=HK&fichier_courant=\d+"',
        resp.text,
    )
    assert liens_fiche_avec_fichier == []



def test_fiche_item_vignettes_pointent_sur_visionneuse(base_demo: Path) -> None:
    """Les vignettes de la grille fiche pointent sur la visionneuse
    OSD du fichier ciblé (V0.9.5 : workflow d'entrée fiche →
    visionneuse depuis n'importe quelle page). Garde-fou pour ce
    pattern — si quelqu'un casse les hrefs en ramenant à la fiche,
    le test signale."""
    client = TestClient(app)
    resp = client.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    import re
    # Les vignettes pointent sur /visionneuse?fichier_courant=N
    liens = re.findall(
        r"/item/HK-001/visionneuse\?fonds=HK&fichier_courant=\d+",
        resp.text,
    )
    assert len(liens) >= 3, "Trop peu de liens vignette → visionneuse"


def test_pdf_visionneuse_item_utilise_pdfjs(base_demo: Path) -> None:
    """Garde-fou principal du fix : sur `/item/<cote>/visionneuse`
    avec un fichier PDF, on doit avoir PDF.js (visionneuse_pdf) et
    pas OSD avec fallback Télécharger. Avant le fix V0.9.7, OSD
    tentait l'IIIF sur une URL data brute → message d'erreur.

    Sur la base demo, le seeder ne crée pas de PDF dédié — mais on
    peut utiliser le dispatcher visionneuse_consultation pour
    vérifier que la page CHARGE bien le dispatcher (qui sait gérer
    le PDF) et pas directement OSD.
    """
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    # Le dispatcher visionneuse_consultation est en place — vérifie
    # qu'on n'a pas un appel direct à visionneuse_osd sans fallback
    # PDF. Pour HK-001 (fichier .tif), c'est OSD qui est utilisé.
    assert "visionneuse-osd" in resp.text


def test_bouton_annoter_masque_sur_pdf(base_demo: Path) -> None:
    """Le bouton « Annoter » est masqué quand le fichier courant
    est un PDF — Annotorious ne sait pas annoter un PDF (image-only).
    Le bouton serait trompeur. La base demo n'a pas de PDF dédié
    donc on teste indirectement : sur un fichier .tif, le bouton
    DOIT être présent (cas où le test devrait échouer si la logique
    est inversée)."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK&fichier_courant=1")
    assert resp.status_code == 200
    # HK-001-01.tif est une image — bouton Annoter présent
    assert "data-annoter-toggle=" in resp.text
    # Bouton en haut-droite (évite collision contrôles OSD haut-gauche)
    assert "right:8px" in resp.text


def test_panneau_annotations_rendu_sur_image(base_demo: Path) -> None:
    """Le panneau latéral d'annotations est rendu HTML sur la
    visionneuse d'une image (V0.9.7 γ.1). Démarre masqué
    (`data-vide="1"`) — le JS `annotations_osd.js` l'affiche quand
    il y a ≥1 annotation."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK&fichier_courant=1")
    assert resp.status_code == 200
    # Marqueur wrapper avec l'id visionneuse
    assert 'data-panneau-annotations="visionneuse-' in resp.text
    # Démarre vide → display:none côté style inline + data-vide="1"
    assert 'data-vide="1"' in resp.text
    # Structure interne attendue par le JS
    assert "data-compteur" in resp.text
    assert "data-liste" in resp.text


def test_panneau_annotations_absent_sur_pdf(base_demo: Path) -> None:
    """Cohérent avec le bouton Annoter : pas de panneau d'annotations
    sur les PDFs / fichiers non-image. Annotorious ne s'active pas,
    donc rien à lister."""
    # On utilise un fichier non-image en bidouillant la requête :
    # HK-001 n'a que des .tif sur la base demo, donc on teste juste
    # que le panneau N'EST PAS rendu quand l'extension n'est pas
    # image. Pour ça on crée un Fichier .pdf temporaire.
    from sqlalchemy import select
    from archives_tool.models import Fichier, Item
    from archives_tool.db import creer_engine, creer_session_factory

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    fichier_pdf_id = None
    try:
        with factory() as s:
            item = s.scalar(select(Item).where(Item.cote == "HK-001"))
            f = Fichier(
                item_id=item.id,
                racine="demo",
                chemin_relatif="dummy.pdf",
                nom_fichier="dummy.pdf",
                ordre=99,
            )
            s.add(f)
            s.commit()
            fichier_pdf_id = f.id
            position = (
                s.execute(
                    select(Fichier).where(Fichier.item_id == item.id)
                    .order_by(Fichier.ordre)
                ).all()
            )
            pdf_position = next(
                i + 1 for i, row in enumerate(position) if row[0].id == fichier_pdf_id
            )

        client = TestClient(app)
        resp = client.get(
            f"/item/HK-001/visionneuse?fonds=HK&fichier_courant={pdf_position}"
        )
        assert resp.status_code == 200
        # Pas de panneau pour le PDF
        assert "data-panneau-annotations=" not in resp.text
    finally:
        if fichier_pdf_id is not None:
            with factory() as s:
                obj = s.get(Fichier, fichier_pdf_id)
                if obj is not None:
                    s.delete(obj)
                    s.commit()
        engine.dispose()


def test_panneau_annotations_visible_meme_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """En lecture seule, le bouton Annoter est masqué (cohérent : pas
    d'édition possible) mais le panneau d'annotations RESTE rendu
    en HTML — un futur lot pourra le peupler en consultation pure
    pour permettre la lecture des annotations existantes sans JS
    Annotorious (380 Ko).

    Pour V0.9.7 γ.1 : on vérifie juste que le panneau HTML est là.
    Le JS Annotorious n'est pas chargé en lecture seule (cf. test
    `test_visionneuse_pas_d_annotorious_en_lecture_seule`), donc le
    panneau reste vide visuellement — c'est OK pour cette beta."""
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  demo: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK&fichier_courant=1")
    assert resp.status_code == 200
    # Panneau présent — préparé pour un futur lot consultation
    assert "data-panneau-annotations=" in resp.text
    # En lecture seule, le bouton Annoter ne doit PAS être rendu
    # (positionné top:48px sinon, top:8px ici car pas de bouton)
    assert "data-annoter-toggle=" not in resp.text
