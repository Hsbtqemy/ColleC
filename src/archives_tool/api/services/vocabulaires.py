"""Vocabulaires de référence pour les champs item à valeurs contrôlées.

Liste frugale (pas de table Vocabulaire au modèle pour l'instant — V2+).
Les valeurs servent à peupler les `<select>` de l'édition inline pour
les champs `langue` et `type_coar`. Une `(valeur, libelle)` par option :
la valeur est ce qui est stocké en base (ISO 639-3 / URI COAR), le
libellé est ce que voit l'utilisateur dans le dropdown.

Étendre cette liste à mesure que les chantiers en font émerger le besoin.
"""

from __future__ import annotations

from archives_tool.reference.loaders import langues_iso639, types_coar_nakala

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


#: Préfixe COAR commun (source de vérité unique, réutilisé partout).
_C = "http://purl.org/coar/resource_type"

# Vocabulaire COAR Resource Types **interne** à ColleC (catalogage).
# ColleC est un outil de collections numérisées **tous types** (textes,
# périodiques, manuscrits, correspondance, images, son, vidéo, cartes,
# œuvres…). Le vocabulaire couvre donc l'intégralité du set de types
# accepté par Nakala (snapshot, 29 entrées), PLUS 3 genres COAR valides
# que Nakala n'accepte pas au dépôt mais utiles au catalogage
# (Chapitre de livre, Document de travail, Photographie). Ces 3 extras
# sont projetés vers une cible Nakala à l'export via
# `COAR_INTERNE_VERS_NAKALA` (design « deux vocabulaires », cf.
# `nakala-depot-future.md`). URIs vérifiées contre le vocabulaire COAR
# autoritatif. Libellés FR adaptés au contexte archives.
TYPES_COAR_OPTIONS: tuple[tuple[str, str], ...] = (
    # — Texte & édition —
    (f"{_C}/c_18cf", "Texte"),
    (f"{_C}/c_2fe3", "Périodique"),
    (f"{_C}/c_6501", "Article"),
    (f"{_C}/c_2f33", "Ouvrage"),
    (f"{_C}/c_3248", "Chapitre de livre"),          # extra (hors set Nakala)
    (f"{_C}/c_0040", "Manuscrit"),
    (f"{_C}/c_0857", "Lettre / Correspondance"),
    (f"{_C}/YC9F-HGCF", "Fonds d'archives"),
    (f"{_C}/c_93fc", "Rapport"),
    (f"{_C}/c_46ec", "Thèse"),
    (f"{_C}/c_816b", "Prépublication"),
    (f"{_C}/c_8042", "Document de travail"),         # extra (hors set Nakala)
    (f"{_C}/c_efa0", "Synthèse"),
    (f"{_C}/c_86bc", "Bibliographie"),
    (f"{_C}/c_ba08", "Note de lecture"),
    # — Image & multimédia —
    (f"{_C}/c_c513", "Image"),
    (f"{_C}/c_ecc8", "Photographie"),                # extra (hors set Nakala)
    (f"{_C}/c_12cd", "Carte"),
    (f"{_C}/c_18cw", "Partition"),
    (f"{_C}/c_12ce", "Vidéo"),
    (f"{_C}/c_18cc", "Enregistrement sonore"),
    (f"{_C}/F8RT-TJK0", "Œuvre artistique"),
    # — Données & ressources —
    (f"{_C}/c_ddb1", "Jeu de données"),
    (f"{_C}/NHD0-W6SY", "Donnée d'enquête"),
    (f"{_C}/c_beb9", "Article de données"),
    (f"{_C}/c_5ce6", "Logiciel"),
    (f"{_C}/c_7ad9", "Site web"),
    (f"{_C}/c_e9a0", "Ressource interactive"),
    (f"{_C}/c_e059", "Objet d'apprentissage"),
    (f"{_C}/c_6670", "Poster de conférence"),
    (f"{_C}/c_c94f", "Objet de conférence"),
    (f"{_C}/c_1843", "Autre"),
)


#: Projection **type interne → type accepté par Nakala** au dépôt.
#: N'inclut QUE les 3 genres COAR valides que Nakala n'accepte pas (les
#: 29 autres sont déjà dans le set Nakala → identité, voir
#: `type_coar_pour_nakala`). Cibles conservatrices, ajustables selon la
#: modération Nakala.
COAR_INTERNE_VERS_NAKALA: dict[str, str] = {
    f"{_C}/c_3248": f"{_C}/c_18cf",   # Chapitre de livre → texte
    f"{_C}/c_8042": f"{_C}/c_816b",   # Document de travail → prépublication
    f"{_C}/c_ecc8": f"{_C}/c_c513",   # Photographie (image fixe) → image
}


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
#: Cibles alignées sur :data:`TYPES_COAR_OPTIONS` (URIs COAR valides,
#: corrigées V0.9.10). Les numéros/issues sont repliés sur Périodique
#: (un numéro est un Item dans un Fonds périodique, pas un type distinct).
#: Préfixe `_C` défini plus haut (avec COAR_INTERNE_VERS_NAKALA).
_ALIAS_VERS_COAR: dict[str, str] = {
    # Périodique (c_2fe3, « journal » Nakala). Numéro / issue repliés
    # sur périodique (un numéro est un Item dans un Fonds, pas un type).
    "journal": f"{_C}/c_2fe3",
    "periodique": f"{_C}/c_2fe3",
    "revue": f"{_C}/c_2fe3",
    "magazine": f"{_C}/c_2fe3",
    "periodical": f"{_C}/c_2fe3",
    "newspaper": f"{_C}/c_2fe3",
    "quotidien": f"{_C}/c_2fe3",
    "numero": f"{_C}/c_2fe3",
    "numero de periodique": f"{_C}/c_2fe3",
    "issue": f"{_C}/c_2fe3",
    "journal issue": f"{_C}/c_2fe3",
    # Article (c_6501)
    "article": f"{_C}/c_6501",
    "article de revue": f"{_C}/c_6501",
    "journal article": f"{_C}/c_6501",
    # Ouvrage (c_2f33) / chapitre = book part (c_3248, extra)
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
    # Manuscrit (c_0040) / correspondance (c_0857)
    "manuscrit": f"{_C}/c_0040",
    "manuscript": f"{_C}/c_0040",
    "lettre": f"{_C}/c_0857",
    "correspondance": f"{_C}/c_0857",
    "letter": f"{_C}/c_0857",
    "correspondence": f"{_C}/c_0857",
    # Archives (fonds YC9F-HGCF)
    "archives": f"{_C}/YC9F-HGCF",
    "document d'archives": f"{_C}/YC9F-HGCF",
    "fonds d'archives": f"{_C}/YC9F-HGCF",
    "archival material": f"{_C}/YC9F-HGCF",
    # Littérature grise : rapport (c_93fc), thèse (c_46ec),
    # prépublication (c_816b), doc de travail (c_8042, extra),
    # synthèse (c_efa0), bibliographie (c_86bc)
    "rapport": f"{_C}/c_93fc",
    "report": f"{_C}/c_93fc",
    "these": f"{_C}/c_46ec",
    "thesis": f"{_C}/c_46ec",
    "prepublication": f"{_C}/c_816b",
    "preprint": f"{_C}/c_816b",
    "document de travail": f"{_C}/c_8042",
    "working paper": f"{_C}/c_8042",
    "synthese": f"{_C}/c_efa0",
    "review": f"{_C}/c_efa0",
    "bibliographie": f"{_C}/c_86bc",
    "bibliography": f"{_C}/c_86bc",
    # Image (c_c513) / photographie = image fixe (c_ecc8, extra) /
    # carte (c_12cd)
    "image": f"{_C}/c_c513",
    "photographie": f"{_C}/c_ecc8",
    "photo": f"{_C}/c_ecc8",
    "photograph": f"{_C}/c_ecc8",
    "carte": f"{_C}/c_12cd",
    "map": f"{_C}/c_12cd",
    # Multimédia : vidéo (c_12ce), son (c_18cc), partition (c_18cw)
    "video": f"{_C}/c_12ce",
    "son": f"{_C}/c_18cc",
    "audio": f"{_C}/c_18cc",
    "enregistrement sonore": f"{_C}/c_18cc",
    "sound recording": f"{_C}/c_18cc",
    "partition": f"{_C}/c_18cw",
    "partition musicale": f"{_C}/c_18cw",
    "musical score": f"{_C}/c_18cw",
    # Œuvre / données / ressources
    "oeuvre": f"{_C}/F8RT-TJK0",
    "oeuvre artistique": f"{_C}/F8RT-TJK0",
    "artwork": f"{_C}/F8RT-TJK0",
    "jeu de donnees": f"{_C}/c_ddb1",
    "dataset": f"{_C}/c_ddb1",
    "logiciel": f"{_C}/c_5ce6",
    "software": f"{_C}/c_5ce6",
    "site web": f"{_C}/c_7ad9",
    "website": f"{_C}/c_7ad9",
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


def type_coar_pour_nakala(uri: object) -> str | None:
    """Projette un type COAR **interne** vers un type **accepté par
    Nakala** au dépôt (design « deux vocabulaires »).

    - non-str / vide → None ;
    - URI dans :data:`COAR_INTERNE_VERS_NAKALA` → sa cible Nakala ;
    - URI déjà dans le set Nakala → inchangée ;
    - sinon → None (l'appelant décide du repli : omettre le type, ou
      `c_1843` « autre »). Un None signale un type interne sans
      projection — à enrichir dans la table si le cas se présente.
    """
    if not isinstance(uri, str) or not uri.strip():
        return None
    u = uri.strip()
    if u in COAR_INTERNE_VERS_NAKALA:
        return COAR_INTERNE_VERS_NAKALA[u]
    if u in types_coar_nakala():
        return u
    return None


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
