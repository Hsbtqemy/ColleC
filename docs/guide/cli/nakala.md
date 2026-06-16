# Nakala (CLI)

L'intégration Nakala expose **15 sous-commandes** sous
`archives-tool nakala …`, organisées en six flux complémentaires :

1. [Lecture](#1-lecture) — consulter un dépôt distant.
2. [Rapatriement](#2-rapatriement) — créer / mettre à jour des items ColleC depuis Nakala.
3. [Export tableur](#3-export-tableur) — extraire une collection en CSV / xlsx.
4. [Dépôt](#4-depot) — créer de nouveaux dépôts Nakala depuis ColleC.
5. [Push métadonnées](#5-push-metadonnees) — pousser des modifs sur un dépôt existant.
6. [Synchronisation fichiers](#6-synchronisation-fichiers) — comparer + pousser les binaires.
7. [Publication](#7-publication) — bascule `pending` → `published` (IRRÉVERSIBLE).

Chaque flux peut s'utiliser indépendamment. L'ordre ci-dessus reflète
le **cycle de vie** typique d'un dépôt : lecture / rapatriement →
catalogage local → dépôt → push → publication.

## Pré-requis

Toutes les commandes Nakala exigent une section `nakala:` dans le
`config_local.yaml` :

```yaml
utilisateur: "Marie"
nakala:
  base_url: https://api.nakala.fr      # ou https://api-test.nakala.fr pour les essais
  api_key: "votre-clé-api"             # obligatoire pour le dépôt / push
```

Sans la section : exit code `2` au démarrage. Sans `api_key` :
exit `2` uniquement pour les commandes d'écriture (lecture
reste tolérée pour `montrer` / `rapatrier` sur dépôts publics).

## Vue d'ensemble

| Commande                  | Type    | Effet                                                       |
| ------------------------- | ------- | ----------------------------------------------------------- |
| `montrer`                 | Lecture | Affiche les métadonnées + fichiers d'un dépôt distant.      |
| `citer`                   | Lecture | Affiche la citation bibliographique d'un dépôt publié.      |
| `rapatrier`               | Lecture | Crée un Item ColleC depuis un dépôt Nakala.                 |
| `rafraichir`              | Lecture | Re-pull + diff sur un item déjà rapatrié.                   |
| `rapatrier-collection`    | Lecture | Crée Fonds + N Items depuis une collection Nakala.          |
| `rafraichir-collection`   | Lecture | Re-pull + diffs des items liés d'une collection.            |
| `exporter-tableur`        | Lecture | Aplatit une collection Nakala en CSV / xlsx.                |
| `deposer`                 | Dépôt   | Crée un nouveau dépôt Nakala depuis un Item ColleC.         |
| `deposer-collection`      | Dépôt   | Crée collection Nakala + dépose ses items.                  |
| `pousser`                 | Push    | `PUT /datas/{id}` — métadonnées d'un item (titre, etc.).    |
| `pousser-collection`      | Push    | Pousse l'entité collection puis ses items liés.             |
| `comparer-fichiers`       | Push    | Diff fichiers ColleC vs Nakala (lecture seule).             |
| `pousser-fichiers`        | Push    | Upload + `POST`/`DELETE` granulaires (+ `PUT` réordon.) — synchronise les binaires. |
| `publier`                 | Pub     | `pending → published` sur un item (DOI DataCite minté).     |
| `publier-collection`      | Pub     | Publie tous les items liés d'une collection.                |

**Dry-run par défaut** sur toutes les opérations d'écriture
(`deposer`, `pousser`, `publier`, `rapatrier`, `rafraichir`). Passer
`--no-dry-run` pour appliquer effectivement.

**Format de sortie** : `--format text` (défaut, Rich coloré) ou
`--format json` (scripts d'automatisation, structure stable).
Toutes les commandes l'exposent depuis la passe 20 P3+c.2.

## 1. Lecture

### `montrer`

Affiche les métadonnées + fichiers d'un dépôt sans toucher la base
locale. Pratique pour vérifier rapidement un DOI avant rapatriement.

```bash
archives-tool nakala montrer 10.34847/nkl.abcdef12
```

Le format text liste les fichiers si ≤ 20, sinon redirige vers
`--format json`. JSON expose les 5 champs `FichierNakala` (`nom`,
`sha1`, `taille`, `mime`, `embargo_actif`). Si le dépôt est **publié**,
une ligne « Citation » est ajoutée (récupérée via l'endpoint citation).

### `citer`

Affiche la citation bibliographique prête à l'emploi d'un dépôt
(`GET /datas/{id}/citation`, lecture seule).

```bash
archives-tool nakala citer 10.34847/nkl.abcdef12
archives-tool nakala citer 10.34847/nkl.abcdef12 --format json
```

Une citation n'a de sens que pour un dépôt **publié** (DOI DataCite
minté). Un dépôt en brouillon (`pending`) renvoie un texte « non
citable ». La même citation est surfacée sur la fiche item de l'UI web
(chargée à la demande, le service Nakala étant lent).

## 2. Rapatriement

### `rapatrier`

Crée un Item ColleC depuis un dépôt Nakala. Dérive la cote du DOI
sauf si `--cote` fourni. Matérialise les fichiers Nakala en
`Fichier` avec `iiif_url_nakala` (rendu navigable dans la
visionneuse).

```bash
# Dry-run : aperçu, ne crée rien
archives-tool nakala rapatrier 10.34847/nkl.abcdef12 --fonds PF

# Réel : crée l'item + cache + matérialise les fichiers
archives-tool nakala rapatrier 10.34847/nkl.abcdef12 \
    --fonds PF --cote PF-001 --no-dry-run
```

Refuse si la cote dérivée est déjà prise (collision avec un autre
item du fonds → exit 1, message explicite, suggestion `--cote`).

Idempotent : si le DOI est déjà rapatrié, retourne `deja_existant=True`
sans recréer (utiliser `rafraichir` pour mettre à jour).

### `rafraichir`

Re-tire le dépôt distant et calcule un diff par rapport à l'item
ColleC. Dry-run (défaut) affiche le diff sans écraser ;
`--no-dry-run` applique.

```bash
archives-tool nakala rafraichir 10.34847/nkl.abcdef12
```

Champs ColleC-only (notes_internes, type_collection…) préservés.
Le sha1 des fichiers n'est PAS re-synchronisé (utiliser
`comparer-fichiers` + `pousser-fichiers` pour ça).

### `rapatrier-collection`

Crée un Fonds + N Items depuis une collection Nakala entière.
Boucle `rapatrier` sur chaque donnée de la collection. Si le fonds
cible n'existe pas, le crée depuis la collection (titre,
description).

```bash
# Aperçu : combien d'items, lesquels sautés
archives-tool nakala rapatrier-collection 10.34847/nkl.716dhx95

# Réel, dans un fonds existant
archives-tool nakala rapatrier-collection 10.34847/nkl.716dhx95 \
    --fonds PF --no-dry-run
```

Items en erreur (cote indérivable, métadonnées invalides) collectés
sans arrêter la boucle. Sortie text liste les comptes par catégorie ;
JSON expose la liste détaillée.

### `rafraichir-collection`

Boucle `rafraichir` sur tous les items liés. Items sans pendant
local listés en `non_lies` (à rapatrier).

```bash
archives-tool nakala rafraichir-collection 10.34847/nkl.716dhx95
```

## 3. Export tableur

### `exporter-tableur`

Aplatit une collection Nakala en CSV (`;`, UTF-8 BOM) ou xlsx, deux
granularités au choix :

- `--granularite donnee` : une ligne par donnée Nakala (item).
- `--granularite fichier` : une ligne par fichier (métadonnées de la
  donnée recopiées + colonnes techniques `nom`, `sha1`, `mime`,
  `taille`, `embargo`).

```bash
archives-tool nakala exporter-tableur 10.34847/nkl.716dhx95 \
    --granularite fichier --format xlsx --sortie pf_fichiers.xlsx
```

Lecture seule (pas d'accès à la base ColleC). Utile pour audit Nakala
ou import dans un autre système.

<a id="4-depot"></a>
## 4. Dépôt

Toutes les commandes d'écriture sont **dry-run par défaut**.

### `deposer`

Crée un nouveau dépôt Nakala depuis un Item ColleC :

1. Upload des fichiers locaux (résolus via `racines:` de la config).
2. `POST /datas` avec metas + files[] + statut.
3. Pose `Item.doi_nakala` (commit DB).

```bash
# Aperçu (statut par défaut = pending)
archives-tool nakala deposer PF-001 --fonds PF

# Réel + rattachement à une collection Nakala existante
archives-tool nakala deposer PF-001 --fonds PF --no-dry-run \
    --collection 10.34847/nkl.716dhx95
```

Garde-fous :
- Item déjà déposé (`doi_nakala` posé) → `deja_depose=True`,
  rien fait. Pour modifier les metas, utiliser `pousser`.
- Aucun fichier local résolvable → `DepotImpossible` (un item
  Nakala-only n'est pas re-déposable).
- Métadonnées insuffisantes (preflight refuse, ex. pas de créateur
  ni de date) → `MetaInvalide` exit 1. *Règle ColleC (qualité
  catalographique) : Nakala accepterait le dépôt sans — il n'exige
  que titre + type.*
- Si le `POST` échoue après uploads → cleanup best-effort des
  uploads orphelins côté Nakala.

### `deposer-collection`

Crée la collection Nakala (si pas déjà existante) puis dépose ses
items en boucle. Items déjà déposés → `sautes`, items sans fichier
local → `non_deposables`, erreurs metiers → `erreurs` (n'arrête pas
le lot).

```bash
archives-tool nakala deposer-collection PF-MIROIR --fonds PF \
    --statut-collection private --statut-donnee pending \
    --no-dry-run
```

Pour les **gros lots** (> 50 items), préférer la CLI à l'UI web : la
CLI a une journalisation propre et reprend plus simplement en cas
d'incident (cf. la décision « tâches de fond » dans
[CLAUDE.md](#) — runner mémoire avec reprise idempotente).

<a id="5-push-metadonnees"></a>
## 5. Push métadonnées

### `pousser`

Re-tire le dépôt distant, calcule le diff par propriété, et applique
un `PUT /datas/{id}` qui **remplace** les metas (Nakala impose
l'envoi de la liste complète, pas un patch).

```bash
# Aperçu du diff
archives-tool nakala pousser PF-001 --fonds PF

# Réel
archives-tool nakala pousser PF-001 --fonds PF --no-dry-run
```

**Garde-fou published** (passe 22) : refus par défaut si l'item est
`status=published` côté Nakala. Modifier les metas d'un item publié
change ce qu'une citation externe reflète (le DOI persiste mais
résout vers un nouveau titre / créateur). Pour confirmer :

```bash
archives-tool nakala pousser PF-001 --fonds PF \
    --no-dry-run --force-published
```

Court-circuité automatiquement si aucun changement (idempotent
silencieux : push 2x sans modif est no-op).

### `pousser-collection`

Pousse l'**entité collection** (titre + description) puis boucle
`pousser` sur les items liés.

```bash
archives-tool nakala pousser-collection PF-MIROIR --fonds PF \
    --no-dry-run
```

Comportement collection :
- Sans `doi_nakala` sur la collection → seul les items sont poussés.
- Avec : fusion des metas Nakala non gérées par ColleC (préservées)
  + valeurs locales pour titre + description (champs ColleC-only).

Items publiés sans `--force-published` → collectés en `erreurs`
(n'arrête pas le lot, à la différence de `pousser` unitaire qui
exit 1).

## 6. Synchronisation fichiers

Cycle distinct des métadonnées : un fichier modifié dans
ScanTailor / OCR retraité doit être ré-uploadé. ColleC distingue
proprement la classification (passe P3+c.1) du push effectif
(passe P3+c.2).

### `comparer-fichiers`

Diff lecture seule entre les `Fichier` ColleC et les fichiers
distants. Classe en **6 catégories** :

| Catégorie               | Sens                                                |
| ----------------------- | --------------------------------------------------- |
| `inchanges`             | sha1 local = sha1 distant, aucune action au push.   |
| `modifies`              | binaire local change, sha1_nakala connu côté distant. |
| `nouveaux`              | binaire local, sha1 absent du distant, à uploader.  |
| `nakala_only_sans_local`| Fichier ColleC sans binaire local (rapatrié seul).  |
| `non_actifs_a_retirer`  | Fichier en CORBEILLE / REMPLACE, sera retiré au PUT.|
| `fichiers_fantomes`     | sha1_nakala désynchronisé du distant (bloque push). |

Plus une catégorie distante : `orphelins_distants` (sha1 sur Nakala
sans Fichier ColleC correspondant).

```bash
archives-tool nakala comparer-fichiers PF-001 --fonds PF \
    --format json | jq .compare
```

Aucune écriture. Pratique pour auditer avant un push.

### `pousser-fichiers`

Pipeline complet : compare → garde-fous → upload nouveaux/modifies →
`POST /datas/{id}/files` (additif) pour les ajouts → `DELETE
/datas/{id}/files/{sha1}` pour les retraits (anciens modifiés,
orphelins, non-actifs) → `PUT files[]` de **réordonnancement** construit
depuis l'état distant relu (fixe l'ordre, sans drop silencieux) → mise à
jour `Fichier.sha1_nakala` + `iiif_url_nakala` + journal
`OperationPushNakala`.

```bash
# Aperçu (plan d'exécution sans toucher au distant)
archives-tool nakala pousser-fichiers PF-001 --fonds PF

# Réel avec retrait d'orphelins distants confirmé
archives-tool nakala pousser-fichiers PF-001 --fonds PF \
    --no-dry-run --retirer-orphelins

# Item publié : flag dangereux explicite
archives-tool nakala pousser-fichiers PF-001 --fonds PF \
    --no-dry-run --force-published
```

Six garde-fous (dans cet ordre d'évaluation) :

1. **`fichiers_fantomes`** (diagnostic) : un Fichier ColleC porte un
   `sha1_nakala` qui ne matche plus le distant. Refus loud →
   re-rapatrier ou nettoyer.
2. **Backfill incomplet** (diagnostic) : un Fichier
   `nakala_only_sans_local` sans `sha1_nakala`. Relancer
   `alembic upgrade head` pour rejouer le backfill.
3. **`DepotPublie`** (consent) : item `status=published`. Confirmer
   avec `--force-published` (DANGEREUX : casse les citations
   externes).
4. **`OrphelinsDetectes`** (consent) : sha1 distants sans pendant
   ColleC. Confirmer avec `--retirer-orphelins`.
5. **`PushImpossible`** (plan vide) : tous les fichiers seraient
   retirés. Nakala refuse un dépôt sans fichier (403 sur le dernier,
   H3) → refus en amont.
6. **`ContenuDuplique`** (pré-vol) : le set final contient deux sha1
   identiques. Nakala refuse les doublons de sha1 (422) → refus avant
   toute mutation, pour ne pas laisser un état partiel en push
   granulaire.

Sortie text liste les compteurs par catégorie + avertissements
critiques (fantôme, published). JSON expose le rapport complet
(`compare.{inchanges,modifies,…,orphelins_distants}` + `statut_distant`
+ `mod_date_distant`).

## 7. Publication

**Toutes les opérations de publication sont IRRÉVERSIBLES** : Nakala
mint un DOI DataCite définitif. Dry-run par défaut, double
confirmation requise (`--no-dry-run`).

### `publier`

Bascule un dépôt `pending → published`.

```bash
# Aperçu (recommandé avant de basculer)
archives-tool nakala publier PF-001 --fonds PF

# Réel — IRRÉVERSIBLE
archives-tool nakala publier PF-001 --fonds PF --no-dry-run
```

Le service émet un log `WARNING` `publication item IRREVERSIBLE START`
côté `nakala_depot.logger` (utile pour un agrégateur de logs en
prod).

### `publier-collection`

Boucle `publier` sur tous les items liés d'une collection. Items
sans `doi_nakala` → `non_lies` (rien fait), erreurs metiers →
`erreurs` (n'arrête pas le lot).

```bash
archives-tool nakala publier-collection PF-MIROIR --fonds PF \
    --no-dry-run
```

Symétrique de `pousser-collection` : la collection Nakala n'est pas
publiée explicitement (les collections n'ont pas de statut
`published` au sens DOI DataCite), seuls ses items le sont.

## Format JSON pour scripts

Toutes les commandes exposent `--format json` (passes 18-20). La
structure est stable et garde-foutée par tests de régression
systématiques. Exemple `pousser-fichiers` :

```json
{
  "cote_item": "PF-001",
  "doi": "10.34847/nkl.abc",
  "dry_run": false,
  "applique": true,
  "derive": false,
  "plan": [...],
  "sha1s_uploades": ["abc..."],
  "sha1s_retires": [],
  "compare": {
    "inchanges": [...],
    "modifies": [...],
    "nouveaux": [...],
    "nakala_only_sans_local": [...],
    "non_actifs_a_retirer": [...],
    "fichiers_fantomes": [],
    "orphelins_distants": [],
    "mod_date_distant": "2026-06-14T12:00:00",
    "statut_distant": "pending"
  }
}
```

Voir [Pour développeurs → Services]({{ repo_main }}/src/archives_tool/api/services/nakala_depot.py)
pour les dataclasses sous-jacentes.

## Codes de sortie

Conventions communes à toutes les commandes Nakala :

| Code | Sens                                                       |
| ---- | ---------------------------------------------------------- |
| `0`  | Succès (ou no-op idempotent).                              |
| `1`  | Erreur métier (item introuvable, garde-fou, erreur API).   |
| `2`  | Erreur de configuration (section `nakala:` absente, etc.). |

Pour un script bash en boucle : tester `$? -eq 0` après chaque
appel ; les autres codes signifient interruption manuelle requise.

## Observabilité

Tous les services Nakala émettent des logs structurés via
`archives_tool.api.services.nakala_depot.logger` et
`archives_tool.api.services.nakala_fichiers.logger` (passes 8 + 21) :

- `INFO` sur les events métiers : `START`, `OK`, `COMMIT`, `END`,
  compteurs.
- `WARNING` sur les conditions à risque : cleanup d'uploads orphelins,
  publications IRREVERSIBLES, dérive distant détectée.
- `DEBUG` opt-in pour le détail par fichier dans les boucles.

Pour activer en CLI :

```bash
export PYTHONLOGGING=INFO  # ou DEBUG pour tout
archives-tool nakala deposer PF-001 --fonds PF --no-dry-run
```

Aucun secret ni PII dans les logs (cote, DOI, compteurs, sha1
tronqués 12 chars). Sécuritaire pour Loki / Sentry / Datadog.

## Voir aussi

- [Concepts → Nakala comme première classe](../concepts.md) — pourquoi
  `Item.doi_nakala` et `Collection.doi_nakala` sont des colonnes
  dédiées (pas en `metadonnees`).
- [Reference → Formats d'export](../../reference/exports.md) —
  l'exporter CSV bulk de Nakala (complémentaire de `deposer`,
  workflow alternatif).
- [Pour développeurs → Backlog Nakala collection]({{ repo_main }}/docs/developpeurs/backlog-nakala-collection.md)
  — détails techniques internes (P1.5, P3+, etc.).
