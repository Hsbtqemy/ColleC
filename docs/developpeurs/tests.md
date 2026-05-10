# Tests

Organisation et conventions des tests.

## Lancer les tests

```bash
uv run pytest                          # toute la suite
uv run pytest tests/test_renamer.py    # un fichier
uv run pytest -k "perimetre"           # par nom (regex)
uv run pytest --lf                     # last failed
uv run pytest -x                       # arrêter au 1er échec
```

Avec couverture :

```bash
uv run pytest --cov=archives_tool
```

Lint et format :

```bash
uv run ruff check .
uv run ruff format .
```

Build de la doc (test d'intégration) :

```bash
uv run mkdocs build --strict
```

## Organisation

```
tests/
├── _helpers.py                       # Helpers partagés (assertions, builders)
├── conftest.py                       # Fixtures globales + collect_ignore
├── docs/                             # Tests de structure documentation
├── fixtures/                         # Profils YAML + données de test
├── test_cli_*.py                     # Tests des commandes CLI
├── test_*_routes.py                  # Tests des routes web
├── test_*_services.py                # Tests des services métier
├── test_export_*.py / test_qa_*.py   # Tests par module
└── ...
```

L'arborescence est plate (pas de sous-dossiers par couche). Le
préfixe (`test_cli_`, `test_export_`, etc.) suffit pour
naviguer.

## Conventions

- **Un fichier de test par module testé**. Un test
  `test_renamer.py` couvre `archives_tool/renamer/`.
- **Fixtures partagées** dans [`tests/conftest.py`]({{ repo_main }}/tests/conftest.py) :
  `engine`, `session`, `fonds_hk`, `session_avec_export`.
- **Helpers** dans [`tests/_helpers.py`]({{ repo_main }}/tests/_helpers.py)
  pour les opérations répétitives (création de fonds + items
  pré-peuplés, capture stdout Rich, etc.).
- **Pas de mocks de la base** : les tests utilisent SQLite sur
  `tmp_path`. Plus lent qu'un mock, mais teste les vraies
  contraintes ON DELETE et CHECK.
- **Vrais fichiers** pour les tests `renamer` / `derivatives` :
  on ne mocke pas le système de fichiers, on écrit dans
  `tmp_path`.

## Tests d'invariants

Pour chaque invariant du modèle, un test explicite vérifie qu'il
est respecté dans des cas normaux et qu'il échoue dans les cas
pathologiques.

Exemple type :

```python
def test_creation_fonds_cree_miroir_automatiquement(session):
    """INV1 : tout fonds créé a sa collection miroir."""
    fonds = creer_fonds(session, FormulaireFonds(
        cote="X", titre="Test",
    ))
    miroirs = [c for c in fonds.collections if c.est_miroir]
    assert len(miroirs) == 1
    assert miroirs[0].cote == fonds.cote
```

Voir `tests/test_fonds.py`, `tests/test_collection_services.py`
pour les invariants 1, 2, 4, 6 côté code.

## Quarantaine

Pendant les phases de refonte profonde (V0.9.0-alpha), les tests
qui dépendent du modèle ancien sont mis sous quarantaine via
`collect_ignore` dans `tests/conftest.py`. Ils sont
progressivement réactivés au fil des sessions ou supprimés
définitivement.

Au moment de V0.9.0 stable, une poignée de fichiers reste sous
quarantaine — voir `conftest.py` pour la liste à jour. Ils
seront soit réactivés en V0.9.1, soit supprimés s'ils ne
correspondent plus à du code vivant.

## Tests de structure docs

[`tests/docs/test_structure.py`]({{ repo_main }}/tests/docs/test_structure.py)
contient un garde-fou paramétré qui vérifie la présence et le
non-vide des fichiers documentaires essentiels. Filet de
sécurité contre les réorganisations accidentelles, en plus de
`mkdocs build --strict` qui valide la cohérence des liens.

## Voir aussi

- [Architecture](architecture.md) — couches du code.
- [Modèle de données](modele.md) — invariants en base et en code.
- [Services](services.md) — patterns testés par couche métier.
