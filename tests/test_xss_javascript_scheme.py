"""Garde-fou XSS via scheme `javascript:` dans les href.

Trouve a l'audit security passe generale : `enrichissement_preview.html`
et `item_fiche.html` rendaient `tag.uri` et `m.valeur_uri` directement
dans `href="{{ ... }}"`. Ces valeurs viennent de `ValeurControlee.uri`
(free text, aucun pattern Pydantic) — un utilisateur pouvait creer une
valeur de vocabulaire avec `uri = "javascript:alert(1)"`. Clic sur le
lien depuis la page enrichissement ou la fiche item = execution JS.
`rel="noopener"` ne bloque pas ce vecteur.

`iiif_url_nakala` (importe depuis un tableur, free text) propagee
dans `url_telechargement_externe` puis dans les fallbacks visionneuse
suit le meme pattern.

Fix : filtre Jinja `url_safe` qui whitelist http://, https://, mailto:
et les URLs relatives. Retourne `"#"` pour tout autre scheme (javascript:,
data:, file:, vbscript:, etc.).
"""

from __future__ import annotations

import pytest

from archives_tool.api.templating import _url_safe


# ---------------------------------------------------------------------------
# Le filtre `_url_safe` directement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://www.wikidata.org/entity/Q733678",
    "http://purl.org/coar/resource_type/c_3e5a",
    "https://doi.org/10.34847/nkl.abc",
    "mailto:archiviste@univ-poitiers.fr",
])
def test_url_safe_accepte_http_https_mailto(url: str) -> None:
    assert _url_safe(url) == url


@pytest.mark.parametrize("url", [
    "/fonds/HK",
    "/collection/HK-FAVORIS",
    "./relative.html",
    "../parent.html",
])
def test_url_safe_accepte_urls_relatives(url: str) -> None:
    assert _url_safe(url) == url


@pytest.mark.parametrize("url_malicieux", [
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",  # case insensitive
    "JavaScript:alert(1)",
    " javascript:alert(1)",  # whitespace
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "ftp://evil.com/x",  # ftp pas dans la whitelist
])
def test_url_safe_refuse_schemes_malicieux(url_malicieux: str) -> None:
    """Tout scheme hors http/https/mailto retourne `#` — lien neutralise."""
    assert _url_safe(url_malicieux) == "#"


def test_url_safe_traite_none_et_vide() -> None:
    assert _url_safe(None) == "#"
    assert _url_safe("") == "#"
    assert _url_safe("   ") == "#"


# ---------------------------------------------------------------------------
# Integration via les templates qui consomment le filtre
# ---------------------------------------------------------------------------


def test_filtre_url_safe_enregistre_sur_jinja_env() -> None:
    """Le filtre est bien expose au template engine — sinon les usages
    `{{ x | url_safe }}` dans les templates leveraient TemplateError."""
    from archives_tool.api.templating import templates
    assert "url_safe" in templates.env.filters
    assert templates.env.filters["url_safe"]("https://x") == "https://x"
    assert templates.env.filters["url_safe"]("javascript:x") == "#"
