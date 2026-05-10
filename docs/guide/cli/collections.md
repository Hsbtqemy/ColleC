# archives-tool collections

Gestion des collections libres en ligne de commande — pendant CLI
de la section *Collections* de l'interface web.

## Sous-commandes

| Sous-commande            | Rôle                                                                       |
| ------------------------ | -------------------------------------------------------------------------- |
| `creer-libre`            | Créer une collection libre (rattachée à un fonds ou transversale).         |
| `lister`                 | Lister les collections, optionnellement filtrées.                          |
| `supprimer`              | Supprimer une collection libre (refuse les miroirs).                       |

Les **collections miroirs** ne sont pas gérées par cette commande :
elles sont créées et supprimées en cascade avec leur fonds parent
(cf. [Concepts → Collection miroir](../concepts.md#collection-miroir)).

## creer-libre

Crée une collection libre :

- *rattachée* à un fonds existant si `--fonds` est passé ;
- *transversale* (sans fonds) si `--fonds` est omis.

```bash
archives-tool collections creer-libre COTE TITRE [OPTIONS]
```

### Arguments

| Argument | Sens                                  |
| -------- | ------------------------------------- |
| `COTE`   | Cote de la nouvelle collection.       |
| `TITRE`  | Titre de la nouvelle collection.      |

### Options

| Option                   | Défaut       | Sens                                                            |
| ------------------------ | ------------ | --------------------------------------------------------------- |
| `--fonds COTE`, `-f`     | aucun        | Rattacher à ce fonds. Omettre pour une transversale.            |
| `--description TEXTE`, `-d` | `""`       | Description courte (libre).                                     |
| `--description-publique TEXTE` | `""`   | Description publique (utilisée par les exports DC / Nakala).    |
| `--phase PHASE`          | `catalogage` | Phase de chantier (`numerisation`, `catalogage`, `valide`, …).  |
| `--db-path PATH`         | `data/archives.db` | Chemin de la base SQLite.                                 |

### Exemples

Collection libre rattachée à un fonds :

```bash
archives-tool collections creer-libre HK-FAVORIS "Hara-Kiri — Sélection éditoriale" \
    --fonds HK \
    --description-publique "Numéros marquants de la revue, sélectionnés par l'équipe."
```

Collection transversale (multi-fonds) :

```bash
archives-tool collections creer-libre TEMOIG "Témoignages d'exil" \
    --description-publique "Documents issus de plusieurs fonds illustrant l'exil."
```

Une fois créée, on remplit la collection en y ajoutant des items
depuis l'[interface web](../interface-web.md) (page Collection,
bouton « Ajouter des items »).

Si la cote est déjà prise par une autre collection du même fonds
(ou par une transversale, pour une transversale), la commande
sort en code 1 avec un message d'erreur explicite.

## lister

Liste les collections existantes, optionnellement filtrées par
fonds ou par type.

```bash
archives-tool collections lister [OPTIONS]
```

### Options

| Option                | Défaut             | Sens                                                                |
| --------------------- | ------------------ | ------------------------------------------------------------------- |
| `--fonds COTE`, `-f`  | aucun              | N'afficher que les collections du fonds COTE.                       |
| `--transversales`, `-t` | `False`          | N'afficher que les collections transversales (sans fonds parent).   |
| `--db-path PATH`      | `data/archives.db` | Chemin de la base SQLite.                                           |

`--fonds` et `--transversales` sont mutuellement informatifs
(`--transversales` l'emporte si les deux sont passés).

### Exemples

Toutes les collections de la base :

```bash
archives-tool collections lister
```

Collections d'un fonds donné (miroir + libres rattachées) :

```bash
archives-tool collections lister --fonds HK
```

Collections transversales uniquement :

```bash
archives-tool collections lister --transversales
```

Sortie texte une ligne par collection : cote, titre tronqué, type
(`[miroir]` ou `[libre]`), rattachement (cote du fonds parent ou
`— transversale`).

## supprimer

Supprime une collection libre. Refuse les miroirs avec un message
explicite — celles-ci ne se suppriment qu'avec leur fonds.

```bash
archives-tool collections supprimer COTE [OPTIONS]
```

### Arguments

| Argument | Sens                              |
| -------- | --------------------------------- |
| `COTE`   | Cote de la collection à supprimer. |

### Options

| Option              | Défaut             | Sens                                                                                    |
| ------------------- | ------------------ | --------------------------------------------------------------------------------------- |
| `--fonds COTE`, `-f` | aucun             | Cote du fonds parent (pour désambiguïser quand la cote est partagée entre fonds).       |
| `--yes`, `-y`       | `False`            | Sauter la confirmation interactive.                                                     |
| `--db-path PATH`    | `data/archives.db` | Chemin de la base SQLite.                                                               |

Par défaut, la commande demande une confirmation interactive
avant de supprimer.

### Exemples

Supprimer une libre rattachée :

```bash
archives-tool collections supprimer HK-FAVORIS --fonds HK
```

Supprimer une transversale, sans confirmation :

```bash
archives-tool collections supprimer TEMOIG --yes
```

### Effets de la suppression

- La collection est retirée de la base.
- Les **items ne sont pas supprimés** : ils restent dans leur
  fonds (et dans la miroir de ce fonds) ; ils perdent juste leur
  appartenance à la collection supprimée (entrée
  `ItemCollection` correspondante effacée).
- L'opération **n'est pas journalée** dans `OperationFichier` car
  elle ne touche pas au disque. Cela peut évoluer (V0.10+).

## Codes de sortie

Convention commune (cf. [Conventions CLI](index.md#codes-de-sortie)) :

| Code | Sens                                                                 |
| ---- | -------------------------------------------------------------------- |
| `0`  | Succès.                                                              |
| `1`  | Erreur métier (cote inconnue, miroir, ambiguïté, formulaire invalide). |
| `2`  | Erreur de saisie (base introuvable).                                 |

## Voir aussi

- [Concepts du modèle](../concepts.md) — distinction miroir /
  libre rattachée / transversale.
- [Profils d'import](../../reference/profils.md) — création
  initiale d'un fonds + miroir via un profil YAML.
- [Interface web](../interface-web.md) — gestion graphique des
  collections (création, ajout/retrait d'items, édition).
