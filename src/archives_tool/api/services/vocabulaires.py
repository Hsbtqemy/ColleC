"""Vocabulaires de référence pour les champs item à valeurs contrôlées.

Liste frugale (pas de table Vocabulaire au modèle pour l'instant — V2+).
Les valeurs servent à peupler les `<select>` de l'édition inline pour
les champs `langue` et `type_coar`. Une `(valeur, libelle)` par option :
la valeur est ce qui est stocké en base (ISO 639-3 / URI COAR), le
libellé est ce que voit l'utilisateur dans le dropdown.

Étendre cette liste à mesure que les chantiers en font émerger le besoin.
"""

from __future__ import annotations

# ISO 639-3 — langues fréquentes en contextes d'archives francophones.
# Source : https://iso639-3.sil.org/
LANGUES_OPTIONS: tuple[tuple[str, str], ...] = (
    ("fra", "Français"),
    ("eng", "Anglais"),
    ("spa", "Espagnol"),
    ("ita", "Italien"),
    ("deu", "Allemand"),
    ("lat", "Latin"),
    ("por", "Portugais"),
    ("nld", "Néerlandais"),
    ("ara", "Arabe"),
    ("rus", "Russe"),
    ("ell", "Grec moderne"),
    ("grc", "Grec ancien"),
    ("oci", "Occitan"),
    ("bre", "Breton"),
    ("cat", "Catalan"),
    ("mul", "Multilingue"),
    ("und", "Indéterminé"),
)


# URIs COAR Resource Types fréquemment utilisés.
# Source : https://vocabularies.coar-repositories.org/resource_types/
TYPES_COAR_OPTIONS: tuple[tuple[str, str], ...] = (
    ("http://purl.org/coar/resource_type/c_18cf", "Texte"),
    ("http://purl.org/coar/resource_type/c_3e5a", "Périodique"),
    ("http://purl.org/coar/resource_type/c_0640", "Numéro de périodique"),
    ("http://purl.org/coar/resource_type/c_6501", "Article de revue"),
    ("http://purl.org/coar/resource_type/c_2f33", "Livre"),
    ("http://purl.org/coar/resource_type/c_3248", "Chapitre de livre"),
    ("http://purl.org/coar/resource_type/c_8042", "Document de travail"),
    ("http://purl.org/coar/resource_type/c_18co", "Document d'archives"),
    ("http://purl.org/coar/resource_type/c_c513", "Image"),
    ("http://purl.org/coar/resource_type/c_ecc8", "Carte"),
    ("http://purl.org/coar/resource_type/c_8a7e", "Manuscrit"),
    ("http://purl.org/coar/resource_type/c_18cd", "Photographie"),
    ("http://purl.org/coar/resource_type/c_18cw", "Partition musicale"),
    ("http://purl.org/coar/resource_type/c_12cd", "Vidéo"),
    ("http://purl.org/coar/resource_type/c_18cc", "Enregistrement sonore"),
)


# Mapping field → options pour le compositeur de cartouche.
OPTIONS_PAR_CHAMP: dict[str, tuple[tuple[str, str], ...]] = {
    "langue": LANGUES_OPTIONS,
    "type_coar": TYPES_COAR_OPTIONS,
}


def libelle_pour_valeur(
    valeur: object,
    options: tuple[tuple[str, str], ...] | None,
) -> str | None:
    """Résout une valeur stockée vers son libellé humain via les options.

    URI COAR → « Texte », code ISO « fra » → « Français ». Si la
    valeur n'est pas dans la liste (legacy / hors-référentiel),
    retourne la valeur brute inchangée — le cartouche l'affichera
    telle quelle.
    """
    if valeur is None or not options:
        return valeur if valeur is None else str(valeur)
    valeur_str = str(valeur)
    for v, libelle in options:
        if v == valeur_str:
            return libelle
    return valeur_str


def resoudre_vocabulaire(
    field: str, valeur: object
) -> tuple[tuple[tuple[str, str], ...] | None, str | None]:
    """Atomise le couple (options du champ, libellé pour la valeur).

    Évite la duplication composer/route : un seul lookup, deux
    informations renvoyées. Retourne `(None, valeur)` si le champ
    n'a pas de vocabulaire enregistré.
    """
    options = OPTIONS_PAR_CHAMP.get(field)
    return options, libelle_pour_valeur(valeur, options)
