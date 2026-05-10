# Exporter

L'outil produit trois formats d'export, tous **par collection** (au
sens Nakala : miroir, libre rattachée, ou transversale). On n'exporte
pas un fonds directement : si l'on veut tous ses items, on exporte sa
miroir.

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
[`composer_export`](https://github.com/Hsbtqemy/ColleC/blob/main/src/archives_tool/exporters/_commun.py)
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

## Format Dublin Core (XML)

Racine `<collection cote="…">` avec :

- une `<notice role="collection">` de tête : cote, titre,
  description(s), DOI Nakala, et un ou plusieurs `dc:source` listant
  le ou les fonds représentés (utile pour les transversales) ;
- une `<notice>` par item, avec ses champs DC mappés via `MAPPING_DC`.

Préfixe XML : `dc:` ↔ `http://purl.org/dc/terms/`. Encodage UTF-8.
Indentation propre. Échappement automatique via
`xml.etree.ElementTree`.

## Format Nakala (CSV)

Colonnes inspirées du format d'import Nakala standard (DC + prédicats
`http://nakala.fr/terms#`). Séparateur `;`, encodage UTF-8 BOM.

Particularités :

- `Linked in collection` se rabat sur le DOI Nakala de la collection
  (`Collection.doi_nakala`) si l'item n'a pas son propre
  `Item.doi_collection_nakala` — utile quand on dépose une collection
  d'un coup.
- `fonds_cote` est ajoutée comme colonne informative — précieuse pour
  les transversales où chaque ligne peut venir d'un fonds différent.
- Licence et statut sont pris dans `metadonnees.licence` /
  `metadonnees.statut_nakala` si renseignés, sinon des défauts CLI
  (`CC-BY-NC-ND-4.0` / `pending`).
- Les colonnes `IsDescribedBy` / `IsIdenticalTo` / `IsDerivedFrom` /
  `IsPublishedIn` sont présentes mais laissées vides pour l'instant.

## Format xlsx

Une feuille avec :

- lignes 1-4 : bandeau métadonnées (titre, cote, type, fonds parent
  ou fonds représentés) ;
- ligne 6 : entêtes (Cote, Titre, Fonds, État, Date, Année, Type,
  Langue, Description, Notes internes, DOI Nakala, Nb fichiers) ;
- ligne 7+ : un item par ligne.

Le titre de feuille est dérivé du titre de la collection, tronqué à
31 caractères (limite Excel) avec retrait des caractères interdits
(`[]:*?/\`).

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

## Reproductibilité

Les exports sont déterministes : deux appels successifs sur les mêmes
données produisent des fichiers identiques. Items triés par
`(fonds.cote, item.cote)`, fichiers d'un item par `ordre`, et listes
de valeurs (auteurs, sujets) triées alphabétiquement avant
sérialisation.

## Limitations V1

- **Pas de JSON-LD** : prévu pour une session ultérieure (contextes
  COAR et Nakala).
- **Type COAR non validé** contre la liste officielle. Le rapport
  signale les valeurs hors `http://purl.org/coar/resource_type/`.
- **Mapping DC évolutif** : `MAPPING_DC` est la source de vérité. Pour
  ajouter un champ récurrent (ex. `metadonnees.orcid` → `dc:creator`),
  éditer le dict et ajouter un test.
- **Pas de dépôt automatique vers Nakala** via API : hors scope V1.
- **Date EDTF** : `Item.date` est exporté littéralement (pas de
  conversion EDTF → ISO 8601). Si l'item a `1969?`, c'est cette
  chaîne qui sort. À évaluer en V2 selon les retours utilisateur.
