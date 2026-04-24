# Exports

L'outil sort ses données en trois formats canoniques, plus un export
de travail libre.

## Les quatre formats

| Format | Cas d'usage | Granularité supportée | Configurabilité |
|---|---|---|---|
| `xlsx` | Inventaire, consultation, vérification. | item, fichier | Colonnes personnalisables. |
| `csv` | Idem, interop tableur. | item, fichier | Colonnes personnalisables. |
| `dc-xml` | Archivage bibliothéconomique, OAI-PMH. | item | Mode agrégé ou un fichier par item. |
| `nakala-csv` | Dépôt Nakala. | item uniquement | Licence et statut paramétrables. |

## Pipeline

```
┌───────────────┐   ┌──────────────┐   ┌────────────────┐
│  selection.py │ → │  mapping_dc  │ → │  {format}.py   │
│  (streaming)  │   │  extraire_    │   │  + rapport     │
│               │   │  valeur, DC   │   │  pré-export    │
└───────────────┘   └──────────────┘   └────────────────┘
```

Modules sous `src/archives_tool/exporters/` :

- [`selection.py`](../src/archives_tool/exporters/selection.py) —
  `CritereSelection` (collection, récursif, états, granularité),
  `selectionner_items()` / `selectionner_fichiers()` en streaming
  (`yield_per=200` côté SQLAlchemy).
- [`mapping_dc.py`](../src/archives_tool/exporters/mapping_dc.py) —
  correspondance champs internes → URI Dublin Core Terms. Source de
  vérité évolutive.
- [`rapport.py`](../src/archives_tool/exporters/rapport.py) —
  `RapportExport` + `verifier_pre_export()` (items incomplets,
  type_coar non URI, langue non ISO 639-3).
- [`excel.py`](../src/archives_tool/exporters/excel.py) — xlsx et csv.
- [`dublin_core.py`](../src/archives_tool/exporters/dublin_core.py) —
  XML, deux modes.
- [`nakala.py`](../src/archives_tool/exporters/nakala.py) — CSV Nakala
  avec ses colonnes propres.

## Granularité item vs fichier

- **Item** (défaut) : une ligne par item, métadonnées de catalogage.
- **Fichier** : une ligne par Fichier rattaché, utile pour le
  rapprochement avec un partage ou un dépôt multi-pages. Les colonnes
  préfixées `item.xxx` viennent de l'Item, `fichier.xxx` du Fichier.

`nakala-csv` est toujours en granularité item (une « donnée » Nakala
= un item, multi-fichiers gérés séparément à l'upload).

## Champs obligatoires par format

| Format | Obligatoires |
|---|---|
| `xlsx` / `csv` | aucun |
| `dc-xml` | `cote`, `titre` |
| `nakala-csv` | `titre`, `date`, `type_coar`, créateur (via `metadonnees.createurs` ou `metadonnees.auteurs`) |

## Rapport de pré-export

Produit par tous les exporters (même quand le fichier est écrit).
Champs :

| Champ | Sens |
|---|---|
| `format` | xlsx / csv / dc_xml / nakala_csv |
| `nb_items_selectionnes` | |
| `nb_fichiers_selectionnes` | (si granularité fichier) |
| `items_incomplets` | Liste de `(cote, [champs_manquants])` |
| `valeurs_non_mappees` | `(champ, valeur)` — type_coar hors URI, langue hors ISO 639-3 |
| `avertissements` | Ex. slugification d'une cote |
| `chemin_sortie` | |
| `duree_secondes` | |

Mode `--dry-run` : produit le rapport sans écrire le fichier. Utile
pour vérifier la couverture avant un export long.

Mode `--strict` : exit 1 si `items_incomplets` non vide. À utiliser
dans un script qui demande une qualité garantie (ex. export Nakala
pré-publication).

## Exemples CLI

```bash
# Inventaire Excel d'une collection.
uv run archives-tool exporter xlsx \
    --collection RDM --sortie inventaire.xlsx

# Inventaire en CSV avec colonnes choisies.
uv run archives-tool exporter csv \
    --collection RDM --sortie min.csv \
    --colonnes "cote,titre,metadonnees.auteurs"

# Granularité fichier (rapprochement disque).
uv run archives-tool exporter xlsx \
    --collection RDM --granularite fichier --sortie fichiers.xlsx

# Dublin Core agrégé, collection et ses sous-collections.
uv run archives-tool exporter dc-xml \
    --collection FA --recursif --sortie fa.xml

# Un fichier XML par item.
uv run archives-tool exporter dc-xml \
    --collection FA --mode un-fichier-par-item --sortie dc_par_item/

# Nakala CSV, items validés seulement, dry-run pour vérifier.
uv run archives-tool exporter nakala-csv \
    --collection RDM --etat valide --sortie depot.csv --dry-run --verbose

# Export Nakala strict (échoue si items incomplets).
uv run archives-tool exporter nakala-csv \
    --collection RDM --etat valide --sortie depot.csv \
    --licence "CC-BY-4.0" --strict
```

## Limitations V1

- **Licence Nakala par défaut** : `CC-BY-NC-ND-4.0`. Override via
  `--licence` OU via un champ `metadonnees.licence` /
  `metadonnees.rights` sur l'item (priorité item > option CLI >
  défaut).
- **Type COAR non validé** contre la liste officielle. Le rapport
  signale les valeurs hors `http://purl.org/coar/resource_type/`,
  mais n'empêche pas l'export.
- **Export Nakala** : les colonnes `IsDescribedBy` / `IsIdenticalTo` /
  `IsDerivedFrom` / `IsPublishedIn` sont présentes mais laissées
  vides. À peupler par un mapping explicite quand le besoin sera
  stabilisé.
- **Mapping DC évolutif** : `MAPPING_DC` dans
  [`mapping_dc.py`](../src/archives_tool/exporters/mapping_dc.py) est
  la source de vérité. Pour ajouter un champ récurrent (ex.
  `metadonnees.orcid` → `dc:creator`), éditer le dict et ajouter un
  test.
- **Pas de JSON-LD** : prévu pour une session ultérieure (contextes
  COAR et Nakala).
- **Pas de dépôt automatique vers Nakala** via API : hors scope V1.

## Reproductibilité

Les exports sont déterministes : deux appels successifs sur les mêmes
données produisent des fichiers identiques. Tri alphabétique appliqué
sur les items (par cote), sur les fichiers d'un item (par ordre), et
sur les listes de valeurs (auteurs, sujets) avant sérialisation.
