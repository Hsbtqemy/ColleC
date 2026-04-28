# Profils d'import

Un profil d'import est un fichier YAML qui décrit **comment lire un
tableur existant et une arborescence de scans** pour amorcer une
collection en base.

> **Vous écrivez votre premier profil ?** Voir le guide pas-à-pas
> dans [`profils_creation.md`](profils_creation.md). Ce document-ci
> est la référence complète du format, à consulter une fois les
> bases acquises.

## Rôle

Les profils sont un **point d'entrée**, pas une configuration
permanente :

- Ils servent à rapatrier du travail déjà fait ailleurs (tableurs
  historiques, exports Nakala, fichiers de catalogueur·ice·s).
- Une fois l'import terminé, la base locale devient la source de
  vérité. Modifier le profil n'affecte pas les items déjà en base.
- Les profils sont versionnés dans Git sous `profiles/` (référence)
  et fournis à l'outil via la CLI ou l'interface au moment de
  l'import.

## Principes de validation

- **Stricte** : `extra="forbid"` sur tous les modèles Pydantic. Toute
  clé inconnue ou mal orthographiée lève une erreur explicite avec
  localisation dans le YAML.
- **Versionnée** : tout profil doit commencer par
  `version_profil: 1`. Sans ce champ ou avec une autre valeur, rejet.
- **Erreurs utiles** : Pydantic 2 remonte le chemin YAML + la valeur
  attendue + la valeur reçue. `ProfilInvalide` les reformate en une
  liste lisible.

## Structure générale

```yaml
version_profil: 1

collection:      # métadonnées de la collection cible
  cote: "..."
  titre: "..."
  # ... autres champs de CollectionProfil

tableur:         # description du fichier source
  chemin: "..."
  # ... options de lecture

granularite_source: "item"   # ou "fichier"

mapping:         # dict champ cible → colonne(s) source
  cote: "..."
  # ...

fichiers:        # optionnel : résolution des scans
  racine: "..."
  motif_chemin: "..."

valeurs_par_defaut:          # copiées sur chaque item
  langue: "fra"

decomposition_cote:          # optionnel : regex nommée
  regex: "..."
  stockage: "hierarchie"

decomposition_type:          # optionnel : colonne à séparateur
  colonne: "Type"
  separateur: " | "
  niveaux: ["categorie", "sous_categorie"]
  stockage: "typologie"
```

## Sections — référence

### `collection`

Métadonnées de la collection cible, écrites telles quelles sur
`Collection` en base (principe d'autonomie).

Champs : `cote` (obligatoire), `titre` (obligatoire), `parent_cote`,
`titre_secondaire`, `editeur`, `lieu_edition`, `periodicite`,
`date_debut`, `date_fin`, `issn`, `doi_nakala`, `description`,
`description_interne`, `auteur_principal`.

### `tableur`

Description du fichier source.

| Clé | Défaut | Rôle |
|---|---|---|
| `chemin` | obligatoire | Relatif au profil, ou absolu. |
| `feuille` | première feuille | Nom de feuille Excel. |
| `ligne_entete` | `1` | Numéro 1-indexé de la ligne d'en-têtes. |
| `lignes_ignorer_apres_entete` | `0` | Sauter des lignes de notes. |
| `valeurs_nulles` | `["none", "n/a", "s.d.", "NaN", ""]` | Converties en `NULL`. |
| `separateur_csv` | `";"` | Si `.csv`. |
| `encodage` | `"utf-8"` | |

### `granularite_source`

- `"item"` (défaut) : une ligne = un item.
- `"fichier"` : une ligne = un fichier. L'importer regroupera les
  lignes par `cote` pour constituer les items. Le mapping **doit**
  alors inclure une clé `cote` (vérifié à la validation).

### `mapping`

Dictionnaire `champ cible → source`. La clé désigne :

- Une colonne dédiée d'`Item` : `cote`, `titre`, `date`, `numero`,
  `annee`, `type_coar`, `langue`, `description`, `doi_nakala`,
  `doi_collection_nakala`, `etat_catalogage`.
- Un champ étendu : `metadonnees.<nom>` (ex. `metadonnees.auteurs`,
  `metadonnees.sujets`) — écrit dans la colonne JSON `Item.metadonnees`.

La valeur prend une des trois formes ci-dessous.

### Les trois formes de mapping

**Forme 1 — chaîne simple**

```yaml
cote: "Cote"
titre: "Titre"
```

Nom de la colonne source, pas de transformation. Équivalent interne à
`MappingSimple(source="Cote")`.

**Forme 2 — colonne unique avec séparateur ou transformation**

```yaml
metadonnees.collaborateurs:
  source: "Aristes et collaborateurs"
  separateur: " / "
```

Utile quand une colonne contient une liste encodée avec séparateur,
ou qu'on veut normaliser (slug, majuscules...). Équivalent interne à
`MappingTransforme`.

Transformations acceptées sur `transformation` (forme 2 et forme 3) :

| Valeur | Sémantique |
|---|---|
| `slug` | `lower` + non-alphanumériques remplacés par tirets + collapse. |
| `upper` | `str.upper()`. |
| `lower` | `str.lower()`. |
| `strip` | Suppression des espaces en bordure. |
| `strip_accents` | NFD + filtrage des diacritiques combinants + NFC. |

Toute autre valeur lève une `ProfilInvalide` à la validation, avec
la liste des valeurs acceptées dans le message.

**Forme 3 — agrégation multi-colonnes**

```yaml
metadonnees.sujets:
  sources: ["sujet 1_fr", "sujet 2_fr", "sujet 3_fr"]
  separateur_sortie: " | "
```

Plusieurs colonnes concaténées avec un séparateur. Équivalent interne
à `MappingAgrege`. Les valeurs nulles (selon `valeurs_nulles`) sont
ignorées avant concaténation.

### `fichiers`

Résolution des scans dans une arborescence.

| Clé | Défaut | Rôle |
|---|---|---|
| `racine` | obligatoire | Nom d'une racine logique (configurée en local). |
| `motif_chemin` | obligatoire | Template avec `{champ}` OU regex avec groupes nommés. |
| `type_motif` | `"template"` | `"regex"` pour une regex — validée à la validation. |
| `recursif` | `true` | Descendre dans les sous-dossiers. |
| `extensions` | `[".tif", ".tiff", ".jpg", ".jpeg", ".png", ".pdf"]` | Extensions acceptées. |
| `template_nommage_canonique` | `None` | Pour renommage ultérieur (pas utilisé à l'import). |

### `valeurs_par_defaut`

Dictionnaire de valeurs copiées sur chaque item créé. Convention
posée : ces valeurs sont **écrites** sur chaque item, pas résolues
dynamiquement (cohérent avec le principe d'autonomie).

### `decomposition_cote`

Décomposition d'une cote composée en sous-parties par regex nommée.
Résultat stocké dans `Item.metadonnees[<stockage>]` (défaut
`hierarchie`).

### `decomposition_type`

Décomposition d'une colonne « Type » multi-niveaux à séparateur.
Résultat stocké dans `Item.metadonnees[<stockage>]` (défaut
`typologie`).

## Exemples

Quatre fixtures représentatives sous `tests/fixtures/profils/` :

- `cas_item_simple/` — granularité item, mapping simple, arborescence
  plate (inspiré de Hara-Kiri).
- `cas_fichier_groupe/` — granularité fichier, DOI Nakala par item
  et DOI collection partagé (inspiré d'un export Nakala type Por Favor).
- `cas_hierarchie_cote/` — `decomposition_cote` + `decomposition_type`,
  arborescence à deux niveaux en mode regex (inspiré d'Ainsa).
- `cas_uri_dc/` — colonnes nommées par URI Dublin Core, deux
  agrégations multi-colonnes avec séparateurs distincts.

Ces fixtures servent de contrats vivants : toute évolution du schéma
doit les garder valides ou, si rupture, les mettre à jour en même
temps.

## Erreurs fréquentes

### « Extra inputs are not permitted »

Une clé n'est pas reconnue (typo, champ renommé, ou clé déplacée).
Vérifier l'orthographe et consulter la référence ci-dessus. La
validation est volontairement stricte pour éviter les dérives
silencieuses (profil accepté mais champ ignoré).

### « decomposition_cote.regex invalide »

La regex n'a pas compilé. Erreur typique : parenthèse non fermée,
groupe nommé mal formé. Tester la regex dans un REPL
(`import re; re.compile(...)`) avant de sauver le profil.

### Chemin du tableur non résolu

Les chemins relatifs sont résolus **depuis le dossier contenant le
profil YAML**, pas depuis le cwd. Si un test ou un script se plaint
d'un tableur introuvable, vérifier que le YAML est bien à la racine
du chantier et que le chemin relatif démarre correctement.

### Version non supportée

`version_profil` absent ou différent de `1` : rejet. Le profil doit
être écrit pour la version courante du schéma. La V2 (future)
introduira un chemin de migration ou un parser rétro-compatible.
