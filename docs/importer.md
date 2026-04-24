# Importer

L'importer prend un [profil YAML validé](profils.md), lit le tableur
associé, résout les fichiers sur disque, et crée ou met à jour les
items et fichiers en base.

## Pipeline

```
┌──────────┐   ┌──────────────┐   ┌────────────────┐   ┌─────────────┐
│ profil + │ → │  lecteur_    │ → │ transformateur │ → │ resolveur_  │
│ tableur  │   │  tableur     │   │                │   │ fichiers    │
└──────────┘   └──────────────┘   └────────────────┘   └─────────────┘
                                                              │
                                                              ▼
                                                       ┌──────────────┐
                                                       │  ecrivain    │
                                                       │  (transaction│
                                                       │   tout-ou-   │
                                                       │   rien)      │
                                                       └──────────────┘
```

Quatre modules découpés sous `src/archives_tool/importers/` :

- [`lecteur_tableur.py`](../src/archives_tool/importers/lecteur_tableur.py)
  — lit un CSV/Excel avec pandas en `dtype=str`, normalise strip + NFC,
  convertit les sentinelles de `valeurs_nulles` et les `NaN` en `None`.
- [`transformateur.py`](../src/archives_tool/importers/transformateur.py)
  — fonction pure ligne → `ItemPrepare`. Applique les trois formes de
  mapping, les `valeurs_par_defaut`, la décomposition de cote par
  regex et la décomposition de type par séparateur.
- [`resolveur_fichiers.py`](../src/archives_tool/importers/resolveur_fichiers.py)
  — cherche les fichiers sur disque selon `profil.fichiers`. Mode
  template (`{champ}` substitué, résultat utilisé en glob) ou regex
  (liste + filtre par cohérence des groupes nommés avec l'item).
- [`ecrivain.py`](../src/archives_tool/importers/ecrivain.py) — orchestre
  tout, écrit en base sous transaction, journalise dans
  `OperationImport`.

## Dry-run par défaut

La commande CLI tourne en dry-run par défaut : le profil est lu, les
lignes transformées, les fichiers résolus, les diffs calculés par
rapport à la base actuelle — puis `session.rollback()` en fin.
Rien n'est écrit en base, aucun hash SHA-256 n'est calculé (rapide).

```bash
archives-tool importer profils/ma_collection.yaml
```

Le rapport affiché montre *ce qui serait fait* en mode réel.

Pour exécuter pour de vrai :

```bash
archives-tool importer profils/ma_collection.yaml --no-dry-run --utilisateur "Marie"
```

En mode réel :
- les hash SHA-256 sont calculés pour chaque fichier ajouté ;
- un `batch_id` UUID est généré ;
- une entrée `OperationImport` est créée (table journal dédiée) avec
  le rapport complet sérialisé en JSON ;
- l'ensemble est dans une seule transaction : **rollback complet**
  si une seule ligne remonte une erreur. L'import est tout-ou-rien
  en mode réel.

## Valeurs par défaut

`valeurs_par_defaut` dans le profil :

```yaml
valeurs_par_defaut:
  langue: "fra"
  etat_catalogage: "brouillon"
```

Sémantique :

- **Copiées** sur chaque item, une par une. Pas de résolution dynamique
  ni de référence partagée (principe d'autonomie des items).
- **Ne remplacent pas** une valeur déjà présente dans le tableur :
  si le tableur a une colonne `langue` avec `"spa"` sur une ligne,
  la valeur du tableur l'emporte.
- **Complètent les champs absents** du mapping : un item sans colonne
  `etat_catalogage` dans le tableur reçoit `"brouillon"`.

## Ré-import

Le ré-import se fait par `(collection_id, cote)` :

- Item existant avec mêmes valeurs → **inchangé** (compteur
  `items_inchanges`).
- Item existant avec une différence sur une colonne ou dans
  `metadonnees` → **mis à jour** (`items_mis_a_jour`). `modifie_par`
  est écrit avec `cree_par` courant.
- Item absent → **créé** (`items_crees`).

La comparaison des colonnes numériques est tolérante : pandas lit en
`str`, SQLite stocke en `int` pour les colonnes `Integer`, donc
`"1960"` et `1960` sont considérés équivalents. Sans cette tolérance,
chaque ré-import marquerait artificiellement à jour tous les items
avec un champ comme `annee`.

## Granularité fichier

Si `granularite_source: "fichier"`, chaque ligne du tableur décrit
**un fichier**, pas un item. L'importer regroupe les lignes par
`cote` avant l'écriture :

- Métadonnées item fusionnées : première valeur non-`None` retenue,
  divergences entre lignes → `warnings` dans le rapport.
- Fichiers concaténés dans l'ordre d'apparition.

La fixture `cas_fichier_groupe` illustre ce cas : 3 lignes pour 2
items (PF-001 avec 2 fichiers, PF-002 avec 1 fichier).

## Rapport

L'objet `RapportImport` retourné par `importer()` contient :

| Champ | Type | Sens |
|---|---|---|
| `dry_run` | bool | Mode d'exécution. |
| `batch_id` | str \| None | UUID de l'opération (None en dry-run). |
| `collection_creee` | bool | True si c'est le premier import. |
| `collection_id` | int \| None | id de la collection cible. |
| `items_crees` | int | Nouveaux items. |
| `items_mis_a_jour` | int | Items modifiés. |
| `items_inchanges` | int | Items déjà identiques. |
| `fichiers_ajoutes` | int | Nouveaux Fichier en base. |
| `fichiers_deja_connus` | int | Fichiers déjà référencés. |
| `fichiers_orphelins` | list[str] | Sur disque, pas référencés. |
| `lignes_ignorees` | list[tuple[int, str]] | (n° ligne, raison). |
| `warnings` | list[str] | Divergences non-bloquantes. |
| `erreurs` | list[str] | Erreurs bloquantes en mode réel. |
| `duree_secondes` | float | Temps total. |

Codes de sortie CLI :

- `0` : succès (même en dry-run avec warnings).
- `1` : l'import a remonté des `erreurs`.
- `2` : config ou profil invalide (erreur amont).

## Exemples

Les quatre fixtures sous `tests/fixtures/profils/` sont testées bout
en bout par `tests/test_importer.py` :

- `cas_item_simple/` — le cas le plus courant.
- `cas_fichier_groupe/` — granularité fichier + DOI Nakala.
- `cas_hierarchie_cote/` — decomposition_cote + decomposition_type.
- `cas_uri_dc/` — colonnes URI Dublin Core + agrégations.

## Erreurs fréquentes

### « Racine logique inconnue »

La clé déclarée dans `profil.fichiers.racine` n'est pas dans
`config.racines` de la config locale. Vérifier que le `config_local.yaml`
du poste déclare bien la racine.

### « Motif template référence un champ absent de l'item »

Le motif `motif_chemin` contient un placeholder `{champ}` qui n'a
pas de valeur correspondante sur l'item. Champs disponibles :

- `{cote}` (toujours) ;
- toutes les clés de `champs_colonne` (colonnes dédiées) ;
- toutes les clés de `metadonnees` (préfixe `metadonnees.` retiré) ;
- toutes les clés de `hierarchie` (si decomposition_cote a matché).

### « Collection parent introuvable »

Le profil déclare un `parent_cote` pour lequel aucune collection
n'existe en base. Importer d'abord le parent.

### Rollback en mode réel

Si *une seule* ligne remonte une erreur, l'import entier est annulé.
Lancer d'abord en dry-run pour identifier toutes les erreurs d'un
coup (qui elles sont toutes collectées sans interruption), corriger,
puis relancer en `--no-dry-run`.
