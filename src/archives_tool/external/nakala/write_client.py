"""Client HTTP **écriture** vers l'API Nakala (P2 — dépôt).

Porté de `plugins-madbot/madbot_nakala_submission/client.py`, découplé du
framework madbot (exceptions ColleC au lieu de `plugins_api`). Pendant
écriture du `ClientLectureNakala` : mêmes garanties de traduction d'erreurs,
mais la **clé API est obligatoire** (Nakala rejette tout POST anonyme en 401).

Opérations couvertes :
- `uploader_fichier`  → `POST /datas/uploads` (multipart `file`) → `{name, sha1}`
- `creer_depot`       → `POST /datas` (status + files[] + metas[]) → DOI
- `creer_collection`  → `POST /collections` (status + metas[] + datas[]) → DOI
- `rattacher_a_collection` → `POST /datas/{id}/collections`
- `supprimer_depot` / `supprimer_upload` → cleanup (dépôt pending / orphelin)

Réversibilité : un dépôt `pending` est supprimable (pas de DOI DataCite
minté). En cas d'échec du `POST /datas` après upload, l'appelant doit
nettoyer les uploads orphelins via `supprimer_upload` (best-effort).
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from archives_tool.external.nakala.client import (
    ErreurNakala,
    NakalaAccesInterdit,
    NakalaAuthRefusee,
    NakalaInjoignable,
    detail_erreur_nakala,
)

logger = logging.getLogger(__name__)

#: Timeout par défaut (s). Les uploads Nakala sont lents sur cache froid.
TIMEOUT_DEFAUT = 60.0


class NakalaSoumissionInvalide(ErreurNakala):
    """4xx (notamment 422) — charge utile refusée, **action utilisateur**
    requise (corriger les métadonnées / fichiers), pas une erreur transitoire.
    """


class NakalaEcritureClient:
    """Client Nakala minimal côté écriture, basé sur httpx."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float | None = None,
        verify_ssl: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            # Fail-fast à la construction plutôt qu'une boucle de 401.
            raise ValueError("La clé API est obligatoire pour le dépôt Nakala.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout if (timeout and timeout > 0) else TIMEOUT_DEFAUT
        self.verify_ssl = verify_ssl

        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Accept": "application/json", "X-API-KEY": self.api_key},
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=True,
            transport=transport,
        )

    # ---- cycle de vie ------------------------------------------------
    def fermer(self) -> None:
        client = getattr(self, "_client", None)
        if client is not None:
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("NakalaEcritureClient.fermer() a échoué : %s", exc)
            self._client = None

    def __enter__(self) -> NakalaEcritureClient:
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
    def _verifier_statut(reponse: httpx.Response, *, contexte: str) -> None:
        if reponse.is_success:
            return
        if reponse.status_code == 401:
            raise NakalaAuthRefusee(
                f"Nakala : authentification requise / clé invalide ({contexte})."
            )
        if reponse.status_code == 403:
            raise NakalaAccesInterdit(
                f"Nakala : écriture refusée (403) pour {contexte} — la clé "
                "a-t-elle le droit de dépôt sur cette ressource ?"
            )
        # Détail lisible + `payload.validationErrors` (champ(s) fautif(s)
        # d'un 422) annexés — sinon message générique « invalid data » (T3).
        detail = detail_erreur_nakala(reponse)
        # 422 = validation métadonnées ; 4xx = charge utile fautive → action
        # utilisateur. 5xx = erreur serveur transitoire.
        if 400 <= reponse.status_code < 500:
            raise NakalaSoumissionInvalide(
                f"Nakala a rejeté {contexte} (HTTP {reponse.status_code}) : {detail}"
            )
        raise ErreurNakala(
            f"Erreur API Nakala à {contexte} (HTTP {reponse.status_code}) : {detail}"
        )

    # ---- API publique ------------------------------------------------
    def uploader_fichier(
        self, chemin_source: Path | str, nom_fichier: str | None = None
    ) -> dict[str, Any]:
        """Téléverse un fichier dans le stockage temporaire de Nakala.

        `POST /datas/uploads` (champ multipart `file`). Renvoie le descripteur
        `{name, sha1}` — le SHA-1 est la poignée pour référencer ce fichier
        dans le `POST /datas` suivant.
        """
        src = Path(chemin_source)
        if not src.is_file():
            raise NakalaSoumissionInvalide(
                f"uploader_fichier : chemin source absent ou non régulier : {src}"
            )
        nom = nom_fichier or src.name
        try:
            with src.open("rb") as fh:
                reponse = self._requete(
                    "POST", "/datas/uploads", files={"file": (nom, fh)}
                )
        except OSError as exc:
            raise NakalaSoumissionInvalide(
                f"uploader_fichier : lecture impossible de {src} : {exc}"
            ) from exc
        self._verifier_statut(reponse, contexte=f"upload {nom}")
        charge = reponse.json()
        if "sha1" not in charge:
            raise NakalaSoumissionInvalide(
                f"uploader_fichier : réponse Nakala sans 'sha1' pour {nom} : {charge!r}"
            )
        return charge

    def creer_depot(
        self,
        *,
        metas: list[dict[str, Any]],
        files: list[dict[str, Any]],
        status: str = "pending",
        collections_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Crée un dépôt Nakala (`POST /datas`).

        Corps : `{status, files:[{sha1,name}], metas:[{propertyUri,value,…}],
        collectionsIds}`. Renvoie la réponse JSON brute (l'identifiant/DOI est
        dans `payload` — forme extraite par l'appelant via `extraire_doi`).
        """
        corps: dict[str, Any] = {"status": status, "files": files, "metas": metas}
        if collections_ids:
            corps["collectionsIds"] = list(collections_ids)
        reponse = self._requete("POST", "/datas", json=corps)
        self._verifier_statut(reponse, contexte="POST /datas")
        return reponse.json()

    def creer_collection(
        self,
        *,
        metas: list[dict[str, Any]],
        status: str = "private",
        datas: list[str] | None = None,
    ) -> dict[str, Any]:
        """Crée une collection Nakala (`POST /collections`).

        Corps : `{status: private|public, metas:[…], datas:[doi…]}`. Renvoie
        la réponse JSON brute (identifiant dans `payload`).
        """
        corps: dict[str, Any] = {"status": status, "metas": metas}
        if datas:
            corps["datas"] = list(datas)
        reponse = self._requete("POST", "/collections", json=corps)
        self._verifier_statut(reponse, contexte="POST /collections")
        return reponse.json()

    def modifier_depot(
        self,
        identifiant: str,
        *,
        metas: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Met à jour un dépôt existant (`PUT /datas/{id}`).

        Chaque clé du corps est **optionnelle** (signature `metas/files
        nullable`) et omise du corps si `None` — exploration apitest H2A
        confirme que les clés non envoyées sont préservées côté Nakala.

        - **metas** : si fourni, **remplace** intégralement les metas
          (envoyer la liste complète, pas un delta).
        - **files** : si fourni, **remplace** la liste `files[]` (H1).
          Chaque entrée `{sha1, name, ...}` doit pointer un upload réussi
          de la session courante OU un sha1 déjà rattaché au dépôt
          (H4 : sha1 fantôme → HTTP 404). Garde l'ordre envoyé (H5).
          Pour renommer un fichier sans re-upload : passer le même
          `sha1` avec un nouveau `name` (H7, gratuit). **Cas dégénéré
          H3 : `files=[]` (liste vide) est silencieusement ignoré
          côté Nakala — utiliser `supprimer_depot` pour vider un
          dépôt.**
        - **status** : `"published"` mint un DOI DataCite (irréversible).

        Renvoie la réponse JSON (souvent vide ou écho selon Nakala).

        Hypothèses validées par `scripts/explorer_put_files_nakala.py`
        contre apitest le 2026-06-14.
        """
        corps: dict[str, Any] = {}
        if metas is not None:
            corps["metas"] = metas
        if files is not None:
            corps["files"] = files
        if status is not None:
            corps["status"] = status
        reponse = self._requete("PUT", f"/datas/{identifiant}", json=corps)
        self._verifier_statut(reponse, contexte=f"PUT /datas/{identifiant}")
        try:
            return reponse.json()
        except Exception:  # noqa: BLE001 - PUT peut renvoyer un corps vide
            return {}

    def modifier_collection(
        self,
        identifiant: str,
        *,
        metas: list[dict[str, Any]],
        status: str | None = None,
    ) -> dict[str, Any]:
        """Met à jour les métadonnées d'une collection (`PUT /collections/{id}`).

        Comme `modifier_depot`, le `PUT` **remplace** les `metas` (titre,
        description…). `status` optionnel (`private`/`public`). Nakala renvoie
        `204` (corps vide) en succès."""
        corps: dict[str, Any] = {"metas": metas}
        if status is not None:
            corps["status"] = status
        reponse = self._requete("PUT", f"/collections/{identifiant}", json=corps)
        self._verifier_statut(reponse, contexte=f"PUT /collections/{identifiant}")
        try:
            return reponse.json()
        except Exception:  # noqa: BLE001 - 204 → corps vide
            return {}

    def rattacher_a_collection(self, depot_id: str, collection_id: str) -> None:
        """Rattache un dépôt existant à une collection (POST, additif)."""
        reponse = self._requete(
            "POST", f"/datas/{depot_id}/collections", json=[collection_id]
        )
        self._verifier_statut(
            reponse, contexte=f"rattacher {depot_id} → collection {collection_id}"
        )

    def ajouter_fichier(
        self,
        identifiant: str,
        sha1: str,
        *,
        description: str | None = None,
        embargoed: str | None = None,
    ) -> dict[str, Any]:
        """Ajoute un fichier déjà uploadé à un dépôt (`POST /datas/{id}/files`).

        **Additif** : n'affecte pas les autres fichiers — contrairement au
        `PUT /datas/{id}` `files[]` qui **remplace** (H1). Corps = `{sha1}` +
        `description?` / `embargoed?` optionnels ; le **nom** est repris de
        l'upload (le schéma `File` de Nakala ne porte pas de `name`). Succès =
        **200** `{code:200, message:"File added"}` (sondé live 2026-06-15,
        `scripts/explorer_files_granulaire_nakala.py`).

        ⚠️ Codes d'erreur Nakala **non fiables** (sondes F/G) : un sha1 jamais
        uploadé → **500** « File not found on server » (≠ le 404 du `PUT`) ;
        re-POST d'un fichier déjà présent → **409 ou 500** selon l'état du
        stockage temporaire. L'appelant doit donc **valider en amont** (sha1
        issu d'un upload de la session courante, fichier pas déjà attaché) —
        cette méthode lève sur tout non-2xx, sans interpréter le code.
        """
        corps: dict[str, Any] = {"sha1": sha1}
        if description is not None:
            corps["description"] = description
        if embargoed is not None:
            corps["embargoed"] = embargoed
        reponse = self._requete("POST", f"/datas/{identifiant}/files", json=corps)
        self._verifier_statut(reponse, contexte=f"POST /datas/{identifiant}/files")
        try:
            return reponse.json()
        except Exception:  # noqa: BLE001 — réponse éventuellement vide
            return {}

    def supprimer_fichier_donnee(self, identifiant: str, sha1: str) -> None:
        """Retire un fichier d'un dépôt par son sha1
        (`DELETE /datas/{id}/files/{sha1}`).

        Le `{fileIdentifier}` de l'API **est le sha1** (sondé live
        2026-06-15) — pas d'id propre. Retrait ciblé → **204**, les autres
        fichiers intacts.

        ⚠️ Retirer le **dernier** fichier d'un dépôt → **403 (refusé)** : un
        dépôt ne peut pas être vidé de tous ses fichiers (cohérent avec
        `PUT files=[]` ignoré, H3 — pour vider, utiliser `supprimer_depot`).
        L'appelant doit préserver ≥1 fichier.
        """
        reponse = self._requete("DELETE", f"/datas/{identifiant}/files/{sha1}")
        self._verifier_statut(
            reponse,
            contexte=f"DELETE /datas/{identifiant}/files/{sha1[:12]}…",
        )

    def supprimer_depot(self, depot_id: str) -> None:
        """Supprime un dépôt (autorisé uniquement en statut `pending`)."""
        reponse = self._requete("DELETE", f"/datas/{depot_id}")
        self._verifier_statut(reponse, contexte=f"suppression {depot_id}")

    def supprimer_collection(self, collection_id: str) -> None:
        """Supprime une collection (cleanup tests d'intégration)."""
        reponse = self._requete("DELETE", f"/collections/{collection_id}")
        self._verifier_statut(
            reponse, contexte=f"suppression collection {collection_id}"
        )

    def supprimer_upload(self, identifiant_fichier: str) -> None:
        """Retire un fichier du stockage temporaire (cleanup orphelins).

        Best-effort : l'appelant avale les échecs (l'utilisateur a déjà une
        vraie erreur sous les yeux)."""
        reponse = self._requete("DELETE", f"/datas/uploads/{identifiant_fichier}")
        self._verifier_statut(
            reponse, contexte=f"suppression upload {identifiant_fichier}"
        )


def extraire_doi(reponse: dict[str, Any]) -> str | None:
    """Extrait l'identifiant (DOI) d'une réponse de création Nakala.

    Nakala ne documente pas la forme exacte dans Swagger ; on tolère les
    variantes observées : `payload.id`, `payload.identifier`, ou `identifier`
    au premier niveau.
    """
    payload = reponse.get("payload")
    if isinstance(payload, dict):
        doi = payload.get("id") or payload.get("identifier")
        if doi:
            return str(doi)
    doi = reponse.get("identifier") or reponse.get("id")
    return str(doi) if doi else None
