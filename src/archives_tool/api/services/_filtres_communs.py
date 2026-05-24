"""Helpers partagés entre `dashboard.parser_filtres_collection` et
`recherche.parser_filtres_recherche`.

Évite la duplication de `_csv_to_liste` et de la validation des
années contre des bornes dynamiques. Les deux parsers restent
spécialisés (champs de sortie différents, validations différentes
sur etat — enum global pour collection vs options scope-aware
pour recherche), mais s'appuient sur ces primitives communes.
"""

from __future__ import annotations


def csv_to_liste(valeur: str | list[str] | None) -> list[str]:
    """Parse une valeur multi-valuée en liste de chaînes uniques.

    Accepte deux serialisations envoyées par les filtres :
    - chaîne CSV `a,b,c` (depuis un lien forgé à la main),
    - liste de chaînes `["a", "b"]` (depuis un `<select multiple>`
      qui envoie `?key=a&key=b` — FastAPI déserialise en liste).

    Cas mixte : une liste dont les éléments contiennent des CSV est
    aplatie. Strip + dédoublonne en préservant l'ordre. Vide sur
    None ou liste vide.
    """
    if valeur is None:
        return []
    parts: list[str]
    if isinstance(valeur, str):
        parts = valeur.split(",")
    else:
        parts = []
        for v in valeur:
            parts.extend(v.split(","))
    vu: set[str] = set()
    sortie: list[str] = []
    for part in parts:
        v = part.strip()
        if v and v not in vu:
            vu.add(v)
            sortie.append(v)
    return sortie


def clamper_annee(
    v: int | None, borne_min: int | None, borne_max: int | None,
) -> int | None:
    """Retourne `v` s'il est dans `[borne_min, borne_max]`, sinon `None`.

    Si les bornes ne sont pas définies (aucun item daté dans le
    périmètre), `v` est rejeté silencieusement — c'est cohérent
    avec la philosophie de validation silencieuse des filtres
    (jamais de 400 sur paramètre invalide).
    """
    if v is None:
        return None
    if borne_min is None or borne_max is None:
        return None
    if v < borne_min or v > borne_max:
        return None
    return v
