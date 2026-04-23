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

---

## Tables

### `utilisateur`

Identité simple pour attribuer les modifications. Pas de mot de passe.

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK, autoincrement |
| `nom` | TEXT | NOT NULL, UNIQUE |
| `actif` | BOOLEAN | NOT NULL, DEFAULT 1 |
| `cree_le` | DATETIME | NOT NULL |

---

### `collection`

Représente une revue, un fonds, un ensemble catalographique.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `cote_collection` | TEXT | UNIQUE, NOT NULL | Ex. `RDM` |
| `titre` | TEXT | NOT NULL | |
| `titre_secondaire` | TEXT | | Sous-titre, ancien titre |
| `editeur` | TEXT | | |
| `lieu_edition` | TEXT | | |
| `periodicite` | TEXT | | Libre : « trimestriel », « mensuel »... |
| `date_debut` | TEXT | | Format EDTF |
| `date_fin` | TEXT | | Format EDTF, NULL si en cours |
| `issn` | TEXT | | |
| `doi_nakala` | TEXT | UNIQUE | DOI d'une collection publiée sur Nakala. Unique pour détecter les doubles imports. |
| `description` | TEXT | | |
| `metadonnees` | JSON | | Champs étendus spécifiques |
| `profil_import_id` | INTEGER | FK → `profil_import.id` | NULL si pas encore défini |
| `notes_internes` | TEXT | | |
| `cree_le` | DATETIME | NOT NULL | |
| `cree_par` | INTEGER | FK → `utilisateur.id` | |
| `modifie_le` | DATETIME | | |
| `modifie_par` | INTEGER | FK → `utilisateur.id` | |
| `version` | INTEGER | NOT NULL, DEFAULT 1 | |

**Index :** `cote_collection`, `titre`, `doi_nakala`.

---

### `item`

L'unité principale de catalogage : un numéro, un volume, une unité.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `collection_id` | INTEGER | FK → `collection.id`, NOT NULL | |
| `cote` | TEXT | NOT NULL | Unique dans la collection |
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
| `cree_par` | INTEGER | FK → `utilisateur.id` | |
| `modifie_le` | DATETIME | | |
| `modifie_par` | INTEGER | FK → `utilisateur.id` | |
| `version` | INTEGER | NOT NULL, DEFAULT 1 | |

**Contraintes :**
- UNIQUE (`collection_id`, `cote`)
- UNIQUE (`doi_nakala`)
- CHECK sur `etat_catalogage` (valeurs enum)

**Index :** `collection_id`, `cote`, `annee`, `etat_catalogage`,
`doi_nakala`, `doi_collection_nakala`,
index plein texte FTS5 sur `titre` + `description` + `metadonnees`.

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
| `racine` | TEXT | NOT NULL | Nom logique de la racine |
| `chemin_relatif` | TEXT | NOT NULL | POSIX, NFC |
| `nom_fichier` | TEXT | NOT NULL | Pour recherche rapide |
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
| `ajoute_par` | INTEGER | FK → `utilisateur.id` | |
| `modifie_le` | DATETIME | | |
| `version` | INTEGER | NOT NULL, DEFAULT 1 | |

**Contraintes :**
- UNIQUE (`racine`, `chemin_relatif`) — un fichier n'existe qu'une fois.
- UNIQUE (`item_id`, `ordre`) — pas de collision d'ordre dans un item.

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
| `description` | TEXT | |
| `uri_base` | TEXT | |

**`valeur_controlee`** :

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `vocabulaire_id` | INTEGER | FK, NOT NULL |
| `code` | TEXT | NOT NULL |
| `libelle` | TEXT | NOT NULL |
| `uri` | TEXT | |
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
| `execute_par` | INTEGER | FK → `utilisateur.id` | |
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
| `modifie_par` | INTEGER | FK → `utilisateur.id` |

**Index :** `item_id`, `modifie_le`.

---

### `session_edition`

Pour le verrou coopératif entre utilisateurs.

| Colonne | Type | Contraintes |
|---|---|---|
| `id` | INTEGER | PK |
| `utilisateur_id` | INTEGER | FK, NOT NULL |
| `item_id` | INTEGER | FK → `item.id` | NULL = session générale |
| `ouverte_le` | DATETIME | NOT NULL |
| `dernier_heartbeat` | DATETIME | NOT NULL |
| `fermee_le` | DATETIME | |

Une session est active si `fermee_le IS NULL` et `dernier_heartbeat`
récent (< 2 min). Le client envoie un heartbeat périodique.

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
| `cree_par` | INTEGER | FK → `utilisateur.id` |

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
