# Premier import

Cette page vous fait passer d'un dossier de scans + un tableur
d'inventaire à un fonds enregistré dans ColleC, en une dizaine de
minutes.

## Vue d'ensemble du flux

```
┌─────────────────┐   ┌────────────┐   ┌─────────────┐   ┌──────────┐
│ Tableur Excel/  │   │   Profil   │   │  Importer   │   │   Base   │
│ CSV inventaire  │ + │   YAML     │ → │ (dry-run)   │ → │ SQLite   │
└─────────────────┘   └────────────┘   └─────────────┘   └──────────┘
        ▲                                       │
        │                                       ▼
┌─────────────────┐                    ┌─────────────┐
│ Scans physiques │ ─────────────────▶ │  rapport    │
│ sur disque      │                    │  d'import   │
└─────────────────┘                    └─────────────┘
```

L'**import est un point d'entrée**. Une fois fait, la base devient
la source de vérité — modifier le tableur a posteriori n'a aucun
effet sur la base.

## Préparer son tableur

Le tableur peut être en Excel (`.xlsx`) ou en CSV. Colonnes
recommandées pour un premier import :

| Colonne   | Rôle                                                    |
| --------- | ------------------------------------------------------- |
| `cote`    | Identifiant unique de l'item dans le fonds (obligatoire). |
| `titre`   | Titre catalographique (obligatoire pour exports DC).    |
| `date`    | Date EDTF (`1969`, `1969-04`, `1969?`, `192X`, …).      |
| `annee`   | Année numérique (4 chiffres) si vous voulez filtrer.    |
| `langue`  | Code ISO 639-3 (`fra`, `eng`, `spa`, …).                |
| `type_coar`| URI COAR (par exemple `http://purl.org/coar/resource_type/c_18cd`). |

Les sentinelles d'absence (`"none"`, `"n/a"`, `"s.d."`, vide,
`NaN`) sont reconnues si vous les déclarez dans le profil.

### Exemple `inventaire_hk.csv`

```csv
cote,titre,date,annee,langue,type_coar
HK-001,"Hara-Kiri n°1","1960-09",1960,fra,http://purl.org/coar/resource_type/c_2659
HK-002,"Hara-Kiri n°2","1960-10",1960,fra,http://purl.org/coar/resource_type/c_2659
HK-003,"Hara-Kiri n°3","1960-11",1960,fra,http://purl.org/coar/resource_type/c_2659
```

## Préparer ses scans

Organiser les fichiers physiques sous une racine déclarée dans
votre `config_local.yaml`. Convention courante : un sous-dossier
par item, fichiers numérotés à l'intérieur.

```
/Users/marie/Archives/Scans/
└── HK/
    ├── HK-001/
    │   ├── HK-001-001.tif
    │   ├── HK-001-002.tif
    │   └── HK-001-003.tif
    ├── HK-002/
    │   └── HK-002-001.tif
    └── HK-003/
        └── HK-003-001.tif
```

Le profil va décrire comment retrouver ces fichiers à partir de
chaque ligne du tableur.

## Écrire son premier profil

Un profil est un fichier YAML. ColleC fournit un générateur :

```bash
uv run archives-tool profil analyser inventaire_hk.csv \
    --sortie profils/hk.yaml
```

Le générateur lit le tableur et écrit un squelette pré-rempli
avec les colonnes détectées. Il reste à compléter quelques
sections.

### Exemple `profils/hk.yaml`

```yaml
version_profil: 2

fonds:
  cote: HK
  titre: "Hara-Kiri (revue)"
  description_publique: >-
    Revue satirique mensuelle française fondée en 1960 par
    François Cavanna et Georges Bernier dit Professeur Choron.
  editeur: "Éditions du Square"
  periodicite: "mensuelle"

tableur:
  chemin: inventaire_hk.csv
  valeurs_nulles: ["none", "n/a", "s.d.", "NaN", ""]

granularite_source: item

mapping:
  cote: "cote"
  titre: "titre"
  date: "date"
  annee: "annee"
  langue: "langue"
  type_coar: "type_coar"

valeurs_par_defaut:
  langue: fra
  etat_catalogage: brouillon

fichiers:
  racine: scans
  motif_chemin: "HK/{cote}/{cote}-{ordre:03d}.tif"
```

Référence complète du format : [Profils d'import](../reference/profils.md).

## Lancer en dry-run

```bash
uv run archives-tool importer profils/hk.yaml
```

Le dry-run lit le tableur, transforme les lignes, résout les
fichiers, calcule les diffs… et `rollback` à la fin. Rien n'est
écrit en base.

Sortie attendue :

```text
Import DRY-RUN — durée 0.42s
  Fonds HK (créé) + miroir personnalisée
  Items créés : 3
  Fichiers ajoutés : 5
```

Si vous voyez des `Erreurs` ou des `Lignes ignorées`, corriger
le profil ou le tableur et relancer en dry-run.

## Lancer pour de vrai

```bash
uv run archives-tool importer profils/hk.yaml \
    --no-dry-run --utilisateur "Marie"
```

En mode réel :

- les hash SHA-256 sont calculés pour chaque fichier ajouté ;
- un `batch_id` UUID est généré et journalé dans
  `OperationImport` ;
- l'ensemble est dans une seule transaction : si une seule ligne
  remonte une erreur, **tout est annulé**.

## Vérifier le résultat

Lister les fonds :

```bash
uv run archives-tool montrer fonds
```

Détailler le fonds créé :

```bash
uv run archives-tool montrer fonds --cote HK
```

Détailler un item :

```bash
uv run archives-tool montrer item HK-001 --fonds HK
```

Vérifier la cohérence :

```bash
uv run archives-tool controler --fonds HK
```

Sur un fonds tout neuf vous verrez probablement des
`FILE-HASH-MANQUANT` (le seeder ne calcule pas encore les hash en
dry-run) ou des avertissements `INV6` si vous avez retiré un
item de la [collection miroir](../guide/concepts.md#collection-miroir).
C'est documenté dans [Contrôles qa](../reference/controles.md).

## Et ensuite ?

[Workflow type](workflow-type.md) : la suite — catalogage,
contrôles, dérivés, export Nakala.
