"""Tests de la CLI `archives-tool nakala` (P1d) — client Nakala mocké."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

import archives_tool.cli as cli_mod
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Item

runner = CliRunner()

_DOI = "10.34847/nkl.abcdef12"
_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"

_DEPOT_JSON = {
    "identifier": _DOI,
    "status": "published",
    "metas": [
        {"propertyUri": f"{_NKL}title", "value": "Titre Nakala", "lang": "fr"},
        {"propertyUri": f"{_NKL}created", "value": "1969-09"},
        {
            "propertyUri": f"{_NKL}type",
            "value": "http://purl.org/coar/resource_type/c_2fe3",
        },
        {"propertyUri": f"{_NKL}creator", "value": "Topor"},
        {"propertyUri": f"{_DCT}language", "value": "fr"},
    ],
    "files": [{"name": "p1.jpg", "sha1": "a", "size": 10, "mime": "image/jpeg"}],
}


class _FakeClient:
    """Stub de ClientLectureNakala : retourne le dépôt fixture."""

    base_url = "https://apitest.nakala.fr"

    def __init__(self, *a, **k) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *a) -> bool:
        return False

    def lire_depot(self, doi: str) -> dict:
        return _DEPOT_JSON

    def citation(self, doi: str) -> str:
        return "Topor (1969). Titre Nakala. Nakala."


@pytest.fixture(autouse=True)
def _mock_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "ClientLectureNakala", _FakeClient)


@pytest.fixture
def config_nakala(tmp_path: Path) -> Path:
    cfg = tmp_path / "config_local.yaml"
    cfg.write_text(
        "utilisateur: TestNakala\n"
        "nakala:\n"
        "  base_url: https://apitest.nakala.fr\n"
        "  api_key: cle-test\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def db_avec_fonds(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    with creer_session_factory(engine)() as s:
        creer_fonds(s, FormulaireFonds(cote="PF", titre="Por Favor"))
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


# ---------------------------------------------------------------------------
# montrer
# ---------------------------------------------------------------------------


def test_montrer_text(config_nakala: Path) -> None:
    r = runner.invoke(app, ["nakala", "montrer", _DOI, "--config", str(config_nakala)])
    assert r.exit_code == 0, r.output
    assert "Titre Nakala" in r.output
    assert _DOI in r.output


def test_montrer_json(config_nakala: Path) -> None:
    r = runner.invoke(
        app,
        ["nakala", "montrer", _DOI, "--config", str(config_nakala), "--format", "json"],
    )
    assert r.exit_code == 0, r.output
    charge = json.loads(r.output)
    assert charge["identifiant"] == _DOI
    assert charge["titre"] == "Titre Nakala"
    assert charge["langues"] == ["fra"]


def test_montrer_affiche_citation_si_publie(config_nakala: Path) -> None:
    """S4 : `montrer` d'un dépôt publié charge et affiche la citation."""
    r = runner.invoke(app, ["nakala", "montrer", _DOI, "--config", str(config_nakala)])
    assert r.exit_code == 0, r.output
    assert "Citation" in r.output and "Topor (1969)" in r.output


def test_citer_text(config_nakala: Path) -> None:
    r = runner.invoke(app, ["nakala", "citer", _DOI, "--config", str(config_nakala)])
    assert r.exit_code == 0, r.output
    assert "Topor (1969)" in r.output


def test_citer_json(config_nakala: Path) -> None:
    r = runner.invoke(
        app,
        ["nakala", "citer", _DOI, "--config", str(config_nakala), "--format", "json"],
    )
    assert r.exit_code == 0, r.output
    charge = json.loads(r.output)
    assert charge["doi"] == _DOI
    assert "Topor" in charge["citation"]


def test_citer_sans_config_nakala_exit2(tmp_path: Path) -> None:
    cfg = tmp_path / "config_local.yaml"
    cfg.write_text("utilisateur: X\n", encoding="utf-8")
    r = runner.invoke(app, ["nakala", "citer", _DOI, "--config", str(cfg)])
    assert r.exit_code == 2


def test_montrer_json_expose_liste_fichiers(
    config_nakala: Path,
) -> None:
    """Trou AC (passe 18) — `montrer --format json` doit exposer la
    LISTE des fichiers (pas seulement `nb_fichiers`). Sans cette
    expose, un script consommateur doit faire un 2e appel pour
    auditer la coherence locale ↔ Nakala."""
    r = runner.invoke(
        app,
        ["nakala", "montrer", _DOI, "--config", str(config_nakala), "--format", "json"],
    )
    assert r.exit_code == 0, r.output
    charge = json.loads(r.output)
    # nb_fichiers reste pour compat retro
    assert charge["nb_fichiers"] == 1
    # Liste exposee avec structure complete (5 champs FichierNakala)
    assert "fichiers" in charge
    assert len(charge["fichiers"]) == 1
    f = charge["fichiers"][0]
    assert f["nom"] == "p1.jpg"
    assert f["sha1"] == "a"
    assert f["taille"] == 10
    assert f["mime"] == "image/jpeg"
    assert f["embargo_actif"] is False


def test_montrer_text_liste_fichiers_si_peu(
    config_nakala: Path,
) -> None:
    """Trou AC — format text liste les fichiers si N ≤ 20. Le user
    voit directement le contenu sans devoir aller sur nakala.fr."""
    r = runner.invoke(app, ["nakala", "montrer", _DOI, "--config", str(config_nakala)])
    assert r.exit_code == 0, r.output
    # Nom du fichier dans la sortie
    assert "p1.jpg" in r.output
    # Sha tronque (12 premiers chars + ellipsis)
    # NOTE : sha "a" est < 12 chars, donc s'affiche brut + ellipsis.
    # On verifie juste que la ligne fichier est presente.
    assert "•" in r.output or "p1.jpg" in r.output


def test_montrer_sans_config_nakala_exit2(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("utilisateur: x\n", encoding="utf-8")  # pas de section nakala
    r = runner.invoke(app, ["nakala", "montrer", _DOI, "--config", str(cfg)])
    assert r.exit_code == 2
    assert "nakala" in r.output.lower()


# ---------------------------------------------------------------------------
# rapatrier
# ---------------------------------------------------------------------------


def test_rapatrier_dry_run_par_defaut(config_nakala: Path, db_avec_fonds: Path) -> None:
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier",
            _DOI,
            "--fonds",
            "PF",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output
    with _session(db_avec_fonds) as s:
        assert s.scalar(select(func.count(Item.id))) == 0  # rien créé


def test_rapatrier_cote_en_collision_erreur_propre(
    config_nakala: Path, db_avec_fonds: Path
) -> None:
    """Cote dérivée déjà prise par un autre item du fonds (DOI différent)
    → erreur propre (exit 1), pas de traceback."""
    with _session(db_avec_fonds) as s:
        f = lire_fonds_par_cote(s, "PF")
        creer_item(s, FormulaireItem(cote="abcdef12", titre="Autre", fonds_id=f.id))
        s.commit()
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier",
            _DOI,
            "--fonds",
            "PF",
            "--no-dry-run",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 1
    assert "cote" in r.output.lower()


def test_rapatrier_reel_cree_item(config_nakala: Path, db_avec_fonds: Path) -> None:
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier",
            _DOI,
            "--fonds",
            "PF",
            "--no-dry-run",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "créé" in r.output
    with _session(db_avec_fonds) as s:
        item = s.scalar(select(Item).where(Item.doi_nakala == _DOI))
        assert item is not None
        assert item.cote == "abcdef12"
        assert item.titre == "Titre Nakala"


# ---------------------------------------------------------------------------
# rafraichir
# ---------------------------------------------------------------------------


def test_rafraichir_dry_run_montre_diff(
    config_nakala: Path, db_avec_fonds: Path
) -> None:
    with _session(db_avec_fonds) as s:
        f = lire_fonds_par_cote(s, "PF")
        item = creer_item(
            s, FormulaireItem(cote="abcdef12", titre="Ancien", fonds_id=f.id)
        )
        item.doi_nakala = _DOI
        s.commit()

    r = runner.invoke(
        app,
        [
            "nakala",
            "rafraichir",
            _DOI,
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "Ancien" in r.output and "Titre Nakala" in r.output  # diff titre
    assert "DRY-RUN" in r.output
    with _session(db_avec_fonds) as s:
        item = s.scalar(select(Item).where(Item.doi_nakala == _DOI))
        assert item.titre == "Ancien"  # pas appliqué


def test_rafraichir_sans_item_lie_exit1(
    config_nakala: Path, db_avec_fonds: Path
) -> None:
    r = runner.invoke(
        app,
        [
            "nakala",
            "rafraichir",
            _DOI,
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 1
    assert "Aucun item" in r.output or "rapatrier" in r.output.lower()


# ---------------------------------------------------------------------------
# Passe 19 — Dette AD : --format json sur commandes destructives Item
# ---------------------------------------------------------------------------


def test_rapatrier_format_json_dry_run(
    config_nakala: Path, db_avec_fonds: Path
) -> None:
    """`rapatrier --format json` (dry-run) : 8 cles minimum."""
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier",
            _DOI,
            "--fonds",
            "PF",
            "--format",
            "json",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["doi"] == _DOI
    assert data["cote"] == "abcdef12"  # derivee du DOI
    assert data["fonds_cote"] == "PF"
    assert data["dry_run"] is True
    assert data["deja_existant"] is False
    assert data["item_id"] is None
    assert data["nb_fichiers"] == 0


def test_rapatrier_format_json_reel(config_nakala: Path, db_avec_fonds: Path) -> None:
    """`rapatrier --no-dry-run --format json` : item_id pose, nb_fichiers
    reflet de la materialisation."""
    r = runner.invoke(
        app,
        [
            "nakala",
            "rapatrier",
            _DOI,
            "--fonds",
            "PF",
            "--no-dry-run",
            "--format",
            "json",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["dry_run"] is False
    assert data["item_id"] is not None
    # `_DEPOT_JSON.files` contient 1 fichier → materialise
    assert data["nb_fichiers"] == 1


def test_rafraichir_format_json_dry_run_montre_diff(
    config_nakala: Path, db_avec_fonds: Path
) -> None:
    """`rafraichir --format json` : structure de diff complete."""
    with _session(db_avec_fonds) as s:
        f = lire_fonds_par_cote(s, "PF")
        item = creer_item(
            s, FormulaireItem(cote="abcdef12", titre="Ancien", fonds_id=f.id)
        )
        item.doi_nakala = _DOI
        s.commit()

    r = runner.invoke(
        app,
        [
            "nakala",
            "rafraichir",
            _DOI,
            "--format",
            "json",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["doi"] == _DOI
    assert data["item_cote"] == "abcdef12"
    assert data["dry_run"] is True
    assert data["applique"] is False
    assert data["a_des_changements"] is True
    # Diffs sont une liste de {champ, avant, apres}
    assert isinstance(data["diffs"], list)
    assert len(data["diffs"]) > 0
    diff_titre = next((d for d in data["diffs"] if d["champ"] == "titre"), None)
    assert diff_titre is not None
    assert diff_titre["avant"] == "Ancien"
    assert diff_titre["apres"] == "Titre Nakala"


# ---------------------------------------------------------------------------
# pousser (metas) + publier — necessitent client ECRITURE en plus
# Le mock du client ecriture n'est pas dans test_cli_nakala.py - on
# documente que la couverture est dans test_nakala_web_push pour les
# routes web et serait dupliquee inutilement ici. Garde-fou minimal :
# verifier que --format est accepte sans crash sur dry-run.
# ---------------------------------------------------------------------------


def test_pousser_format_accepte(config_nakala: Path, db_avec_fonds: Path) -> None:
    """Garde-fou minimal : `pousser --format json` est accepte (parse
    de l'option). Le scenario complet est couvert par les tests
    services + web."""
    # Sans item lie au DOI → exit 1 mais le parse de --format passe
    r = runner.invoke(
        app,
        [
            "nakala",
            "pousser",
            "PF-001",
            "--fonds",
            "PF",
            "--format",
            "json",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    # Exit 1 attendu (item introuvable) - ce qui compte : pas de
    # crash sur --format inconnue.
    assert r.exit_code == 1
    # L'option n'a pas leve d'erreur Click
    assert "Invalid value" not in r.output


def test_publier_format_accepte(config_nakala: Path, db_avec_fonds: Path) -> None:
    """Symetrie : `publier --format json` accepte (parse OK)."""
    r = runner.invoke(
        app,
        [
            "nakala",
            "publier",
            "PF-001",
            "--fonds",
            "PF",
            "--format",
            "json",
            "--config",
            str(config_nakala),
            "--db-path",
            str(db_avec_fonds),
        ],
    )
    assert r.exit_code == 1
    assert "Invalid value" not in r.output
