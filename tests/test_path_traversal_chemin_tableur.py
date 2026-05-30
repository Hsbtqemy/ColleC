"""Garde-fou path traversal sur `_chemin_tableur_absolu`.

Trouve a l'audit security import_assistant V0.9.x : la fonction
construisait `RACINE_IMPORT_TMP / session.chemin_tableur` sans
valider la valeur DB. Si compromise (faille SQL injection ailleurs,
edition manuelle), un chemin absolu ou contenant `..` :
- via `abandonner_session_import` → `chemin.unlink()` sur fichier
  systeme (suppression !).
- via `composer_profil` → pandas parse contenu hors racine.

Fix : valider_chemin_relatif (rejette `..` et absolu) +
is_relative_to apres resolve. Pattern identique a derives.py /
servir_fichier_item.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from archives_tool.api.services.import_web import (
    RACINE_IMPORT_TMP,
    _chemin_tableur_absolu,
)
from archives_tool.models import SessionImport


class _FauxSession:
    """Stub minimal de SessionImport pour bypasser la DB."""

    def __init__(self, chemin_tableur: str | None) -> None:
        self.chemin_tableur = chemin_tableur


def test_chemin_tableur_absolu_chemin_legitime(tmp_path: Path) -> None:
    """Cas nominal : `chemin_tableur = "session_42.xlsx"` (forme posee
    par attacher_tableur) → retourne le path absolu sous RACINE_IMPORT_TMP."""
    RACINE_IMPORT_TMP.mkdir(parents=True, exist_ok=True)
    s = _FauxSession("session_42.xlsx")
    cible = _chemin_tableur_absolu(s)
    assert cible is not None
    # Resoud bien sous la racine
    assert cible.is_relative_to(RACINE_IMPORT_TMP.resolve())
    assert cible.name == "session_42.xlsx"


def test_chemin_tableur_absolu_none_si_pas_de_chemin() -> None:
    """`chemin_tableur = None` → retourne None (cas normal d'une
    session creee mais sans tableur encore uploade)."""
    s = _FauxSession(None)
    assert _chemin_tableur_absolu(s) is None
    s2 = _FauxSession("")
    assert _chemin_tableur_absolu(s2) is None


def test_chemin_tableur_absolu_refuse_chemin_absolu() -> None:
    """DB compromise avec chemin absolu (`/etc/passwd`) → None plutot
    que le fichier systeme."""
    s = _FauxSession("/etc/passwd")
    cible = _chemin_tableur_absolu(s)
    assert cible is None


def test_chemin_tableur_absolu_refuse_dotdot() -> None:
    """DB compromise avec `..` → None plutot que sortir de la racine."""
    s = _FauxSession("../../../etc/passwd")
    assert _chemin_tableur_absolu(s) is None
    # Aussi : passe la garde 1 (pas de `..` au top mais sortir via
    # mid-segment) → garde 2 catch.
    s2 = _FauxSession("foo/../../../etc/passwd")
    assert _chemin_tableur_absolu(s2) is None


def test_chemin_tableur_absolu_refuse_chemin_windows_absolu() -> None:
    """`C:\\Windows\\System32\\config\\SAM` (chemin Windows absolu) :
    la garde 1 ne le detecte pas comme absolu en POSIX, mais la garde 2
    (`is_relative_to`) catche apres resolution Windows."""
    s = _FauxSession("C:\\Windows\\System32\\config\\SAM")
    cible = _chemin_tableur_absolu(s)
    # Sur Linux ce sera un nom de fichier exotique qui ne sort pas de
    # la racine (autorise). Sur Windows, garde 2 le rejette. Le contrat
    # est : si on retourne quelque chose, c'est SOUS la racine.
    if cible is not None:
        assert cible.is_relative_to(RACINE_IMPORT_TMP.resolve())


def test_construire_mapping_simple_passe_par_le_helper_securise() -> None:
    """Verifie via source code que `construire_mapping_depuis_simple`
    n'utilise PAS `RACINE_IMPORT_TMP / session.chemin_tableur` direct
    mais passe par `_chemin_tableur_absolu` (helper securise).

    Audit V0.9.x avait trouve que la ligne 651 reconstruisait le path
    sans validation, bypassant la garde path traversal du helper.
    Test de regression : si quelqu'un re-introduit le bypass, il
    echoue."""
    chemin = Path("src/archives_tool/api/services/import_web.py")
    contenu = chemin.read_text(encoding="utf-8")

    # Recherche `RACINE_IMPORT_TMP / session.chemin_tableur` hors
    # `_chemin_tableur_absolu` (le helper lui-meme).
    import re

    # Extrait toutes les occurences de RACINE_IMPORT_TMP / X
    occurrences = re.findall(
        r"RACINE_IMPORT_TMP\s*/\s*([^\s,)]+)", contenu
    )
    for op in occurrences:
        # Acceptes : nom_stocke (cree par attacher_tableur), f-strings
        # avec session.id (literal entier), helper lui-meme.
        if op in (
            "nom_stocke",
            "rel",  # dans _chemin_tableur_absolu
        ):
            continue
        # f-strings : "session_..." ou f"profil_session_..."
        if op.startswith('f"') or op.startswith("f'"):
            continue
        # PAS d'access direct a session.chemin_tableur en dehors du
        # helper.
        if "chemin_tableur" in op:
            pytest.fail(
                f"import_web.py construit `RACINE_IMPORT_TMP / {op}` — "
                f"bypass potentiel du helper `_chemin_tableur_absolu`. "
                "Utiliser le helper securise plutot."
            )


def test_chemin_tableur_absolu_avec_sous_dossier_legit() -> None:
    """Cas pas naturel mais possible : chemin_tableur avec sous-dossier
    sous RACINE_IMPORT_TMP doit etre accepte (les gardes ne sont pas
    trop strictes)."""
    s = _FauxSession("subdir/session_99.xlsx")
    cible = _chemin_tableur_absolu(s)
    assert cible is not None
    assert cible.is_relative_to(RACINE_IMPORT_TMP.resolve())
    assert cible.name == "session_99.xlsx"
