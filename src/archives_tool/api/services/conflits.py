"""Exceptions partagées par les services de modification.

`ConflitVersion` matérialise le verrou optimiste : le formulaire
porte la version qu'il a lue, le service relit la version actuelle,
et lève l'exception si elles divergent — signe que quelqu'un d'autre
a modifié l'entité entre l'ouverture du formulaire et la soumission.
"""

from __future__ import annotations


class ConflitVersion(Exception):
    """Le formulaire a été soumis sur une version périmée.

    Le caller (route web ou CLI) intercepte et présente à
    l'utilisateur un message lui demandant de recharger la page
    pour récupérer les modifications de l'autre auteur avant de
    ressoumettre.
    """

    def __init__(self, version_attendue: int, version_actuelle: int) -> None:
        super().__init__(
            f"Conflit de version : formulaire soumis avec version "
            f"{version_attendue}, mais la base est à la version "
            f"{version_actuelle}. Rechargez la page pour voir les "
            "modifications avant de ressoumettre."
        )
        self.version_attendue = version_attendue
        self.version_actuelle = version_actuelle
