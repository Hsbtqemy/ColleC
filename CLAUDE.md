# CLAUDE.md

Ce fichier fournit le contexte du projet à Claude Code. Il est lu
automatiquement à chaque session. Tenir à jour au fil des décisions
structurantes.

---

## Vue d'ensemble du projet

**Nom provisoire :** archives-tool (à renommer)

**Objet :** outil interne de gestion de collections numérisées (revues
anciennes, périodiques, textes). Pas un outil de valorisation publique :
l'usage est la constitution, le suivi, la correction et le contrôle de
catalogues d'archives scannées.

**Utilisateurs :** quelques personnes, édition jamais simultanée sur un
même item, consultation possible à plusieurs.

**Statut :** projet en cours de conception. Pas encore de code.

---

## Principes directeurs

Ces principes doivent guider toutes les décisions de conception et de
code. Si une demande les contredit, signaler avant d'exécuter.

1. **La base locale est la source de vérité pendant le travail.** Les
   tableurs Excel et les arborescences de fichiers sont des
   formats d'entrée (import) et de sortie (export), pas la vérité
   courante.

2. **Les données doivent pouvoir sortir de l'outil à tout moment.**
   Exports CSV/Excel et JSON/XML (Dublin Core) sont des fonctions de
   premier ordre. L'utilisateur ne doit jamais se sentir prisonnier.

3. **Ne jamais modifier un fichier utilisateur sans aperçu préalable.**
   Tout renommage, déplacement, écrasement passe par un mode
   « simulation » affichant le diff avant exécution.

4. **Journaliser toutes les opérations destructives.** Renommage,
   déplacement, suppression : table `OperationFichier` avec batch_id
   permettant l'annulation d'un lot.

5. **Portabilité Windows + macOS.** Jamais de chemin absolu stocké en
   base. Jamais de concaténation de chemin par chaîne. Toujours
   `pathlib.Path`. Normalisation Unicode NFC systématique pour les noms
   de fichiers.

6. **La complexité s'ajoute, ne se présume pas.** V1 minimale et
   utilisable avant toute extension. Pas de sur-ingénierie.

7. **Tests d'abord sur les zones à risque.** Importers, renamer,
   rapprochement fichiers / base : tests écrits avant implémentation.

---

## Stack technique

**Langage :** Python 3.11+

**Backend :**
- FastAPI (API + rendu serveur via Jinja2)
- SQLAlchemy 2.x (ORM)
- Alembic (migrations, dès la V1)
- SQLite (base locale, mode WAL activé)
- Pydantic 2.x (validation, schemas)
- Typer (CLI)

**Frontend :**
- Jinja2 + HTMX pour les interactions
- Tailwind CSS pour le style
- SortableJS pour les réordonnancements (drag & drop vignettes)
- OpenSeadragon pour la visionneuse d'images (IIIF-compatible)

**Traitement fichiers :**
- Pillow pour les dérivés simples
- pyvips (via bindings) pour le traitement TIFF lourd si disponible
- PyMuPDF si des PDF sont à manipuler

**Intégrations externes (V2+) :**
- httpx pour les appels API (Nakala, autres entrepôts)
- Support IIIF pour affichage d'images externes

**Outils de développement :**
- uv pour la gestion d'environnement et dépendances
- pytest pour les tests
- ruff pour lint + format

---

## Architecture générale

### Modèle conceptuel

```
Collection (une revue, un fonds)
  └── Item (un numéro, un volume, une unité catalographique)
        └── Fichier (un scan, une page)
```

Une **Collection** porte des métadonnées communes (titre, éditeur,
périodicité, cote de collection) qui peuvent être héritées par ses items.

Un **Item** est l'unité principale de catalogage : une notice complète
avec ses métadonnées Dublin Core étendues.

Un **Fichier** est un scan rattaché à un item, avec un ordre, un type de
page (couverture, page, planche...), un folio.

### Sources externes (V2+)

Une entité parallèle permet de référencer des ressources consultées dans
des entrepôts externes (Nakala d'abord, éventuellement d'autres).

```
SourceExterne (Nakala, HAL, Gallica...)
  └── RessourceExterne (une notice consultée, avec cache local)
        └── LienExterneItem (rattachement à un item local, optionnel)
```

### Flux de données

```
Tableurs existants  ─┐
Arborescence scans  ─┼─► Import (profils YAML) ─► Base SQLite ─► Export (Excel, DC/XML)
Saisie nouvelle     ─┘                                ▲
                                                      │
                                            Interface FastAPI + HTMX
                                                      ▲
                                                      │
                                            Consultation Nakala (V2+)
```

---

## Modèle de données (résumé)

Entités principales — détails dans `docs/schema.md`.

- **Collection** : id, titre, cote_collection, éditeur, périodicité,
  dates, profil_import_id, métadonnées_communes (JSON).

- **Item** : id, collection_id, numéro, date (EDTF), cote, type_coar,
  état_catalogage, métadonnées (JSON), version, traçabilité.

- **Fichier** : id, item_id, racine (nom logique), chemin_relatif, hash,
  ordre, type_page, folio, état, largeur, hauteur, format.

- **ProfilImport** : rattaché à une collection, contient mapping colonnes
  tableur → champs, règles de résolution fichiers, template de nommage.

- **ChampPersonnalisé** : permet à une collection d'avoir des champs
  spécifiques en plus du socle DC.

- **OperationFichier** : journal des opérations sur fichiers (rename,
  move, delete). Batch_id pour annulation de lot.

- **ModificationItem** : journal des modifications de métadonnées.

- **SourceExterne**, **RessourceExterne**, **LienExterneItem** : V2+,
  pour Nakala.

- **Utilisateur** : identité simple (nom, actif), pas d'auth forte.

- **Racine** : nom logique → chemin local (par utilisateur, dans la
  config locale, jamais en base partagée).

---

## Conventions de code

### Structure du dépôt

```
archives-tool/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── alembic.ini
├── alembic/
│   └── versions/
├── src/
│   └── archives_tool/
│       ├── __init__.py
│       ├── config.py          # Chargement config locale
│       ├── db.py              # Session SQLAlchemy, init WAL
│       ├── models/            # Modèles SQLAlchemy
│       ├── schemas/           # Pydantic
│       ├── importers/         # Lecture tableurs + profils YAML
│       ├── exporters/         # Excel, CSV, DC/XML
│       ├── files/             # Résolution chemins, racines, hash
│       ├── renamer/           # Logique de renommage transactionnel
│       ├── derivatives/       # Génération vignettes / aperçus
│       ├── external/          # Connecteurs Nakala, IIIF (V2+)
│       ├── qa/                # Contrôles de cohérence
│       ├── api/               # Routes FastAPI
│       ├── web/               # Templates Jinja2, HTMX, assets
│       └── cli.py             # Commandes Typer
├── profiles/                  # Profils d'import par collection (YAML)
├── tests/
├── data/                      # .db et dérivés (gitignoré)
├── scripts/
└── docs/
    ├── schema.md
    ├── profils.md
    └── deploiement.md
```

### Règles de code

- **Typage statique systématique.** Tous les paramètres et retours de
  fonction typés. `from __future__ import annotations` en tête.
- **Fonctions courtes, responsabilités uniques.** Une fonction qui
  dépasse 40 lignes doit être questionnée.
- **Pas de logique métier dans les routes FastAPI.** Les routes
  délèguent à des services. Testabilité > concision.
- **Pas de SQL brut** sauf cas très justifiés ; SQLAlchemy ORM ou Core.
- **Chemins : toujours `pathlib.Path`.** Jamais de `os.path.join` ni de
  concaténation. Toujours normaliser Unicode en NFC avant comparaison.
- **Encodage : toujours UTF-8 explicite** à la lecture/écriture de
  fichiers. Détection bienveillante à l'import des tableurs anciens.
- **Docstrings en français** pour les fonctions métier. Anglais ok pour
  les utilitaires bas-niveau.
- **Noms de variables en français** pour les concepts métier (cote,
  item, racine), anglais pour la technique (session, hash, path).

### Tests

- **pytest** avec fixtures.
- **Tests d'intégration pour les importers** avec de vrais petits
  tableurs d'exemple et arborescences de fichiers fictives.
- **Tests de transaction pour le renamer** : simulations de pannes,
  conflits, circuits. Cas limites explicites.
- **Tests de portabilité chemin** : tests paramétrés Windows + POSIX
  (via pyfakefs si pertinent).

---

## Plan de développement (phasage)

### V1 — Socle utilisable (objectif : 2-4 semaines)

- Modèle de données SQLAlchemy + Alembic.
- CLI minimale (init, import, list, export).
- Importers avec profils YAML : lire un Excel existant + scanner une
  arborescence, peupler la base.
- Résolution chemins via racines configurables par utilisateur.
- Génération de dérivés (vignettes + aperçu moyen).
- Interface web FastAPI + HTMX : vue collection, vue item, visionneuse
  OpenSeadragon, formulaire de consultation/édition basique.
- Renommage transactionnel avec aperçu et journal (batch_id, undo
  dernier batch).
- Exports CSV/Excel de base.
- Contrôles de cohérence minimaux (fichiers orphelins, liens cassés).

### V2 — Nakala et enrichissement

- Connecteur Nakala (API REST) avec cache local.
- Support IIIF pour visionneuse (local et externe).
- Exploration et consultation de collections Nakala.
- Liens optionnels entre items locaux et ressources externes.
- Exports enrichis (Dublin Core XML, JSON-LD).

### V3 — Confort et robustesse

- Édition en masse avec aperçu.
- Rapports de qualité avancés.
- Scission / fusion de scans multi-pages.
- Versionnement des fichiers (historique des remplacements).
- Empaquetage distribuable (PyInstaller ou équivalent).

### Hors scope initial (à ne pas implémenter sans discussion)

- Dépôt vers Nakala.
- OCR intégré (possible en V3+ mais non prioritaire).
- Multi-utilisateurs simultanés en édition avec résolution de conflits.
- Authentification forte, gestion de droits.
- Déploiement cloud.

---

## Décisions d'architecture notables

### Stockage des chemins

Les fichiers sont stockés en base sous forme **(racine_logique,
chemin_relatif)**, jamais en absolu. Chaque utilisateur configure ses
racines dans un `config_local.yaml` hors base et hors dépôt Git.

Exemple :
```yaml
# config_local.yaml (local à chaque poste, non versionné)
utilisateur: "Marie Dupont"
racines:
  scans_revues: /Users/marie/Archives/Scans
  miniatures: /Volumes/NAS/archives/miniatures
```

Avantages : portabilité entre machines, collaboration possible avec des
chemins différents par utilisateur.

### Métadonnées étendues en JSON

Les champs Dublin Core étendus et spécifiques à chaque collection sont
stockés dans un champ `metadonnees` de type JSON sur `Item`. Les champs
structurants récurrents (titre, date, cote, type COAR) sont des colonnes
dédiées pour l'indexation et la recherche performante.

### Profils d'import YAML

Chaque collection reprise a un profil YAML qui décrit :
- Le mapping colonnes du tableur → champs de l'item
- La convention de nommage des scans (regex ou template)
- La règle de dérivation de la cote
- Le template de nommage cible (pour renommage canonique)

Les profils sont versionnés dans le dépôt Git (dossier `profiles/`).

### Renommage transactionnel

Toute opération de renommage :
1. Calcule le nom cible selon le template.
2. Détecte les conflits (deux fichiers cible identiques, cycles).
3. Présente un aperçu (mode simulation).
4. Exécute en transaction : déplacement physique + mise à jour base.
5. Journalise dans `OperationFichier` avec un batch_id.

Toute opération est annulable via le batch_id.

### SQLite en mode WAL

Activer dès l'ouverture de connexion :
```python
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
```

Note : si la base est un jour mise sur partage réseau, repasser en mode
journal DELETE classique (plus fiable sur SMB/NFS).

### Configuration locale vs partagée

- **Config locale (par poste)** : fichier YAML hors base, contenant
  racines de fichiers, identité utilisateur, préférences UI.
- **Config partagée (en base ou dans le dépôt)** : profils de
  collections, vocabulaires contrôlés, templates de nommage.

---

## Vocabulaires et standards

- **Dublin Core qualifié** comme socle de métadonnées.
- **COAR Resource Types** pour la typologie documentaire (stocker
  URI + label, pas juste le label).
- **EDTF (Extended Date/Time Format)** pour les dates incertaines
  (`1923`, `192X`, `1923-04?`, `1923/1924`).
- **ISO 639-3** pour les langues.
- **IIIF Presentation API 3.x** pour les manifestes de visionneuse
  (V2+).

Les valeurs contrôlées (types COAR, langues) sont stockées en table
dédiée avec URI + label, pas en dur dans le code.

---

## Questions ouvertes / à décider

(Mettre à jour au fil du projet.)

- [ ] Nom définitif du projet et du package Python.
- [ ] Choix précis de l'empaquetage final (PyInstaller, Briefcase,
      simple scripts run.bat/run.sh ?).
- [ ] Stratégie exacte de sauvegarde automatique (fréquence, rotation).
- [ ] Gestion des droits par collection (tous utilisateurs voient tout
      ou cloisonnement ?).
- [ ] Format canonique des noms de fichiers après renommage (tout
      minuscule ? tirets ou underscores ?).
- [ ] Intégration FTS5 sur `item` (titre, description, métadonnées). SQL
      et triggers déjà rédigés dans le modèle initial mais non portés en
      migration. À faire dans une migration dédiée.
      **Piège à retenir** : `render_as_batch=True` reconstruit la table
      pour certains `ALTER` SQLite et peut perdre les triggers. Prévoir
      `alembic/helpers.py` avec `drop_fts_triggers()` /
      `create_fts_triggers()` à appeler en début et fin de toute
      migration qui touche à `item`.

---

## Comment Claude Code doit travailler sur ce projet

- **Lire ce fichier en début de session** et relever toute contradiction
  avec les demandes.
- **Proposer les décisions structurantes avant de coder.** Si une
  question n'est pas tranchée ici ou dans `docs/`, la poser avant
  d'implémenter.
- **Écrire les tests avant ou en parallèle du code** pour les zones à
  risque (importers, renamer, rapprochement fichiers).
- **Ne pas introduire de nouvelle dépendance sans la justifier** dans le
  message et la documenter.
- **Mettre à jour `CLAUDE.md` et `docs/`** quand une décision
  structurante est prise.
- **Commit fréquents avec messages explicites** (convention Conventional
  Commits recommandée).
- **En cas de doute sur la portabilité Windows/Mac**, signaler et
  proposer un test.

---

## Commandes utiles

(À compléter au fur et à mesure.)

```bash
# Installation
uv sync

# Lancer les tests
uv run pytest

# Lancer l'application en dev
uv run uvicorn archives_tool.api.main:app --reload

# CLI
uv run archives-tool --help

# Migration base
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# Lint / format
uv run ruff check .
uv run ruff format .
```
