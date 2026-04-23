# archives-tool

Outil interne de gestion de collections numérisées (revues anciennes,
périodiques, textes). Voir [CLAUDE.md](CLAUDE.md) pour la vue d'ensemble
et [docs/schema.md](docs/schema.md) pour le modèle de données.

## Démarrage rapide

```bash
uv sync
uv run alembic upgrade head
uv run pytest
```

## Structure

- `src/archives_tool/models/` — modèles SQLAlchemy découpés par domaine.
- `src/archives_tool/db.py` — engine SQLite + pragmas (WAL, FK).
- `alembic/` — migrations (autogen depuis `Base.metadata`).
- `tests/` — contraintes d'intégrité, pragmas, parité migration/schéma.
- `profiles/` — profils d'import YAML par collection.
- `data/` — base SQLite locale (gitignoré).
