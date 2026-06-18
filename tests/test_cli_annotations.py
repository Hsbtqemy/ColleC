"""Tests de `archives-tool annotations enrichir` (T4 scoping vocabs)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from archives_tool.api.services.annotations import (
    FormulaireAnnotation,
    creer_annotation,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import AnnotationRegion, Base, Fichier
from archives_tool.models.profil import ValeurControlee, Vocabulaire

runner = CliRunner()


def _base_avec_annotation_libre(
    tmp_path: Path,
    *,
    vocab_uri: str | None = "https://www.wikidata.org/entity/Q733678",
) -> tuple[Path, int, int]:
    """Crée une base avec un fonds HK, 1 item, 1 fichier, 1 vocab
    « Dessinateurs » contenant « Copi » (URI configurable), et une
    annotation TextualBody « Copi » sur le fichier.

    Retourne (db_path, vocab_id, fonds_id) pour utilisation côté CLI.
    """
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        fonds = lire_fonds_par_cote(s, "HK")
        item = creer_item(
            s,
            FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id),
        )
        # Fichier minimum requis : un chemin relatif unique sous la
        # racine (les modèles imposent racine + chemin_relatif).
        fichier = Fichier(
            item_id=item.id,
            racine="masters",
            chemin_relatif="hk-001/page-1.tif",
            nom_fichier="page-1.tif",
            hash_sha256="0" * 64,
            ordre=1,
        )
        s.add(fichier)
        s.flush()
        # Vocabulaire « Dessinateurs » avec entrée Copi
        vocab = Vocabulaire(code="dessinateurs", libelle="Dessinateurs")
        s.add(vocab)
        s.flush()
        s.add(
            ValeurControlee(
                vocabulaire_id=vocab.id,
                code="copi",
                libelle="Copi",
                uri=vocab_uri,
                actif=True,
            )
        )
        # Annotation libre « Copi » avant rattachement vocab
        creer_annotation(
            s,
            fichier.id,
            FormulaireAnnotation(
                selecteur="xywh=0,0,100,100",
                corps=[{"type": "TextualBody", "purpose": "tagging", "value": "Copi"}],
            ),
        )
        s.commit()
        vid = vocab.id
        fid = fonds.id
    engine.dispose()
    return db, vid, fid


def test_cli_enrichir_dry_run_par_defaut(tmp_path: Path) -> None:
    """Sans `--appliquer`, la CLI fait un dry-run. Le rapport sort, la
    base reste inchangée."""
    db, _, _ = _base_avec_annotation_libre(tmp_path)
    result = runner.invoke(
        app,
        [
            "annotations",
            "enrichir",
            "--vocabulaire",
            "dessinateurs",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    assert "1 match" in result.output
    assert "Copi" in result.output
    assert "Q733678" in result.output
    assert "--appliquer" in result.output  # hint
    # Base inchangée
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        ann = s.query(AnnotationRegion).first()
        assert ann is not None
        assert ann.corps[0]["type"] == "TextualBody"
    engine.dispose()


def test_cli_enrichir_appliquer_modifie_base(tmp_path: Path) -> None:
    """Avec `--appliquer`, l'enrichissement écrit en base."""
    db, _, _ = _base_avec_annotation_libre(tmp_path)
    result = runner.invoke(
        app,
        [
            "annotations",
            "enrichir",
            "--vocabulaire",
            "dessinateurs",
            "--fonds",
            "HK",
            "--appliquer",
            "--utilisateur",
            "marie",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "APPLIQUÉ" in result.output
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        ann = s.query(AnnotationRegion).first()
        assert ann is not None
        assert ann.corps[0]["type"] == "SpecificResource"
        assert ann.corps[0]["source"]["id"] == "https://www.wikidata.org/entity/Q733678"
        assert ann.modifie_par == "marie"
    engine.dispose()


def test_cli_enrichir_vocab_introuvable(tmp_path: Path) -> None:
    """Vocab code inconnu → exit 1 + message d'erreur sur stderr."""
    db, _, _ = _base_avec_annotation_libre(tmp_path)
    result = runner.invoke(
        app,
        [
            "annotations",
            "enrichir",
            "--vocabulaire",
            "inexistant",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1
    assert "introuvable" in result.output.lower()


def test_cli_enrichir_fonds_introuvable(tmp_path: Path) -> None:
    """Fonds cote inconnue → exit 1."""
    db, _, _ = _base_avec_annotation_libre(tmp_path)
    result = runner.invoke(
        app,
        [
            "annotations",
            "enrichir",
            "--vocabulaire",
            "dessinateurs",
            "--fonds",
            "INCONNU",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1


def test_cli_enrichir_no_match_silencieux(tmp_path: Path) -> None:
    """Vocab sans URI → 0 match, exit 0 (rien à propager mais pas une
    erreur). La doc utilisateur affiche le rapport vide proprement."""
    db, _, _ = _base_avec_annotation_libre(tmp_path, vocab_uri=None)
    result = runner.invoke(
        app,
        [
            "annotations",
            "enrichir",
            "--vocabulaire",
            "dessinateurs",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "0 match" in result.output
