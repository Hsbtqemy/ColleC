"""Tests S7-UI — édition de la transcription par scan (`description_externe`).

Surface d'**édition** = viewer de catalogage (`/item/<cote>/visionneuse`,
même page que « Annoter »). Route `POST /item/<cote>/fichiers/<id>/transcription`.
La **liseuse l'affiche en lecture seule** (rendu dans le dispatcher
`visionneuse_consultation` → voyage avec le swap HTMX, contrairement à la
colonne méta gauche non swappée). httpx via TestClient, base SQLite isolée
par test (pas la demo module-scoped → pas de contamination puisque ces tests
MUTENT).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fichier, Item


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "t.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    with creer_session_factory(engine)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        it = creer_item(s, FormulaireItem(cote="AS-001", titre="x", fonds_id=f.id))
        autre = creer_item(s, FormulaireItem(cote="AS-002", titre="y", fonds_id=f.id))
        for nom, ordre in (("p1.jpg", 1), ("p2.jpg", 2)):
            s.add(Fichier(item_id=it.id, nom_fichier=nom, racine="scans",
                          chemin_relatif=nom, ordre=ordre))
        s.add(Fichier(item_id=autre.id, nom_fichier="o1.jpg", racine="scans",
                      chemin_relatif="o1.jpg", ordre=1))
        s.commit()
    engine.dispose()
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _fid(db: Path, cote: str, nom: str) -> int:
    eng = creer_engine(db)
    with creer_session_factory(eng)() as s:
        fid = s.scalar(
            select(Fichier.id).join(Item).where(
                Item.cote == cote, Fichier.nom_fichier == nom
            )
        )
    eng.dispose()
    return fid


def _description(db: Path, fid: int) -> str | None:
    eng = creer_engine(db)
    with creer_session_factory(eng)() as s:
        val = s.get(Fichier, fid).description_externe
    eng.dispose()
    return val


def _set_description(db: Path, fid: int, texte: str | None) -> None:
    eng = creer_engine(db)
    with creer_session_factory(eng)() as s:
        s.get(Fichier, fid).description_externe = texte
        s.commit()
    eng.dispose()


def test_post_transcription_enregistre_et_redirige(base: Path) -> None:
    fid = _fid(base, "AS-001", "p1.jpg")
    r = TestClient(app).post(
        f"/item/AS-001/fichiers/{fid}/transcription?fonds=AS",
        data={"texte": "Recto, page de titre.", "fichier_courant": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/item/AS-001/visionneuse" in r.headers["location"]
    assert "fichier_courant=1" in r.headers["location"]
    assert _description(base, fid) == "Recto, page de titre."


def test_post_transcription_vide_donne_none(base: Path) -> None:
    fid = _fid(base, "AS-001", "p1.jpg")
    client = TestClient(app)
    client.post(f"/item/AS-001/fichiers/{fid}/transcription?fonds=AS",
                data={"texte": "x", "fichier_courant": "1"}, follow_redirects=False)
    # Espaces seuls → strip → None (pas de transcription vide stockée).
    r2 = client.post(f"/item/AS-001/fichiers/{fid}/transcription?fonds=AS",
                     data={"texte": "   ", "fichier_courant": "1"}, follow_redirects=False)
    # 303 : le None vient bien du strip d'une requête ACCEPTÉE (pas d'un rejet).
    assert r2.status_code == 303
    assert _description(base, fid) is None


def test_post_transcription_cross_item_404(base: Path) -> None:
    """Anti-confused-deputy : un fichier_id d'un AUTRE item sous la cote
    AS-001 → 404, aucune écriture."""
    fid_autre = _fid(base, "AS-002", "o1.jpg")
    r = TestClient(app).post(
        f"/item/AS-001/fichiers/{fid_autre}/transcription?fonds=AS",
        data={"texte": "intrus", "fichier_courant": "1"}, follow_redirects=False,
    )
    assert r.status_code == 404
    assert _description(base, fid_autre) is None  # rien écrit


def test_viewer_catalogage_affiche_panneau_transcription(base: Path) -> None:
    """Le viewer de catalogage rend le panneau (form éditable) avec la
    valeur courante pré-remplie."""
    fid = _fid(base, "AS-001", "p1.jpg")
    eng = creer_engine(base)
    with creer_session_factory(eng)() as s:
        s.get(Fichier, fid).description_externe = "Transcription test ZQX"
        s.commit()
    eng.dispose()

    r = TestClient(app).get("/item/AS-001/visionneuse?fonds=AS&fichier_courant=1")
    assert r.status_code == 200
    assert "Transcription du scan" in r.text          # libellé du panneau
    assert "Transcription test ZQX" in r.text          # valeur pré-remplie
    assert f"/fichiers/{fid}/transcription" in r.text  # action du form
    assert 'name="texte"' in r.text  # surface ÉDITABLE (textarea), pas un simple affichage


def test_post_transcription_bloque_en_lecture_seule(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En mode lecture seule (config), le middleware bloque le POST en 423
    et rien n'est écrit."""
    import yaml

    cfg = tmp_path / "config_ro.yaml"
    cfg.write_text(yaml.safe_dump({
        "utilisateur": "test", "racines": {"scans": str(tmp_path)},
        "lecture_seule": True,
    }), encoding="utf-8")
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    fid = _fid(base, "AS-001", "p1.jpg")
    r = TestClient(app).post(
        f"/item/AS-001/fichiers/{fid}/transcription?fonds=AS",
        data={"texte": "interdit", "fichier_courant": "1"}, follow_redirects=False,
    )
    assert r.status_code == 423
    assert _description(base, fid) is None  # rien écrit


# ---------------------------------------------------------------------------
# Liseuse (consultation) — affichage LECTURE SEULE, synchronisé aux swaps HTMX
# ---------------------------------------------------------------------------


def test_liseuse_affiche_transcription_lecture_seule(base: Path) -> None:
    """La liseuse affiche la transcription du scan courant, en LECTURE SEULE
    (pas de form/textarea — l'édition vit sur le viewer de catalogage)."""
    fid = _fid(base, "AS-001", "p1.jpg")  # position 1 = scan courant par défaut
    _set_description(base, fid, "Transcription liseuse ABC")

    r = TestClient(app).get("/lire/AS/AS-001")
    assert r.status_code == 200
    assert "Transcription du scan" in r.text
    assert "Transcription liseuse ABC" in r.text
    # Lecture seule : aucune surface d'édition de transcription dans la liseuse.
    assert 'name="texte"' not in r.text
    assert "/transcription" not in r.text


def test_liseuse_partial_swap_inclut_la_transcription(base: Path) -> None:
    """Le partial de swap HTMX (navigation page) porte la transcription du
    NOUVEAU scan → reste synchronisée pendant la navigation (sinon la colonne
    méta gauche, non swappée, afficherait une transcription périmée)."""
    fid2 = _fid(base, "AS-001", "p2.jpg")
    _set_description(base, fid2, "Transcription du scan 2 XYZ")

    r = TestClient(app).get(f"/lire/AS/AS-001/visionneuse/{fid2}")
    assert r.status_code == 200
    assert "Transcription du scan 2 XYZ" in r.text  # voyage avec le swap


def test_liseuse_pas_de_panneau_si_aucune_transcription(base: Path) -> None:
    """Sans transcription, le panneau ne s'affiche pas (auto-masquage, comme
    le panneau annotations)."""
    r = TestClient(app).get("/lire/AS/AS-001")
    assert r.status_code == 200
    assert "Transcription du scan" not in r.text
