"""Application FastAPI : montage des routes et des fichiers statiques.

Routers enregistrés :
- `dashboard` : tableau de bord, pages fonds / collection / item, et
  les opérations sur les CollaborateurFonds (V0.9.0).
- `preferences` : panneau de configuration des colonnes du tableau d'items.
- `derives` : sert les vignettes / aperçus locaux sous `/derives/<racine>/<chemin>`
  pour la visionneuse OpenSeadragon de la page item.
- `import_assistant` : placeholder `/import` (assistant d'import à
  venir en V0.7+).

`routes/collaborateurs.py` est archivé en dette V0.8 — les
collaborateurs sont gérés exclusivement au niveau fonds.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from archives_tool.api.routes import dashboard, derives, import_assistant, preferences

RACINE_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"

app = FastAPI(
    title="archives-tool",
    description="Outil de gestion de collections numérisées",
    version="0.9.2",
)

app.mount("/static", StaticFiles(directory=RACINE_STATIC), name="static")
app.include_router(dashboard.router)
app.include_router(preferences.router)
app.include_router(derives.router, prefix="/derives")
app.include_router(import_assistant.router)
