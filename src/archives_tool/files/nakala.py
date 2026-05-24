"""Helpers Nakala (reconnaissance d'URL + transformations).

Centralise le regex et les fonctions de transformation entre les
trois endpoints Nakala (`data`, `embed`, `iiif`) — utilisé côté
import (`ecrivain.py`) pour normaliser vers IIIF info.json au moment
du stockage, et côté affichage (`services/sources_image.py`) pour
reconstruire l'URL de téléchargement quand le viewer OSD échoue.

Garanties :
- Hostname strict : exige `<sub>.nakala.fr` (sous-domaine
  alphanumérique + `-`). Empêche un faux positif sur des domaines
  pirate type `evil-nakala.fr`.
- Hostname préservé : la cible utilise le hostname d'origine —
  `api-test.nakala.fr/data/...` reste sur `api-test.nakala.fr/iiif/...`
  (pas redirigé vers `api.nakala.fr`). Indispensable pour les
  environnements de test.
"""

from __future__ import annotations

import re

#: URL Nakala reconnue (data, embed ou IIIF image) — capture le
#: hostname, le DOI (2 segments) et le SHA pour reconstruire toute
#: variante. Le suffixe après `<sha>` (ex. `/full/!200,200/0/default.jpg`
#: sur les thumb IIIF) est ignoré.
PATTERN_URL_NAKALA = re.compile(
    r"^(?P<scheme>https?)://(?P<host>[a-z0-9][a-z0-9-]*\.nakala\.fr)"
    r"/(?P<endpoint>data|embed|iiif)/(?P<doi>[^/]+/[^/]+)/(?P<sha>[a-f0-9]+)",
    re.IGNORECASE,
)


def vers_iiif_info_json(url: str) -> str:
    """Transforme une URL Nakala data/embed/iiif-image en URL IIIF
    info.json. Retourne `url` inchangée si pas un pattern Nakala
    reconnu.

    Sert au stockage côté import : OpenSeadragon attend une URL
    info.json pour fonctionner en Image API. `data_url` (binaire)
    ou `embed_url` (iframe HTML) ne sont pas compris par OSD.
    """
    m = PATTERN_URL_NAKALA.match(url)
    if m is None:
        return url
    return f"{m['scheme']}://{m['host']}/iiif/{m['doi']}/{m['sha']}/info.json"


def vers_data(url: str) -> str | None:
    """Transforme une URL Nakala (data/embed/iiif) en URL `data`
    (binaire téléchargeable). Retourne `None` si pas un pattern
    Nakala reconnu — le caller doit alors fallback ailleurs.

    Sert côté affichage : le bouton « Télécharger » de la
    visionneuse OSD doit pointer sur le fichier binaire (PDF, JPG…),
    pas sur l'info.json IIIF (JSON technique).
    """
    m = PATTERN_URL_NAKALA.match(url)
    if m is None:
        return None
    return f"{m['scheme']}://{m['host']}/data/{m['doi']}/{m['sha']}"
