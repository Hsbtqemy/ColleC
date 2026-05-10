# ColleC

Outil de gestion de collections numérisées pour archives
universitaires. Développé à l'Université de Poitiers.

📖 **Documentation : <https://hsbtqemy.github.io/ColleC/>**

ColleC gère le travail interne (métadonnées riches, états de
catalogage, multi-appartenance d'items à plusieurs collections)
sans contraindre la sémantique Nakala pour la publication. Modèle
Fonds / Collection / Item, interface web pour le travail
quotidien, CLI pour l'automatisation, exports Dublin Core /
Nakala / xlsx.

**Statut** : V0.9.0 stable. Modèle stable, fonctionnalités
complètes. La V1.0 marquera la stabilisation après usage en
production sur plusieurs vrais fonds.

## Démarrage rapide

```bash
git clone https://github.com/Hsbtqemy/ColleC.git
cd ColleC
uv sync
uv run alembic upgrade head
uv run pytest
```

Pour explorer l'interface avec une base de démonstration :

```bash
uv run archives-tool demo init
ARCHIVES_DB=data/demo.db uv run uvicorn archives_tool.api.main:app --reload
```

Voir la doc en ligne (lien ci-dessus) ou en local
(`uv run mkdocs serve`) pour le guide complet.

## Structure

- `src/archives_tool/` — code Python (modèles, services, CLI, API).
- `alembic/` — migrations.
- `tests/` — pytest (~430 tests).
- `profiles/` — profils d'import YAML par fonds.
- `data/` — base SQLite locale (gitignoré).
- `docs/` — sources MkDocs ; build déployé sur GitHub Pages via
  CI (`.github/workflows/docs.yml`).
