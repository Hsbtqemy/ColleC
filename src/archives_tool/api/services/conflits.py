"""Exceptions partagées par les services de modification.

`ConflitVersion` matérialise le verrou optimiste : le formulaire
porte la version qu'il a lue, le service relit la version actuelle,
et lève l'exception si elles divergent — signe que quelqu'un d'autre
a modifié l'entité entre l'ouverture du formulaire et la soumission.

Deux niveaux de protection cohabitent :
1. *Niveau service* — `verifier_et_incrementer_version` compare la
   version du formulaire à celle lue en base et incrémente la valeur.
   Couvre la race intra-process (deux requêtes successives au même
   uvicorn) : la seconde requête lit la version déjà incrémentée.
2. *Niveau SQLAlchemy* — `version_id_col` sur les modèles (Fonds,
   Collection, Item) ajoute `AND version=?` au WHERE de l'UPDATE.
   Couvre la race cross-process (deux uvicorn pointant la même base
   partagée WebDAV) : si quelqu'un commit entre notre lecture et
   notre commit, l'UPDATE matche 0 ligne et `StaleDataError` est
   levée. `convertir_stale_data` la traduit en `ConflitVersion`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm.exc import StaleDataError


class ConflitVersion(Exception):
    """Le formulaire a été soumis sur une version périmée.

    Le caller (route web ou CLI) intercepte et présente à
    l'utilisateur un message lui demandant de recharger la page
    pour récupérer les modifications de l'autre auteur avant de
    ressoumettre.
    """

    def __init__(self, *, version_attendue: int, version_actuelle: int) -> None:
        super().__init__(
            f"Conflit de version : formulaire soumis avec version "
            f"{version_attendue}, mais la base est à la version "
            f"{version_actuelle}. Rechargez la page pour voir les "
            "modifications avant de ressoumettre."
        )
        self.version_attendue = version_attendue
        self.version_actuelle = version_actuelle


def verifier_et_incrementer_version(entite, formulaire) -> None:
    """Pattern partagé par les services modifier_fonds/collection/item.

    1. Compare `formulaire.version` (None autorisé en back-compat) à
       `entite.version`. Lève `ConflitVersion` si mismatch.
    2. Incrémente `entite.version` manuellement — SQLAlchemy avec
       `version_id_generator=False` se base sur cette nouvelle valeur
       pour la colonne et utilise l'ancienne dans le WHERE de l'UPDATE.

    Le `(or 1)` couvre les entités transientes des tests qui
    instancient `Fonds(...)` directement sans flush (les server_default
    ne sont pas encore appliqués).
    """
    if formulaire.version is not None and formulaire.version != entite.version:
        raise ConflitVersion(
            version_attendue=formulaire.version,
            version_actuelle=entite.version,
        )
    entite.version = (entite.version or 1) + 1


@contextmanager
def convertir_stale_data(version_attendue: int | None) -> Iterator[None]:
    """Traduit `StaleDataError` (race cross-process) en `ConflitVersion`.

    À placer autour du `db.commit()` qui suit
    `verifier_et_incrementer_version`. Si une autre transaction a
    bumpé la version entre notre lecture et notre commit, le WHERE
    `AND version=?` du `version_id_col` matche 0 ligne et SQLAlchemy
    lève `StaleDataError` — qu'on convertit en `ConflitVersion` avec
    `version_actuelle=None` puisqu'on ne peut pas la lire sans relancer
    une transaction.
    """
    try:
        yield
    except StaleDataError as e:
        raise ConflitVersion(
            version_attendue=version_attendue or 0,
            version_actuelle=0,
        ) from e
