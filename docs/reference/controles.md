# Contrôles qa

Référence des 14 contrôles disponibles dans
[`archives-tool controler`](../guide/cli/controler.md). Cette page
documente **ce que vérifie chaque contrôle, pourquoi, et comment
résoudre** s'il échoue. Pour l'usage de la CLI, voir le guide.

Les contrôles sont strictement en **lecture seule** : aucun
`db.add` ni `db.commit`. On peut les exécuter sur une base de
production sans risque, dans une CI, ou sur une copie en cours
d'analyse — la base est garantie inchangée.

## Vue d'ensemble

Les contrôles sont organisés en **4 familles** :

| Famille          | Contrôles                                                                          | Sévérités principales       |
| ---------------- | ---------------------------------------------------------------------------------- | --------------------------- |
| `invariants`     | INV1, INV2, INV4, INV6                                                             | erreur (sauf INV6)          |
| `fichiers`       | FILE-MISSING, FILE-ITEM-VIDE, FILE-HASH-DUPLIQUE, FILE-HASH-MANQUANT               | avertissement / info        |
| `metadonnees`    | META-COTE-INVALIDE, META-TITRE-VIDE, META-DATE-INVALIDE, META-ANNEE-IMPLAUSIBLE    | erreur / avertissement      |
| `cross`          | CROSS-COTE-DUPLIQUEE-FONDS, CROSS-FONDS-VIDE                                       | erreur / info               |

## Sévérités

| Sévérité      | Symbole | Comportement                                                            |
| ------------- | ------- | ----------------------------------------------------------------------- |
| Erreur        | ✗       | Exit code 1 dès qu'une seule erreur remonte.                            |
| Avertissement | ⚠       | Exit code 0 par défaut ; exit 1 si `--strict` est passé.                |
| Info          | ℹ       | Jamais d'exit code non-zéro (sauf `--strict`).                          |

## Tableau récapitulatif

| ID                            | Famille       | Sévérité       | Vérifie                                                                  |
| ----------------------------- | ------------- | -------------- | ------------------------------------------------------------------------ |
| `INV1`                        | invariants    | erreur         | Tout fonds a exactement une collection miroir.                           |
| `INV2`                        | invariants    | erreur         | Toute miroir a un fonds parent.                                          |
| `INV4`                        | invariants    | erreur         | Tout item a un fonds parent.                                             |
| `INV6`                        | invariants    | avertissement  | Tout item est dans la miroir de son fonds.                               |
| `FILE-MISSING`                | fichiers      | avertissement  | Fichier référencé en base mais absent du disque.                         |
| `FILE-ITEM-VIDE`              | fichiers      | info           | Item sans aucun fichier rattaché.                                        |
| `FILE-HASH-DUPLIQUE`          | fichiers      | avertissement  | Plusieurs fichiers ACTIF avec même hash SHA-256.                         |
| `FILE-HASH-MANQUANT`          | fichiers      | info           | Fichier ACTIF sans hash calculé.                                         |
| `META-COTE-INVALIDE`          | metadonnees   | erreur         | Cote (fonds/collection/item) hors pattern `^[A-Za-z0-9_-]+$`.            |
| `META-TITRE-VIDE`             | metadonnees   | erreur         | Titre vide ou whitespace-only sur fonds, collection ou item.             |
| `META-DATE-INVALIDE`          | metadonnees   | avertissement  | `Item.date` ne reconnaît pas la syntaxe EDTF tolérante.                  |
| `META-ANNEE-IMPLAUSIBLE`      | metadonnees   | avertissement  | `Item.annee` hors plage `[1000, 2100]` (configurable).                   |
| `CROSS-COTE-DUPLIQUEE-FONDS`  | cross         | erreur         | Plusieurs fonds avec la même cote (filet — UNIQUE en DB).                |
| `CROSS-FONDS-VIDE`            | cross         | info           | Fonds créé mais sans aucun item.                                         |

## Détail des contrôles

### Famille `invariants`

#### `INV1` — Collection miroir unique par fonds

**Vérifie** : pour chaque fonds en base, il existe **exactement
une** collection miroir (ni zéro, ni deux ou plus).

**Pourquoi** : la miroir est créée automatiquement par le service
`creer_fonds`. Une violation indique soit une intervention
manuelle directe en base, soit un bug du seeder ou de l'importer.
La miroir est le point d'attache Nakala par défaut, et on ne peut
en avoir qu'un.

**Comment résoudre** : si zéro miroir, créer manuellement la
collection avec `est_miroir=True` (et la même cote que le fonds).
Si plusieurs, identifier les doublons via la sortie du contrôle
et en supprimer toutes sauf une (privilégier celle qui contient
le plus d'items).

#### `INV2` — Collection miroir avec fonds parent

**Vérifie** : toute collection avec `est_miroir = True` a un
`fonds_id` non null.

**Pourquoi** : une miroir reflète un fonds par définition. Un
`fonds_id NULL` la rend orpheline et incohérente avec son rôle.

**Comment résoudre** : convertir la collection en libre
transversale (`est_miroir = False`) ou la supprimer si elle est
vide.

#### `INV4` — Item rattaché à un fonds

**Vérifie** : tout item a un `fonds_id` non null.

**Pourquoi** : `Item.fonds_id` est `NOT NULL` au niveau du
schéma. Ce contrôle est un **filet de sécurité** — il ne devrait
jamais remonter une erreur. S'il en remonte une, c'est qu'une
intervention SQL directe a corrompu la base (ou un bug
catastrophique).

**Comment résoudre** : restaurer une sauvegarde. La contrainte
`NOT NULL` rendant le cas pratiquement impossible sans
intervention SQL directe, il s'agit toujours d'un signe de
corruption.

#### `INV6` — Item dans la collection miroir de son fonds

**Vérifie** : tout item figure dans la miroir de son fonds (via
`ItemCollection`).

**Pourquoi** : à la création d'un item, il est ajouté
automatiquement à la miroir. **Avertissement** seulement (pas
erreur) car le retrait manuel est explicitement autorisé
(invariant 7 du modèle — cf. [Concepts](../guide/concepts.md#invariants-du-modèle)).

**Comment résoudre** : si le retrait est intentionnel (cas rare,
typiquement pour exclure un item d'une publication Nakala),
ignorer l'avertissement. Sinon, ré-ajouter l'item dans la miroir
via l'interface web ou un INSERT dans `item_collection`.

### Famille `fichiers`

#### `FILE-MISSING` — Fichier référencé absent du disque

**Vérifie** : tout `Fichier` en base avec `etat = ACTIF` a son
fichier physique présent à `racine + chemin_relatif`.

**Pourquoi** : décalage base ↔ disque, fréquent quand des scans
ont été déplacés ou supprimés sans passer par
[`renommer`](../guide/cli/renommer.md). Bloque la génération de
dérivés et casse la visionneuse.

**Comment résoudre** :

- vérifier que la racine est bien configurée dans
  `config_local.yaml` (cf. [Configuration](../premiers-pas/configuration.md)) ;
- si les fichiers ont été déplacés, les remettre en place ou
  utiliser `renommer` pour aligner la base ;
- si les fichiers ont été supprimés, marquer les lignes en base
  comme `etat = corbeille` (via SQL ou interface).

Sur la **base de démonstration** (chemins fictifs), tous les
fichiers signalent `racine non configurée` ou un message
similaire — c'est attendu.

#### `FILE-ITEM-VIDE` — Item sans fichier

**Vérifie** : tout item a au moins un `Fichier` rattaché.

**Pourquoi** : un item de catalogue sans aucun scan rattaché est
souvent un import incomplet ou un placeholder. **Info**
seulement — un item peut légitimement être catalogué sans scan
(notice purement bibliographique).

**Comment résoudre** : ajouter des fichiers via l'interface web
(onglet Fichiers de l'item) ou via un ré-import du profil avec
les scans en place.

#### `FILE-HASH-DUPLIQUE` — Doublons par hash SHA-256

**Vérifie** : aucune paire de `Fichier` ACTIF n'a le même hash
SHA-256.

**Pourquoi** : doublons potentiels — soit le même scan a été
importé deux fois, soit une copie traîne. Garde-fou contre
duplications accidentelles avant publication.

**Comment résoudre** : examiner chaque paire signalée. Si c'est
bien un doublon, marquer une des deux lignes en
`etat = remplace` ou `etat = corbeille`. Si c'est légitime
(scans identiques rattachés à deux items distincts), accepter
l'avertissement.

#### `FILE-HASH-MANQUANT` — Fichier sans hash

**Vérifie** : tout `Fichier` ACTIF a un `hash_sha256` calculé.

**Pourquoi** : le hash sert au contrôle d'intégrité et à la
détection de doublons. Calculé à l'import en mode réel, mais pas
en dry-run, ni par le seeder de la base demo.

**Comment résoudre** : sur une base de démonstration, ignorer
(attendu). Sur une base réelle, lancer un script de calcul
de hash a posteriori (à venir, V0.10) ou ré-importer en mode
réel.

### Famille `metadonnees`

#### `META-COTE-INVALIDE` — Cote hors pattern alphanumérique

**Vérifie** : toute cote (fonds, collection, item) respecte le
pattern `^[A-Za-z0-9_-]+$`.

**Pourquoi** : les cotes apparaissent dans des chemins de
fichiers, des URLs, des cotes d'identification. Les caractères
spéciaux causent des bugs de templating, d'export Nakala (qui
n'aime pas les espaces ni accents), et de résolution de fichiers.

**Comment résoudre** : renommer l'entité incriminée (interface
web : modifier la cote ; CLI : il n'existe pas encore de
commande de rename de cote — à venir V0.10). En attendant,
SQL direct.

#### `META-TITRE-VIDE` — Titre vide

**Vérifie** : `Fonds.titre`, `Collection.titre` et `Item.titre`
ne sont pas vides ni whitespace-only.

**Pourquoi** : un titre vide casse les exports DC (champ
obligatoire) et l'affichage dans l'interface.

**Comment résoudre** : remplir le titre via l'interface web ou
un ré-import.

#### `META-DATE-INVALIDE` — Date EDTF non reconnue

**Vérifie** : `Item.date` (quand renseigné) reconnaît la regex
EDTF tolérante (formes : `1969`, `1969-04`, `1969?`, `192X`,
`1969/1970`, etc.).

**Pourquoi** : les exports Nakala et DC incluent la date telle
quelle. Une date au mauvais format peut être rejetée par Nakala
ou mal indexée.

**Comment résoudre** : ouvrir l'item dans l'interface web,
corriger la date pour qu'elle corresponde à un format EDTF
valide. La regex est tolérante (incertitude `?`, troncature `X`,
ranges `/`) — voir [EDTF](https://www.loc.gov/standards/datetime/).

#### `META-ANNEE-IMPLAUSIBLE` — Année hors plage

**Vérifie** : `Item.annee` (quand renseigné) est dans
`[1000, 2100]` (plage par défaut).

**Pourquoi** : une année à `99` ou `20240` est presque toujours
une erreur de saisie ou de parsing.

**Comment résoudre** : corriger via l'interface. La plage est
configurable via les arguments du contrôle si vous travaillez
sur des fonds antiques ou anticipés.

### Famille `cross`

Ces contrôles opèrent **toujours sur la base entière**,
indépendamment du périmètre `--fonds` ou `--collection` passé en
ligne de commande. Logique : la duplication de cote ou un fonds
vide sont des problèmes globaux dont la détection ne dépend pas
du périmètre demandé.

#### `CROSS-COTE-DUPLIQUEE-FONDS` — Cotes de fonds dupliquées

**Vérifie** : aucune paire de `Fonds` n'a la même cote.

**Pourquoi** : la cote de fonds est globalement unique
(contrainte UNIQUE en DB). Garde-fou — ne devrait jamais
remonter une erreur sauf intervention SQL directe.

**Comment résoudre** : restaurer une sauvegarde ou renommer une
des cotes via SQL.

#### `CROSS-FONDS-VIDE` — Fonds sans items

**Vérifie** : tout fonds a au moins un item.

**Pourquoi** : un fonds sans items est légitime juste après sa
création, en attendant l'import. **Info** seulement.

**Comment résoudre** : importer les items du fonds, ou supprimer
le fonds si la création était une erreur.

## Interpréter les avertissements sur la base demo

Sur la base de démonstration (`archives-tool demo init`) :

- `FILE-MISSING` (avertissement) : tous les fichiers signalent
  `racine non configurée` → c'est attendu, la base demo ne
  pointe vers aucun disque réel.
- `FILE-HASH-MANQUANT` (info) : aucun fichier n'a de hash → le
  seeder ne calcule pas de SHA-256 (gain de temps).
- `INV6` (avertissement) : peut remonter si le seeder a retiré
  un item d'une miroir intentionnellement.

Sur une vraie base, ces mêmes avertissements méritent enquête.

## Format JSON

Pour intégration CI / outillage, voir
[`controler --format json`](../guide/cli/controler.md#format-json-intégration-ci).
La structure est documentée et stable — toute évolution
incompatible bumpera le champ `version_qa`.

## Voir aussi

- [Guide CLI controler](../guide/cli/controler.md) — comment
  invoquer la commande, options et codes de sortie.
- [Concepts du modèle](../guide/concepts.md) — invariants 1 à 10,
  fondement des contrôles `invariants`.
