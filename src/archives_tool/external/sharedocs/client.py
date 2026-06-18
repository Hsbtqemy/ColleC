"""Client WebDAV minimal pour ShareDocs (Huma-Num), basé sur httpx.

Ingestion *remote-first* (Chantier 1) : **lister** un dossier (PROPFIND) et
**télécharger** un fichier (GET) depuis un partage WebDAV, **sans monter**
le partage. Porté du prototype BD_ditor (`pipeline/sharedocs.py`),
re-implémenté au style ColleC :

- **classe à config explicite** (`base_url` + identifiants au constructeur),
  réutilisable par le web ET la CLI — ≠ la session module-globale de
  BD_ditor ;
- **transport injectable** (`httpx.MockTransport`) pour des tests sans
  réseau, comme `ClientLectureNakala`.

Correctifs issus de l'audit BD_ditor (appliqués ici dès le départ) :

- **HTTPS exigé** : `http://` refusé — les identifiants Basic ne doivent
  jamais circuler en clair.
- **anti-traversal** : un segment `..` dans un chemin distant est refusé
  (pas de remontée d'arborescence WebDAV).

Sécurité (modèle local de confiance) : les identifiants sont passés au
constructeur, **jamais écrits sur disque ni loggés**. Anti-SSRF : allowlist
d'hôte, refus des IP internes, **redirections non suivies** (une 3xx ne doit
jamais être prise pour un succès). On n'expose que la **lecture** (lister /
télécharger) ; l'écriture WebDAV (dépôt) n'est pas implémentée (pas de
besoin ColleC à ce stade).
"""

from __future__ import annotations

import ipaddress
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from types import TracebackType
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpx

logger = logging.getLogger(__name__)

#: Espace de noms WebDAV (RFC 4918) pour le parsing du `<multistatus>`.
_DAV = {"d": "DAV:"}

#: Hôtes ShareDocs autorisés par défaut (anti-SSRF). Surchargé au besoin
#: via le paramètre `hotes_autorises` du constructeur.
HOTES_AUTORISES_DEFAUT: frozenset[str] = frozenset({"sharedocs.huma-num.fr"})

#: Timeout réseau par défaut (s), aligné sur le client Nakala.
TIMEOUT_DEFAUT = 30.0

#: Corps PROPFIND minimal : juste de quoi distinguer dossier/fichier,
#: la taille, la date et le nom d'affichage.
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop>'
    "<d:resourcetype/><d:getcontentlength/>"
    "<d:getlastmodified/><d:displayname/>"
    "</d:prop></d:propfind>"
)


class ErreurShareDocs(Exception):
    """Erreur générique côté ShareDocs (réseau, identifiants, réponse)."""


class ShareDocsInjoignable(ErreurShareDocs):
    """Connexion impossible / timeout réseau."""


class ShareDocsAuthRefusee(ErreurShareDocs):
    """401 / 403 — identifiants refusés ou accès interdit."""


class ShareDocsHoteInterdit(ErreurShareDocs):
    """URL hors allowlist d'hôte, schéma non-HTTPS, ou IP interne (anti-SSRF)."""


class ShareDocsCheminInvalide(ErreurShareDocs):
    """Chemin distant invalide (segment `..` — anti-traversal)."""


@dataclass(frozen=True)
class EntreeShareDocs:
    """Une entrée d'un dossier ShareDocs (résultat de ``lister``).

    - ``nom`` : nom d'affichage (displayname WebDAV, sinon dernier segment) ;
    - ``chemin`` : chemin **relatif** à la `base_url` (réutilisable tel quel
      dans ``lister`` / ``telecharger``) ;
    - ``est_dossier`` : True si collection WebDAV ;
    - ``taille`` : octets (``getcontentlength``) ou None (dossier / inconnu) ;
    - ``modifie_le`` : date HTTP brute (``getlastmodified``) ou None — non
      parsée (utile pour affichage/tri dans la future UI de parcours).
    """

    nom: str
    chemin: str
    est_dossier: bool
    taille: int | None
    modifie_le: str | None = None


def _valider_base_url(base_url: str, hotes_autorises: frozenset[str]) -> str:
    """Valide et normalise la `base_url` ShareDocs (anti-SSRF + HTTPS).

    Lève ``ShareDocsHoteInterdit`` si le schéma n'est pas HTTPS, si l'hôte
    n'est pas dans l'allowlist, ou si c'est une IP interne. Renvoie l'URL
    sans `/` final.
    """
    base_url = (base_url or "").strip().rstrip("/")
    parts = urlsplit(base_url)
    # HTTPS exigé (correctif audit BD_ditor) : Basic Auth jamais en clair.
    if parts.scheme != "https":
        raise ShareDocsHoteInterdit(
            "URL ShareDocs invalide : HTTPS requis (schéma reçu : "
            f"{parts.scheme or '∅'!r})."
        )
    # Pas d'identifiants dans l'URL (`https://user:pass@host`) : sinon ils
    # seraient conservés dans `self.base_url` puis ré-exposés dans les
    # messages d'erreur / tracebacks. Les creds passent par user/password.
    if parts.username or parts.password:
        raise ShareDocsHoteInterdit(
            "URL ShareDocs invalide : pas d'identifiants dans l'URL "
            "(passer utilisateur / mot de passe séparément)."
        )
    host = (parts.hostname or "").lower()
    if not host:
        raise ShareDocsHoteInterdit("URL ShareDocs invalide (hôte manquant).")
    if host not in hotes_autorises:
        raise ShareDocsHoteInterdit(
            f"Hôte ShareDocs non autorisé : {host}. "
            f"Autorisé(s) : {', '.join(sorted(hotes_autorises)) or '(aucun)'}."
        )
    # Défense supplémentaire : pas d'IP interne (si l'hôte est une IP).
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass  # nom de domaine, pas une IP → OK
    else:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ShareDocsHoteInterdit("Adresse IP interne interdite.")
    return base_url


def _segments_surs(chemin: str) -> list[str]:
    """Découpe un chemin relatif en segments, en refusant `..` (traversal).

    Les segments vides et `.` sont écartés. Lève ``ShareDocsCheminInvalide``
    sur tout `..` (correctif audit BD_ditor : pas de remontée d'arborescence
    WebDAV).
    """
    segments: list[str] = []
    for seg in (chemin or "").strip("/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ShareDocsCheminInvalide(
                f"Chemin ShareDocs interdit (remontée `..`) : {chemin!r}."
            )
        segments.append(seg)
    return segments


def _prop_du_propstat_ok(resp: ET.Element) -> ET.Element | None:
    """Renvoie le ``<d:prop>`` du ``<d:propstat>`` à statut **200**.

    RFC 4918 §9.1 : une ``<d:response>`` peut porter plusieurs
    ``<d:propstat>`` (typiquement un 200 « props trouvées » + un 404 « props
    absentes »), dans un **ordre non normatif**. Prendre aveuglément le
    premier (ce que faisait le prototype BD_ditor) peut lire un bloc 404 et
    perdre `getcontentlength` / `displayname`. On sélectionne donc le bloc
    dont le ``<d:status>`` contient ``200`` ; repli sur le premier
    ``<d:prop>`` si aucun statut 200 lisible (serveurs mono-propstat)."""
    propstats = resp.findall("d:propstat", _DAV)
    for ps in propstats:
        statut = ps.findtext("d:status", default="", namespaces=_DAV) or ""
        if "200" in statut.split():  # "HTTP/1.1 200 OK" → {"HTTP/1.1","200","OK"}
            prop = ps.find("d:prop", _DAV)
            if prop is not None:
                return prop
    return resp.find("d:propstat/d:prop", _DAV)


class ClientShareDocs:
    """Client WebDAV ShareDocs minimal (lecture), basé sur httpx."""

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        timeout: float | None = None,
        verify_ssl: bool = True,
        hotes_autorises: frozenset[str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not (base_url and user and password):
            raise ShareDocsAuthRefusee(
                "URL, utilisateur et mot de passe ShareDocs requis."
            )
        self._hotes_autorises = hotes_autorises or HOTES_AUTORISES_DEFAUT
        self.base_url = _valider_base_url(base_url, self._hotes_autorises)
        self.timeout = timeout if (timeout and timeout > 0) else TIMEOUT_DEFAUT
        self.verify_ssl = verify_ssl

        # `follow_redirects=False` (anti-SSRF) : une redirection depuis
        # l'hôte autorisé vers une cible interne ne doit jamais être suivie.
        # `auth=(user, password)` = Basic. `transport` injectable pour les
        # tests (MockTransport) — None en prod.
        self._client = httpx.Client(
            auth=(user, password),
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=False,
            transport=transport,
        )

    # ---- cycle de vie / context manager ------------------------------
    def fermer(self) -> None:
        client = getattr(self, "_client", None)
        if client is not None:
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("ClientShareDocs.fermer() a échoué : %s", exc)
            self._client = None

    def __enter__(self) -> ClientShareDocs:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.fermer()

    # ---- bas niveau --------------------------------------------------
    def _url(self, chemin: str) -> str:
        """Construit l'URL absolue d'un chemin relatif (segments url-encodés,
        anti-traversal). `chemin=""` → la racine."""
        segments = _segments_surs(chemin)
        if not segments:
            return self.base_url + "/"
        return self.base_url + "/" + "/".join(quote(seg) for seg in segments)

    def _requete(self, methode: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            reponse = self._client.request(methode, url, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ShareDocsInjoignable(self.base_url) from exc
        except httpx.RequestError as exc:
            raise ErreurShareDocs(f"Requête ShareDocs échouée : {exc}") from exc
        # Redirection non suivie (anti-SSRF) → jamais un succès.
        if 300 <= reponse.status_code < 400:
            raise ErreurShareDocs(
                f"Redirection inattendue ({reponse.status_code}) — non suivie "
                "(sécurité)."
            )
        if reponse.status_code in (401, 403):
            raise ShareDocsAuthRefusee("Identifiants refusés par ShareDocs (401/403).")
        if reponse.status_code >= 400:
            raise ErreurShareDocs(f"ShareDocs a répondu {reponse.status_code}.")
        return reponse

    def _parse_multistatus(self, texte: str) -> list[EntreeShareDocs]:
        """Transforme un ``<d:multistatus>`` en liste d'``EntreeShareDocs``."""
        base_path = unquote(urlsplit(self.base_url).path).rstrip("/")
        try:
            racine = ET.fromstring(texte.encode("utf-8"))
        except ET.ParseError as exc:
            raise ErreurShareDocs(f"Réponse ShareDocs illisible : {exc}") from exc

        entrees: list[EntreeShareDocs] = []
        for resp in racine.findall("d:response", _DAV):
            href = resp.findtext("d:href", default="", namespaces=_DAV)
            rel = unquote(urlsplit(href).path)
            # Retire le préfixe de base sur une frontière de segment (évite de
            # tronquer un voisin du type .../u → .../username2).
            if rel == base_path:
                rel = ""
            elif rel.startswith(base_path + "/"):
                rel = rel[len(base_path) :]
            rel = rel.strip("/")

            prop = _prop_du_propstat_ok(resp)
            est_dossier, taille, nom, modifie_le = False, None, None, None
            if prop is not None:
                rtype = prop.find("d:resourcetype", _DAV)
                est_dossier = (
                    rtype is not None and rtype.find("d:collection", _DAV) is not None
                )
                taille_txt = (
                    prop.findtext("d:getcontentlength", namespaces=_DAV) or ""
                ).strip()
                taille = int(taille_txt) if taille_txt.isdigit() else None
                nom = (
                    prop.findtext("d:displayname", namespaces=_DAV) or ""
                ).strip() or None
                modifie_le = (
                    prop.findtext("d:getlastmodified", namespaces=_DAV) or ""
                ).strip() or None
            if not nom:
                nom = rel.rsplit("/", 1)[-1] or "/"
            entrees.append(
                EntreeShareDocs(
                    nom=nom,
                    chemin=rel,
                    est_dossier=est_dossier,
                    taille=taille,
                    modifie_le=modifie_le,
                )
            )
        return entrees

    # ---- API publique ------------------------------------------------
    def lister(self, chemin: str = "") -> list[EntreeShareDocs]:
        """Liste un dossier distant (dossiers d'abord, puis fichiers, par nom).

        L'entrée représentant le dossier lui-même (incluse par PROPFIND
        Depth:1) est retirée du résultat.
        """
        url = self._url(chemin)
        reponse = self._requete(
            "PROPFIND",
            url,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=_PROPFIND_BODY,
        )
        cible = (chemin or "").strip("/")
        entrees = [
            e
            for e in self._parse_multistatus(reponse.text)
            if e.chemin.strip("/") != cible
        ]
        entrees.sort(key=lambda e: (not e.est_dossier, e.nom.lower()))
        return entrees

    def telecharger(self, chemin: str) -> bytes:
        """Télécharge le contenu binaire d'un fichier distant."""
        reponse = self._requete("GET", self._url(chemin))
        return reponse.content
