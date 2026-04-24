"""Tests du loader YAML de profils d'import."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from archives_tool.profils import ProfilInvalide, charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


def test_charger_avec_chemin_absolu() -> None:
    chemin_abs = (FIXTURES / "cas_item_simple" / "profil.yaml").resolve()
    profil = charger_profil(chemin_abs)
    assert profil.collection.cote == "HK"


def test_charger_avec_chemin_relatif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Depuis n'importe quel cwd, le chargement doit fonctionner tant
    # que le chemin transmis résout bien le fichier ; on teste ici
    # un chemin relatif calculé par l'appelant.
    # FIXTURES = .../tests/fixtures/profils ; on vise la racine du repo
    # (parent du dossier tests/).
    racine_repo = FIXTURES.parent.parent.parent
    monkeypatch.chdir(racine_repo)
    profil = charger_profil(
        Path("tests") / "fixtures" / "profils" / "cas_item_simple" / "profil.yaml"
    )
    assert profil.collection.cote == "HK"


def test_fichier_inexistant(tmp_path: Path) -> None:
    with pytest.raises(ProfilInvalide) as exc:
        charger_profil(tmp_path / "n_existe_pas.yaml")
    assert "introuvable" in str(exc.value).lower()


def test_yaml_syntaxe_cassee() -> None:
    with pytest.raises(ProfilInvalide) as exc:
        charger_profil(FIXTURES / "invalides" / "yaml_casse.yaml")
    assert "yaml" in str(exc.value).lower()


def test_yaml_non_mapping(tmp_path: Path) -> None:
    chemin = tmp_path / "liste.yaml"
    chemin.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ProfilInvalide) as exc:
        charger_profil(chemin)
    assert "mapping" in str(exc.value).lower()


def test_normalisation_nfc_sur_chaines(tmp_path: Path) -> None:
    # On écrit un profil avec « café » en NFD ; après chargement,
    # les chaînes du Profil doivent être en NFC (invariant requis
    # par les opérations de chemin et de comparaison cross-OS).
    nfd = unicodedata.normalize("NFD", "café")
    assert nfd != "café"  # sanity check : la chaîne est bien NFD

    chemin = tmp_path / "profil.yaml"
    chemin.write_text(
        f"""
version_profil: 1
collection:
  cote: "X"
  titre: "{nfd}"
tableur:
  chemin: "x.csv"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(chemin)
    assert profil.collection.titre == "café"
    assert unicodedata.is_normalized("NFC", profil.collection.titre)
