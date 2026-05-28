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
