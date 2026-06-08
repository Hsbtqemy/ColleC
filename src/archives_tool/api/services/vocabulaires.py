"""Vocabulaires de référence pour les champs item à valeurs contrôlées.

Liste frugale (pas de table Vocabulaire au modèle pour l'instant — V2+).
Les valeurs servent à peupler les `<select>` de l'édition inline pour
les champs `langue` et `type_coar`. Une `(valeur, libelle)` par option :
la valeur est ce qui est stocké en base (ISO 639-3 / URI COAR), le
libellé est ce que voit l'utilisateur dans le dropdown.

Étendre cette liste à mesure que les chantiers en font émerger le besoin.
"""

from __future__ import annotations

from archives_tool.reference.loaders import langues_iso639

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


# Workflow d'état du catalogage : les 5 états « actifs » du cycle de
# vie d'un item (brouillon → à vérifier → vérifié → validé, plus
# l'état « à corriger » qui permet de re-rentrer dans le cycle). Les
# états techniques (`actif`, `remplace`, `corbeille`) sont exclus du
# sélecteur d'édition inline — ils relèvent du cycle de vie de la
# notice (suppression / archivage), pas du suivi de catalogage.
ETATS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("brouillon", "brouillon"),
    ("a_verifier", "à vérifier"),
    ("verifie", "vérifié"),
    ("valide", "validé"),
    ("a_corriger", "à corriger"),
)


# Phases de chantier — utilisé pour l'inline edit du champ
# Collection.phase (et déjà rendu via le composant phase_chantier
# dans le bandeau). Source : PhaseChantier + LIBELLES_PHASE.
PHASES_OPTIONS: tuple[tuple[str, str], ...] = (
    ("numerisation", "numérisation"),
    ("catalogage", "catalogage"),
    ("revision", "révision"),
    ("finalisation", "finalisation"),
    ("archivee", "archivée"),
    ("en_pause", "en pause"),
)


# Mapping field → options pour le compositeur de cartouche.
OPTIONS_PAR_CHAMP: dict[str, tuple[tuple[str, str], ...]] = {
    "langue": LANGUES_OPTIONS,
    "type_coar": TYPES_COAR_OPTIONS,
    "etat_catalogage": ETATS_OPTIONS,
    "phase": PHASES_OPTIONS,
}


#: Mapping libellé/alias textuel → URI COAR. Utilisé à l'import pour
#: convertir automatiquement les valeurs textuelles (`journal`,
#: `périodique`, `revue`…) en URI canonique. Sans cette table, un
#: tableur avec une colonne `Type=journal` mappée à `type_coar`
#: stockerait `"journal"` brut — pas exportable proprement en
#: `dc:type` URI, et invisible au sélecteur d'édition inline (qui
#: pré-remplit selon la valeur stockée vs URI).
#:
#: Les clés sont normalisées (lower + strip + sans accents) avant
#: lookup dans `_normaliser_type_coar`.
_C = "http://purl.org/coar/resource_type"
_ALIAS_VERS_COAR: dict[str, str] = {
    # Périodique (c_3e5a) et numéro de périodique (c_0640) — alias
    # fr / en / variants. `journal` est ambigu (français : quotidien
    # OU livre de bord ; anglais : revue scientifique) mais la
    # dénomination la plus fréquente sur Nakala = périodique.
    "journal": f"{_C}/c_3e5a",
    "periodique": f"{_C}/c_3e5a",
    "revue": f"{_C}/c_3e5a",
    "magazine": f"{_C}/c_3e5a",
    "periodical": f"{_C}/c_3e5a",
    "newspaper": f"{_C}/c_3e5a",
    "quotidien": f"{_C}/c_3e5a",
    "numero": f"{_C}/c_0640",
    "numero de periodique": f"{_C}/c_0640",
    "issue": f"{_C}/c_0640",
    "journal issue": f"{_C}/c_0640",
    # Article (c_6501)
    "article": f"{_C}/c_6501",
    "article de revue": f"{_C}/c_6501",
    "journal article": f"{_C}/c_6501",
    # Livre (c_2f33) / chapitre (c_3248)
    "livre": f"{_C}/c_2f33",
    "book": f"{_C}/c_2f33",
    "ouvrage": f"{_C}/c_2f33",
    "monographie": f"{_C}/c_2f33",
    "chapitre": f"{_C}/c_3248",
    "chapter": f"{_C}/c_3248",
    "chapitre de livre": f"{_C}/c_3248",
    "book chapter": f"{_C}/c_3248",
    # Texte générique (c_18cf)
    "texte": f"{_C}/c_18cf",
    "text": f"{_C}/c_18cf",
    # Manuscrit / archives / photo / carte
    "manuscrit": f"{_C}/c_8a7e",
    "manuscript": f"{_C}/c_8a7e",
    "archives": f"{_C}/c_18co",
    "document d'archives": f"{_C}/c_18co",
    "archival material": f"{_C}/c_18co",
    "image": f"{_C}/c_c513",
    "photographie": f"{_C}/c_18cd",
    "photo": f"{_C}/c_18cd",
    "photograph": f"{_C}/c_18cd",
    "carte": f"{_C}/c_ecc8",
    "map": f"{_C}/c_ecc8",
    # Multimedia
    "video": f"{_C}/c_12cd",
    "son": f"{_C}/c_18cc",
    "audio": f"{_C}/c_18cc",
    "enregistrement sonore": f"{_C}/c_18cc",
    "sound recording": f"{_C}/c_18cc",
    "partition": f"{_C}/c_18cw",
    "partition musicale": f"{_C}/c_18cw",
    "musical score": f"{_C}/c_18cw",
}


def _normaliser_texte(s: str) -> str:
    """Lowercase + strip + sans accents combinés (NFD → drop diacritiques
    → NFC). Identique à la slugification mais sans collapse des espaces
    — on garde « numero de periodique » comme une seule clé reconnue."""
    import unicodedata

    nfd = unicodedata.normalize("NFD", s.lower().strip())
    return "".join(c for c in nfd if not unicodedata.combining(c))


def normaliser_type_coar(valeur: object) -> str | None:
    """Convertit un libellé textuel (`journal`, `périodique`, `numéro`,
    …) en URI COAR canonique via :data:`_ALIAS_VERS_COAR`.

    Retourne `None` si :
    - la valeur est vide ou non-str ;
    - la valeur est déjà une URI COAR (déjà canonique, pas besoin
      de re-mapper) ;
    - le libellé n'est pas dans la table d'alias (l'import garde
      alors la valeur brute, l'utilisateur peut éditer via inline).
    """
    if not isinstance(valeur, str):
        return None
    brut = valeur.strip()
    if not brut:
        return None
    if brut.startswith("http://purl.org/coar/"):
        return None  # déjà canonique
    return _ALIAS_VERS_COAR.get(_normaliser_texte(brut))


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


def libelle_langue(code: object) -> str | None:
    """Résout un code langue vers son libellé humain.

    Cascade : liste curée :data:`LANGUES_OPTIONS` (libellés FR du
    dropdown) → table snapshotée Nakala (~8043 langues) → code brut si
    inconnu. Strict sur-ensemble du comportement antérieur : résout plus
    de codes, n'en casse aucun.

    ⚠️ **Impédance de schéma** : le snapshot Nakala est en ISO 639-1
    pour les langues majeures (`fr`, `en`, `es`…) + ISO 639-3 pour la
    longue traîne, alors que ColleC stocke en ISO 639-3 (`fra`, `eng`,
    `spa`). Conséquence : les codes 639-3 de la longue traîne (`cmn`,
    `und`, `mul`…) résolvent ; les majeurs 639-3 hors liste curée ne
    résolvent PAS via le snapshot (retour code brut). Un pont
    639-1↔639-3 est reporté au chantier round-trip Nakala (voir
    `docs/developpeurs/nakala-depot-future.md`).
    """
    if code is None:
        return None
    s = str(code)
    for v, libelle in LANGUES_OPTIONS:
        if v == s:
            return libelle
    return langues_iso639().get(s, s)


def resoudre_vocabulaire(
    field: str, valeur: object
) -> tuple[tuple[tuple[str, str], ...] | None, str | None]:
    """Atomise le couple (options du champ, libellé pour la valeur).

    Évite la duplication composer/route : un seul lookup, deux
    informations renvoyées. Retourne `(None, valeur)` si le champ
    n'a pas de vocabulaire enregistré.

    Cas `langue` : les options restent la liste curée (dropdown
    raisonnable), mais le libellé est résolu sur la table ISO 639-3
    complète — un code hors liste s'affiche correctement au lieu du
    code brut.
    """
    options = OPTIONS_PAR_CHAMP.get(field)
    if field == "langue":
        return options, libelle_langue(valeur)
    return options, libelle_pour_valeur(valeur, options)
