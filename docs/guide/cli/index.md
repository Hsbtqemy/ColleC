# CLI archives-tool

Vue d'ensemble des commandes CLI et conventions communes.

## Commandes disponibles

| Commande                        | Rôle                                                                  |
| ------------------------------- | --------------------------------------------------------------------- |
| [`importer`](importer.md)       | Importer un fonds depuis un profil YAML.                              |
| [`collections`](collections.md) | Gérer les collections libres.                                         |
| [`exporter`](exporter.md)       | Exporter une collection (Dublin Core, Nakala, xlsx).                  |
| [`controler`](controler.md)     | Vérifier la cohérence d'une base.                                     |
| [`montrer`](montrer.md)         | Consulter fonds, collections, items, fichiers.                        |
| [`renommer`](renommer.md)       | Renommer transactionnellement les fichiers.                           |
| [`deriver`](deriver.md)         | Générer ou nettoyer les dérivés (vignettes, aperçus).                 |

D'autres sous-commandes (non détaillées dans cette section) :

- `archives-tool demo init` — peuple une base de démonstration.
- `archives-tool profil {init,analyser}` — assistants de création
  de profils d'import (référence : [Profils](../../reference/profils.md)).

L'aide complète est toujours disponible via `--help` :

```bash
archives-tool --help
archives-tool exporter --help
archives-tool exporter dublin-core --help
```

## Conventions de périmètre

La plupart des commandes destructives ou opérant en masse
(`controler`, `renommer`, `deriver`) acceptent un périmètre via
quatre sélecteurs **mutuellement exclusifs** :

- `--fonds COTE` : opère sur un fonds entier ;
- `--collection COTE` : opère sur une collection (et ses items) ;
- `--item COTE` : opère sur un item unique ;
- `--fichier-id ID [...]` : opère sur des fichiers spécifiques
  (option répétable).

Exactement un de ces sélecteurs doit être fourni. La validation
est faite à la construction du `Perimetre` (dataclass partagée),
qui retourne un message d'erreur explicite et l'exit code `2` si
la combinaison est invalide.

`exporter` est un cas légèrement à part : il prend une cote de
**collection** en argument positionnel (pas en `--collection`),
puisque l'unité d'export est toujours la collection.

## Désambiguïsation

Les cotes ne sont uniques que dans certains contextes (cf.
[Concepts → Cote](../concepts.md#cote)) :

| Entité     | Unicité       |
| ---------- | ------------- |
| Fonds      | Globale.      |
| Collection | Par fonds.    |
| Item       | Par fonds.    |

Pour désambiguïser une cote partagée :

- `--item COTE` : ajouter `--fonds COTE_FONDS` (fortement
  recommandé même quand non strictement requis) ;
- `--collection COTE` : ajouter `--fonds COTE_FONDS` quand la cote
  est ambiguë ; sinon, optionnel ;
- `--fonds COTE` (seul) : pas de désambiguïsation nécessaire (la
  cote de fonds est globalement unique).

## Codes de sortie

Convention commune à toutes les commandes :

| Code | Sens                                                              |
| ---- | ----------------------------------------------------------------- |
| `0`  | Succès.                                                           |
| `1`  | Erreur métier (entité introuvable, conflit, échec d'opération).   |
| `2`  | Erreur de saisie (option manquante, mutex violé, base absente).   |

Cas particuliers :

- `controler --strict` peut sortir `1` même quand seul un
  *avertissement* remonte (voir [controler](controler.md)).
- `importer` en mode réel sort `1` si la transaction est rollback
  par une erreur sur une seule ligne.

## Format de sortie

Plusieurs commandes acceptent `--format text|json` :

- `text` : sortie [Rich](https://rich.readthedocs.io/) avec couleurs
  (par défaut). Lisible humain, non-stable entre versions.
- `json` : sortie structurée, **stable** entre versions mineures
  (toute évolution incompatible bumpera le champ `version_qa` ou
  équivalent). Prévue pour intégration CI / automatisation.

Les commandes qui supportent `--format` aujourd'hui :
[`controler`](controler.md), [`montrer`](montrer.md).

## Configuration

Toutes les commandes lisent `config_local.yaml` à la racine du
projet par défaut. Pour utiliser un autre fichier :

```bash
archives-tool importer --config /chemin/vers/config.yaml ...
```

La base de données par défaut est `data/archives.db`. Pour en
utiliser une autre :

```bash
archives-tool montrer fonds --db-path /chemin/vers/base.db
```

Voir [Configuration](../../premiers-pas/configuration.md) pour le
détail des deux niveaux (config locale par poste vs config
partagée).

## Dry-run

Les commandes destructives offrent un **dry-run par défaut** :

- [`importer`](importer.md) — `--dry-run` actif par défaut, basculer
  avec `--no-dry-run` pour exécuter.
- [`renommer appliquer`](renommer.md) — idem.
- [`renommer annuler`](renommer.md) — idem.

[`deriver appliquer`](deriver.md) et [`deriver nettoyer`](deriver.md)
sont l'exception : par défaut elles agissent. Utiliser `--dry-run`
explicitement pour ne pas écrire.

Convention : tant que vous n'êtes pas certain·e du résultat,
laisser le dry-run actif et lire le rapport avant de basculer.
