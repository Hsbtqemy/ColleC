"""État de connexion ShareDocs en mémoire (RAM) — Chantier 1, tranche 3.

Côté web, les identifiants ShareDocs (Basic Auth = mot de passe du compte
Huma-Num) sont gardés **uniquement en mémoire** du process : jamais sur
disque, jamais en config, jamais renvoyés au client, jamais loggés. Perdus
au redémarrage. Pattern aligné sur `nakala_depot_jobs._JOBS` (registre
mémoire + ``threading.Lock``).

Mono-processus, mono-utilisateur local. En V1.0 multi-utilisateurs, ce
porteur deviendra **per-compte** (résolveur collection → espace → creds,
cf. `deploiement-future.md` § *Credentials Huma-Num multi-comptes*).
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_session: dict[str, str | None] = {"base_url": None, "user": None, "password": None}


def connecter(base_url: str, user: str, password: str) -> None:
    with _lock:
        _session.update(base_url=base_url, user=user, password=password)


def deconnecter() -> None:
    with _lock:
        _session.update(base_url=None, user=None, password=None)


def est_connecte() -> bool:
    with _lock:
        return bool(_session["base_url"])


def identifiants() -> tuple[str, str, str] | None:
    """``(base_url, user, password)`` si connecté, sinon ``None``. Usage
    **interne** (construction du client) — ne JAMAIS exposer au template
    ni au client."""
    with _lock:
        if not _session["base_url"]:
            return None
        return (_session["base_url"], _session["user"], _session["password"])


def etat_public() -> dict[str, object]:
    """État **affichable** : connecté + base_url + user. **Jamais** le mot
    de passe."""
    with _lock:
        return {
            "connecte": bool(_session["base_url"]),
            "base_url": _session["base_url"],
            "user": _session["user"],
        }
