"""Tests CLI `nakala comparer-fichiers` (palier P3+b).

Couvre la couche CLI (parsing args, formattage text/json, exit codes)
au-dessus du service `comparer_fichiers_item` déjà testé unitairement
dans `test_nakala_fichiers.py`. Patron aligné sur `test_cli_nakala_depot.py`
(monkeypatch `ClientLectureNakala` au module CLI).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import archives_tool.cli as cli_mod
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fichier

runner = CliRunner()


def _sha1(data: bytes) -> str:
    h = hashlib.sha1(usedforsecurity=False)  # noqa: S324
    h.update(data)
    return h.hexdigest()


class _FakeReadClient:
    """Client lecture stub : `lire_depot` renvoie `files` configurables.

    Variable de classe pour permettre aux tests de configurer le distant
    sans toucher au constructeur."""

    files: list[dict] = []

    def __init__(self, *a, **k) -> None:
        pass

    def __enter__(self) -> "_FakeReadClient":
        return self

    def __exit__(self, *a) -> bool:
        return False

    def lire_depot(self, doi: str) -> dict:
        return {"identifier": doi, "files": list(_FakeReadClient.files),
                "status": "pending", "metas": []}


@pytest.fixture(autouse=True)
def _mock_read_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeReadClient.files = []
    monkeypatch.setattr(cli_mod, "ClientLectureNakala", _FakeReadClient)


@pytest.fixture
def config_nakala(tmp_path: Path) -> Path:
    (tmp_path / "scans").mkdir(exist_ok=True)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "utilisateur": "T",
        "racines": {"scans": str(tmp_path / "scans")},
        "nakala": {"base_url": "https://apitest.nakala.fr", "api_key": "cle"},
    }), encoding="utf-8")
    return cfg


def _ecrire_binaire(tmp_path: Path, nom: str, contenu: bytes) -> str:
    """Écrit un binaire dans scans/, renvoie son sha1.

    Crée `scans/` s'il n'existe pas — la fixture `config_nakala` le
    crée habituellement, mais certains tests n'utilisent pas cette
    fixture (config ad-hoc) tout en appelant `_db_avec_item_depose`
    en amont du `runner.invoke`."""
    (tmp_path / "scans").mkdir(exist_ok=True)
    (tmp_path / "scans" / nom).write_bytes(contenu)
    return _sha1(contenu)


def _db_avec_item_depose(
    tmp_path: Path, *,
    contenu: bytes = b"\xff\xd8\xff init",
    doi_nakala: str = "10.34847/nkl.x1",
    sha1_nakala: str | None = None,
) -> tuple[Path, str]:
    """Crée base + fonds AS + item AS-001 avec doi posé et 1 fichier.
    Renvoie (chemin_db, sha1_du_binaire)."""
    sha1 = _ecrire_binaire(tmp_path, "x.jpg", contenu)
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    with creer_session_factory(engine)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="X", fonds_id=f.id,
        ))
        item.doi_nakala = doi_nakala
        s.add(Fichier(
            item_id=item.id, nom_fichier="x.jpg", racine="scans",
            chemin_relatif="x.jpg", ordre=1,
            sha1_nakala=sha1_nakala,
        ))
        s.commit()
    engine.dispose()
    return db, sha1


def _invoke(config: Path, db: Path, *args: str):
    return runner.invoke(app, [
        "nakala", "comparer-fichiers", "AS-001", "--fonds", "AS",
        *args,
        "--config", str(config), "--db-path", str(db),
    ])


# ---------------------------------------------------------------------------
# Cas nominaux : 5 catégories cote text
# ---------------------------------------------------------------------------


def test_text_inchange_aucun_changement(
    config_nakala: Path, tmp_path: Path,
) -> None:
    db, sha1 = _db_avec_item_depose(tmp_path, sha1_nakala=None)
    _FakeReadClient.files = [{"sha1": sha1, "name": "x.jpg"}]

    r = _invoke(config_nakala, db)
    assert r.exit_code == 0, r.output
    assert "Inchangés : 1" in r.output
    assert "Aucun changement" in r.output
    # Pas de section "Nouveaux" / "Modifies" si vide.
    assert "Nouveaux (à uploader)" not in r.output


def test_text_modifie_affiche_diff_sha1(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Fichier local change, sha1 distant connu (sha1_nakala) → modifié."""
    nouveau = b"\xff\xd8\xff NOUVEAU"
    sha1_ancien = "a" * 40
    db, sha1_local = _db_avec_item_depose(
        tmp_path, contenu=nouveau, sha1_nakala=sha1_ancien,
    )
    _FakeReadClient.files = [{"sha1": sha1_ancien, "name": "x.jpg"}]

    r = _invoke(config_nakala, db)
    assert r.exit_code == 0, r.output
    assert "Modifiés : 1" in r.output
    # Le format text affiche les 12 premiers char du sha1.
    assert sha1_local[:12] in r.output
    assert sha1_ancien[:12] in r.output


def test_text_nouveau_quand_sha1_distant_inconnu(
    config_nakala: Path, tmp_path: Path,
) -> None:
    db, _ = _db_avec_item_depose(tmp_path, sha1_nakala=None)
    # Distant vide → notre fichier est nouveau.
    _FakeReadClient.files = []

    r = _invoke(config_nakala, db)
    assert r.exit_code == 0, r.output
    assert "Nouveaux : 1" in r.output
    assert "Nouveaux (à uploader)" in r.output


def test_text_orphelin_distant_signale(
    config_nakala: Path, tmp_path: Path,
) -> None:
    db, sha1 = _db_avec_item_depose(tmp_path, sha1_nakala=None)
    sha1_orphan = "c" * 40
    _FakeReadClient.files = [
        {"sha1": sha1, "name": "x.jpg"},  # apparié → inchangé
        {"sha1": sha1_orphan, "name": "perdu.jpg"},  # orphelin
    ]

    r = _invoke(config_nakala, db)
    assert r.exit_code == 0, r.output
    assert "Orphelins distants : 1" in r.output
    assert "perdu.jpg" in r.output
    assert sha1_orphan[:12] in r.output


def test_text_nakala_only_signale_meme_si_aucun_changement(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Item à 1 fichier Nakala-only (pas de binaire local) : aucun
    changement à pousser, mais le CLI doit signaler le Nakala-only."""
    sha1_distant = "d" * 40
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    with creer_session_factory(engine)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="X", fonds_id=f.id,
        ))
        item.doi_nakala = "10.34847/nkl.x1"
        s.add(Fichier(
            item_id=item.id, nom_fichier="x.jpg", ordre=1,
            iiif_url_nakala="https://x/y",  # Nakala-only, pas de chemin local
            sha1_nakala=sha1_distant,
        ))
        s.commit()
    engine.dispose()
    _FakeReadClient.files = [{"sha1": sha1_distant, "name": "x.jpg"}]

    r = _invoke(config_nakala, db)
    assert r.exit_code == 0, r.output
    assert "Nakala-only sans local : 1" in r.output
    # Signal d'attention specifique (la garde `aucun_changement` + nakala_only).
    assert "Nakala-only sans local sont signalés" in r.output


# ---------------------------------------------------------------------------
# Format JSON
# ---------------------------------------------------------------------------


def test_json_serialise_les_5_categories(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Le format json produit une structure parsable + complète."""
    db, sha1 = _db_avec_item_depose(tmp_path, sha1_nakala=None)
    _FakeReadClient.files = [{"sha1": sha1, "name": "x.jpg"}]

    r = _invoke(config_nakala, db, "--format", "json")
    assert r.exit_code == 0, r.output

    # Output doit etre du JSON valide.
    data = json.loads(r.output)
    assert data["cote_item"] == "AS-001"
    assert data["doi"] == "10.34847/nkl.x1"
    assert data["aucun_changement"] is True
    assert len(data["inchanges"]) == 1
    assert data["inchanges"][0]["nom_fichier"] == "x.jpg"
    assert data["inchanges"][0]["sha1"] == sha1
    assert data["nouveaux"] == []
    assert data["modifies"] == []
    assert data["nakala_only_sans_local"] == []
    assert data["orphelins_distants"] == []


# ---------------------------------------------------------------------------
# Exit codes : cas d'erreur
# ---------------------------------------------------------------------------


def test_item_sans_doi_nakala_exit1(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Item sans doi_nakala → ComparaisonImpossible → exit 1 + message."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    with creer_session_factory(engine)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        creer_item(s, FormulaireItem(
            cote="AS-001", titre="X", fonds_id=f.id,
        ))
        # doi_nakala reste None
        s.commit()
    engine.dispose()

    r = _invoke(config_nakala, db)
    assert r.exit_code == 1, r.output
    assert "sans doi_nakala" in r.output.lower() or "impossible" in r.output.lower()


def test_item_introuvable_exit1(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Cote item inconnue → exit 1 standard."""
    db, _ = _db_avec_item_depose(tmp_path)

    r = runner.invoke(app, [
        "nakala", "comparer-fichiers", "INEXISTANT", "--fonds", "AS",
        "--config", str(config_nakala), "--db-path", str(db),
    ])
    assert r.exit_code == 1
    assert "introuvable" in r.output.lower()


def test_fonds_inconnu_exit1(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Cote fonds inconnue → exit 1 standard (resoudre_fonds_ou_sortie)."""
    db, _ = _db_avec_item_depose(tmp_path)

    r = runner.invoke(app, [
        "nakala", "comparer-fichiers", "AS-001", "--fonds", "INEXISTANT",
        "--config", str(config_nakala), "--db-path", str(db),
    ])
    assert r.exit_code == 1


def test_config_sans_section_nakala_exit2(tmp_path: Path) -> None:
    """Config locale sans section `nakala:` → exit 2 (saisie invalide)
    avec message clair. Pattern aligne sur `_client_nakala_ou_sortie`.

    Important : exit 2 (vs exit 1 pour les erreurs metier) signale
    une config a corriger, pas un cas d'erreur a gerer dans un
    pipeline."""
    db, _ = _db_avec_item_depose(tmp_path)
    cfg = tmp_path / "sans_nakala.yaml"
    cfg.write_text(yaml.safe_dump({
        "utilisateur": "T",
        "racines": {"scans": str(tmp_path / "scans")},
        # PAS de section `nakala:`
    }), encoding="utf-8")

    r = runner.invoke(app, [
        "nakala", "comparer-fichiers", "AS-001", "--fonds", "AS",
        "--config", str(cfg), "--db-path", str(db),
    ])
    assert r.exit_code == 2, r.output
    assert "nakala" in r.output.lower()


def test_config_sans_api_key_n_exit_pas_au_demarrage(tmp_path: Path) -> None:
    """Note de pattern projet : `_client_nakala_ou_sortie` (lecture) ne
    valide PAS `api_key`. Comportement aligné sur Nakala : les dépôts
    publics se lisent sans auth. Une 401 surviendra à `lire_depot` si
    le dépôt est pending/private.

    Ce test verrouille le pattern : la commande **ne quitte pas au
    démarrage** si api_key manque. Au futur, si on veut valider api_key
    pour comparer-fichiers (puisqu'on opère sur des dépôts utilisateur
    souvent pending), aligner aussi `nakala rafraichir` /
    `nakala montrer` pour cohérence — chantier transverse, pas
    spécifique à P3+b. Cf. dette signalee en commit message."""
    db, _ = _db_avec_item_depose(tmp_path)
    cfg = tmp_path / "sans_api_key.yaml"
    cfg.write_text(yaml.safe_dump({
        "utilisateur": "T",
        "racines": {"scans": str(tmp_path / "scans")},
        "nakala": {"base_url": "https://apitest.nakala.fr"},  # api_key manquant
    }), encoding="utf-8")

    r = runner.invoke(app, [
        "nakala", "comparer-fichiers", "AS-001", "--fonds", "AS",
        "--config", str(cfg), "--db-path", str(db),
    ])
    # PAS d'exit 2 (= validation api_key au démarrage), contrairement à
    # `_client_ecriture_nakala_ou_sortie`. La commande continue avec le
    # client lecture sans auth — en prod, lèverait 401 à `lire_depot`.
    assert r.exit_code != 2
    # Avec notre stub `_FakeReadClient`, le lire_depot reussit (pas
    # de check auth dans le mock) et la commande exit 0 normalement.
    assert r.exit_code == 0


# ===========================================================================
# CLI `nakala pousser-fichiers` (P3+c.2)
# ===========================================================================


class _FakeWriteClient:
    """Stub `NakalaEcritureClient` pour la CLI `pousser-fichiers`.

    Capture les uploads + PUT pour assertion. Renvoie un sha1 séquentiel
    `upload-N`. Auto-mocke via fixture `_mock_write_client` qui patche
    aussi `_client_ecriture_nakala_ou_sortie` (validation api_key)."""

    instances: list["_FakeWriteClient"] = []

    def __init__(self, *a, **k) -> None:
        self.uploads: list[str] = []
        self.uploads_sha1s: list[str] = []
        self.puts: list[dict] = []
        self.supprimes: list[str] = []
        _FakeWriteClient.instances.append(self)

    def __enter__(self) -> "_FakeWriteClient":
        return self

    def __exit__(self, *a) -> bool:
        return False

    def uploader_fichier(self, chemin, nom=None):
        from pathlib import Path as _P
        n = nom or _P(chemin).name
        self.uploads.append(n)
        sha1 = f"upload-{len(self.uploads)}"
        self.uploads_sha1s.append(sha1)
        return {"name": n, "sha1": sha1}

    def modifier_depot(self, identifiant, *, metas=None, files=None, status=None):
        self.puts.append({"id": identifiant, "files": files, "metas": metas,
                          "status": status})
        return {}

    def supprimer_upload(self, sha1):
        self.supprimes.append(sha1)


@pytest.fixture(autouse=True)
def _mock_write_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeWriteClient.instances.clear()
    monkeypatch.setattr(cli_mod, "NakalaEcritureClient", _FakeWriteClient)


def _invoke_pousser(config: Path, db: Path, *args: str):
    return runner.invoke(app, [
        "nakala", "pousser-fichiers", "AS-001", "--fonds", "AS",
        *args,
        "--config", str(config), "--db-path", str(db),
    ])


def test_pousser_dry_run_par_defaut(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Dry-run par défaut : pas d'écriture distante, plan affiché.

    Cas "modifié" : sha1_nakala stocké = sha1 distant connu, binaire
    local porte un sha1 différent → classé en modifié → plan rempli,
    pas d'orphelin (pas de refus)."""
    sha1_ancien = "a" * 40
    # Binaire local actuel != sha1_ancien stocké → modifié
    contenu = b"newer content"
    db, _ = _db_avec_item_depose(
        tmp_path, contenu=contenu, sha1_nakala=sha1_ancien,
    )
    _FakeReadClient.files = [{"sha1": sha1_ancien, "name": "x.jpg"}]

    r = _invoke_pousser(config_nakala, db)
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output
    assert "Plan" in r.output
    assert "Relancer avec --no-dry-run" in r.output
    # Aucun upload, aucun PUT
    assert _FakeWriteClient.instances == [] or _FakeWriteClient.instances[0].puts == []
    assert _FakeWriteClient.instances == [] or _FakeWriteClient.instances[0].uploads == []


def test_pousser_aucun_changement_no_op_exit_0(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Aucun changement → no-op clair, exit 0."""
    contenu = b"unchanged"
    sha1 = _sha1(contenu)
    db, _ = _db_avec_item_depose(
        tmp_path, contenu=contenu, sha1_nakala=sha1,
    )
    _FakeReadClient.files = [{"sha1": sha1, "name": "x.jpg"}]

    r = _invoke_pousser(config_nakala, db)
    assert r.exit_code == 0, r.output
    assert "Aucun changement" in r.output


def test_pousser_orphelins_sans_flag_exit_1(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Orphelins distants sans --retirer-orphelins → exit 1 + message."""
    contenu = b"local"
    sha1 = _sha1(contenu)
    sha1_orphan = "f" * 40
    db, _ = _db_avec_item_depose(
        tmp_path, contenu=contenu, sha1_nakala=sha1,
    )
    _FakeReadClient.files = [
        {"sha1": sha1, "name": "x.jpg"},
        {"sha1": sha1_orphan, "name": "perdu.jpg"},
    ]

    r = _invoke_pousser(config_nakala, db)
    assert r.exit_code == 1, r.output
    assert "orphelin" in r.output.lower()
    assert "--retirer-orphelins" in r.output


def test_pousser_avec_flag_orphelins_no_dry_run_effectue_put(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """--retirer-orphelins + --no-dry-run → upload nouveaux + PUT envoye."""
    # Item local avec 1 nouveau fichier, distant a 1 orphelin
    contenu_nouveau = b"new local"
    sha1_orphan = "e" * 40
    db, _ = _db_avec_item_depose(
        tmp_path, contenu=contenu_nouveau, sha1_nakala=None,
    )
    _FakeReadClient.files = [
        {"sha1": sha1_orphan, "name": "perdu.jpg"},
    ]

    r = _invoke_pousser(
        config_nakala, db, "--no-dry-run", "--retirer-orphelins",
    )
    assert r.exit_code == 0, r.output
    assert "APPLIQUÉ" in r.output
    # 1 upload (le nouveau), 1 PUT envoye
    inst = _FakeWriteClient.instances[0]
    assert inst.uploads == ["x.jpg"]
    assert len(inst.puts) == 1
    # files cible ne contient que le nouveau (l'orphelin est exclu)
    files_envoyes = inst.puts[0]["files"]
    sha1s_envoyes = [f["sha1"] for f in files_envoyes]
    assert sha1_orphan not in sha1s_envoyes


def test_pousser_format_json(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """--format json → sortie JSON parsable."""
    import json as _json
    contenu = b"unchanged"
    sha1 = _sha1(contenu)
    db, _ = _db_avec_item_depose(
        tmp_path, contenu=contenu, sha1_nakala=sha1,
    )
    _FakeReadClient.files = [{"sha1": sha1, "name": "x.jpg"}]

    r = _invoke_pousser(config_nakala, db, "--format", "json")
    assert r.exit_code == 0, r.output
    data = _json.loads(r.output)
    assert data["cote_item"] == "AS-001"
    assert data["dry_run"] is True
    assert data["raison"] == "aucun_changement"
    assert "plan" in data


def test_pousser_item_sans_doi_exit_1(
    config_nakala: Path, tmp_path: Path,
) -> None:
    """Item sans doi_nakala → DepotImpossible → exit 1."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    with creer_session_factory(engine)() as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        creer_item(s, FormulaireItem(cote="AS-001", titre="X", fonds_id=f.id))
        # doi_nakala reste None
        s.commit()
    engine.dispose()

    r = _invoke_pousser(config_nakala, db)
    assert r.exit_code == 1, r.output
    assert "doi_nakala" in r.output.lower() or "deposer" in r.output.lower()
