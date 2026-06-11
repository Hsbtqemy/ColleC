"""Itération d'une collection Nakala (Lot 1, T1.1).

Pagine `GET /collections/{id}/datas` via :class:`ClientLectureNakala` et
yield chaque dépôt (`data`) brut. Le listing Nakala renvoie déjà les
`files` complets (nom, sha1, mime, taille, embargo…) : **aucun appel par
dépôt n'est nécessaire** pour produire un tableur niveau donnée *ou*
fichier.

Lecture pure : aucune écriture en base, aucune projection (le mapping
vit dans `mapper.py`, l'aplatissement tableur dans `tableur.py`).
"""

from __future__ import annotations

from collections.abc import Iterator

from archives_tool.external.nakala.client import ClientLectureNakala

#: Taille de page par défaut (Nakala accepte jusqu'à 100 ; 50 est un bon
#: compromis débit / mémoire pour les grosses collections).
TAILLE_PAGE_DEFAUT = 50


def iterer_donnees_collection(
    client: ClientLectureNakala,
    identifiant: str,
    *,
    taille: int = TAILLE_PAGE_DEFAUT,
) -> Iterator[dict]:
    """Yield chaque dépôt d'une collection Nakala, page après page.

    `identifiant` = DOI de la collection (`10.34847/nkl.xxxxxxxx`).
    Le nombre de pages est figé sur le `lastPage` observé à la première
    page (borne anti-boucle : un `lastPage` mouvant côté API ne fait pas
    tourner l'itérateur indéfiniment). Les erreurs HTTP (404, 401…) sont
    propagées telles quelles par le client.
    """
    premiere = client.lister_depots_collection(identifiant, page=1, taille=taille)
    derniere_page = int(premiere.get("lastPage") or 1)
    yield from (premiere.get("data") or [])

    for page in range(2, derniere_page + 1):
        charge = client.lister_depots_collection(identifiant, page=page, taille=taille)
        yield from (charge.get("data") or [])
