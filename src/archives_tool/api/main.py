"""Application FastAPI : montage des routes et des fichiers statiques.

Seul le router `dashboard` est actuellement enregistré : il porte
le tableau de bord et les pages fonds / collection / item. Les
routers collaborateurs / preferences / derives / import_assistant
seront ré-introduits à mesure que les pages détail sont étoffées.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from archives_tool.api.routes import dashboard

RACINE_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"

app = FastAPI(
    title="archives-tool",
    description="Outil de gestion de collections numérisées",
    version="0.9.0-beta.1",
)

app.mount("/static", StaticFiles(directory=RACINE_STATIC), name="static")
app.include_router(dashboard.router)
