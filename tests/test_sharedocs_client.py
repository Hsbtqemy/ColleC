"""Tests du client WebDAV ShareDocs (Chantier 1) — httpx MockTransport,
aucun réseau réel.

Couvre : parsing du `<multistatus>` PROPFIND, téléchargement, mapping des
erreurs HTTP (401/403/404/5xx/redirection), anti-SSRF (hôte hors allowlist,
HTTPS exigé, IP interne), anti-traversal (`..`), et la forme des requêtes
(PROPFIND Depth:1, URL construite/encodée).
"""

from __future__ import annotations

import httpx
import pytest

from archives_tool.external.sharedocs import (
    ClientShareDocs,
    ErreurShareDocs,
    ShareDocsAuthRefusee,
    ShareDocsCheminInvalide,
    ShareDocsHoteInterdit,
    ShareDocsInjoignable,
)

_BASE = "https://sharedocs.huma-num.fr/dav/colleC"

# Réponse PROPFIND Depth:1 réaliste : le dossier lui-même (à écarter), un
# sous-dossier (collection), un fichier (getcontentlength + displayname).
_MULTISTATUS = """<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/dav/colleC/</d:href>
    <d:propstat><d:prop>
      <d:resourcetype><d:collection/></d:resourcetype>
      <d:displayname>colleC</d:displayname>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/colleC/Por%20Favor/</d:href>
    <d:propstat><d:prop>
      <d:resourcetype><d:collection/></d:resourcetype>
      <d:displayname>Por Favor</d:displayname>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/colleC/notice.pdf</d:href>
    <d:propstat><d:prop>
      <d:resourcetype/>
      <d:getcontentlength>1234</d:getcontentlength>
      <d:displayname>notice.pdf</d:displayname>
    </d:prop></d:propstat>
  </d:response>
</d:multistatus>"""


def _client(handler, *, base_url: str = _BASE, **kw) -> ClientShareDocs:
    return ClientShareDocs(
        base_url,
        "marie",
        "secret",
        transport=httpx.MockTransport(handler),
        **kw,
    )


# ---------------------------------------------------------------------------
# lister / telecharger — chemin nominal
# ---------------------------------------------------------------------------


def test_lister_parse_multistatus_et_ecarte_le_dossier_lui_meme() -> None:
    recu: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        recu.append(req)
        return httpx.Response(207, text=_MULTISTATUS)

    with _client(handler) as c:
        entrees = c.lister()

    # Le dossier lui-même (href racine) est écarté ; restent sous-dossier + fichier.
    assert [e.nom for e in entrees] == ["Por Favor", "notice.pdf"]
    # Dossiers d'abord, puis fichiers.
    assert entrees[0].est_dossier is True and entrees[1].est_dossier is False
    assert entrees[0].chemin == "Por Favor"
    assert entrees[1].chemin == "notice.pdf"
    assert entrees[1].taille == 1234
    # Requête : méthode PROPFIND + en-tête Depth:1.
    assert recu[0].method == "PROPFIND"
    assert recu[0].headers["Depth"] == "1"


def test_lister_sous_dossier_construit_url_encodee() -> None:
    vus: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vus.append(str(req.url))
        return httpx.Response(207, text=_MULTISTATUS)

    with _client(handler) as c:
        c.lister("Por Favor")

    # L'espace est url-encodé dans le segment.
    assert vus[0] == "https://sharedocs.huma-num.fr/dav/colleC/Por%20Favor"


def test_telecharger_renvoie_les_octets() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert str(req.url) == "https://sharedocs.huma-num.fr/dav/colleC/notice.pdf"
        return httpx.Response(200, content=b"%PDF-1.4 ...")

    with _client(handler) as c:
        data = c.telecharger("notice.pdf")
    assert data == b"%PDF-1.4 ..."


# ---------------------------------------------------------------------------
# Mapping des erreurs HTTP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", [401, 403])
def test_auth_refusee(code: int) -> None:
    with _client(lambda req: httpx.Response(code)) as c:
        with pytest.raises(ShareDocsAuthRefusee):
            c.lister()


@pytest.mark.parametrize("code", [404, 500, 503])
def test_erreur_serveur(code: int) -> None:
    with _client(lambda req: httpx.Response(code)) as c:
        with pytest.raises(ErreurShareDocs):
            c.telecharger("absent.pdf")


def test_redirection_non_suivie_est_une_erreur() -> None:
    """Anti-SSRF : une 3xx ne doit jamais être suivie ni passer pour un succès.

    On PROUVE le non-suivi : le handler n'est appelé qu'**une fois** (si les
    redirections étaient suivies, httpx rappellerait le handler en boucle
    jusqu'à TooManyRedirects). Et le message confirme notre branche de refus
    explicite (pas un TooManyRedirects ré-emballé)."""
    appels: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        appels.append(req)
        return httpx.Response(
            302, headers={"Location": "https://sharedocs.huma-num.fr/autre"}
        )

    with _client(handler) as c:
        with pytest.raises(ErreurShareDocs, match="[Rr]edirection"):
            c.telecharger("piege")
    assert len(appels) == 1  # non suivie : un seul aller, pas de boucle


def test_injoignable_mappe_connecterror() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("réseau down")

    with _client(handler) as c:
        with pytest.raises(ShareDocsInjoignable):
            c.lister()


# ---------------------------------------------------------------------------
# Anti-SSRF (validation au constructeur)
# ---------------------------------------------------------------------------


def test_hote_hors_allowlist_refuse() -> None:
    with pytest.raises(ShareDocsHoteInterdit):
        ClientShareDocs("https://evil.example.com/dav", "u", "p")


def test_https_exige_http_refuse() -> None:
    """Correctif audit BD_ditor : Basic Auth jamais en clair."""
    with pytest.raises(ShareDocsHoteInterdit):
        # Même un hôte autorisé en http:// est refusé.
        ClientShareDocs("http://sharedocs.huma-num.fr/dav", "u", "p")


def test_ip_interne_refusee() -> None:
    # On autorise explicitement l'IP pour atteindre la garde IP-interne
    # (sinon l'allowlist d'hôte refuserait avant).
    with pytest.raises(ShareDocsHoteInterdit):
        ClientShareDocs(
            "https://127.0.0.1/dav",
            "u",
            "p",
            hotes_autorises=frozenset({"127.0.0.1"}),
        )


def test_identifiants_manquants_refuses() -> None:
    with pytest.raises(ShareDocsAuthRefusee):
        ClientShareDocs(_BASE, "marie", "")


# ---------------------------------------------------------------------------
# Anti-traversal (correctif audit BD_ditor)
# ---------------------------------------------------------------------------


def test_traversal_refuse_sur_lister() -> None:
    with _client(lambda req: httpx.Response(207, text=_MULTISTATUS)) as c:
        with pytest.raises(ShareDocsCheminInvalide):
            c.lister("../../etc")


def test_traversal_refuse_sur_telecharger() -> None:
    with _client(lambda req: httpx.Response(200, content=b"x")) as c:
        with pytest.raises(ShareDocsCheminInvalide):
            c.telecharger("dossier/../../../secret")


def test_segments_vides_et_point_sont_ignores() -> None:
    """`.` et segments vides sont écartés sans erreur (chemin normalisé)."""
    vus: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vus.append(str(req.url))
        return httpx.Response(200, content=b"ok")

    with _client(handler) as c:
        c.telecharger("a/./b//c.pdf")
    assert vus[0] == "https://sharedocs.huma-num.fr/dav/colleC/a/b/c.pdf"


def test_traversal_encode_reste_litteral_pas_de_remontee() -> None:
    """`%2e%2e` / `%2f` ne sont PAS reconnus comme `..` / `/` par le check
    littéral — mais `quote()` les ré-encode (`%25…`), donc le serveur reçoit
    un nom de segment littéral, jamais une remontée. Documente l'invariant."""
    vus: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vus.append(str(req.url))
        return httpx.Response(200, content=b"x")

    with _client(handler) as c:
        c.telecharger("%2e%2e/secret")
    assert vus[0] == "https://sharedocs.huma-num.fr/dav/colleC/%252e%252e/secret"


def test_chemin_double_slash_ne_change_pas_d_hote() -> None:
    """`//evil.com/x` reste un sous-chemin de l'hôte autorisé (pas de
    changement d'autorité)."""
    vus: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vus.append(str(req.url))
        return httpx.Response(200, content=b"x")

    with _client(handler) as c:
        c.telecharger("//evil.com/x")
    assert vus[0] == "https://sharedocs.huma-num.fr/dav/colleC/evil.com/x"


# ---------------------------------------------------------------------------
# Parsing multistatus — branches de robustesse
# ---------------------------------------------------------------------------

_SOUS_DOSSIER = """<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:">
  <d:response><d:href>/dav/colleC/Por%20Favor/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
      <d:displayname>Por Favor</d:displayname></d:prop></d:propstat></d:response>
  <d:response><d:href>/dav/colleC/Por%20Favor/sub/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
      <d:displayname>sub</d:displayname></d:prop></d:propstat></d:response>
  <d:response><d:href>/dav/colleC/Por%20Favor/n01.pdf</d:href>
    <d:propstat><d:prop><d:resourcetype/>
      <d:getcontentlength>10</d:getcontentlength>
      <d:displayname>n01.pdf</d:displayname></d:prop></d:propstat></d:response>
</d:multistatus>"""


def test_lister_sous_dossier_ecarte_le_self() -> None:
    """Le strip du dossier lui-même marche aussi hors racine (la logique
    préfixe/frontière n'était prouvée qu'à la racine)."""
    with _client(lambda req: httpx.Response(207, text=_SOUS_DOSSIER)) as c:
        entrees = c.lister("Por Favor")
    assert [e.chemin for e in entrees] == ["Por Favor/sub", "Por Favor/n01.pdf"]
    # L'entrée « Por Favor » nue (le dossier listé) est bien écartée.
    assert all(e.chemin.strip("/") != "Por Favor" for e in entrees)


def test_xml_malforme_leve_erreur() -> None:
    with _client(lambda req: httpx.Response(207, text="<pas-du-xml")) as c:
        with pytest.raises(ErreurShareDocs):
            c.lister()


def test_dossier_vide_renvoie_liste_vide() -> None:
    """Seule l'entrée self → liste vide (cas courant d'un dossier neuf)."""
    seul_self = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:"><d:response>'
        "<d:href>/dav/colleC/</d:href><d:propstat><d:prop>"
        "<d:resourcetype><d:collection/></d:resourcetype>"
        "</d:prop></d:propstat></d:response></d:multistatus>"
    )
    with _client(lambda req: httpx.Response(207, text=seul_self)) as c:
        assert c.lister() == []


def test_displayname_absent_taille_non_numerique() -> None:
    """`displayname` absent → nom = dernier segment du href ;
    `getcontentlength` absent/non-numérique → taille None."""
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:">'
        "<d:response><d:href>/dav/colleC/sans-nom.txt</d:href><d:propstat><d:prop>"
        "<d:resourcetype/><d:getcontentlength>abc</d:getcontentlength>"
        "</d:prop></d:propstat></d:response>"
        "</d:multistatus>"
    )
    with _client(lambda req: httpx.Response(207, text=xml)) as c:
        entrees = c.lister()
    assert len(entrees) == 1
    assert entrees[0].nom == "sans-nom.txt"  # repli sur le href
    assert entrees[0].taille is None  # "abc" non numérique


def test_propstat_404_en_premier_ignore_au_profit_du_200() -> None:
    """RFC 4918 : si un `<propstat>` 404 précède le 200, on lit quand même le
    bloc 200 (sinon taille/nom perdus). `modifie_le` capté au passage."""
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:"><d:response>'
        "<d:href>/dav/colleC/multi.pdf</d:href>"
        "<d:propstat><d:prop><d:getcontentlength/><d:displayname/></d:prop>"
        "<d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>"
        "<d:propstat><d:prop><d:resourcetype/>"
        "<d:getcontentlength>9999</d:getcontentlength>"
        "<d:displayname>Document Multi.pdf</d:displayname>"
        "<d:getlastmodified>Tue, 17 Jun 2026 10:00:00 GMT</d:getlastmodified>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        "</d:response></d:multistatus>"
    )
    with _client(lambda req: httpx.Response(207, text=xml)) as c:
        entrees = c.lister()
    assert len(entrees) == 1
    e = entrees[0]
    # Discriminant : displayname (bloc 200) ≠ dernier segment du href.
    assert e.nom == "Document Multi.pdf"
    assert e.taille == 9999
    assert e.modifie_le == "Tue, 17 Jun 2026 10:00:00 GMT"


def test_fermer_idempotent() -> None:
    c = ClientShareDocs(_BASE, "u", "p")
    c.fermer()
    c.fermer()  # second appel : pas d'exception
    with ClientShareDocs(_BASE, "u", "p") as c2:
        pass
    c2.fermer()  # après __exit__ : toujours sûr


def test_userinfo_dans_url_refuse() -> None:
    """Pas d'identifiants dans l'URL (sinon conservés dans base_url puis
    ré-exposés en traceback)."""
    with pytest.raises(ShareDocsHoteInterdit):
        ClientShareDocs("https://marie:secret@sharedocs.huma-num.fr/dav", "u", "p")
