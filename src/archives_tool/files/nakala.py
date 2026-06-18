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

#: Extensions de fichier dont Nakala expose une dérivée IIIF Image API.
#: Hors de cette liste, ni la normalisation `data` → `iiif/info.json`
#: ni la génération de thumb n'ont de sens (404). Centralisé ici (en
#: plus de l'usage import) parce que le service affichage en a aussi
#: besoin (cf. `services/sources_image.py` qui skip les thumbs PDF).
EXTENSIONS_IMAGE_IIIF: frozenset[str] = frozenset(
    {"jpg", "jpeg", "png", "tif", "tiff", "gif", "webp", "bmp", "jp2"}
)


def est_extension_image_iiif(nom_fichier: str | None) -> bool:
    """True si le nom de fichier a une extension d'image que Nakala
    sert via IIIF Image API. Bénéfice du doute (True) si pas de nom
    ou pas d'extension — laisse les fonctions amont tenter leur chance.
    """
    if not nom_fichier or "." not in nom_fichier:
        return True
    ext = nom_fichier.rsplit(".", 1)[-1].lower()
    return ext in EXTENSIONS_IMAGE_IIIF


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


def remplacer_sha(url: str, nouveau_sha: str) -> str:
    """Substitue le SHA d'une URL Nakala par ``nouveau_sha``, en
    préservant scheme/host/endpoint/DOI/suffixe.

    Cas typique (Trou V passe 11) : après un push fichiers qui
    change le sha côté Nakala (upload de nouveau binaire), l'URL
    IIIF stockée sur ``Fichier.iiif_url_nakala`` (qui contient le
    sha dans son chemin) doit être recalée — sinon le viewer
    OpenSeadragon hérite d'un 404 silencieux.

    Retourne ``url`` inchangée si elle ne matche pas le pattern
    Nakala (préserve le comportement neutre du module : on ne
    touche pas aux URLs non reconnues).
    """
    m = PATTERN_URL_NAKALA.match(url)
    if m is None:
        return url
    debut, fin = m.span("sha")
    return url[:debut] + nouveau_sha + url[fin:]


def vers_thumb(url: str, taille_max: int = 200) -> str | None:
    """Transforme une URL Nakala en URL de vignette IIIF carrée.

    `https://api.nakala.fr/data/<doi>/<sha>` →
        `https://api.nakala.fr/iiif/<doi>/<sha>/full/!200,200/0/default.jpg`

    `taille_max` borne la dimension la plus grande (preservation
    ratio via le `!` IIIF Image API). Retourne `None` si pas Nakala.

    Sert au panneau fichiers de la page item pour afficher une
    miniature des Fichier Nakala-only — sinon l'utilisateur voit
    juste des numéros de page sans aperçu (UX critique sur les
    items à 39+ scans).
    """
    m = PATTERN_URL_NAKALA.match(url)
    if m is None:
        return None
    return (
        f"{m['scheme']}://{m['host']}/iiif/{m['doi']}/{m['sha']}/"
        f"full/!{taille_max},{taille_max}/0/default.jpg"
    )


def construire_source_fichier_nakala(
    base_url: str, doi: str, sha1: str, *, nom_fichier: str | None = None
) -> str:
    """Construit l'URL source d'un fichier Nakala à partir de ses identifiants.

    Pendant « montant » des helpers de transformation : ici on **bâtit**
    l'URL depuis `(base_url, doi, sha1)` (cas du rapatriement depuis le
    listing de collection, où l'on n'a pas d'URL pré-existante à
    transformer).

    - image (extension IIIF) → URL IIIF `…/iiif/<doi>/<sha1>/info.json`
      (consommable par OpenSeadragon) ;
    - autre (PDF, vidéo…) → URL `data` binaire `…/data/<doi>/<sha1>`
      (pas de viewer, mais source valide + fallback « Télécharger »).

    Même convention que l'importer (`ecrivain._fichier_depuis_colonnes`) :
    les deux formes satisfont le CHECK `ck_fichier_source_au_moins_une`.
    """
    base = base_url.rstrip("/")
    if est_extension_image_iiif(nom_fichier):
        return f"{base}/iiif/{doi}/{sha1}/info.json"
    return f"{base}/data/{doi}/{sha1}"


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
