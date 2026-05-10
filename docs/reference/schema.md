# Modèle de données

Document de référence du schéma de la base SQLite. À tenir à jour avec
le code (`src/archives_tool/models/`).

---

## Vue d'ensemble

Le modèle s'organise autour de trois entités principales — **Collection**,
**Item**, **Fichier** — et de tables périphériques pour la configuration,
la traçabilité et les intégrations externes.

```
┌────────────────┐
│   Collection   │  une revue, un fonds
└────────┬───────┘
         │ 1..n
┌────────▼───────┐     ┌──────────────────┐
│      Item      │────▶│ ModificationItem │  journal des édits
└────────┬───────┘     └──────────────────┘
         │ 1..n
┌────────▼───────┐     ┌──────────────────┐
│    Fichier     │────▶│ OperationFichier │  journal des opérations
└────────────────┘     └──────────────────┘
         │
         ▼
   (racine logique + chemin relatif)

┌─────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ ProfilImport    │   │ ChampPersonnalise│   │ ValeurControlee  │
└─────────────────┘   └──────────────────┘   └──────────────────┘

┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  SourceExterne   │───▶│ RessourceExterne │───▶│ LienExterneItem  │  (V2+)
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

---

## Principes structurants

### 1. Hybridation colonnes dédiées / JSON

Les champs **structurants et récurrents** (titre, cote, date, type COAR,
état) sont des **colonnes dédiées** pour permettre indexation, recherche
performante, contraintes.

Les champs **étendus et variables par collection** sont stockés dans un
champ `metadonnees` de type JSON. Cela accueille la variabilité des
conventions de catalogage sans multiplier les migrations.

Règle : si un champ est interrogé régulièrement ou soumis à contrainte,
il devient colonne. Sinon, il reste dans le JSON.

### 2. Chemins en deux parties

Jamais de chemin absolu en base. Toujours **(racine_logique, chemin_relatif)** :

- `racine` : nom symbolique (`scans_revues`, `miniatures`) résolu par la
  config locale de chaque utilisateur.
- `chemin_relatif` : chemin à partir de la racine, en séparateurs POSIX
  (`/`) même sous Windows, normalisé en Unicode NFC.

Résolution du chemin absolu au moment de l'accès uniquement.

### 3. Traçabilité systématique

Toutes les entités éditables portent :
- `cree_le`, `cree_par`
- `modifie_le`, `modifie_par`
- `version` (entier, incrémenté à chaque modification, utilisé pour
  verrou optimiste)

### 4. États explicites plutôt que booléens

Les workflows métier (catalogage, validation, suppression) utilisent
des **enums d'état** et non des booléens. Permet d'affiner sans
migration.

### 5. Suppression logique par défaut

Pas de `DELETE` physique sur les entités métier. Un champ `etat` permet
la corbeille logique. Purge explicite séparée, journalisée.

---

## Enums

Définis côté Python avec `enum.StrEnum`, stockés en TEXT en base.

### `EtatCatalogage`

Progression du catalogage d'un item.

| Valeur | Description |
|---|---|
| `brouillon` | Saisie incomplète, travail en cours. |
| `a_verifier` | Saisie terminée, en attente de contrôle. |
| `verifie` | Contrôlé, prêt pour validation finale. |
| `valide` | Notice définitive. |
| `a_corriger` | Anomalie détectée, retour au catalogueur. |

### `EtatFichier`

| Valeur | Description |
|---|---|
| `actif` | Fichier courant, utilisé. |
| `remplace` | Remplacé par une version plus récente, conservé pour historique. |
| `corbeille` | Supprimé logiquement, restaurable. |

### `PhaseChantier`

Phase courante d'un chantier de catalogage. Pilote l'affichage et
permettra des filtres « collections en cours » plus tard.

| Valeur | Description |
|---|---|
| `numerisation` | Scans en cours de production. |
| `catalogage` | Saisie initiale des notices. |
| `revision` | Relecture, vérifications croisées. |
| `finalisation` | Validation finale, préparation export. |
| `archivee` | Chantier clos, plus de modifications attendues. |
| `en_pause` | Travail suspendu, à reprendre plus tard. |

### `TypePage`

Typologie métier des scans.

| Valeur | Description |
|---|---|
| `couverture` | Première de couverture. |
| `dos_couverture` | Verso de couverture. |
| `page_titre` | Page de titre. |
| `page` | Page courante (cas général). |
| `planche` | Planche hors-texte, illustration. |
| `supplement` | Encart, supplément. |
| `quatrieme` | Quatrième de couverture. |
| `autre` | Hors nomenclature (rare, préciser en notes). |

### `TypeOperationFichier`

| Valeur |
|---|
| `rename` |
| `move` |
| `delete` |
| `restore` |
| `replace` |

### `StatutOperation`

| Valeur |
|---|
| `simulee` | Aperçu calculé, pas exécuté. |
| `reussie` |
| `echouee` |
| `annulee` | Revenue à l'état antérieur. |

### `RoleCollaborateur`

Vocabulaire fermé des rôles techniques d'un collaborateur de
collection. Toute extension demande une migration (l'enum est validée
applicativement contre cette liste).

| Valeur | Libellé |
|---|---|
| `numerisation` | Numérisation |
| `transcription` | Transcription |
| `indexation` | Indexation |
| `catalogage` | Catalogage |

### `TypeCollection`

Distingue les deux espèces de collections (V0.9.0-alpha).

| Valeur | Description |
|---|---|
| `miroir` | Collection créée automatiquement avec un fonds, regroupe par défaut tous ses items. Toujours rattachée à un fonds (CHECK constraint). |
| `libre` | Collection créée manuellement. Rattachée à un fonds (`fonds_id` non NULL) ou transversale (`fonds_id IS NULL`). |

---

## Tables

### Identité

Il n'y a pas de table `utilisateur`. Chaque poste est configuré avec
un nom libre dans la config locale (`utilisateur: "Marie"`). Ce nom
est copié tel quel dans les champs d'audit des tables (`cree_par`,
`modifie_par`, `ajoute_par`, `execute_par`). Aucune FK, aucune
contrainte d'unicité : l'information est uniquement informative.

---

### `fonds` (V0.9.0-alpha)

Le **corpus brut** : matériel issu d'une source identifiée (un don,
un fonds éditorial, une numérisation), interne à l'outil. Nakala ne
connaît pas cette notion. Chaque fonds porte exactement une
**collection miroir** créée automatiquement à sa création.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `cote` | VARCHAR(64) | UNIQUE, NOT NULL | Ex. `HK`, `FA`, `CONC-1789`. |
| `titre` | VARCHAR(500) | NOT NULL | |
| `description` | TEXT | | Description courte (interne ou publique selon usage). |
| `description_publique` | TEXT | | Réservée à l'export Nakala. |
| `description_interne` | TEXT | | Notes équipe, conventions de chantier. |
| `personnalite_associee` | VARCHAR(255) | | Personne/mouvement/institution autour de qui s'organise le fonds. |
| `responsable_archives` | VARCHAR(255) | | Personne ou institution responsable de la constitution. |
| `editeur` | VARCHAR(255) | | Champs périodique : présents si le fonds ressemble à une revue. |
| `lieu_edition` | VARCHAR(255) | | |
| `periodicite` | VARCHAR(64) | | |
| `issn` | VARCHAR(32) | | |
| `date_debut` | VARCHAR(64) | | EDTF tolérant. |
| `date_fin` | VARCHAR(64) | | |
| `cree_le` / `cree_par` / `modifie_le` / `modifie_par` / `version` | TracabiliteMixin | | |

**Index :** `cote`, `titre`.

**Cascade :** supprimer un fonds supprime ses items et sa collection
miroir ; les collections libres rattachées passent à transversales
(`fonds_id = NULL` via FK `ON DELETE SET NULL`).

---

### `collection` (refondue V0.9.0-alpha)

Un **classement publiable** : sélection d'items pour une présentation,
un thème, un export Nakala. Distingué du fonds par
`type_collection`.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `cote` | VARCHAR(64) | NOT NULL | **Plus globalement unique** ; unique par fonds via `(fonds_id, cote)`. |
| `titre` | VARCHAR(500) | NOT NULL | |
| `type_collection` | VARCHAR(20) | NOT NULL, DEFAULT `libre` | `miroir` ou `libre` (cf. `TypeCollection`). |
| `fonds_id` | INTEGER | FK → `fonds.id` ON DELETE SET NULL | NULL pour une collection libre transversale. |
| `phase` | VARCHAR(20) | NOT NULL, DEFAULT `catalogage` | |
| `description` / `description_publique` / `description_interne` | TEXT | | |
| `personnalite_associee` / `responsable_archives` | VARCHAR(255) | | |
| `editeur` / `lieu_edition` / `periodicite` / `issn` | varchars | | Champs périodique conservés (si la collection ressemble à une revue, par exemple une miroir d'un fonds-revue). |
| `date_debut` / `date_fin` | VARCHAR(50) | | |
| `doi_nakala` | TEXT | UNIQUE | DOI de la collection sur Nakala. |
| `doi_collection_nakala_parent` | VARCHAR(128) | | Rattachement à une collection Nakala parente (sans contrainte d'unicité). |
| `metadonnees` / `notes_internes` | JSON / TEXT | | |
| `profil_import_id` | INTEGER | FK → `profil_import.id` | |
| `cree_le` / `cree_par` / `modifie_le` / `modifie_par` / `version` | TracabiliteMixin | | |

**Index :**
- `(fonds_id, cote)` UNIQUE : cote unique par fonds.
- `cote`, `titre`, `fonds_id`, `doi_nakala`.

**CHECK constraint :** `(type_collection = 'libre') OR (fonds_id IS NOT NULL)` —
une miroir doit toujours pointer vers son fonds.

#### Invariants

1. Tout fonds a exactement une collection MIROIR (création au service `fonds`).
2. Une collection MIROIR a toujours `fonds_id` non NULL (CHECK).
3. Une collection LIBRE peut être rattachée (`fonds_id` non NULL) ou transversale (`fonds_id IS NULL`).
4. Tout item a `fonds_id` non NULL.
5. À la création d'un Fonds : la miroir est créée avec la même cote et le même titre.
6. À l'ajout d'un Item dans un fonds : il est ajouté à la miroir (à charger côté service `items` — V0.9.0-alpha.1).
7. Un item peut être retiré manuellement de sa miroir sans être supprimé du fonds.
8. Suppression d'un Fonds : items + miroir supprimés, libres rattachées passent transversales.
9. Une cote de fonds peut coïncider avec la cote d'une collection libre (cas de la miroir).

---

### `item` (refondu V0.9.0-alpha)

L'unité principale de catalogage : un numéro, un volume, un document.
Appartient à exactement un fonds (FK obligatoire) et peut figurer
dans 0..N collections via la junction `item_collection`.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `fonds_id` | INTEGER | FK → `fonds.id` ON DELETE CASCADE, NOT NULL | Le matériel d'origine. |
| `cote` | VARCHAR(128) | NOT NULL | Unique par fonds via `(fonds_id, cote)`. Plus globalement unique. |
| `numero` | TEXT | | Peut être `47`, `47-48`, `iv`, etc. |
| `numero_tri` | INTEGER | | Pour tri numérique fiable |
| `titre` | TEXT | | Titre propre du numéro si pertinent |
| `date` | TEXT | | Format EDTF |
| `annee` | INTEGER | | Pour filtre/tri rapide |
| `type_coar` | TEXT | | URI COAR, ex. `http://purl.org/coar/resource_type/c_2fe3` |
| `langue` | TEXT | | ISO 639-3 |
| `doi_nakala` | TEXT | UNIQUE | DOI Nakala de l'item. Unique : un DOI ne référence qu'un seul item local. |
| `doi_collection_nakala` | TEXT | | DOI de la collection Nakala de rattachement. Non-unique : plusieurs items partagent la même collection Nakala. |
| `description` | TEXT | | Résumé, sommaire |
| `metadonnees` | JSON | | Champs étendus (auteurs multiples, sujets, relations...) |
| `etat_catalogage` | TEXT | NOT NULL, DEFAULT `brouillon` | Enum |
| `notes_internes` | TEXT | | |
| `cree_le` | DATETIME | NOT NULL | |
| `cree_par` | TEXT | | Nom libre copié de la config locale. |
| `modifie_le` | DATETIME | | |
| `modifie_par` | TEXT | | Idem. |
| `version` | INTEGER | NOT NULL, DEFAULT 1 | |

**Contraintes :**
- UNIQUE (`fonds_id`, `cote`)
- UNIQUE (`doi_nakala`)
- CHECK sur `etat_catalogage` (valeurs enum)

**Index :** `fonds_id`, `annee`, `etat_catalogage`, `doi_nakala`,
`doi_collection_nakala`. (FTS5 prévu mais à reconstruire en
V0.9.0-gamma sur la nouvelle forme.)

#### `item_collection` (V0.9.0-alpha)

Liaison N-N entre `item` et `collection`. Un item est typiquement
dans la miroir de son fonds et, optionnellement, dans des collections
libres (rattachées au même fonds ou transversales).

| Colonne | Type | Contraintes |
|---|---|---|
| `item_id` | INTEGER | PK, FK → `item.id` ON DELETE CASCADE |
| `collection_id` | INTEGER | PK, FK → `collection.id` ON DELETE CASCADE |
| `ajoute_le` | DATETIME | NOT NULL, server_default=now() |
| `ajoute_par` | VARCHAR(255) | |

**Note sur `metadonnees` JSON :** structure recommandée :
```json
{
  "auteurs": [
    {"nom": "Dupont", "prenom": "Jean", "orcid": "0000-..."}
  ],
  "sujets": ["Histoire", "XIXe siècle"],
  "relations": [
    {"type": "partie_de", "ref": "item:42"},
    {"type": "supplement_de", "ref": "nakala:10.34847/nkl.xxx"}
  ],
  "champs_collection": {
    "rubrique": "Littérature",
    "illustrateurs": ["..."]
  }
}
```

---

### `fichier`

Un scan ou document rattaché à un item.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `item_id` | INTEGER | FK → `item.id`, NOT NULL | |
| `racine` | TEXT | | Nom logique de la racine. NULL si fichier exclusivement référencé via `iiif_url_nakala`. |
| `chemin_relatif` | TEXT | | POSIX, NFC. NULL si fichier exclusivement Nakala. |
| `nom_fichier` | TEXT | NOT NULL | Pour recherche rapide |
| `apercu_chemin` | TEXT | | Chemin relatif sous la racine `miniatures` du JPEG aperçu (1200 px). Rempli par `derivatives`. |
| `vignette_chemin` | TEXT | | Chemin relatif sous la racine `miniatures` du JPEG vignette (300 px). Rempli par `derivatives`. |
| `dzi_chemin` | TEXT | | Réservé V2+ : chemin du DZI local (tuiles). Jamais rempli en V0.6. |
| `iiif_url_nakala` | TEXT | | URL info.json IIIF du fichier déposé sur Nakala. Source primaire pour la visionneuse quand renseigné. |
| `hash_sha256` | TEXT | | Calculé à l'import, vérifié périodiquement |
| `taille_octets` | INTEGER | | |
| `format` | TEXT | | `tiff`, `jpeg`, `pdf`... |
| `largeur_px` | INTEGER | | Pour images |
| `hauteur_px` | INTEGER | | Pour images |
| `ordre` | INTEGER | NOT NULL | Position dans l'item |
| `type_page` | TEXT | NOT NULL, DEFAULT `page` | Enum |
| `folio` | TEXT | | Numérotation logique (« iv », « 12bis ») |
| `etat` | TEXT | NOT NULL, DEFAULT `actif` | Enum |
| `derive_genere` | BOOLEAN | NOT NULL, DEFAULT 0 | Vignette/aperçu générés ? |
| `notes_techniques` | TEXT | | |
| `ajoute_le` | DATETIME | NOT NULL | |
| `ajoute_par` | TEXT | | Nom libre copié de la config locale. |
| `modifie_le` | DATETIME | | |
| `version` | INTEGER | NOT NULL, DEFAULT 1 | |

**Contraintes :**
- UNIQUE (`racine`, `chemin_relatif`) — un fichier n'existe qu'une fois.
- UNIQUE (`item_id`, `ordre`) — pas de collision d'ordre dans un item.
- CHECK `chemin_relatif IS NOT NULL OR iiif_url_nakala IS NOT NULL` —
  un fichier doit avoir au moins une source (locale ou IIIF).

**Index :** `item_id`, `hash_sha256`, `nom_fichier`, `etat`.

---

### `profil_import`

Décrit comment importer les métadonnées et fichiers d'une collection.

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `nom` | TEXT | UNIQUE, NOT NULL |
| `description` | TEXT | |
| `chemin_yaml` | TEXT | NOT NULL — chemin relatif vers `profiles/xxx.yaml` |
| `contenu` | JSON | Copie du YAML parsé, snapshot |
| `cree_le` | DATETIME | NOT NULL |
| `modifie_le` | DATETIME | |

Le YAML source reste dans `profiles/` (versionné Git). La base stocke
un snapshot pour retracer ce qui a été appliqué lors d'un import.

---

### `champ_personnalise`

Définit les champs étendus utilisables par une collection.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `collection_id` | INTEGER | FK → `collection.id` | NULL = champ global |
| `cle` | TEXT | NOT NULL | Clé JSON, ex. `illustrateur` |
| `libelle` | TEXT | NOT NULL | Affichage UI |
| `type` | TEXT | NOT NULL | `texte`, `texte_long`, `date_edtf`, `liste`, `liste_multiple`, `reference` |
| `obligatoire` | BOOLEAN | NOT NULL, DEFAULT 0 | |
| `valeurs_controlees_id` | INTEGER | FK → `vocabulaire.id` | Pour listes |
| `ordre` | INTEGER | NOT NULL | Ordre d'affichage |
| `aide` | TEXT | | Infobulle |
| `description_interne` | TEXT | | Documentation longue pour l'équipe : pourquoi ce champ, comment le remplir. |

**Contraintes :** UNIQUE (`collection_id`, `cle`).

---

### `vocabulaire` et `valeur_controlee`

Pour les listes contrôlées (types COAR, langues, vocabulaires
métier).

**`vocabulaire`** :

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `code` | TEXT | UNIQUE, NOT NULL — ex. `coar_resource_types` |
| `libelle` | TEXT | NOT NULL |
| `description` | TEXT | Description publique du vocabulaire. |
| `description_interne` | TEXT | Documentation équipe (conventions, périmètre). |
| `uri_base` | TEXT | |

**`valeur_controlee`** :

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `vocabulaire_id` | INTEGER | FK, NOT NULL |
| `code` | TEXT | NOT NULL |
| `libelle` | TEXT | NOT NULL |
| `uri` | TEXT | |
| `description_interne` | TEXT | Documentation équipe sur la valeur. |
| `parent_id` | INTEGER | FK → `valeur_controlee.id` — pour hiérarchies |
| `ordre` | INTEGER | |
| `actif` | BOOLEAN | NOT NULL, DEFAULT 1 |

**Contrainte :** UNIQUE (`vocabulaire_id`, `code`).

---

### `operation_fichier`

Journal des opérations sur fichiers (renommage, déplacement, suppression).

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `batch_id` | TEXT | NOT NULL | UUID regroupant un lot |
| `fichier_id` | INTEGER | FK → `fichier.id` | NULL si fichier détruit |
| `type_operation` | TEXT | NOT NULL | Enum |
| `racine_avant` | TEXT | | |
| `chemin_avant` | TEXT | | |
| `racine_apres` | TEXT | | |
| `chemin_apres` | TEXT | | |
| `hash_avant` | TEXT | | Vérification intégrité |
| `hash_apres` | TEXT | | |
| `statut` | TEXT | NOT NULL | Enum |
| `message` | TEXT | | Erreur ou info |
| `execute_le` | DATETIME | NOT NULL | |
| `execute_par` | TEXT | | Nom libre copié de la config locale. |
| `annule_par_batch_id` | TEXT | | Batch qui a annulé |

**Index :** `batch_id`, `fichier_id`, `execute_le`.

---

### `modification_item`

Journal des modifications de métadonnées sur les items.

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `item_id` | INTEGER | FK → `item.id`, NOT NULL |
| `champ` | TEXT | NOT NULL — nom de colonne ou clé JSON |
| `valeur_avant` | TEXT | JSON sérialisé si complexe |
| `valeur_apres` | TEXT | |
| `modifie_le` | DATETIME | NOT NULL |
| `modifie_par` | TEXT | | Nom libre copié de la config locale. |

**Index :** `item_id`, `modifie_le`.

---

### `operation_import`

Journal des imports depuis un profil YAML. Une entrée par exécution
réelle (pas en dry-run). Le `rapport_json` contient la sérialisation
complète du `RapportImport` pour inspection future.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `batch_id` | TEXT | NOT NULL, UNIQUE | UUID du lot. Lié aux `operation_fichier` éventuellement produites pendant l'import. |
| `profil_chemin` | TEXT | NOT NULL | Chemin du profil YAML utilisé. |
| `collection_id` | INTEGER | FK → `collection.id` | |
| `items_crees` | INTEGER | | |
| `items_mis_a_jour` | INTEGER | | |
| `items_inchanges` | INTEGER | | |
| `fichiers_ajoutes` | INTEGER | | |
| `execute_le` | DATETIME | NOT NULL | |
| `execute_par` | TEXT | | Nom libre copié de la config locale. |
| `rapport_json` | TEXT | | Sérialisation JSON du `RapportImport`. |

**Contrainte :** UNIQUE (`batch_id`).
**Index :** `batch_id`.

---

### `preferences_affichage`

Persiste l'ordre des colonnes choisi par un utilisateur dans une vue
tabulaire (items, fichiers, sous-collections). Une entrée par
combinaison (utilisateur, collection, vue). Pas d'utilisation
effective avant V0.6 ; structure créée pour ne pas avoir à reprendre
la migration plus tard.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `utilisateur` | TEXT | NOT NULL | Nom libre copié de la config locale. |
| `collection_id` | INTEGER | FK → `collection.id` (CASCADE) | NULL = préférences globales (vue dashboard, toutes collections). |
| `vue` | TEXT | NOT NULL | `items`, `fichiers`, `sous_collections`, etc. |
| `colonnes_ordonnees` | JSON | NOT NULL | Liste de noms de colonnes dans l'ordre voulu. |
| `cree_le` | DATETIME | NOT NULL | |
| `modifie_le` | DATETIME | | |

**Contrainte :** UNIQUE (`utilisateur`, `collection_id`, `vue`).
**Index :** `utilisateur`, `collection_id`.

---

### `collaborateur_collection`

Personnes ayant contribué techniquement à la constitution d'une
collection (numérisation, transcription, indexation, catalogage).
Pas de FK utilisateur — le nom est texte libre, identique au modèle
d'audit `cree_par` / `modifie_par`. Une personne peut porter
plusieurs rôles ; le stockage se fait en JSON.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `collection_id` | INTEGER | FK → `collection.id` (CASCADE) | Indexé. |
| `nom` | VARCHAR(255) | NOT NULL | Texte libre. |
| `roles` | JSON | NOT NULL | Liste de valeurs `RoleCollaborateur` (chaînes). Au moins un rôle, validation applicative. |
| `periode` | VARCHAR(64) | NULL | EDTF tolérant (« 2022 », « 2022-2023 »). |
| `notes` | TEXT | NULL | Texte libre. |
| `cree_le` | DATETIME | NOT NULL | |
| `modifie_le` | DATETIME | NOT NULL | Mise à jour automatique. |

**Index :** `collection_id`.

Les filtres SQL natifs sur les rôles ne sont pas possibles avec le
stockage JSON ; c'est accepté pour V0.8.0 — pas de besoin de
recherche transverse pour l'instant.

### `collaborateur_fonds` (V0.9.0-alpha)

Analogue de `collaborateur_collection` mais rattaché au fonds. C'est
l'usage **par défaut** pour les contributeurs d'un corpus ; les
collaborateurs propres à une collection particulière restent dans
`collaborateur_collection`.

Mêmes colonnes que `collaborateur_collection` (nom, roles JSON,
periode, notes, cree_le, modifie_le) avec FK `fonds_id` → `fonds.id`
ON DELETE CASCADE. Index sur `fonds_id`.

---

## Services CRUD (V0.9.0-alpha.1)

Les services Python applicatifs garantissent les invariants
au-dessus du schéma SQL. Trois services principaux :

### `services/fonds.py`

- `creer_fonds(formulaire)` → crée le fonds + sa miroir dans la
  même transaction (invariants 1, 5).
- `lire_fonds` / `lire_fonds_par_cote` / `lister_fonds` (compteurs
  agrégés en 3 queries, pas de N+1).
- `modifier_fonds`, `supprimer_fonds` (cascade items + miroir,
  libres rattachées passent transversales via `ON DELETE SET NULL`).

### `services/collections.py`

Gère **uniquement les collections libres**. Les miroirs sont créées
et supprimées par `services/fonds.py`.

- `creer_collection_libre(formulaire)` → vérifie le fonds_id si
  fourni, IntegrityError sur conflit `(fonds_id, cote)`.
- `lire_collection`, `lire_collection_par_cote(cote, fonds_id=None)`
  (lève `OperationCollectionInterdite` si plusieurs matches sans fonds).
- `lister_collections(fonds_id=None, type_collection=None)`.
- `modifier_collection` : refuse de changer `fonds_id` d'une miroir.
- `supprimer_collection_libre` : refuse les miroirs.
- `ajouter_item_a_collection`, `retirer_item_de_collection` :
  idempotents, valident l'existence des entités.

### `services/items.py`

- `creer_item(formulaire)` → ajoute automatiquement à la miroir
  du fonds (invariant 6) ; lève si miroir absente (anomalie).
- `lire_item`, `lire_item_par_cote(cote, fonds_id)` (fonds_id
  obligatoire, cote n'étant pas globalement unique).
- `collections_de_item` : requête SQL fraîche via la junction
  (la relation ORM `Item.collections` peut être obsolète après
  écritures directes).
- `lister_items_fonds`, `lister_items_collection` :
  pagination + tri whitelisté + filtre etat_catalogage, retournent
  `Listage[ItemResume]` (réutilise `services/tri.py`).
- `modifier_item` : `fonds_id` est immuable (`OperationItemInterdite`
  si changement).
- `supprimer_item` : cascade fichiers + liaisons N-N.

### Erreurs partagées (`services/_erreurs.py`)

- `EntiteIntrouvable(LookupError)` → 404.
- `FormulaireInvalide(ValueError)` avec dict `erreurs` champ→message → 400.
- `OperationInterdite(Exception)` → 409.

Chaque service spécialise (FondsIntrouvable, CollectionInvalide, etc.)
pour les `try/except` typés et des messages contextualisés.

---

## Base de démonstration (V0.9.0-alpha.2)

`archives-tool demo init` produit `data/demo.db` via le seeder
`archives_tool.demo.peupler_base`. Composition reproductible (RNG
seedé à 42 par défaut) :

| Fonds | Cote | Items | Caractéristique |
|---|---|---|---|
| Hara-Kiri | `HK` | 40 | Revue satirique, Cavanna |
| Fonds Aínsa | `FA` | 167 | Fonds personnel + 4 libres rattachées |
| Revue des Deux Mondes | `RDM` | 36 | Bimensuel, ISSN 0035-1962 |
| Marges | `MAR` | 40 | Zine personnel |
| Concorde 1789 | `CONC-1789` | 50 | Fonds historique révolutionnaire |

**Collections libres rattachées au fonds Aínsa** :
`FA-OEUVRES` (39), `FA-CORRESP` (32), `FA-DOCU` (47),
`FA-PHOTOS` (49). Chaque item est dans la miroir **et** dans sa
libre (multi-appartenance, invariant 6).

**Collection transversale** : `TEMOIG` (« Témoignages d'exil »),
sans fonds_id. Pioche 12 items dans Aínsa (œuvres + correspondance)
et 6 dans Concorde — démontre la transversalité possible des
collections libres.

**Collaborateurs** seedés sur HK, FA, RDM via `CollaborateurFonds`
(insertion directe — pas de service CRUD dédié pour l'instant ;
suivra avec les routes web V0.9.0-beta).

Total : **5 fonds, 10 collections, 333 items, ~1300 fichiers**.
Les fichiers sont des entrées DB seulement (pas de scan physique sur
disque) ; l'UI V0.9.0-beta gérera le cas « fichier référencé absent ».

Tests d'intégrité (composition + invariants 1, 4, 6 +
reproductibilité) dans `tests/test_demo_seeder.py`.

---

## Routes web

| Route | Méthode | Notes |
|---|---|---|
| `/` | GET | Dashboard : arborescence dépliable fonds → collections + transversales. |
| `/fonds` | GET | Table simple des fonds (alternative au dashboard). |
| `/fonds/{cote}` | GET | Page fonds : bandeau métadonnées, collections, collaborateurs (par rôle), items récents. |
| `/fonds/{cote}/modifier` | GET / POST | Édition complète du fonds, cote verrouillée. PRG : 303 vers `/fonds/{cote}` au succès, 400 + re-render au refus. |
| `/fonds/{cote}/collaborateurs` | POST | Ajout d'un `CollaborateurFonds`. |
| `/fonds/{cote}/collaborateurs/{id}` | POST | Modification. |
| `/fonds/{cote}/collaborateurs/{id}/supprimer` | POST | Suppression dure. |
| `/collection/{cote}?fonds=COTE` | GET | Page collection (3 variantes : miroir, libre rattachée, transversale). Tableau d'items paginé (`page`, `par_page`, `tri`, `ordre`, `etat`). Précédence : si la cote matche un fonds et qu'aucun `?fonds=` n'est passé, redirige 303 vers `/fonds/{cote}`. |
| `/collection/{cote}/modifier` | GET / POST | Édition (libres uniquement). 403 sur miroir. PRG : 303 au succès, 400 + re-render au refus. |
| `/collection/{cote}/items/picker` | GET | Picker pour ajouter des items (filtre fonds, recherche, pagination). 403 sur miroir. |
| `/collection/{cote}/items` | POST | Ajout multi-id idempotent depuis le picker. 403 sur miroir. |
| `/collection/{cote}/items/{id}/retirer` | POST | Retrait d'un item, idempotent. Permis sur miroir (l'item reste dans le fonds, invariant 7). |
| `/item/{cote}?fonds=COTE` | GET | Placeholder ; page complète en V0.9.0-beta.3. `?fonds=` obligatoire. |

**Convention `?fonds=` en query string** : les cotes d'items et de
collections (libres) ne sont uniques que par fonds. La query string
désambiguïse. Pour les collections, la précédence par défaut envoie
sur le fonds homonyme s'il existe.

**Anti-confused-deputy** : les routes mutantes
(`/fonds/{cote}/collaborateurs/{id}/...`) vérifient que le
collaborateur appartient bien au fonds passé dans le chemin (404
sinon).

**Services dashboard** (`services/dashboard.py`) :
- `composer_dashboard(db)` : tous les fonds + transversales pour `/`.
- `composer_page_fonds(db, cote)` : `FondsDetail` (fonds + collections
  + items récents + collaborateurs groupés par rôle).
- `composer_page_collection(db, collection)` : `CollectionDetail`
  avec fonds parent ou fonds représentés selon le type.
Tous en agrégats SQL — pas de N+1.

---

## Pages Fonds et Collection — variantes d'édition

**Fonds (édition)** — formulaire complet ; cote verrouillée
(disabled côté HTML, ignorée côté serveur — la valeur du chemin est
imposée). Toute autre modification est libre. PRG : redirection au
succès, re-render avec dict `erreurs` au refus.

**Collection (édition)** — V0.9.0-beta.2.1 :
- **MIROIR** : 403 sur la route d'édition (pas de bouton « Modifier »
  dans la lecture). Pas d'API publique pour muter le titre / la
  cote / le `fonds_id`.
- **LIBRE rattachée** : édition complète sauf `fonds_id` (verrouillé
  côté serveur — le formulaire n'expose pas le champ ; pour changer
  de nature on supprime / recrée).
- **LIBRE transversale** : idem rattachée, sans `fonds_id`.

**Items dans une collection (V0.9.0-beta.2.1)** :
- Tableau paginé directement sur `GET /collection/{cote}` (pas de
  page séparée). Tri whitelist (`cote`, `titre`, `date`, `annee`,
  `etat`, `modifie`), filtre `etat`, pagination `par_page` 10–200.
- Ajout via picker (`/items/picker` GET → soumission `POST /items`)
  multi-id idempotent. Filtre fonds par défaut = fonds parent pour
  une libre rattachée, tous fonds pour une transversale.
- Retrait via bouton par ligne, `POST /items/{id}/retirer`.
  Idempotent. Permis sur miroir aussi (invariant 7 : l'item reste
  dans le fonds).

---

## Sources externes (V2+)

### `source_externe`

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `code` | TEXT | UNIQUE, NOT NULL — `nakala`, `hal`, `gallica` |
| `libelle` | TEXT | NOT NULL |
| `type_api` | TEXT | NOT NULL — `rest`, `oai-pmh`, `iiif` |
| `url_base` | TEXT | NOT NULL |
| `ttl_cache_heures` | INTEGER | NOT NULL, DEFAULT 24 |
| `actif` | BOOLEAN | NOT NULL, DEFAULT 1 |

Notes : la clé API éventuelle n'est **pas** stockée en base. Elle reste
dans la config locale de chaque utilisateur (chiffrée si sensible).

---

### `ressource_externe`

Cache local des ressources consultées.

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `source_id` | INTEGER | FK → `source_externe.id`, NOT NULL |
| `identifiant_externe` | TEXT | NOT NULL — DOI, handle, URI |
| `type` | TEXT | `data`, `collection` |
| `titre` | TEXT | |
| `auteurs` | JSON | |
| `date` | TEXT | EDTF |
| `metadonnees_brutes` | JSON | Réponse API complète |
| `manifeste_iiif` | TEXT | URL du manifeste IIIF si disponible |
| `recupere_le` | DATETIME | NOT NULL |
| `statut` | TEXT | NOT NULL — `actif`, `introuvable`, `erreur` |

**Contrainte :** UNIQUE (`source_id`, `identifiant_externe`).

---

### `lien_externe_item`

Rattachement optionnel entre un item local et une ressource externe.

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `item_id` | INTEGER | FK → `item.id`, NOT NULL |
| `ressource_externe_id` | INTEGER | FK, NOT NULL |
| `type_relation` | TEXT | NOT NULL — `meme_ressource`, `partie_de`, `supplement_de`, `evoque` |
| `notes` | TEXT | |
| `cree_le` | DATETIME | NOT NULL |
| `cree_par` | TEXT | | Nom libre copié de la config locale. |

**Contrainte :** UNIQUE (`item_id`, `ressource_externe_id`, `type_relation`).

---

## Recherche plein texte

Utiliser SQLite FTS5, table virtuelle `item_fts` synchronisée via
triggers :

```sql
CREATE VIRTUAL TABLE item_fts USING fts5(
    titre, description, metadonnees_texte,
    content='item', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
```

Le tokenizer `unicode61 remove_diacritics 2` gère les accents français
correctement. Triggers AFTER INSERT / UPDATE / DELETE sur `item` pour
maintenir l'index.

---

## Pragmas SQLite recommandés

À appliquer à l'ouverture de chaque connexion :

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA temp_store=MEMORY;
PRAGMA mmap_size=268435456;  -- 256 MB
```

Note : si passage sur partage réseau, repasser en `journal_mode=DELETE`.

---

## Questions ouvertes sur le modèle

- [ ] Gestion des **collections imbriquées** (un fonds contenant plusieurs
      revues) : ajouter `collection.parent_id` ou garder plat ?
- [ ] **Droits par collection** : table `droit_collection` ou rester
      ouvert à tous ?
- [ ] **Champs d'item multivalués natifs** (auteurs, sujets) : table
      dédiée `item_auteur` / `item_sujet` ou JSON ?
      Recommandation actuelle : JSON pour la souplesse, table dédiée
      si on a besoin d'interroger/dédoublonner.
- [ ] **Versioning des fichiers** (historique des remplacements) : table
      `fichier_version` ou état `remplace` suffit ?
      Recommandation actuelle : V3, état `remplace` suffit pour la V1.
- [ ] **Représentation précise des dates EDTF** : stockage brut + parsing
      applicatif, ou colonnes calculées `date_min` / `date_max` pour
      filtrage ?

---

## Évolutivité

Le modèle est pensé pour évoluer sans migration lourde sur les cas
fréquents :

- Nouveau champ métier spécifique : ajouter dans `metadonnees` JSON.
- Nouvelle collection avec champs propres : déclarer dans
  `champ_personnalise`.
- Nouveau vocabulaire contrôlé : `vocabulaire` + `valeur_controlee`.
- Nouveau connecteur externe : ajouter une `source_externe`.

Les migrations Alembic restent nécessaires pour les colonnes dédiées et
les contraintes structurantes.
