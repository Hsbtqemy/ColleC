# Modèle de données (côté code)

Vue technique du modèle ORM. Pour les concepts métier
(Fonds/Collection/Item, multi-appartenance), voir
[Concepts](../guide/concepts.md). Pour le schéma SQLite complet,
voir [Schéma de données](../reference/schema.md).

## Tables principales

| Table                  | Rôle                                              |
| ---------------------- | ------------------------------------------------- |
| `fonds`                | Corpus matériel, point d'entrée du modèle.        |
| `collection`           | Regroupement publiable (miroir / libre rattachée / libre transversale). |
| `item`                 | Unité de matériel, granularité Nakala.            |
| `item_collection`      | Liaison N-N item ↔ collection (multi-appartenance). |
| `fichier`              | Scan ou dérivé d'un item.                         |
| `collaborateur_fonds`  | Personne associée à un fonds.                     |
| `modification_item`    | Journal des modifications d'item.                 |
| `operation_fichier`    | Journal des opérations sur fichiers (renommage, suppression, restore). |
| `preferences_affichage`| Préférences utilisateur (ordre des colonnes).     |

## Invariants exprimés en base

Quand SQLite le permet, les invariants sont exprimés au niveau
schéma :

- `fonds.cote` UNIQUE.
- `collection.cote` UNIQUE par `fonds_id` (NULL inclus pour les
  transversales — clé partielle).
- `item.cote` UNIQUE par `fonds_id`.
- `item.fonds_id` NOT NULL, FK avec `ON DELETE CASCADE` (la
  suppression d'un fonds emporte ses items).
- `collection.fonds_id` :
  - NOT NULL pour les miroirs (CHECK applicatif),
  - NULL autorisé pour les libres transversales,
  - `ON DELETE SET NULL` pour les libres rattachées (la
    suppression du fonds bascule la libre en transversale,
    cf. [invariant 9](../guide/concepts.md#invariants-du-modèle)).
- `item_collection` : PK composite `(item_id, collection_id)`.
- `fichier.item_id` NOT NULL, FK avec `ON DELETE CASCADE`.

## Invariants vérifiés en code

Certains invariants ne s'expriment pas en SQL et sont vérifiés
soit dans les services, soit dans les [contrôles qa](../reference/controles.md) :

- **INV1** : tout fonds a exactement une collection miroir
  (vérifié par `controler` ; garanti par le service `creer_fonds`
  qui crée la miroir automatiquement).
- **INV6** : tout item est dans la miroir de son fonds (peut
  être retiré manuellement, exception documentée — invariant 7
  des concepts).
- **Création atomique** : à la création d'un fonds, sa miroir
  est créée dans la même transaction. À la création d'un item,
  l'entrée `item_collection` vers la miroir est insérée dans la
  même transaction.

## Champs notables

### `Item`

| Champ              | Type        | Notes                                                  |
| ------------------ | ----------- | ------------------------------------------------------ |
| `cote`             | str         | Unique par fonds, pattern `^[A-Za-z0-9_-]+$`.          |
| `etat_catalogage`  | enum        | `brouillon`, `a_verifier`, `verifie`, `valide`, `a_corriger`. |
| `date`             | str (EDTF)  | Format brut, peut être incertain (`1969?`) ou range (`1969/1985`). |
| `annee`            | int \| None | Dérivée pour le tri ; pas toujours alignée avec `date`. |
| `langue`           | str         | Code ISO 639-3 (`fra`, `eng`, …).                      |
| `type_coar`        | str (URI)   | URI COAR, pas le label.                                |
| `metadonnees`      | JSON        | Dict libre pour champs custom, structure dépend du profil. |
| `doi_nakala`       | str \| None | DOI item-level (UNIQUE si renseigné).                  |
| `doi_collection_nakala` | str \| None | DOI collection-level pour ce dépôt.               |

### `Fichier`

| Champ              | Type        | Notes                                                  |
| ------------------ | ----------- | ------------------------------------------------------ |
| `racine`           | str \| None | Nom logique de la racine (`scans`, `miniatures`, …).   |
| `chemin_relatif`   | str \| None | Chemin POSIX/NFC dans la racine.                       |
| `iiif_url_nakala`  | str \| None | URL IIIF Nakala (alternative à racine + chemin).       |
| `apercu_chemin`    | str \| None | Chemin du dérivé aperçu (régénérable).                 |
| `vignette_chemin`  | str \| None | Chemin du dérivé vignette (régénérable).               |
| `derive_genere`    | bool        | Flag : dérivés à jour ? Invalidé après rename.         |
| `etat`             | enum        | `actif`, `corbeille`, `remplace`.                      |
| `version`          | int         | Incrémental pour traçabilité.                          |
| `hash_sha256`      | str \| None | SHA-256 du binaire (calculé à l'import en mode réel).  |

CHECK constraint : au moins une source doit exister
(`racine + chemin_relatif` OU `iiif_url_nakala`).

## Relations clés

```
Fonds (1) ──< (N) Item
Fonds (1) ──< (N) Collection
Collection (N) >──< (M) Item via ItemCollection
Item (1) ──< (N) Fichier
Fonds (1) ──< (N) CollaborateurFonds
```

Les relations sont chargées en *eager loading* (`selectinload`)
dans les composeurs de pages (`api/services/dashboard.py`) pour
éviter le N+1 sur les routes principales.

## Migrations

Alembic gère les migrations. Voir `alembic/versions/` pour
l'historique.

La V0.9.0 a entraîné une refonte complète du modèle (suppression
de `Collection.parent_id`, ajout de `Fonds`, ajout de
`item_collection`). Les bases V0.5/V0.6 ne sont pas
automatiquement migrables — voir [Limites](../annexes/limites.md).

## Voir aussi

- [Concepts](../guide/concepts.md) — vue côté utilisateur.
- [Schéma de données](../reference/schema.md) — vue détaillée
  des contraintes SQLite.
- [Services](services.md) — comment le modèle est manipulé en
  pratique.
