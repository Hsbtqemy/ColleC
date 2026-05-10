# Commandes `montrer`

Sous-groupe `archives-tool montrer ...` : consultation en lecture
seule. Quatre sous-commandes alignées sur le modèle Fonds /
Collection / Item / Fichier.

| Sous-commande   | Avec / sans cote                  | Service utilisé          |
|-----------------|-----------------------------------|---------------------------|
| `montrer fonds`      | liste si pas de `--cote`, détail sinon | `lister_fonds` / `composer_page_fonds` |
| `montrer collection` | liste (filtrable par `--fonds`), détail si `--cote`. Désambiguïse via `--fonds` si cote partagée | `lister_collections` / `composer_page_collection` |
| `montrer item`       | détail uniquement, `--fonds` obligatoire (cote item unique par fonds) | `composer_page_item` |
| `montrer fichier`    | détail uniquement, par id global  | accès ORM direct (`session.get(Fichier, id)`) |

Tous les rendus sont **lecture seule** (aucun `db.commit`). Le
sous-groupe partage l'enum `_FormatRapport` avec `controler` :
`--format text` (défaut, Rich) ou `--format json`.

## `montrer fonds`

```bash
# Liste tous les fonds.
uv run archives-tool montrer fonds

# Détail d'un fonds.
uv run archives-tool montrer fonds --cote HK

# JSON pour outillage / CI.
uv run archives-tool montrer fonds --format json
uv run archives-tool montrer fonds --cote HK --format json
```

Détail (text) : titre, cote, descriptions, responsable archives,
métadonnées de revue (si applicables), période, collections,
items récents, collaborateurs par rôle, traçabilité.

## `montrer collection`

```bash
# Liste toutes les collections (miroirs + libres + transversales).
uv run archives-tool montrer collection

# Liste limitée à un fonds.
uv run archives-tool montrer collection --fonds FA

# Détail d'une collection rattachée.
uv run archives-tool montrer collection --cote FA-OEUVRES --fonds FA

# Détail d'une transversale (pas de --fonds).
uv run archives-tool montrer collection --cote TEMOIG
```

Le détail change selon les 3 variantes :
- **miroir** : étiquette « miroir », fonds parent affiché.
- **libre rattachée** : étiquette « libre rattachée », fonds parent
  affiché.
- **transversale** : étiquette « transversale », section « Fonds
  représentés » (vide si la transversale n'a pas encore d'items).

## `montrer item`

```bash
# Détail d'un item (--fonds obligatoire).
uv run archives-tool montrer item HK-001 --fonds HK

# JSON.
uv run archives-tool montrer item HK-001 --fonds HK --format json
```

Détail : identification (cote, numéro, date/année, type COAR,
langue, état), DOI Nakala, descriptions, **métadonnées custom**
(itéré sur le JSON `Item.metadonnees`), collections d'appartenance,
fichiers, dernières modifications (depuis le journal
`ModificationItem`), traçabilité.

## `montrer fichier`

```bash
# Détail d'un fichier par id global.
uv run archives-tool montrer fichier 42

# JSON.
uv run archives-tool montrer fichier 42 --format json
```

Détail : contexte item + fonds, source originale (racine + chemin
relatif local *ou* URL Nakala IIIF), dérivés (aperçu, vignette,
DZI) avec ✓/✗ selon présence, métadonnées techniques (format,
taille, dimensions, SHA-256, état), opérations récentes (depuis
le journal `OperationFichier`), traçabilité.

## Format JSON

Chaque rendu inclut un champ `type` en tête pour distinguer les
sortes de réponses sans ambiguïté :

| `type`               | Contenu principal                          |
|----------------------|--------------------------------------------|
| `fonds_liste`        | `fonds: [{cote, titre, nb_items, ...}]`    |
| `fonds_detail`       | `fonds: {…, collections, items_recents, collaborateurs_par_role, tracabilite}` |
| `collection_liste`   | `collections: [{cote, titre, type_collection, fonds_cote, phase}]` |
| `collection_detail`  | `collection: {…, est_miroir, est_transversale, fonds_parent, fonds_representes, tracabilite}` |
| `item_detail`        | `item: {…, fonds, collections, fichiers, metadonnees, tracabilite}` |
| `fichier_detail`     | `fichier: {…, item, fonds, source, derives, technique, tracabilite}` |

Format moins strict que `controler --format json` (pas de garantie
de stabilité forte avant V1.0). Les noms de champs reflètent le
modèle ORM directement.

## Codes de sortie

| Code | Sens                                                        |
|------|-------------------------------------------------------------|
| `0`  | Succès.                                                     |
| `1`  | Entité introuvable (`--cote=INEXISTANT`, fichier absent).   |
| `2`  | Saisie invalide (base absente, `--fonds` manquant pour item). |

## Couleurs Rich

Le format text utilise le `THEME` global du projet
(`affichage/console.py`). Couleurs visibles uniquement en TTY ;
Rich gère automatiquement la dégradation pour les pipes et fichiers.

## Composabilité depuis Python

Les fonctions de rendu sont importables individuellement :

```python
from archives_tool.affichage.montrer import (
    rendu_text_item_detail,
    rendu_json_item_detail,
)
from archives_tool.api.services.dashboard import composer_page_item

detail = composer_page_item(session, "HK-001", fonds_id=fonds.id)
print(rendu_text_item_detail(detail))
```

Toutes les fonctions retournent une `str` ; à charge de l'appelant
de l'écrire vers stdout, un fichier ou une autre destination.
