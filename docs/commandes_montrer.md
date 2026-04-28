# Commandes `montrer`

Sous-groupe `archives-tool montrer ...` : visualisation en lecture
seule de ce qui se trouve en base, avec mise en forme Rich.

Ces commandes ne modifient jamais la base. Elles servent à :
- vérifier qu'un import s'est bien passé ;
- inspecter un item ou un fichier précis avant édition ;
- suivre l'avancement du catalogage ;
- diagnostiquer un fichier qui aurait disparu du disque.

Elles resteront utiles même quand l'interface web sera là, pour le
travail rapide en ligne de commande et le debug.

## Vue d'ensemble

| Commande | Rôle |
|---|---|
| `montrer collections` | Lister toutes les collections (plat ou arbre). |
| `montrer collection COTE` | Fiche d'une collection + tableau de ses items. |
| `montrer item COTE` | Fiche détaillée d'un item, métadonnées, fichiers. |
| `montrer fichier ID` | Fiche d'un fichier + diagnostic disque. |
| `montrer statistiques` | Vue d'ensemble globale ou par collection. |

Toutes les commandes acceptent `--db-path PATH` (défaut
`data/archives.db`).

## `montrer collections`

```bash
archives-tool montrer collections [OPTIONS]
```

| Option | Défaut | Effet |
|---|---|---|
| `--recursif` / `--pas-recursif` | plat | Arbre `rich.Tree` au lieu d'un tableau plat. |
| `--vide` / `--avec-items` | toutes | Filtrer les collections sans items (mode plat). |

**Mode plat** — tableau trié par cote :

```
        Collections
┌──────┬───────────────┬───────┬──────────┬───────────────┬─────────────────────┐
│ Cote │ Titre         │ Items │ Fichiers │ Avancement    │ Modifié le          │
├──────┼───────────────┼───────┼──────────┼───────────────┼─────────────────────┤
│ FA   │ Fonds Aínsa   │   380 │   1 245  │ ▓▓▓▓░░░░░░ 38% │ 2026-04-18 11:02   │
│ HK   │ Hara-Kiri     │    72 │     189  │ ▓▓▓▓▓▓▓░░░ 71% │ 2026-04-12 14:32   │
│ RDM  │ Revue 2 Mondes│    95 │     280  │ ▓▓▓▓▓▓▓▓▓░ 94% │ 2026-04-20 09:15   │
└──────┴───────────────┴───────┴──────────┴───────────────┴─────────────────────┘
```

L'avancement est le ratio d'items en état `valide` ou `verifie`.

**Mode récursif** — `rich.Tree` :

```
Collections
├── FA — Fonds Aínsa (380 items, 1245 fichiers, ▓▓▓▓░░░░░░  38%)
│   ├── FA-AA — Sous-fonds AA (120 items, 350 fichiers, ▓▓▓▓▓░░░░░  52%)
│   └── FA-BB — Sous-fonds BB (260 items, 895 fichiers, ▓▓▓░░░░░░░  31%)
└── HK — Hara-Kiri (72 items, 189 fichiers, ▓▓▓▓▓▓▓░░░  71%)
```

## `montrer collection COTE`

```bash
archives-tool montrer collection COTE [OPTIONS]
```

| Option | Défaut | Effet |
|---|---|---|
| `--items` / `--pas-items` | items | Affiche le tableau d'items (sinon fiche seule). |
| `--limite N` | 50 | Nombre max d'items dans le tableau (0 = illimité). |
| `--tri-par CHAMP` | cote | Tri par `cote`, `date`, `etat`, `modifie`. |

Sortie : un panneau Rich avec les métadonnées de la collection, suivi
d'un tableau des items avec leur cote, numéro, date, titre tronqué,
état coloré et nombre de fichiers. Footer indique si la liste a été
tronquée par `--limite`.

Codes de sortie : `0` succès, `1` collection introuvable.

## `montrer item COTE`

```bash
archives-tool montrer item COTE [OPTIONS]
```

| Option | Défaut | Effet |
|---|---|---|
| `--collection COTE_COLLECTION` | — | À fournir si la cote item n'est pas unique globalement. |
| `--metadonnees-completes` | off | Affiche tout le JSON `metadonnees` (sinon résumé une-ligne-par-champ). |
| `--fichiers` / `--pas-fichiers` | fichiers | Affiche le tableau des fichiers rattachés. |

Sortie en trois panneaux : fiche principale (cote, collection,
numéro, date, titre, type COAR, langue, état, DOI Nakala),
métadonnées étendues, tableau des fichiers (ordre, type, folio, nom,
taille humaine, état).

Codes de sortie : `0` succès, `1` introuvable ou ambigu sans
`--collection`.

## `montrer fichier ID`

```bash
archives-tool montrer fichier ID [OPTIONS]
```

| Option | Défaut | Effet |
|---|---|---|
| `--config PATH` | `config_local.yaml` | Config locale pour le diagnostic disque (optionnelle). |

Sortie en deux panneaux :

1. **Fiche du fichier** : item parent, ordre, type de page, folio,
   nom, racine logique, chemin relatif POSIX, format, taille,
   dimensions, hash SHA-256, état, timestamp d'ajout, ajouté par.

2. **Chemin résolu** (si la config est valide) : résolution de la
   racine logique vers un chemin disque absolu, et trois
   vérifications :
   - `✓ existe sur disque` ou `✗ absent sur disque` ;
   - `✓ hash inchangé` ou `⚠ hash modifié depuis l'import` (avec les
     deux hashes affichés pour diff) ;
   - `vérification hash impossible` si pas de hash en base.

Si la racine n'est pas configurée localement, le diagnostic est
sauté avec un avertissement.

Codes de sortie : `0` succès, `1` fichier introuvable en base.

## `montrer statistiques`

```bash
archives-tool montrer statistiques [--collection COTE]
```

Vue globale par défaut, périmètre restreint avec `--collection` (la
collection cible et ses sous-collections, parcours descendant).

Sortie : un panneau avec
- compteurs (collections racines, sous-collections, items, fichiers,
  volume disque référencé) ;
- répartition des items par état avec mini-graphes ▓▓▓░░ + pourcentage ;
- top 5 collections par items (vue globale uniquement).

Codes de sortie : `0` succès (y compris base vide → message
bienveillant), `1` collection introuvable.

## Cas d'usage typiques

### Vérifier qu'un import s'est bien passé

```bash
archives-tool importer profils/ainsa.yaml --no-dry-run
archives-tool montrer collections
archives-tool montrer collection FA --limite 10
archives-tool montrer statistiques --collection FA
```

### Inspecter un item avant édition

```bash
archives-tool montrer item FA-AA-01-01 --metadonnees-completes
```

### Suivre l'avancement du catalogage

```bash
archives-tool montrer statistiques
```

Ratio par état + barre de progression visible en un coup d'œil.

### Diagnostiquer un fichier disparu

```bash
archives-tool montrer fichier 142 --config config_local.yaml
```

Les `✗ absent sur disque` ou `⚠ hash modifié` apparaissent dans le
panneau Chemin résolu.

## Sortie redirigée vers un fichier

Rich détecte automatiquement le mode non-tty quand la sortie est
redirigée :

```bash
archives-tool montrer collection FA > inventaire.txt
```

Pas de codes ANSI dans le fichier, mise en forme simplifiée mais
lisible.

## Largeur du terminal

Rich adapte automatiquement les colonnes à la largeur disponible
(`COLUMNS` env). Tester sur 80 et 200 colonnes : pas de débordement,
les colonnes longues (titre, description) sont tronquées avec `…` ou
repliées (`overflow="fold"`).
