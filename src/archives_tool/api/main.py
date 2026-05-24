"""Application FastAPI : montage des routes et des fichiers statiques.

Routers enregistrés :
- `dashboard` : tableau de bord, pages fonds / collection / item, et
  les opérations sur les CollaborateurFonds (V0.9.0).
- `preferences` : panneau de configuration des colonnes du tableau d'items.
- `derives` : sert les vignettes / aperçus locaux sous `/derives/<racine>/<chemin>`
  pour la visionneuse OpenSeadragon de la page item.
- `import_assistant` : assistant d'import web (`/import`) — cycle de
  vie des `SessionImport` ; le wizard est livré par sous-étapes.

Les collaborateurs sont gérés exclusivement au niveau fonds (V0.9.0+) —
l'ancienne route `routes/collaborateurs.py` (V0.8 CollaborateurCollection)
a été supprimée en lot de purge dead code.

Startup : `assurer_tables_fts` est appelé au démarrage pour créer les
tables FTS5 si elles sont absentes (cas d'une base ancienne pré-V0.9.3
ou restaurée depuis une sauvegarde sans index). Idempotent — n'a pas
d'effet sur une base déjà à jour.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from archives_tool.api.deps import chemin_base_courant
from archives_tool.api.middleware import middleware_lecture_seule
from archives_tool.api.routes import (
    dashboard,
    derives,
    import_assistant,
    inline_edit,
    preferences,
)
from archives_tool.db import assurer_tables_fts, creer_engine

RACINE_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Hook startup/shutdown FastAPI. Au démarrage : s'assure que les
    tables FTS existent sur la base courante. Au shutdown : rien (les
    engines SQLAlchemy sont créés par requête via `get_db` et disposed
    automatiquement).

    Lit la base via `chemin_base_courant` (respecte `ARCHIVES_DB`).
    Si la base n'existe pas encore (premier démarrage avant
    `demo init`), on skip silencieusement — le check sera refait au
    prochain démarrage une fois la base présente.
    """
    try:
        chemin = chemin_base_courant()
        if chemin.is_file():
            engine = creer_engine(chemin)
            assurer_tables_fts(engine)
            engine.dispose()
    except Exception:
        # Pas d'exception au startup — on dégrade gracieusement.
        # Si FTS pose vraiment problème, le user le verra à la
        # première recherche (résultats vides) et pourra appeler
        # `archives-tool reindexer` manuellement.
        pass
    yield


app = FastAPI(
    title="archives-tool",
    description="Outil de gestion de collections numérisées",
    version="0.9.3",
    lifespan=_lifespan,
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
