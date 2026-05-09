"""Application FastAPI : montage des routes et des fichiers statiques.

V0.9.0-beta.1 : seul le router `dashboard` (refondu) est enregistré
côté web. Les anciens routers (collection détaillée, collaborateurs,
preferences, derives, import_assistant, item) dépendent encore de
l'ancien modèle / d'anciens services et seront ré-enregistrés au fil
de V0.9.0-beta.2 (page fonds + collection détaillée), V0.9.0-beta.3
(page item).
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
