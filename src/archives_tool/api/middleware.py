"""Middleware FastAPI partagés.

`MiddlewareLectureSeule` rejette les mutations (POST/PUT/PATCH/DELETE)
avec un code 423 (« Locked ») quand `config_local.yaml` active
`lecture_seule: true`. Pensé pour exposer ColleC à un consultant
occasionnel sans risque d'édition accidentelle ; pas un mécanisme
d'authentification.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from archives_tool.api.deps import est_lecture_seule

METHODES_MUTATION: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def middleware_lecture_seule(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if request.method in METHODES_MUTATION and est_lecture_seule():
        return JSONResponse(
            status_code=423,
            content={
                "detail": (
                    "Mode lecture seule actif : modifications désactivées. "
                    "Désactivez `lecture_seule` dans `config_local.yaml` "
                    "pour réautoriser les écritures."
                )
            },
        )
    return await call_next(request)
