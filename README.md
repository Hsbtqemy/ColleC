# archives-tool

Outil interne de gestion de collections numérisées (revues anciennes,
périodiques, textes). Voir [CLAUDE.md](CLAUDE.md) pour la vue d'ensemble
et [schema.md](schema.md) pour le modèle de données.

## Démarrage rapide

```bash
uv sync
uv run alembic upgrade head
uv run pytest
```

Pour l'interface web, installer aussi Tailwind :

```bash
npm install
npm run build:css
```

## Lancement en dev

Deux processus en parallèle :

```bash
npm run watch:css
uv run uvicorn archives_tool.api.main:app --reload --port 8000
```

## Démo

Créer une base SQLite peuplée pour explorer l'UI sans toucher à la
base de production :

```bash
uv run archives-tool demo init
ARCHIVES_DB=data/demo.db uv run uvicorn archives_tool.api.main:app --reload
```

`ARCHIVES_DB` est lue par l'API ; sans elle, `data/archives.db` sert.

## Structure

- `src/archives_tool/models/` — modèles SQLAlchemy par domaine.
- `src/archives_tool/db.py` — engine SQLite + pragmas (WAL, FK).
- `src/archives_tool/{importers,exporters,renamer,derivatives,qa}/` —
  modules métier de la CLI.
- `src/archives_tool/api/` — application FastAPI (routes, services).
- `src/archives_tool/web/` — templates Jinja2 + assets statiques.
- `src/archives_tool/cli.py` — commandes Typer.
- `alembic/` — migrations.
- `tests/` — pytest (contraintes, parité migration, intégration web).
- `profiles/` — profils d'import YAML par collection.
- `data/` — base SQLite locale (gitignoré).
- `docs/` — références par module (importer, exports, qa, renamer,
  derivatives, interface web, profils).
