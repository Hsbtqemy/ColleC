"""Middleware FastAPI partagés.

`MiddlewareLectureSeule` rejette les mutations (POST/PUT/PATCH/DELETE)
avec un code 423 (« Locked ») quand `config_local.yaml` active
`lecture_seule: true`. Pensé pour exposer ColleC à un consultant
occasionnel sans risque d'édition accidentelle ; pas un mécanisme
d'authentification.

Le format de la réponse est négocié via l'en-tête `Accept` : HTML
(petite page avec lien retour) pour les requêtes navigateur, JSON
sinon. Évite que l'utilisateur qui clique « Enregistrer » sur un
form HTML voie du JSON brut dans son navigateur — bannière en haut
de page + page d'erreur HTML lisible.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from archives_tool.api.deps import est_lecture_seule

METHODES_MUTATION: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_MESSAGE_LECTURE_SEULE = (
    "Mode lecture seule actif : modifications désactivées. "
    "Désactivez `lecture_seule` dans `config_local.yaml` "
    "pour réautoriser les écritures."
)

_PAGE_HTML_LECTURE_SEULE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Mode lecture seule — archives-tool</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 560px;
            margin: 80px auto; padding: 0 24px; color: #1f1f1f; }}
    h1 {{ font-size: 20px; margin: 0 0 16px 0; color: #92400e; }}
    p {{ font-size: 14px; line-height: 1.6; margin: 0 0 12px 0; }}
    code {{ background: #f3f4f6; padding: 1px 4px; border-radius: 3px;
            font-size: 13px; }}
    a.retour {{ display: inline-block; margin-top: 16px; padding: 8px 16px;
                background: #fff; color: #1f1f1f;
                border: 1px solid rgba(0,0,0,0.15); border-radius: 4px;
                text-decoration: none; font-size: 13px; }}
    a.retour:hover {{ background: #f9fafb; }}
  </style>
</head>
<body>
  <h1>Mode lecture seule</h1>
  <p>{message}</p>
  <a class="retour" href="javascript:history.back()">← Retour</a>
</body>
</html>
"""


def _prefere_html(request: Request) -> bool:
    """Vrai si le client préfère une réponse HTML (navigateur web).

    Heuristique : `Accept: text/html` présent. Les clients API (httpx,
    requests, curl par défaut) envoient `*/*` ou `application/json` —
    qui tombent en JSON.
    """
    accept = request.headers.get("accept", "")
    return "text/html" in accept


async def middleware_lecture_seule(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if request.method in METHODES_MUTATION and est_lecture_seule():
        if _prefere_html(request):
            return HTMLResponse(
                status_code=423,
                content=_PAGE_HTML_LECTURE_SEULE.format(message=_MESSAGE_LECTURE_SEULE),
            )
        return JSONResponse(
            status_code=423,
            content={"detail": _MESSAGE_LECTURE_SEULE},
        )
    return await call_next(request)
