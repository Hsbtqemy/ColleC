"""Client HTTP **lecture seule** vers l'API Nakala (Huma-Num).

Fin wrapper httpx, sans logique métier (le mapping des métadonnées vit
dans `mapper.py`) :
  - porte la clé API, l'hôte (prod / apitest), le timeout, le verify SSL ;
  - traduit les erreurs HTTP Nakala en exceptions ColleC ;
  - expose les lectures dont P1 a besoin : `lire_depot`, `lire_collection`,
    `lister_depots_collection`, `lister_depots`, `lister_collections`.

Pièges Nakala intégrés ici (cf. plugin `madbot_nakala_data`, dont ce
client est porté) :
  - `X-API-KEY` est facultatif pour les dépôts *publiés*, obligatoire pour
    les dépôts privés / en attente / sous embargo — on l'envoie dès qu'il
    est configuré ;
  - `POST /users/datas/{scope}` est un POST bien que ce soit une lecture
    (le corps est une requête de recherche) ;
  - le téléchargement binaire (non couvert en P1a) utilise le chemin
    SINGULIER `/data/{id}/{sha1}`.
"""

from __future__ import annotations

import logging
import re
from types import TracebackType
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: Timeout par défaut (s). Nakala est lent sur cache froid (la recherche
#: prend régulièrement 3-5 s en prod).
TIMEOUT_DEFAUT = 30.0

#: Préfixe de l'espace de noms canonique Nakala.
PREFIXE_NAKALA = "10.34847/nkl."

#: Scopes exposés pour `POST /users/{datas,collections}/{scope}`.
SCOPES_CONNUS = ("readable", "owned", "deposited")

#: DOI Nakala dans une chaîne libre : `10.<registrant>/<suffixe>` (le
#: suffixe peut porter une version `.vN`). S'arrête au prochain `/`, espace,
#: `?` ou `#` — donc s'extrait proprement d'une URL.
_PATTERN_DOI = re.compile(r"10\.\d+/[^\s/?#]+")


def normaliser_identifiant_nakala(entree: str) -> str:
    """Extrait le DOI Nakala d'une saisie (URL ou DOI déjà nu).

    Tolère les formes que l'utilisateur copie-colle :
    `https://nakala.fr/collection/10.34847/nkl.xxx`,
    `https://api.nakala.fr/datas/10.34847/nkl.xxx`, `doi:10.34847/nkl.xxx`,
    ou le DOI nu `10.34847/nkl.xxx`. Best-effort : si aucun motif DOI n'est
    trouvé, retourne la saisie strippée (l'API renverra alors un 404 propre).
    """
    s = (entree or "").strip()
    m = _PATTERN_DOI.search(s)
    return m.group(0) if m else s


class ErreurNakala(Exception):
    """Erreur générique côté API Nakala (5xx, 422, réponse inattendue)."""


class NakalaInjoignable(ErreurNakala):
    """Connexion impossible / timeout réseau."""


class NakalaAuthRefusee(ErreurNakala):
    """401 — clé API manquante ou invalide pour la ressource demandée."""


class NakalaAccesInterdit(ErreurNakala):
    """403 — la clé n'a pas le droit d'accéder à la ressource."""


class NakalaIntrouvable(ErreurNakala):
    """404 — l'identifiant demandé n'existe pas (ou pas accessible)."""


def detail_erreur_nakala(reponse: httpx.Response) -> str:
    """Extrait un message d'erreur lisible d'une réponse Nakala en échec.

    Annexe ``payload.validationErrors`` (le **détail par champ** d'un 422,
    p.ex. ``["The metadata http://nakala.fr/terms#title is required."]``) au
    message générique — sinon l'utilisateur ne voit que « Data could not be
    submitted because of invalid data », sans savoir quel champ pose problème
    (T3, validé live 2026-06-15).

    Défensif : corps non-JSON / non-dict, ``payload`` absent ou non-dict,
    ``validationErrors`` absent ou vide → on retombe sur le message générique
    (`message`/`error`) ou le texte brut, sans erreur. Les libellés sont des
    URIs de propriété (pas de PII)."""
    try:
        charge = reponse.json()
    except Exception:  # noqa: BLE001 — corps non-JSON
        return reponse.text
    if not isinstance(charge, dict):
        return reponse.text
    detail = charge.get("message") or charge.get("error") or reponse.text
    payload = charge.get("payload")
    if isinstance(payload, dict):
        erreurs = payload.get("validationErrors")
        if isinstance(erreurs, list) and erreurs:
            libelles = "; ".join(str(e) for e in erreurs)
            detail = f"{detail} — champs en cause : {libelles}"
    return detail


class ClientLectureNakala:
    """Client Nakala minimal, lecture seule, basé sur httpx."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        timeout: float | None = None,
        verify_ssl: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or None
        self.timeout = timeout if (timeout and timeout > 0) else TIMEOUT_DEFAUT
        self.verify_ssl = verify_ssl

        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key

        # `transport` injectable pour les tests (httpx.MockTransport) —
        # None en prod (httpx choisit le transport réseau par défaut).
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=True,
            transport=transport,
        )

    # ---- cycle de vie / context manager ------------------------------
    def fermer(self) -> None:
        client = getattr(self, "_client", None)
        if client is not None:
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("ClientLectureNakala.fermer() a échoué : %s", exc)
            self._client = None

    def __enter__(self) -> ClientLectureNakala:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.fermer()

    # ---- bas niveau --------------------------------------------------
    def _requete(self, methode: str, chemin: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(methode, chemin, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise NakalaInjoignable(self.base_url) from exc
        except httpx.RequestError as exc:
            raise ErreurNakala(f"Requête Nakala échouée : {exc}") from exc

    @staticmethod
    def _verifier_statut(reponse: httpx.Response, *, ressource: str | None = None) -> None:
        if reponse.is_success:
            return
        cible = ressource or str(reponse.url)
        if reponse.status_code == 401:
            raise NakalaAuthRefusee(
                f"Nakala : authentification requise / invalide pour {cible}"
            )
        if reponse.status_code == 403:
            raise NakalaAccesInterdit(f"Nakala : accès refusé (403) pour {cible}")
        if reponse.status_code == 404:
            raise NakalaIntrouvable(cible)
        detail = detail_erreur_nakala(reponse)
        raise ErreurNakala(
            f"Erreur API Nakala (HTTP {reponse.status_code}) pour {cible} : {detail}"
        )

    # ---- API publique ------------------------------------------------
    def lire_depot(self, identifiant: str) -> dict[str, Any]:
        """Retourne un dépôt (`metas`, `files`, …) par identifiant Nakala.

        `identifiant` = forme canonique `10.34847/nkl.xxxxxxxx` (ou
        versionnée `...vN`).
        """
        reponse = self._requete("GET", f"/datas/{identifiant}")
        self._verifier_statut(reponse, ressource=identifiant)
        return reponse.json()

    def lire_collection(self, identifiant: str) -> dict[str, Any]:
        """Retourne les métadonnées d'une collection Nakala."""
        reponse = self._requete("GET", f"/collections/{identifiant}")
        self._verifier_statut(reponse, ressource=identifiant)
        return reponse.json()

    def lister_depots_collection(
        self, identifiant: str, *, page: int = 1, taille: int = 25
    ) -> dict[str, Any]:
        """Une page de dépôts d'une collection (`GET /collections/{id}/datas`)."""
        params = {"page": page, "limit": taille}
        reponse = self._requete(
            "GET", f"/collections/{identifiant}/datas", params=params
        )
        self._verifier_statut(reponse, ressource=f"/collections/{identifiant}/datas")
        return reponse.json()

    def lister_depots(
        self, scope: str = "readable", *, page: int = 1, taille: int = 25
    ) -> dict[str, Any]:
        """Page de dépôts visibles par la clé API dans `scope`.

        `POST /users/datas/{scope}` (POST mais lecture, corps de recherche
        vide). Lève `NakalaAuthRefusee` si le scope exige une clé absente.
        """
        self._garde_scope(scope)
        params = {"page": page, "limit": taille}
        reponse = self._requete(
            "POST", f"/users/datas/{scope}", params=params, json={}
        )
        self._verifier_statut(reponse, ressource=f"/users/datas/{scope}")
        return reponse.json()

    def lister_collections(
        self, scope: str = "readable", *, page: int = 1, taille: int = 25
    ) -> dict[str, Any]:
        """Page de collections visibles par la clé API dans `scope`."""
        self._garde_scope(scope)
        params = {"page": page, "limit": taille}
        reponse = self._requete(
            "POST", f"/users/collections/{scope}", params=params, json={}
        )
        self._verifier_statut(reponse, ressource=f"/users/collections/{scope}")
        return reponse.json()

    @staticmethod
    def _garde_scope(scope: str) -> None:
        if scope not in SCOPES_CONNUS:
            raise ValueError(
                f"scope inconnu {scope!r} ; attendu l'un de {list(SCOPES_CONNUS)}"
            )
