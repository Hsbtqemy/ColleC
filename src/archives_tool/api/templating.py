"""Instance Jinja2Templates partagée et filtres exposés.

Vit ici pour éviter le cycle `main.py ↔ routes/*.py` quand une route a
besoin de `templates.TemplateResponse`.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from archives_tool.affichage.formatters import (
    LIBELLES_ETAT,
    formater_taille_octets,
    temps_relatif,
)
from archives_tool.api.deps import est_lecture_seule
from archives_tool.api.services.vocabulaires import (
    LANGUES_OPTIONS,
    TYPES_COAR_OPTIONS,
    libelle_pour_valeur,
)
from archives_tool.models import (
    LIBELLES_ROLE,
    EtatCatalogage,
    PhaseChantier,
    RoleCollaborateur,
)

RACINE_TEMPLATES = Path(__file__).resolve().parent.parent / "web" / "templates"
RACINE_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def _static_url(path: str) -> str:
    """Retourne `/static/<path>?v=<mtime>` pour bust le cache navigateur
    quand on édite un asset. Si le fichier est introuvable (cas test,
    racine déplacée), renvoie l'URL sans suffix — pas de plantage."""
    cible = RACINE_STATIC / path
    try:
        mtime_ns = cible.stat().st_mtime_ns
    except FileNotFoundError:
        return f"/static/{path}"
    return f"/static/{path}?v={mtime_ns}"


def _libelle_etat(etat: EtatCatalogage | str | None) -> str:
    if etat is None:
        return "—"
    code = etat.value if isinstance(etat, EtatCatalogage) else etat
    return LIBELLES_ETAT.get(code, code)


def _url_avec(base: str, **params: object) -> str:
    """Compose une URL avec les params donnés (remplace les existants).

    Préserve les autres params de la base. URL-encode proprement les
    valeurs (q='tom&jerry' → q=tom%26jerry, pas de corruption).

    Une page paginée passant à une nouvelle valeur de `tri` doit aussi
    reset `page` — gérer côté appelant en passant `page=1` explicitement.
    """
    parts = urlsplit(base)
    existants = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k not in params
    ]
    nouveaux = [(k, str(v)) for k, v in params.items()]
    return urlunsplit(parts._replace(query=urlencode(existants + nouveaux)))


def _url_tri(base: str, key: str, current_tri: str, current_ordre: str) -> str:
    """Compose une URL de tri : si `key` est déjà actif, inverse l'ordre ;
    sinon on repart en `asc`. Reset `page` à 1 (un nouveau tri repagine).
    """
    if key == current_tri:
        ordre = "desc" if current_ordre == "asc" else "asc"
    else:
        ordre = "asc"
    return _url_avec(base, tri=key, ordre=ordre, page=1)


def _url_page(base: str, page: int) -> str:
    return _url_avec(base, page=page)


def _pages_visibles(courante: int, total: int) -> list[int | str]:
    """Liste compacte de pages à afficher dans un pager.

    [1, '…', cur-1, cur, cur+1, '…', N] avec collapses naturels quand
    les fenêtres se chevauchent. Pour `total <= 7`, retourne 1..N.
    """
    if total <= 7:
        return list(range(1, total + 1))
    pages: list[int | str] = [1]
    debut = max(2, courante - 1)
    fin = min(total - 1, courante + 1)
    if debut > 2:
        pages.append("…")
    for p in range(debut, fin + 1):
        pages.append(p)
    if fin < total - 1:
        pages.append("…")
    pages.append(total)
    return pages


def _libelle_role(role: RoleCollaborateur | str | None) -> str:
    if role is None:
        return "—"
    code = role.value if isinstance(role, RoleCollaborateur) else role
    return LIBELLES_ROLE.get(code, code)


def _snippet_fts_safe(snippet: str | None) -> str:
    """Échappe le HTML d'un snippet FTS5 sauf les balises `<mark>` /
    `</mark>` qu'on a explicitement injectées via `snippet(...)`.

    Sans cet échappement, un `Item.metadonnees = {"x": "<script>..."}`
    se retrouverait rendu tel quel dans la page de recherche via
    `{{ r.snippet | safe }}` — XSS via contenu utilisateur. On
    échappe tout, puis on **dé-échappe** les `<mark>` connues (sûres
    car insérées par FTS5 avec ces littéraux exacts).

    Implémentation : convertir le résultat de `escape()` en `str`
    avant le `.replace()` — sinon `Markup.replace()` réescape le
    replacement (`<mark>` deviendrait `&lt;mark&gt;`).
    """
    if not snippet:
        return ""
    safe = str(escape(snippet))  # str pour .replace() sans réescape
    safe = safe.replace("&lt;mark&gt;", "<mark>").replace(
        "&lt;/mark&gt;", "</mark>"
    )
    return Markup(safe)


def _surligner_q(text: object, q: str | None) -> str:
    """Surligne les mots de `q` dans `text` via des balises `<mark>`.

    Utilisé par les pages d'entité (item/fonds/collection) quand on
    y arrive depuis la page de recherche avec `?q=...` propagé. Le
    surlignage aide l'utilisateur à voir tout de suite *où* le mot
    cherché apparaît dans la notice.

    Limitation V0.9.x : insensible à la casse mais PAS aux accents.
    Le serveur FTS5 indexe avec `remove_diacritics 2` (`numero`
    matche `Numéro` en search), mais le surlignage côté UI fait
    juste la casse — sans cela il faudrait normaliser le texte et
    tracker les offsets, complexe pour un gain marginal sur des
    corpus francophones (la grande majorité des matchs reste
    visible par la casse). Si le besoin remonte, refactor possible
    via une lib de normalisation (`unidecode`) + matching par
    offset preserves.

    Sécurité : échappe le HTML d'entrée avant d'injecter les marks
    (anti-XSS si `text` vient de `metadonnees` libre).
    """
    if text is None:
        return Markup("")
    text_str = str(text)
    if not q or not q.strip():
        return Markup(escape(text_str))
    tokens = [re.escape(t) for t in q.strip().split() if t]
    if not tokens:
        return Markup(escape(text_str))
    # Échappe d'abord (sécurité XSS) puis surligne sur le texte
    # échappé — les `<` deviennent `&lt;` donc le `<mark>` injecté
    # est la seule balise réelle dans la sortie.
    escaped = str(escape(text_str))
    pattern = re.compile("(" + "|".join(tokens) + ")", re.IGNORECASE)
    return Markup(pattern.sub(r"<mark>\1</mark>", escaped))


def _url_safe(value: object) -> str:
    """Filtre Jinja qui rend un href safe contre l'injection
    `javascript:` / `data:` exécutable.

    Cas d'usage : `ValeurControlee.uri` et `AnnotationRegion` body URIs
    sont saisis librement (Wikidata, VIAF, COAR, DOI…). Pas de pattern
    Pydantic — un utilisateur peut poser `uri = "javascript:alert(1)"`
    et un visiteur qui clique le lien depuis la page enrichissement
    preview ou la fiche item se ferait exécuter le JS. `rel="noopener"`
    ne bloque pas ce vecteur.

    Whitelist conservatrice :
    - URLs absolues http:// / https://
    - URLs absolues mailto: (cas legit pour les autorités)

    Tout autre scheme (javascript:, data:, file:, vbscript:, etc.)
    retourne `"#"` — le lien reste visible mais ne navigue nulle part.
    Les URLs relatives sans scheme sont aussi acceptees (par exemple
    `/fonds/HK`) car elles sont confinees au site.
    """
    if value is None:
        return "#"
    s = str(value).strip()
    if not s:
        return "#"
    # URLs relatives (sans scheme) : autorisees, restent sous notre
    # origin.
    if s.startswith("/") or s.startswith("./") or s.startswith("../"):
        return s
    # URLs absolues : whitelist explicite.
    bas = s.lower()
    for prefixe in ("http://", "https://", "mailto:"):
        if bas.startswith(prefixe):
            return s
    return "#"


templates = Jinja2Templates(directory=RACINE_TEMPLATES)
templates.env.filters["url_safe"] = _url_safe
templates.env.filters["libelle_phase"] = lambda p: (
    p.libelle if isinstance(p, PhaseChantier) else "—"
)
templates.env.filters["libelle_etat"] = _libelle_etat
templates.env.filters["libelle_role"] = _libelle_role
# Vocabulaires contrôlés : URI/code → libellé humain via la table
# `TYPES_COAR_OPTIONS` / `LANGUES_OPTIONS` partagée avec l'édition
# inline. Si la valeur n'est pas dans la table (legacy / hors
# référentiel), retourne la valeur brute — l'UI continue de
# l'afficher, l'utilisateur peut la corriger via inline edit.
templates.env.filters["libelle_coar"] = lambda v: libelle_pour_valeur(
    v, TYPES_COAR_OPTIONS
)
templates.env.filters["libelle_langue"] = lambda v: libelle_pour_valeur(
    v, LANGUES_OPTIONS
)
templates.env.filters["temps_relatif"] = temps_relatif
templates.env.filters["taille_humaine"] = formater_taille_octets
templates.env.filters["url_tri"] = _url_tri
templates.env.filters["url_page"] = _url_page
templates.env.filters["snippet_fts_safe"] = _snippet_fts_safe
templates.env.filters["surligner_q"] = _surligner_q
templates.env.globals["pages_visibles"] = _pages_visibles
templates.env.globals["est_lecture_seule"] = est_lecture_seule
templates.env.globals["static_url"] = _static_url
