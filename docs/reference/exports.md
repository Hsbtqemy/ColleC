# Formats d'export

Documentation technique des trois formats produits par
[`archives-tool exporter`](../guide/cli/exporter.md). Cette page
décrit la **structure des fichiers de sortie** ; pour l'usage de
la CLI, voir le guide.

L'unité d'export est toujours **la collection** (miroir, libre
rattachée ou transversale) — cf. [Concepts](../guide/concepts.md#collection).

## Dublin Core XML

Format pivot pour archivage bibliothéconomique et OAI-PMH.

### Structure

Racine `<collection cote="…">` avec :

- une notice de tête `<notice role="collection">` portant les
  métadonnées de la collection elle-même (cote, titre,
  description(s), DOI Nakala, fonds représentés) ;
- une `<notice>` par item, avec ses champs Dublin Core mappés.

```xml
<?xml version='1.0' encoding='utf-8'?>
<collection cote="HK">
  <notice role="collection">
    <dc:identifier>HK</dc:identifier>
    <dc:title>Hara-Kiri (revue)</dc:title>
    <dc:description>Revue satirique...</dc:description>
    <dc:source>Hara-Kiri (HK)</dc:source>
  </notice>
  <notice>
    <dc:identifier>HK-001</dc:identifier>
    <dc:title>Hara-Kiri n°1</dc:title>
    <dc:date>1960-09</dc:date>
    <dc:type>http://purl.org/coar/resource_type/c_2659</dc:type>
    <dc:language>fra</dc:language>
  </notice>
  <!-- … -->
</collection>
```

Préfixe XML : `dc:` ↔ `http://purl.org/dc/terms/`. Encodage UTF-8.
Indentation propre. Échappement automatique via
`xml.etree.ElementTree`.

### Mapping des champs

Source de vérité : [`mapping_dc.py`]({{ repo_main }}/src/archives_tool/exporters/mapping_dc.py).

**Colonnes dédiées de `Item`** :

| Champ ColleC | Élément DC                          | Notes                              |
| ------------ | ----------------------------------- | ---------------------------------- |
| `cote`       | `dc:identifier`                     | Cote interne, unique par fonds.    |
| `titre`      | `dc:title`                          |                                    |
| `date`       | `dc:date`                           | EDTF préservé tel quel.            |
| `description`| `dc:description`                    |                                    |
| `type_coar`  | `dc:type`                           | URI COAR (pas de label).           |
| `langue`     | `dc:language`                       | Code ISO 639-3 (`fra`, `eng`, …).  |

**Métadonnées étendues** (clés JSON `Item.metadonnees`) :

| Clé interne                  | Élément DC          |
| ---------------------------- | ------------------- |
| `metadonnees.auteurs`        | `dc:creator`        |
| `metadonnees.createurs`      | `dc:creator`        |
| `metadonnees.editeur`        | `dc:publisher`      |
| `metadonnees.publisher`      | `dc:publisher`      |
| `metadonnees.sujets`         | `dc:subject`        |
| `metadonnees.rubrique`       | `dc:subject`        |
| `metadonnees.collaborateurs` | `dc:contributor`    |
| `metadonnees.droits`         | `dc:rights`         |
| `metadonnees.source`         | `dc:source`         |
| `metadonnees.relation`       | `dc:relation`       |
| `metadonnees.format`         | `dc:format`         |

Les listes (par exemple plusieurs auteurs) sont triées
alphabétiquement avant sérialisation pour garantir la
reproductibilité des exports.

### Cas particuliers

- **Collections transversales** : la notice de tête liste tous
  les fonds représentés en `<dc:source>` (un par fonds).
- **Métadonnées custom non mappées** (`metadonnees.hierarchie.*`,
  clés ad-hoc) : non exportées en DC plat. Elles servent à la
  consultation interne, pas à la diffusion.
- **Champs vides** : non sérialisés du tout (pas de `<dc:title/>`
  vide).

## Nakala CSV

Format de dépôt bulk pour [Nakala](https://nakala.fr/).

### Structure

CSV à séparateur `;`, encodage **UTF-8 BOM** (compatible Excel),
une ligne d'entête + une ligne par item.

### Colonnes

Ordre exact (source : [`nakala.py`]({{ repo_main }}/src/archives_tool/exporters/nakala.py)) :

| #  | Colonne                                | Source ColleC                                  |
| -- | -------------------------------------- | ---------------------------------------------- |
| 1  | `Linked in collection`                 | DOI Nakala de l'item (`Item.doi_collection_nakala`), repli sur celui de la collection (`Collection.doi_nakala`). |
| 2  | `Status collection`                    | Vide (constant).                               |
| 3  | `collectionsIds`                       | Vide par défaut.                               |
| 4  | `Linked in item`                       | DOI Nakala de l'item (`Item.doi_nakala`).      |
| 5  | `Status donnee`                        | `metadonnees.statut_nakala` ou défaut CLI (`pending`). |
| 6  | `http://nakala.fr/terms#title`         | `Item.titre`.                                  |
| 7  | `langTitle`                            | `Item.langue` (code ISO).                      |
| 8  | `http://nakala.fr/terms#creator`       | `metadonnees.createurs` / `auteurs`.           |
| 9  | `http://nakala.fr/terms#created`       | `Item.date` (EDTF préservé).                   |
| 10 | `http://nakala.fr/terms#type`          | `Item.type_coar` (URI COAR).                   |
| 11 | `http://nakala.fr/terms#license`       | `metadonnees.licence` ou défaut CLI.           |
| 12 | `Embargoed`                            | Vide par défaut.                               |
| 13 | `http://purl.org/dc/terms/identifier`  | `Item.cote`.                                   |
| 14 | `http://purl.org/dc/terms/title`       | `Item.titre`.                                  |
| 15 | `http://purl.org/dc/terms/creator`     | `metadonnees.createurs` / `auteurs`.           |
| 16 | `http://purl.org/dc/terms/date`        | `Item.date`.                                   |
| 17 | `http://purl.org/dc/terms/description` | `Item.description`.                            |
| 18 | `http://purl.org/dc/terms/subject`     | `metadonnees.sujets`.                          |
| 19 | `http://purl.org/dc/terms/language`    | `Item.langue`.                                 |
| 20 | `http://purl.org/dc/terms/publisher`   | `metadonnees.editeur`.                         |
| 21 | `http://purl.org/dc/terms/type`        | `Item.type_coar`.                              |
| 22 | `http://purl.org/dc/terms/rights`      | `metadonnees.droits`.                          |
| 23 | `fonds_cote`                           | Cote du fonds d'origine (informatif).          |
| 24 | `IsDescribedBy`                        | Vide par défaut.                               |
| 25 | `IsIdenticalTo`                        | Vide par défaut.                               |
| 26 | `IsDerivedFrom`                        | Vide par défaut.                               |
| 27 | `IsPublishedIn`                        | Vide par défaut.                               |

### Cas particuliers

- **Listes** (créateurs multiples, sujets…) : concaténées avec
  ` | ` et triées alphabétiquement.
- **Linked in collection** : pris sur `Item.doi_collection_nakala`
  s'il est renseigné, sinon sur `Collection.doi_nakala` — utile
  quand on dépose une collection d'un coup, l'item-level prenant
  toujours la priorité s'il est explicitement renseigné.
- **Licence et statut** : pris dans `metadonnees.licence` /
  `metadonnees.statut_nakala` si renseignés ; sinon les défauts
  fournis par la CLI (`CC-BY-NC-ND-4.0` / `pending`).
- **Colonne `fonds_cote`** : ne fait pas partie du schéma Nakala
  officiel, ajoutée comme colonne informative — précieuse pour
  les transversales où chaque ligne peut venir d'un fonds
  différent. À retirer manuellement avant upload si nécessaire.

### Upload sur Nakala

Hors périmètre de l'outil. Le CSV produit est compatible avec
l'import bulk de Nakala via leur interface ou leur API.

## xlsx (Excel)

Format pratique pour le catalogage manuel et la relecture.

### Structure

Une seule feuille par fichier :

| Lignes      | Contenu                                                                          |
| ----------- | -------------------------------------------------------------------------------- |
| 1-4         | Bandeau métadonnées de la collection (titre, cote, type, fonds parent ou représentés). |
| 5           | Vide.                                                                            |
| 6           | Entêtes des colonnes item.                                                       |
| 7+          | Un item par ligne.                                                               |

### Colonnes item (ligne 6)

`Cote` · `Titre` · `Fonds` · `État` · `Date` · `Année` · `Type` ·
`Langue` · `Description` · `Notes internes` · `DOI Nakala` ·
`Nb fichiers`.

`Fonds` reflète le fonds d'origine de chaque item — particulièrement
utile pour les collections transversales.

### Limites Excel

- Cellules : 32 767 caractères max (descriptions longues
  tronquées par Excel à l'ouverture, pas par ColleC).
- Titre de feuille : 31 caractères max ; le titre de collection
  est tronqué et les caractères interdits (`[]:*?/\`) sont
  retirés.
- Encodage : pas de question, xlsx est XML compressé.

## Limitations communes

- **Pas de conversion EDTF** vers ISO 8601 : `Item.date` est
  exporté littéralement. Si l'item a `1969?`, c'est cette chaîne
  qui sort. À évaluer en V2 selon les retours utilisateur.
- **Pas de JSON-LD** (contextes COAR / Nakala) : reporté à une
  session ultérieure.
- **Type COAR non validé** contre la liste officielle. Le rapport
  d'export signale les valeurs hors `http://purl.org/coar/resource_type/`.
- **Fichiers non inclus** dans les exports : seules les
  métadonnées des items sont exportées, pas les binaires des
  scans. Pour une publication Nakala complète, l'upload des
  fichiers se fait séparément via l'interface Nakala.

## Reproductibilité

Tous les exports sont déterministes : deux appels successifs sur
les mêmes données produisent des fichiers **identiques au
bit près**.

Garanties :

- items triés par `(fonds.cote, item.cote)` ;
- fichiers d'un item triés par `ordre` ;
- listes de valeurs (auteurs, sujets, …) triées alphabétiquement
  avant sérialisation.

Permet d'utiliser un export comme empreinte d'état (diff entre
deux exports = ce qui a changé).

## Voir aussi

- [Guide CLI exporter](../guide/cli/exporter.md) — comment
  invoquer la commande, avec exemples.
- [Concepts du modèle](../guide/concepts.md) — distinction miroir /
  libre rattachée / transversale, fondamentale pour comprendre
  l'unité d'export.
