"""Garde-fou structurel : vérifie que les fichiers documentaires
de l'ossature sont là et non vides.

Filet de sécurité contre les réorganisations accidentelles. La
présence des pages individuelles référencées dans la nav est déjà
garantie par `mkdocs build --strict` (qui échoue sur tout fichier
manquant) ; on ne couvre ici que les *index* de section et les
quelques pages réellement écrites en gamma.5.1, dont la perte
serait une régression silencieuse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_RACINE = Path(__file__).resolve().parent.parent.parent / "docs"

FICHIERS_REQUIS = [
    "index.md",
    "premiers-pas/index.md",
    "premiers-pas/installation.md",
    "premiers-pas/configuration.md",
    "premiers-pas/premier-import.md",
    "premiers-pas/workflow-type.md",
    "guide/concepts.md",
    "guide/cli/index.md",
    "guide/cli/collections.md",
    "reference/index.md",
    "reference/exports.md",
    "reference/controles.md",
    "developpeurs/architecture.md",
    "developpeurs/modele.md",
    "developpeurs/services.md",
    "developpeurs/tests.md",
    "developpeurs/composants-ui.md",
    "developpeurs/contribuer.md",
    "annexes/changelog.md",
    "annexes/limites.md",
]


@pytest.mark.parametrize("fichier", FICHIERS_REQUIS)
def test_fichier_existe(fichier: str) -> None:
    chemin = DOCS_RACINE / fichier
    assert chemin.exists(), f"Fichier doc manquant : {fichier}"
    contenu = chemin.read_text(encoding="utf-8").strip()
    assert contenu, f"Fichier doc vide : {fichier}"


def test_mkdocs_yml_present() -> None:
    racine = DOCS_RACINE.parent
    assert (racine / "mkdocs.yml").is_file(), "mkdocs.yml manquant à la racine"
