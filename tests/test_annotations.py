"""Tests des annotations W3C / IIIF (V0.9.7 alpha) — service + routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services.annotations import (
    AnnotationIntrouvable,
    AnnotationInvalide,
    FormulaireAnnotation,
    creer_annotation,
    lister_annotations_fichier,
    modifier_annotation,
    serialiser_w3c,
    supprimer_annotation,
)
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import AnnotationRegion, Fichier


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _premier_fichier_id(db_path: Path) -> int:
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        fid = s.scalar(select(Fichier.id).order_by(Fichier.id).limit(1))
    engine.dispose()
    assert fid is not None, "Demo doit avoir au moins un Fichier"
    return fid


# ---------------------------------------------------------------------------
# Service : creer / lire / modifier / supprimer
# ---------------------------------------------------------------------------


def test_creer_annotation_succes(base_demo: Path) -> None:
    """Cas nominal : créer une annotation taggée."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        formulaire = FormulaireAnnotation(
            selecteur="xywh=100,200,300,400",
            selecteur_type="fragment",
            corps=[
                {"type": "TextualBody", "purpose": "tagging", "value": "Copi"}
            ],
            motivation="tagging",
        )
        annotation = creer_annotation(s, fid, formulaire, cree_par="marie")
        assert annotation.id is not None
        assert annotation.fichier_id == fid
        assert annotation.selecteur == "xywh=100,200,300,400"
        assert annotation.cree_par == "marie"
        assert annotation.version == 1
        assert len(annotation.corps) == 1
    engine.dispose()


def test_creer_annotation_fichier_inconnu_refuse(base_demo: Path) -> None:
    """Fichier inexistant → AnnotationIntrouvable."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        formulaire = FormulaireAnnotation(
            selecteur="xywh=0,0,10,10",
            corps=[{"type": "TextualBody", "purpose": "tagging", "value": "x"}],
        )
        with pytest.raises(AnnotationIntrouvable):
            creer_annotation(s, 99999, formulaire)
    engine.dispose()


def test_creer_annotation_selecteur_vide_refuse(base_demo: Path) -> None:
    """Sélecteur vide → AnnotationInvalide."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        formulaire = FormulaireAnnotation(
            selecteur="   ",  # whitespace only
            corps=[{"type": "TextualBody", "value": "x"}],
        )
        with pytest.raises(AnnotationInvalide) as exc:
            creer_annotation(s, fid, formulaire)
        assert "selecteur" in exc.value.erreurs
    engine.dispose()


def test_creer_annotation_corps_vide_refuse(base_demo: Path) -> None:
    """Corps vide (sans body) → AnnotationInvalide. Une annotation
    qui ne dit rien n'apporte rien."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        formulaire = FormulaireAnnotation(
            selecteur="xywh=0,0,10,10",
            corps=[],
        )
        with pytest.raises(AnnotationInvalide) as exc:
            creer_annotation(s, fid, formulaire)
        assert "corps" in exc.value.erreurs
    engine.dispose()


def test_motivation_invalide_refuse() -> None:
    """Motivation hors W3C → ValueError au moment de la validation
    Pydantic (avant même d'atteindre le service)."""
    with pytest.raises(Exception):  # ValidationError Pydantic
        FormulaireAnnotation(
            selecteur="xywh=0,0,10,10",
            corps=[{"type": "TextualBody", "value": "x"}],
            motivation="inventee",  # pas dans MOTIVATIONS_W3C
        )


def test_selecteur_type_invalide_refuse() -> None:
    """selecteur_type hors {fragment, svg} → ValueError Pydantic."""
    with pytest.raises(Exception):
        FormulaireAnnotation(
            selecteur="xywh=0,0,10,10",
            selecteur_type="invente",
            corps=[{"type": "TextualBody", "value": "x"}],
        )


def test_lister_annotations_fichier(base_demo: Path) -> None:
    """Liste les annotations d'un fichier, tri chronologique."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        for i, nom in enumerate(["Copi", "Forges", "Reiser"]):
            creer_annotation(
                s, fid,
                FormulaireAnnotation(
                    selecteur=f"xywh={i*100},0,50,50",
                    corps=[
                        {"type": "TextualBody", "purpose": "tagging", "value": nom}
                    ],
                ),
            )
        annotations = lister_annotations_fichier(s, fid)
        assert len(annotations) == 3
        # Tri chronologique : Copi puis Forges puis Reiser
        valeurs = [a.corps[0]["value"] for a in annotations]
        assert valeurs == ["Copi", "Forges", "Reiser"]
    engine.dispose()


def test_modifier_annotation_succes(base_demo: Path) -> None:
    """Modification simple avec version correcte."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        a = creer_annotation(
            s, fid,
            FormulaireAnnotation(
                selecteur="xywh=0,0,10,10",
                corps=[{"type": "TextualBody", "value": "v1"}],
            ),
            cree_par="marie",
        )
        version_avant = a.version
        modifie = modifier_annotation(
            s, a.id,
            FormulaireAnnotation(
                selecteur="xywh=0,0,20,20",
                corps=[{"type": "TextualBody", "value": "v2"}],
                version=version_avant,
            ),
            modifie_par="hugo",
        )
        assert modifie.selecteur == "xywh=0,0,20,20"
        assert modifie.corps[0]["value"] == "v2"
        assert modifie.modifie_par == "hugo"
        assert modifie.version == version_avant + 1
    engine.dispose()


def test_modifier_annotation_conflit_version(base_demo: Path) -> None:
    """Version périmée → ConflitVersion."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        a = creer_annotation(
            s, fid,
            FormulaireAnnotation(
                selecteur="xywh=0,0,10,10",
                corps=[{"type": "TextualBody", "value": "x"}],
            ),
        )
        with pytest.raises(ConflitVersion):
            modifier_annotation(
                s, a.id,
                FormulaireAnnotation(
                    selecteur="xywh=0,0,20,20",
                    corps=[{"type": "TextualBody", "value": "x"}],
                    version=a.version + 999,  # version périmée
                ),
            )
    engine.dispose()


def test_supprimer_annotation_idempotent(base_demo: Path) -> None:
    """Supprimer une annotation puis ré-supprimer ne lève pas d'erreur."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        a = creer_annotation(
            s, fid,
            FormulaireAnnotation(
                selecteur="xywh=0,0,10,10",
                corps=[{"type": "TextualBody", "value": "x"}],
            ),
        )
        a_id = a.id
        supprimer_annotation(s, a_id)
        # ré-suppression OK
        supprimer_annotation(s, a_id)
        supprimer_annotation(s, 99999)
        # confirmation : plus en base
        assert s.get(AnnotationRegion, a_id) is None
    engine.dispose()


# ---------------------------------------------------------------------------
# Serialisation W3C
# ---------------------------------------------------------------------------


def test_serialiser_w3c_format_canonique(base_demo: Path) -> None:
    """Une annotation sérialisée doit avoir le format JSON-LD W3C
    canonique (@context, type, target/selector, body, motivation)."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        a = creer_annotation(
            s, fid,
            FormulaireAnnotation(
                selecteur="xywh=100,200,50,50",
                corps=[
                    {"type": "TextualBody", "purpose": "tagging", "value": "Copi"}
                ],
                motivation="identifying",
            ),
            cree_par="marie",
        )
        w3c = serialiser_w3c(a, base_url="https://test")
        assert w3c["@context"] == "http://www.w3.org/ns/anno.jsonld"
        assert w3c["type"] == "Annotation"
        assert w3c["motivation"] == "identifying"
        assert w3c["creator"] == "marie"
        assert w3c["target"]["selector"]["type"] == "FragmentSelector"
        assert w3c["target"]["selector"]["value"] == "xywh=100,200,50,50"
        assert "/api/fichiers/" in w3c["target"]["source"]
        assert isinstance(w3c["body"], list)
        assert w3c["body"][0]["value"] == "Copi"
    engine.dispose()


def test_serialiser_svg_selector(base_demo: Path) -> None:
    """selecteur_type='svg' produit un SvgSelector."""
    fid = _premier_fichier_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        a = creer_annotation(
            s, fid,
            FormulaireAnnotation(
                selecteur='<svg><polygon points="0,0 10,0 5,10"/></svg>',
                selecteur_type="svg",
                corps=[{"type": "TextualBody", "value": "polygone"}],
            ),
        )
        w3c = serialiser_w3c(a)
        assert w3c["target"]["selector"]["type"] == "SvgSelector"
    engine.dispose()


# ---------------------------------------------------------------------------
# Routes REST : GET / POST / PUT / DELETE
# ---------------------------------------------------------------------------


def test_route_get_liste_vide_renvoie_annotation_page(base_demo: Path) -> None:
    """GET sur un fichier sans annotation renvoie une AnnotationPage
    avec items=[]."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.get(f"/api/fichiers/{fid}/annotations")
    assert r.status_code == 200
    page = r.json()
    assert page["type"] == "AnnotationPage"
    assert page["items"] == []
    assert "/api/fichiers/" in page["id"]


def test_route_get_fichier_inconnu_404(base_demo: Path) -> None:
    """GET sur un fichier_id inconnu → 404 (pas une page vide)."""
    client = TestClient(app)
    r = client.get("/api/fichiers/99999/annotations")
    assert r.status_code == 404


def test_route_post_creer_annotation_forme_simple(base_demo: Path) -> None:
    """POST avec forme simple (champs plats). Réponse 201 + W3C complet."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/api/fichiers/{fid}/annotations",
        json={
            "selecteur": "xywh=10,20,30,40",
            "selecteur_type": "fragment",
            "corps": [
                {"type": "TextualBody", "purpose": "tagging", "value": "Forges"}
            ],
            "motivation": "tagging",
        },
    )
    assert r.status_code == 201, r.text
    w3c = r.json()
    assert w3c["type"] == "Annotation"
    assert w3c["target"]["selector"]["value"] == "xywh=10,20,30,40"
    assert w3c["body"][0]["value"] == "Forges"
    # Listing redonne 1 entrée
    r2 = client.get(f"/api/fichiers/{fid}/annotations")
    assert len(r2.json()["items"]) == 1


def test_route_post_creer_annotation_forme_w3c_native(base_demo: Path) -> None:
    """POST avec forme W3C native (target/body), comme un client
    Annotorious enverrait directement."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/api/fichiers/{fid}/annotations",
        json={
            "type": "Annotation",
            "motivation": "identifying",
            "target": {
                "selector": {
                    "type": "FragmentSelector",
                    "value": "xywh=50,50,100,100",
                }
            },
            "body": [
                {
                    "type": "SpecificResource",
                    "purpose": "identifying",
                    "source": "https://www.wikidata.org/entity/Q733678",
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    w3c = r.json()
    assert w3c["motivation"] == "identifying"
    assert (
        w3c["body"][0]["source"]
        == "https://www.wikidata.org/entity/Q733678"
    )


def test_route_post_payload_invalide_400(base_demo: Path) -> None:
    """POST avec corps vide → 400 + erreurs."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/api/fichiers/{fid}/annotations",
        json={
            "selecteur": "xywh=0,0,10,10",
            "corps": [],
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert "erreurs" in body
    assert "corps" in body["erreurs"]


def test_route_put_modifier_annotation(base_demo: Path) -> None:
    """PUT avec la bonne version → 200 + nouvelle annotation, version
    incrémentée."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/api/fichiers/{fid}/annotations",
        json={
            "selecteur": "xywh=0,0,10,10",
            "corps": [{"type": "TextualBody", "value": "v1"}],
        },
    )
    assert r.status_code == 201
    annotation_id = int(r.json()["id"].rsplit("/", 1)[-1])

    # Récupérer la version courante (1 à la création)
    r_put = client.put(
        f"/api/annotations/{annotation_id}",
        json={
            "selecteur": "xywh=0,0,20,20",
            "corps": [{"type": "TextualBody", "value": "v2"}],
            "version": 1,
        },
    )
    assert r_put.status_code == 200, r_put.text
    w3c = r_put.json()
    assert w3c["target"]["selector"]["value"] == "xywh=0,0,20,20"


def test_route_put_conflit_version_409(base_demo: Path) -> None:
    """PUT avec version périmée → 409 + détail."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/api/fichiers/{fid}/annotations",
        json={
            "selecteur": "xywh=0,0,10,10",
            "corps": [{"type": "TextualBody", "value": "v1"}],
        },
    )
    annotation_id = int(r.json()["id"].rsplit("/", 1)[-1])

    r_put = client.put(
        f"/api/annotations/{annotation_id}",
        json={
            "selecteur": "xywh=0,0,20,20",
            "corps": [{"type": "TextualBody", "value": "v2"}],
            "version": 999,
        },
    )
    assert r_put.status_code == 409


def test_route_delete_annotation_204(base_demo: Path) -> None:
    """DELETE renvoie 204, l'annotation disparait."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/api/fichiers/{fid}/annotations",
        json={
            "selecteur": "xywh=0,0,10,10",
            "corps": [{"type": "TextualBody", "value": "x"}],
        },
    )
    annotation_id = int(r.json()["id"].rsplit("/", 1)[-1])

    r_del = client.delete(f"/api/annotations/{annotation_id}")
    assert r_del.status_code == 204

    # Re-DELETE idempotent
    r_del2 = client.delete(f"/api/annotations/{annotation_id}")
    assert r_del2.status_code == 204

    # GET unitaire → 404 (n'existe plus)
    r_get = client.get(f"/api/annotations/{annotation_id}")
    assert r_get.status_code == 404


def test_route_get_unitaire_succes(base_demo: Path) -> None:
    """GET /api/annotations/{id} renvoie le W3C de l'annotation."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/api/fichiers/{fid}/annotations",
        json={
            "selecteur": "xywh=0,0,10,10",
            "corps": [{"type": "TextualBody", "value": "x"}],
        },
    )
    annotation_id = int(r.json()["id"].rsplit("/", 1)[-1])
    r_get = client.get(f"/api/annotations/{annotation_id}")
    assert r_get.status_code == 200
    assert r_get.json()["type"] == "Annotation"


def test_route_cascade_suppression_fichier(base_demo: Path) -> None:
    """Si on supprime le Fichier, ses annotations sont aussi
    supprimées (cascade ondelete + relationship cascade)."""
    fid = _premier_fichier_id(base_demo)
    client = TestClient(app)
    r = client.post(
        f"/api/fichiers/{fid}/annotations",
        json={
            "selecteur": "xywh=0,0,10,10",
            "corps": [{"type": "TextualBody", "value": "x"}],
        },
    )
    annotation_id = int(r.json()["id"].rsplit("/", 1)[-1])

    # Supprime le Fichier
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        f = s.get(Fichier, fid)
        s.delete(f)
        s.commit()
        # Annotation aussi disparue
        assert s.get(AnnotationRegion, annotation_id) is None
    engine.dispose()
