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
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from archives_tool.api.middleware import middleware_lecture_seule
from archives_tool.api.routes import (
    dashboard,
    derives,
    import_assistant,
    inline_edit,
    preferences,
)

RACINE_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"

app = FastAPI(
    title="archives-tool",
    description="Outil de gestion de collections numérisées",
    version="0.9.2",
)

app.add_middleware(BaseHTTPMiddleware, dispatch=middleware_lecture_seule)

app.mount("/static", StaticFiles(directory=RACINE_STATIC), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """Stub silencieux : les navigateurs reclament systematiquement
    /favicon.ico, on repond 204 pour eviter le bruit 404 dans les logs."""
    return Response(status_code=204)


app.include_router(dashboard.router)
app.include_router(preferences.router)
app.include_router(inline_edit.router)
app.include_router(derives.router, prefix="/derives")
app.include_router(import_assistant.router)
