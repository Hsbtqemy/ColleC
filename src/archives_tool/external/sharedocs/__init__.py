"""Accès ShareDocs (WebDAV Huma-Num) — ingestion remote-first.

Chantier 1 de la roadmap. Porté du prototype BD_ditor
(`pipeline/sharedocs.py`), re-implémenté au style ColleC (classe à config
explicite, transport injectable), **sans dépendance ni couplage à
BD_ditor** (copie → possession → divergence). Cf.
`docs/developpeurs/roadmap.md` § Chantier 1.
"""

from __future__ import annotations

from archives_tool.external.sharedocs.client import (
    ClientShareDocs,
    EntreeShareDocs,
    ErreurShareDocs,
    ShareDocsAuthRefusee,
    ShareDocsCheminInvalide,
    ShareDocsHoteInterdit,
    ShareDocsInjoignable,
)

__all__ = [
    "ClientShareDocs",
    "EntreeShareDocs",
    "ErreurShareDocs",
    "ShareDocsAuthRefusee",
    "ShareDocsCheminInvalide",
    "ShareDocsHoteInterdit",
    "ShareDocsInjoignable",
]
