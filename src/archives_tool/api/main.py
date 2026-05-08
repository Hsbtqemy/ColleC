"""Application FastAPI : montage des routes et des fichiers statiques."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from archives_tool.api.routes import (
    collection,
    collections,
    dashboard,
    derives,
    import_assistant,
    item,
    preferences,
)

RACINE_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"

app = FastAPI(
    title="archives-tool",
    description="Outil de gestion de collections numérisées",
    version="0.5.0",
)

app.mount("/static", StaticFiles(directory=RACINE_STATIC), name="static")
app.include_router(dashboard.router)
app.include_router(collections.router)
app.include_router(collection.router)
app.include_router(item.router)
app.include_router(import_assistant.router)
app.include_router(preferences.router)
app.include_router(derives.router, prefix="/derives")
