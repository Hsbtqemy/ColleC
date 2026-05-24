# Assistant d'import web

L'assistant web complète la CLI [`archives-tool importer`](cli/importer.md)
en exposant le mapping colonnes → champs depuis l'interface,
sans avoir à écrire un profil YAML à la main. Le workflow est
itératif (chaque étape sauvegarde dans une `SessionImport`),
permet de revenir en arrière, et produit le profil YAML qui
peut ensuite être réutilisé en CLI pour des imports identiques.

## Accéder à l'assistant

Depuis le tableau de bord : bouton **« Importer »** → ouvre
`/import`. Liste les sessions en cours (reprises possibles) et un
bouton **« Nouvel import »** pour démarrer.

Désactivé en mode lecture seule.

## Pipeline en 5 étapes

```
1. Tableur          2. Fonds           3. Mapping         4. Fichiers        5. Aperçu
   uploader le        cote / titre /     colonnes →         résolution sur     dry-run +
   CSV/Excel          éditeur du         champs item        disque (regex      validation
                      fonds cible        et fichier         ou template)       avant écriture
```

### 1. Tableur (`/import/<sid>/tableur`)

Upload du fichier source : CSV (séparateur auto-détecté) ou Excel
(`.xlsx`, `.xls`). Le contenu est lu avec pandas en `dtype=str`
(préserve les zéros initiaux des cotes, les caractères Unicode),
NFC + strip, et les sentinelles nulles courantes (`""`, `"n/a"`,
`"none"`, `"s.d."`, NaN) sont converties en `None`.

La table d'analyse calcule par colonne :

- 3 valeurs d'**échantillon** (premières valeurs non-vides),
- taux de **remplissage** (« 173/173 »),
- nombre de valeurs **uniques** (clé pour deviner si c'est une
  cote, une métadonnée stable, ou un titre).

Cette analyse alimente les heuristiques et l'aperçu inline de
l'étape mapping.

### 2. Fonds (`/import/<sid>/fonds`)

Renseigne la cote du fonds cible (création ou réutilisation
existante) + titre + métadonnées principales (éditeur, ISSN,
périodicité, descriptions…). Si la cote existe déjà, le profil
réutilisera le fonds (et sa miroir auto-créée).

### 3. Mapping (`/import/<sid>/mapping`)

**Deux modes coexistent**.

#### Mode simple (par défaut)

4 questions explicites :

1. **Quelle colonne contient la cote** de chaque item ?
2. **Granularité** : une ligne = un item (cote stable) ou une
   ligne = un fichier (plusieurs lignes par cote) ?
3. **Quelle colonne contient le titre** ?
4. **Quelle colonne contient la date** ?

Le reste des colonnes est **auto-classé** en :

- Cibles DC dédiées (`auteur`, `description`, `doi`, `langue`,
  `numero`, etc.) quand l'heuristique nominative reconnaît le nom
  de la colonne (`Author`, `Description`, `DOI`, `Lang`, `Num`…).
- Métadonnées libres `metadonnees.<slug>` sinon, avec classif
  par-item / par-fichier selon les statistiques (≥ 90 % stables
  par cote → item, > 50 % variables → fichier promu en
  `fichier.metadonnees.<slug>`).

#### Mode avancé (`?avance=1` ou lien « Affiner colonne par colonne »)

Grille des 28 champs internes + sélecteur par colonne. Sous
chaque colonne :

- Aperçu inline (3 valeurs, taux de remplissage, uniques).
- **Heuristique** affichée comme suggestion (« Cible suggérée :
  `metadonnees.auteur` »).
- **Indice de classif** (« par-item / par-fichier »).
- **Promotion auto** pour les colonnes par-fichier vers
  `fichier.metadonnees.<slug>` quand pertinent.

Une **section « Anomalies détectées »** signale les conflits
entre la cible choisie et la classif statistique (ex. : « la
colonne `Page` est classée par-fichier mais cible
`item.metadonnees` »). Bouton client-side pour corriger sans
POST intermédiaire.

### 4. Fichiers (`/import/<sid>/fichiers`)

Définit la stratégie de résolution des fichiers sur disque (ou
sur Nakala) :

- **Aucun** : import de métadonnées seules (cas valide pour
  amorcer un catalogue avant numérisation).
- **Colonne** : la valeur d'une colonne contient le nom de
  fichier (`PF_1978_07_017.pdf`) — chercher sous la racine
  configurée.
- **Regex** : extraire un pattern depuis la cote pour reconstruire
  le nom de fichier (`PF-(\d+)` → `PF_{1}.pdf`).
- **Template** : composer un nom de fichier depuis plusieurs
  colonnes (`{annee}/{numero}.pdf`).
- **URL Nakala** : promouvoir une URL Nakala d'une colonne vers
  `fichier.iiif_url_nakala` (cas standard pour les exports
  Nakala — voir « Cas Nakala » plus bas).

### 5. Aperçu (`/import/<sid>/apercu`)

**Dry-run obligatoire avant validation**. Affiche :

- Nombre d'items à créer / mettre à jour.
- Nombre de fichiers résolus, manquants, en double.
- Warnings (cotes invalides, dates incertaines, valeurs non
  canoniques).
- 10 premiers items en exemple (cote, titre, date, fichier
  rattaché).

Si tout est OK, bouton **« Valider l'import »** déclenche
l'écriture réelle. Le profil YAML généré est sauvegardé dans
`profiles/<cote_fonds>.yaml` pour reproductibilité CLI.

## Cas Nakala

Les exports Nakala ont un format standard (CSV avec colonnes
`doi`, `data_url`, `Type`, `Langue`, `Description`, etc.). L'assistant
les reconnaît automatiquement en mode simple :

- `DOI` → `Item.doi_nakala`
- `DOI collection` → `Item.doi_collection_nakala` (avec propagation
  auto vers `Collection.miroir.doi_nakala` si valeur unique sur
  tous les items)
- `Type` → `Item.type_coar` (avec conversion alias textuel
  → URI canonique : `journal` → `http://purl.org/coar/.../c_3e5a`)
- `Langue` → `Item.langue` (code ISO 639-3 attendu)
- `data_url` → `Fichier.iiif_url_nakala` (avec normalisation
  `data` → `info.json` IIIF Image API pour OpenSeadragon)

Sans cette reconnaissance, l'utilisateur devait remapper chaque
colonne en mode avancé. Cf. les frictions F1-F4 + bugs A/B/C
documentés dans le [changelog V0.9.3](../annexes/changelog.md).

## Erreurs courantes

| Symptôme | Cause probable | Résolution |
| --- | --- | --- |
| « 0 fichiers résolus » | Racine disque mal configurée | Vérifier `config_local.yaml`, section `racines:` |
| Items créés mais sans fichiers | Granularité = fichier sans colonne URL Nakala mappée | Repasser en mode avancé, mapper `fichier.iiif_url_nakala` |
| Champs perdus | Mode simple n'a pas reconnu la colonne | Repasser en mode avancé, mapper manuellement |
| Vignettes Nakala manquantes | Pas de dérivés locaux ET pas d'URL IIIF | Lancer `archives-tool deriver`, ou vérifier `iiif_url_nakala` |

## Reprendre une session interrompue

Les `SessionImport` sont persistées en base. La liste sur `/import`
permet de reprendre une session en cours à l'étape où elle a été
abandonnée. Bouton **« Abandonner cet import »** pour la
supprimer définitivement.

## Profil YAML généré

À la validation, l'assistant écrit un profil YAML v2 dans
`profiles/<cote>.yaml` qui peut être réutilisé en CLI :

```bash
uv run archives-tool importer profiles/PF.yaml --no-dry-run
```

Utile pour re-importer après correction du tableur source (un
nouveau dump Nakala par exemple), ou pour cloner la structure
d'un fonds vers un autre similaire (copier le profil, ajuster
les valeurs).
