# Exporter

L'outil produit trois formats d'export, tous **par collection** (au
sens Nakala : miroir, libre rattachée, ou transversale — voir
[Concepts](../concepts.md#collection)). On n'exporte pas un fonds
directement : si l'on veut tous ses items, on exporte sa miroir.

## Granularité d'export

L'unité d'export est **la collection**. Selon son type :

- **Collection miroir d'un fonds** : exporte tous les items du fonds
  qui figurent dans la miroir (par défaut tous, sauf retraits explicites).
- **Collection libre rattachée** : exporte les items sélectionnés.
  Tous viennent du même fonds parent (cohérence attendue, non garantie
  techniquement).
- **Collection libre transversale** : exporte les items, qui peuvent
  provenir de plusieurs fonds. Le contexte de chaque item garde le
  fonds d'origine.

L'exporter charge le contexte d'export complet via
[`composer_export`]({{ repo_main }}/src/archives_tool/exporters/_commun.py)
(une seule requête principale avec `selectinload(items.fichiers)` +
JOIN fonds). Pas de N+1.

## Les trois formats

| Format        | Cas d'usage                            | Sortie                  |
| ------------- | -------------------------------------- | ----------------------- |
| `dublin-core` | Archivage bibliothéconomique, OAI-PMH. | XML, un fichier agrégé. |
| `nakala`      | Dépôt bulk Nakala.                     | CSV `;`, UTF-8 BOM.     |
| `xlsx`        | Catalogage manuel, vérification.       | xlsx Excel/LibreOffice. |

Tous incluent les **métadonnées de la collection en tête** : cote,
titre, type, fonds parent (rattachée) ou fonds représentés
(transversale), DOI Nakala si renseigné.

## Modules

```
src/archives_tool/exporters/
├── _commun.py      # composer_export(db, collection)
├── mapping_dc.py   # champs internes → URI DC Terms (table partagée)
├── rapport.py      # RapportExport + verifier_pre_export()
├── dublin_core.py  # XML
├── excel.py        # xlsx
└── nakala.py       # CSV bulk Nakala
```

`_commun.py` centralise le chargement (items + fichiers + fonds
d'origine, eager loading). `mapping_dc.py` reste la source de vérité
pour le mapping vers Dublin Core (réutilisé par DC et Nakala).
`rapport.py` détecte les items incomplets (champs obligatoires
manquants, type_coar non URI, langue non ISO 639-3).

## Champs obligatoires par format

| Format        | Champs obligatoires sur les items                                              |
| ------------- | ------------------------------------------------------------------------------ |
| `dublin-core` | `cote`, `titre`                                                                |
| `nakala`      | `titre`, `date`, `type_coar`, créateur (`metadonnees.createurs` ou `.auteurs`) |
| `xlsx`        | aucun                                                                          |

Les items qui manquent un champ obligatoire apparaissent dans
`RapportExport.items_incomplets`. L'export n'est pas bloqué — c'est à
l'utilisateur d'arbitrer.

## Rapport d'export

Produit par tous les exporters et affiché par le CLI :

| Champ                      | Sens                                                                            |
| -------------------------- | ------------------------------------------------------------------------------- |
| `format`                   | `dc_xml` / `nakala_csv` / `xlsx`                                                |
| `nb_items_selectionnes`    |                                                                                 |
| `nb_fichiers_selectionnes` | total des fichiers liés aux items                                               |
| `items_incomplets`         | `[(cote, [champs_manquants]), …]`                                               |
| `valeurs_non_mappees`      | `[(champ, valeur), …]` — type_coar hors URI COAR, langue hors ISO 639-3         |
| `avertissements`           | Liste libre                                                                     |
| `chemin_sortie`            | Chemin du fichier produit                                                       |
| `duree_secondes`           |                                                                                 |

`--verbose` détaille les `items_incomplets` ligne par ligne.

## Détail des formats produits

Pour la **structure exacte** de chaque format (mapping complet
Dublin Core, liste des 27 colonnes Nakala, structure xlsx
détaillée, particularités d'encodage), voir
[Formats d'export](../../reference/exports.md). La présente page
documente uniquement l'usage de la CLI.

## CLI

```bash
# Dublin Core d'une miroir.
archives-tool exporter dublin-core HK --fonds HK \
    --sortie hk_dc.xml

# Nakala d'une libre rattachée, avec licence personnalisée.
archives-tool exporter nakala HK-FAVORIS --fonds HK \
    --licence "CC-BY-4.0" --statut publié

# xlsx d'une transversale (pas de --fonds car cote unique).
archives-tool exporter xlsx TEMOIG

# Sortie par défaut dans le cwd : <cote>_dc.xml / <cote>_nakala.csv /
# <cote>.xlsx — pas besoin de --sortie pour un export ad-hoc.
archives-tool exporter dublin-core HK --fonds HK
```

`--fonds COTE` désambiguïse quand une cote de collection est partagée
entre plusieurs fonds (cohérent avec les routes web).

## Voir aussi

- [Formats d'export](../../reference/exports.md) — détail des
  structures, mappings, particularités, reproductibilité et
  limitations.
- [Concepts → Collection](../concepts.md#collection) — pourquoi
  l'unité d'export est la collection.
