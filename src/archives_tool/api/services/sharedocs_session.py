"""État de connexion ShareDocs en mémoire (RAM) — Chantier 1, tranche 3.

Côté web, les identifiants ShareDocs (Basic Auth = mot de passe du compte
Huma-Num) sont gardés **uniquement en mémoire** du process : jamais sur
disque, jamais en config, jamais renvoyés au client, jamais loggés. Perdus
au redémarrage.

**Isolation per-owner (dé-risquage multi-utilisateurs).** Les creds sont
rangés dans ``_sessions`` *keyé par owner* (``deps.get_owner_key()``), pas
dans un singleton. En mode local mono-utilisateur il n'y a qu'un owner
(``OWNER_DEFAUT``) → comportement identique à avant. En mode serveur
(Chantier 3), chaque session/utilisateur a sa propre entrée → un
utilisateur ne peut **pas** voir ni réutiliser les creds d'un autre. Le
seul changement à faire le jour venu est de faire renvoyer à
``deps.get_owner_key()`` l'id de session courant. Cf.
`deploiement-future.md` § *Credentials Huma-Num multi-comptes*.
"""

from __future__ import annotations

import threading

#: Défaut en mode local — réplique `deps.OWNER_DEFAUT` (les services
#: n'importent pas `deps` pour éviter un cycle). Garder alignés.
OWNER_DEFAUT = "local"

_lock = threading.Lock()
#: owner -> {"base_url", "user", "password"}. Une entrée par owner connecté.
_sessions: dict[str, dict[str, str | None]] = {}


def connecter(
    base_url: str, user: str, password: str, *, owner: str = OWNER_DEFAUT
) -> None:
    with _lock:
        _sessions[owner] = {"base_url": base_url, "user": user, "password": password}


def deconnecter(*, owner: str = OWNER_DEFAUT) -> None:
    with _lock:
        _sessions.pop(owner, None)


def est_connecte(*, owner: str = OWNER_DEFAUT) -> bool:
    with _lock:
        return bool(_sessions.get(owner, {}).get("base_url"))


def identifiants(*, owner: str = OWNER_DEFAUT) -> tuple[str, str, str] | None:
    """``(base_url, user, password)`` si connecté, sinon ``None``. Usage
    **interne** (construction du client) — ne JAMAIS exposer au template
    ni au client."""
    with _lock:
        s = _sessions.get(owner)
        if not s or not s["base_url"]:
            return None
        return (s["base_url"], s["user"], s["password"])  # type: ignore[return-value]


def etat_public(*, owner: str = OWNER_DEFAUT) -> dict[str, object]:
    """État **affichable** : connecté + base_url + user. **Jamais** le mot
    de passe."""
    with _lock:
        s = _sessions.get(owner) or {}
        return {
            "connecte": bool(s.get("base_url")),
            "base_url": s.get("base_url"),
            "user": s.get("user"),
        }


def _reset_pour_tests() -> None:
    """Vide toutes les sessions (isolation des tests)."""
    with _lock:
        _sessions.clear()
