"""Tests T1+T2 du scoping vocabulaire ↔ fonds (V0.9.x).

T1 : table de liaison `vocabulaire_fonds` (many-to-many) + service
`attacher_vocabulaire_au_fonds` / `detacher_vocabulaire_du_fonds`.

T2 : autocomplete `/api/vocabulaires/autocomplete?fichier_id=<id>`
filtre les `ValeurControlee` selon le fonds courant (vocab non
rattaché = global = visible partout ; vocab rattaché à A = visible
seulement sur les annotations d'items du fonds A).

Voir `docs/developpeurs/vocabulaire-scoping-future.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.api.services._erreurs import EntiteIntrouvable
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.vocabulaires_db import (
    FormulaireValeur,
    FormulaireVocabulaire,
    VocabulaireIntrouvable,
    ajouter_valeur,
    attacher_vocabulaire_au_fonds,
    creer_vocabulaire,
    detacher_vocabulaire_du_fonds,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fichier, Fonds, Vocabulaire


@pytest.fixture
def db_factory(tmp_path: Path):
    engine = creer_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture
def session(db_factory) -> Session:
    with db_factory() as s:
        yield s


def _slugifier(s: str) -> str:
    """Produit un code ASCII alphanumérique + underscores, pour
    passer le validator `_valider_valeur` qui refuse les accents."""
    import unicodedata
    norm = unicodedata.normalize("NFD", s)
    sans_accents = norm.encode("ascii", "ignore").decode("ascii")
    return "".join(c if c.isalnum() else "_" for c in sans_accents.lower())


def _vocab_avec_valeurs(s: Session, code: str, libelles: list[str]) -> Vocabulaire:
    vocab = creer_vocabulaire(s, FormulaireVocabulaire(code=code, libelle=code))
    for lib in libelles:
        ajouter_valeur(
            s,
            vocab.id,
            FormulaireValeur(code=_slugifier(lib), libelle=lib),
        )
    s.refresh(vocab)
    return vocab


# ---------------------------------------------------------------------------
# T1 — Service attacher / detacher
# ---------------------------------------------------------------------------


def test_attacher_vocabulaire_au_fonds(session: Session) -> None:
    hk = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    vocab = _vocab_avec_valeurs(session, "dessinateurs_hk", ["Reiser", "Cabu"])
    assert vocab.fonds_rattaches == []

    attacher_vocabulaire_au_fonds(session, vocab.id, hk.id)

    session.refresh(vocab)
    assert [f.cote for f in vocab.fonds_rattaches] == ["HK"]
    session.refresh(hk)
    assert vocab in hk.vocabulaires_rattaches


def test_attacher_idempotent(session: Session) -> None:
    """Ré-attacher le même couple → pas de doublon, no-op silencieux."""
    hk = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    vocab = _vocab_avec_valeurs(session, "v", ["A"])

    attacher_vocabulaire_au_fonds(session, vocab.id, hk.id)
    attacher_vocabulaire_au_fonds(session, vocab.id, hk.id)

    session.refresh(vocab)
    assert len(vocab.fonds_rattaches) == 1


def test_detacher_vocabulaire(session: Session) -> None:
    hk = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    vocab = _vocab_avec_valeurs(session, "v", ["A"])
    attacher_vocabulaire_au_fonds(session, vocab.id, hk.id)

    detacher_vocabulaire_du_fonds(session, vocab.id, hk.id)

    session.refresh(vocab)
    assert vocab.fonds_rattaches == []
    # Le vocab et le fonds existent toujours, seul le lien a disparu.
    assert session.get(Vocabulaire, vocab.id) is not None
    assert session.get(Fonds, hk.id) is not None


def test_detacher_idempotent(session: Session) -> None:
    """Détacher quand le lien n'existe pas → no-op."""
    hk = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    vocab = _vocab_avec_valeurs(session, "v", ["A"])

    detacher_vocabulaire_du_fonds(session, vocab.id, hk.id)  # pas d'erreur

    session.refresh(vocab)
    assert vocab.fonds_rattaches == []


def test_attacher_vocab_inconnu(session: Session) -> None:
    hk = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    with pytest.raises(VocabulaireIntrouvable):
        attacher_vocabulaire_au_fonds(session, 9999, hk.id)


def test_attacher_fonds_inconnu(session: Session) -> None:
    vocab = _vocab_avec_valeurs(session, "v", ["A"])
    with pytest.raises(EntiteIntrouvable):
        attacher_vocabulaire_au_fonds(session, vocab.id, 9999)


def test_cascade_suppression_fonds_retire_le_lien(session: Session) -> None:
    """Suppression d'un fonds → la junction est nettoyée (FK CASCADE),
    le vocab survit."""
    hk = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    vocab = _vocab_avec_valeurs(session, "v", ["A"])
    attacher_vocabulaire_au_fonds(session, vocab.id, hk.id)

    from archives_tool.api.services.fonds import supprimer_fonds
    supprimer_fonds(session, hk.id)

    # Le vocab existe toujours et n'a plus de fonds rattaché.
    vocab_relu = session.get(Vocabulaire, vocab.id)
    assert vocab_relu is not None
    assert vocab_relu.fonds_rattaches == []


def test_cascade_suppression_vocab_retire_le_lien(session: Session) -> None:
    """Suppression d'un vocab → la junction est nettoyée, le fonds
    survit avec ses autres vocabs."""
    hk = creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    v1 = _vocab_avec_valeurs(session, "v1", ["A"])
    v2 = _vocab_avec_valeurs(session, "v2", ["B"])
    attacher_vocabulaire_au_fonds(session, v1.id, hk.id)
    attacher_vocabulaire_au_fonds(session, v2.id, hk.id)

    from archives_tool.api.services.vocabulaires_db import supprimer_vocabulaire
    supprimer_vocabulaire(session, v1.id)

    session.refresh(hk)
    cotes_restantes = {v.code for v in hk.vocabulaires_rattaches}
    assert cotes_restantes == {"v2"}


# ---------------------------------------------------------------------------
# T2 — Autocomplete filtré par fichier_id
# ---------------------------------------------------------------------------


def _amorcer_pour_autocomplete(s: Session) -> tuple[int, int, int, int]:
    """2 fonds (HK, PF), 1 item dans chaque, 1 fichier par item.
    3 vocabs : `dess_hk` rattaché à HK, `dess_pf` rattaché à PF,
    `langues` global (non rattaché).

    Retourne `(fichier_hk_id, fichier_pf_id, vocab_hk_id, vocab_pf_id)`.
    """
    hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    pf = creer_fonds(s, FormulaireFonds(cote="PF", titre="Por Favor"))
    item_hk = creer_item(
        s, FormulaireItem(cote="HK-001", titre="N°1", fonds_id=hk.id)
    )
    item_pf = creer_item(
        s, FormulaireItem(cote="PF-001", titre="N°1", fonds_id=pf.id)
    )
    f_hk = Fichier(
        item_id=item_hk.id,
        racine="x",
        chemin_relatif="hk/01.tif",
        nom_fichier="hk-01.tif",
        ordre=1,
    )
    f_pf = Fichier(
        item_id=item_pf.id,
        racine="x",
        chemin_relatif="pf/01.tif",
        nom_fichier="pf-01.tif",
        ordre=1,
    )
    s.add_all([f_hk, f_pf])
    s.flush()

    v_hk = _vocab_avec_valeurs(s, "dess_hk", ["Reiser", "Cabu"])
    v_pf = _vocab_avec_valeurs(s, "dess_pf", ["Copi", "Forges"])
    v_global = _vocab_avec_valeurs(s, "langues", ["français", "espagnol"])

    attacher_vocabulaire_au_fonds(s, v_hk.id, hk.id)
    attacher_vocabulaire_au_fonds(s, v_pf.id, pf.id)
    # v_global non rattaché → visible partout.

    s.commit()
    return f_hk.id, f_pf.id, v_hk.id, v_pf.id


def test_autocomplete_sans_fichier_id_retourne_tout(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """Sans `?fichier_id=`, l'endpoint retombe sur le comportement
    actuel (toutes les valeurs actives, tous vocabs confondus).
    Cas d'usage : édition d'un champ personnalisé sur la fiche item,
    hors contexte annotation."""
    with db_factory() as s:
        _amorcer_pour_autocomplete(s)

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    client = TestClient(app)
    r = client.get("/api/vocabulaires/autocomplete")
    assert r.status_code == 200
    libelles = {v["libelle"] for v in r.json()["valeurs"]}
    # Toutes les valeurs, tous vocabs.
    assert {"Reiser", "Cabu", "Copi", "Forges", "français", "espagnol"} <= libelles


def test_autocomplete_avec_fichier_id_filtre_par_fonds(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """Avec `?fichier_id=<id>`, l'endpoint résout fichier → item →
    fonds, et retourne uniquement les vocabs rattachés à ce fonds
    + les vocabs globaux (non rattachés)."""
    with db_factory() as s:
        fid_hk, fid_pf, _, _ = _amorcer_pour_autocomplete(s)

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    client = TestClient(app)

    # Sur fichier HK : dess_hk + langues, pas dess_pf.
    r_hk = client.get(f"/api/vocabulaires/autocomplete?fichier_id={fid_hk}")
    assert r_hk.status_code == 200
    libelles_hk = {v["libelle"] for v in r_hk.json()["valeurs"]}
    assert "Reiser" in libelles_hk
    assert "Cabu" in libelles_hk
    assert "français" in libelles_hk  # global
    assert "Copi" not in libelles_hk  # rattaché à PF
    assert "Forges" not in libelles_hk

    # Sur fichier PF : dess_pf + langues, pas dess_hk.
    r_pf = client.get(f"/api/vocabulaires/autocomplete?fichier_id={fid_pf}")
    assert r_pf.status_code == 200
    libelles_pf = {v["libelle"] for v in r_pf.json()["valeurs"]}
    assert "Copi" in libelles_pf
    assert "Forges" in libelles_pf
    assert "espagnol" in libelles_pf  # global
    assert "Reiser" not in libelles_pf
    assert "Cabu" not in libelles_pf


def test_autocomplete_vocab_rattache_a_plusieurs_fonds(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """Cas réel : un vocab partagé entre 2 fonds (ex. « Onomatopées BD »
    sur PF + HK). Doit apparaître dans l'autocomplete des deux, mais
    pas dans celle d'un troisième fonds non rattaché."""
    with db_factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        pf = creer_fonds(s, FormulaireFonds(cote="PF", titre="Por Favor"))
        fa = creer_fonds(s, FormulaireFonds(cote="FA", titre="Fonds A"))
        item_hk = creer_item(
            s, FormulaireItem(cote="HK-001", titre="N°1", fonds_id=hk.id)
        )
        item_fa = creer_item(
            s, FormulaireItem(cote="FA-001", titre="N°1", fonds_id=fa.id)
        )
        f_hk = Fichier(
            item_id=item_hk.id, racine="x", chemin_relatif="hk/01.tif",
            nom_fichier="hk-01.tif", ordre=1,
        )
        f_fa = Fichier(
            item_id=item_fa.id, racine="x", chemin_relatif="fa/01.tif",
            nom_fichier="fa-01.tif", ordre=1,
        )
        s.add_all([f_hk, f_fa])
        s.flush()
        partage = _vocab_avec_valeurs(s, "onomatopees_bd", ["Bang", "Crash"])
        attacher_vocabulaire_au_fonds(s, partage.id, hk.id)
        attacher_vocabulaire_au_fonds(s, partage.id, pf.id)
        s.commit()
        fid_hk, fid_fa = f_hk.id, f_fa.id

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    client = TestClient(app)

    # Sur HK : visible (rattaché)
    r_hk = client.get(f"/api/vocabulaires/autocomplete?fichier_id={fid_hk}")
    libelles_hk = {v["libelle"] for v in r_hk.json()["valeurs"]}
    assert "Bang" in libelles_hk
    assert "Crash" in libelles_hk

    # Sur FA : invisible (vocab rattaché à HK+PF mais pas FA)
    r_fa = client.get(f"/api/vocabulaires/autocomplete?fichier_id={fid_fa}")
    libelles_fa = {v["libelle"] for v in r_fa.json()["valeurs"]}
    assert "Bang" not in libelles_fa
    assert "Crash" not in libelles_fa


def test_autocomplete_valeur_inactive_exclue(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """Une `ValeurControlee.actif=False` doit être absente du résultat,
    qu'on filtre par fonds ou pas. Garde-fou pour le `deprecier_valeur`
    qui peut être appelé via l'UI."""
    from archives_tool.api.services.vocabulaires_db import deprecier_valeur

    with db_factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        item = creer_item(
            s, FormulaireItem(cote="HK-001", titre="N°1", fonds_id=hk.id)
        )
        f = Fichier(
            item_id=item.id, racine="x", chemin_relatif="x.tif",
            nom_fichier="x.tif", ordre=1,
        )
        s.add(f)
        s.flush()
        v = _vocab_avec_valeurs(s, "v", ["Actif", "Deprecie"])
        # Récupère la valeur « Deprecie » et la déprécie.
        depreciee = next(val for val in v.valeurs if val.libelle == "Deprecie")
        deprecier_valeur(s, depreciee.id)
        s.commit()
        fid = f.id

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    client = TestClient(app)
    r = client.get(f"/api/vocabulaires/autocomplete?fichier_id={fid}")
    libelles = {v["libelle"] for v in r.json()["valeurs"]}
    assert "Actif" in libelles
    assert "Deprecie" not in libelles


# ---------------------------------------------------------------------------
# T3 — UI rattachement (routes POST + badges sur la liste)
# ---------------------------------------------------------------------------


def test_page_vocabulaire_detail_affiche_section_fonds(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """La page détail d'un vocab montre la section « Fonds rattachés »
    avec une case (form) par fonds de la base + état coché ou pas."""
    with db_factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        pf = creer_fonds(s, FormulaireFonds(cote="PF", titre="Por Favor"))
        v = _vocab_avec_valeurs(s, "test", ["A"])
        attacher_vocabulaire_au_fonds(s, v.id, pf.id)
        s.commit()
        vid = v.id

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app)
    r = client.get(f"/vocabulaires/{vid}")
    assert r.status_code == 200
    assert "Fonds rattachés" in r.text
    # Le fonds PF est coché (rattaché) → bouton détacher
    assert f'/vocabulaires/{vid}/fonds/PF/detacher' in r.text
    # Le fonds HK n'est pas coché → bouton attacher
    assert f'/vocabulaires/{vid}/fonds/HK/attacher' in r.text


def test_attacher_via_route(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    with db_factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        v = _vocab_avec_valeurs(s, "test", ["A"])
        s.commit()
        vid = v.id

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/vocabulaires/{vid}/fonds/HK/attacher")
    assert r.status_code == 303
    assert r.headers["location"] == f"/vocabulaires/{vid}"

    with db_factory() as s:
        v_relu = s.get(Vocabulaire, vid)
        assert [f.cote for f in v_relu.fonds_rattaches] == ["HK"]


def test_detacher_via_route(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    with db_factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        v = _vocab_avec_valeurs(s, "test", ["A"])
        attacher_vocabulaire_au_fonds(s, v.id, hk.id)
        s.commit()
        vid = v.id

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/vocabulaires/{vid}/fonds/HK/detacher")
    assert r.status_code == 303

    with db_factory() as s:
        v_relu = s.get(Vocabulaire, vid)
        assert v_relu.fonds_rattaches == []


def test_attacher_idempotent_via_route(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """POST attacher sur un vocab DÉJÀ rattaché → 303 sans erreur ni
    doublon (contrat idempotent du service, vérifié au niveau route)."""
    with db_factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        v = _vocab_avec_valeurs(s, "test", ["A"])
        attacher_vocabulaire_au_fonds(s, v.id, hk.id)
        s.commit()
        vid = v.id

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/vocabulaires/{vid}/fonds/HK/attacher")
    assert r.status_code == 303

    with db_factory() as s:
        v_relu = s.get(Vocabulaire, vid)
        # Toujours rattaché une seule fois — pas de doublon.
        assert [f.cote for f in v_relu.fonds_rattaches] == ["HK"]


def test_attacher_fonds_inconnu_404(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    with db_factory() as s:
        v = _vocab_avec_valeurs(s, "test", ["A"])
        s.commit()
        vid = v.id

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/vocabulaires/{vid}/fonds/ZZ/attacher")
    assert r.status_code == 404


def test_page_liste_vocab_affiche_badges(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """La page `/vocabulaires` affiche un badge « global » pour les
    vocabs sans rattachement, et « N fonds » pour les autres."""
    with db_factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        pf = creer_fonds(s, FormulaireFonds(cote="PF", titre="Por Favor"))
        v_global = _vocab_avec_valeurs(s, "global_vocab", ["A"])
        v_scope = _vocab_avec_valeurs(s, "scope_vocab", ["B"])
        attacher_vocabulaire_au_fonds(s, v_scope.id, hk.id)
        attacher_vocabulaire_au_fonds(s, v_scope.id, pf.id)
        s.commit()

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app)
    r = client.get("/vocabulaires")
    assert r.status_code == 200
    # Le vocab global est marqué « global »
    assert "global" in r.text
    # Le vocab rattaché à HK + PF est marqué « 2 fonds »
    assert "2 fonds" in r.text


def test_routes_attacher_detacher_bloquees_en_lecture_seule(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """Le middleware lecture_seule bloque POST en 423, donc les
    routes attacher/detacher renvoient 423 sans toucher à la base."""
    with db_factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        v = _vocab_avec_valeurs(s, "test", ["A"])
        s.commit()
        vid = v.id

    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  d: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))

    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/vocabulaires/{vid}/fonds/HK/attacher")
    assert r.status_code == 423
    # Vérifie en base que rien n'a bougé
    with db_factory() as s:
        v_relu = s.get(Vocabulaire, vid)
        assert v_relu.fonds_rattaches == []


def test_autocomplete_fichier_inconnu_retombe_sur_global(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """`?fichier_id=9999` (fichier inexistant) → l'endpoint ne crash
    pas, retourne toutes les valeurs (pas de fonds courant identifiable,
    on fallback au comportement sans filtre)."""
    with db_factory() as s:
        _amorcer_pour_autocomplete(s)

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    client = TestClient(app)
    r = client.get("/api/vocabulaires/autocomplete?fichier_id=9999")
    assert r.status_code == 200
    # Comportement global (tout retourné)
    libelles = {v["libelle"] for v in r.json()["valeurs"]}
    assert len(libelles) == 6


# ---------------------------------------------------------------------------
# T4 — Enrichissement rétroactif (routes UI)
# ---------------------------------------------------------------------------


def _amorcer_pour_enrichissement(s: Session) -> tuple[int, str, int, int]:
    """Crée un fonds HK avec un item + un fichier + une annotation
    libre « Copi » + un vocab « dessinateurs » avec valeur « Copi »
    portant l'URI Wikidata, rattaché à HK.

    Retourne `(vocab_id, fonds_cote, fichier_id, annotation_id)`.
    """
    from archives_tool.api.services.annotations import (
        FormulaireAnnotation, creer_annotation,
    )
    from archives_tool.models import ValeurControlee
    hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    item = creer_item(
        s, FormulaireItem(cote="HK-001", titre="N°1", fonds_id=hk.id),
    )
    fichier = Fichier(
        item_id=item.id, racine="x",
        chemin_relatif="hk/01.tif", nom_fichier="hk-01.tif", ordre=1,
    )
    s.add(fichier)
    s.flush()
    vocab = creer_vocabulaire(
        s, FormulaireVocabulaire(code="dessinateurs", libelle="Dessinateurs"),
    )
    s.flush()
    # Ajoute directement la ValeurControlee avec URI (le FormulaireValeur
    # standard la prend en charge, mais on évite la dépendance pour
    # rester local au helper).
    s.add(ValeurControlee(
        vocabulaire_id=vocab.id,
        code="copi",
        libelle="Copi",
        uri="https://www.wikidata.org/entity/Q733678",
        actif=True,
    ))
    attacher_vocabulaire_au_fonds(s, vocab.id, hk.id)
    ann = creer_annotation(
        s, fichier.id,
        FormulaireAnnotation(
            selecteur="xywh=0,0,100,100",
            corps=[
                {"type": "TextualBody", "purpose": "tagging", "value": "Copi"}
            ],
        ),
    )
    s.commit()
    return vocab.id, hk.cote, fichier.id, ann.id


def test_page_enrichissement_preview_affiche_matches(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """GET /vocabulaires/<id>/fonds/<cote>/enrichir rend la page
    preview avec le match Copi dans le tableau."""
    with db_factory() as s:
        vid, cote, _, ann_id = _amorcer_pour_enrichissement(s)

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app)
    r = client.get(f"/vocabulaires/{vid}/fonds/{cote}/enrichir")
    assert r.status_code == 200
    # Présence des éléments clés du rapport
    assert "1 match" in r.text or "1 match(es)" in r.text
    assert f"#{ann_id}" in r.text
    assert "Q733678" in r.text
    assert "Confirmer l'enrichissement" in r.text


def test_post_enrichissement_applique_et_redirige(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """POST /vocabulaires/<id>/fonds/<cote>/enrichir applique en base
    et redirige (303) vers la page vocab avec compteur en query string."""
    from archives_tool.models import AnnotationRegion

    with db_factory() as s:
        vid, cote, _, ann_id = _amorcer_pour_enrichissement(s)

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/vocabulaires/{vid}/fonds/{cote}/enrichir")
    assert r.status_code == 303
    assert f"/vocabulaires/{vid}" in r.headers["location"]
    assert "enrichi=1" in r.headers["location"]

    # Vérifie en base que le body est devenu SpecificResource
    with db_factory() as s:
        ann = s.get(AnnotationRegion, ann_id)
        assert ann is not None
        assert ann.corps[0]["type"] == "SpecificResource"
        assert (
            ann.corps[0]["source"]["id"]
            == "https://www.wikidata.org/entity/Q733678"
        )


def test_page_vocab_montre_bouton_enrichir_sur_fonds_rattache(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """Sur la page vocab détail, chaque fonds rattaché expose un lien
    « ⤴ Enrichir ». Les fonds non rattachés n'ont pas ce lien."""
    with db_factory() as s:
        vid, cote, _, _ = _amorcer_pour_enrichissement(s)
        # 2e fonds non rattaché
        creer_fonds(s, FormulaireFonds(cote="PF", titre="Por Favor"))
        s.commit()

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app)
    r = client.get(f"/vocabulaires/{vid}")
    assert r.status_code == 200
    # Lien enrichir sur HK (rattaché)
    assert f"/vocabulaires/{vid}/fonds/HK/enrichir" in r.text
    # Pas de lien enrichir pour PF (non rattaché)
    assert f"/vocabulaires/{vid}/fonds/PF/enrichir" not in r.text


def test_post_enrichissement_bloque_en_lecture_seule(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """Middleware lecture seule → 423 sur le POST, base inchangée."""
    from archives_tool.models import AnnotationRegion

    with db_factory() as s:
        vid, cote, _, ann_id = _amorcer_pour_enrichissement(s)

    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  d: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))

    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/vocabulaires/{vid}/fonds/{cote}/enrichir")
    assert r.status_code == 423

    with db_factory() as s:
        ann = s.get(AnnotationRegion, ann_id)
        assert ann is not None
        assert ann.corps[0]["type"] == "TextualBody"  # toujours libre


def test_page_enrichissement_preview_aucun_match(
    db_factory, monkeypatch, tmp_path: Path
) -> None:
    """Aucun tag libre dans le fonds → la page affiche un message
    « Aucune annotation à enrichir » sans bouton confirmer."""
    with db_factory() as s:
        hk = creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        v = _vocab_avec_valeurs(s, "vide", ["Untagged"])
        attacher_vocabulaire_au_fonds(s, v.id, hk.id)
        s.commit()
        vid = v.id

    monkeypatch.setenv("ARCHIVES_DB", str(tmp_path / "test.db"))
    client = TestClient(app)
    r = client.get(f"/vocabulaires/{vid}/fonds/HK/enrichir")
    assert r.status_code == 200
    assert "Aucune annotation" in r.text
    # Pas de bouton Confirmer (rien à appliquer)
    assert "Confirmer l'enrichissement" not in r.text
