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

## Positionnement de l'outil

Cet outil est un **espace de travail** pour des chantiers de
constitution et d'enrichissement de collections numériques. Il n'est
pas un catalogue bibliothéconomique figé qui attendrait des données
déjà propres.

Conséquences structurantes :

- La création, la restructuration et le nettoyage sont des
  opérations de premier ordre, pas des cas marginaux.
- Les structures de métadonnées (champs personnalisés, vocabulaires)
  évoluent en cours de route. Ajouter, renommer, scinder, fusionner
  un champ doit être possible nativement depuis l'interface.
- Plusieurs personnes peuvent se passer le relais sur la vie longue
  d'une collection. L'outil doit capitaliser la connaissance tacite
  (descriptions internes sur les entités, traçabilité des
  opérations, journal auto-généré consultable).
- L'export vers des formats canoniques (Dublin Core, COAR, Nakala)
  est un aboutissement vérifiable : il permet de sortir le travail
  pour relecture externe, archivage, publication.
- L'import depuis des tableurs existants est un point d'entrée
  utile (amorçage, rapatriement de travail fait ailleurs), mais pas
  la voie royale.

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

8. **Autonomie des items.** Chaque item stocke ses métadonnées de
   manière complète et autonome. Même si certains champs (responsable
   scientifique, éditeur, auteur de la notice) ont la même valeur pour
   tous les items d'une collection, cette valeur est stockée sur chaque
   item, sans factorisation ni résolution dynamique.

   Justifications :
   - Traçabilité : chaque notice est auto-suffisante, lisible et
     exportable sans contexte.
   - Évolution : un item peut diverger d'un défaut collection sans
     casser la structure.
   - Export propre : les exports Dublin Core et Nakala reflètent ce
     qui est en base.

   Conséquence sur les profils d'import : une clé
   `valeurs_par_defaut` sera prévue pour la commodité de saisie, mais
   elle écrit les valeurs sur chaque item individuellement.

9. **La structure s'adapte au chantier.** Les champs personnalisés
   et les vocabulaires contrôlés ne sont pas figés dans le code. Ils
   se créent, se renomment, se déprécient au fil du travail, via
   l'interface et via des opérations tracées.

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
- Rich (affichage tableaux, panneaux, arbres, syntaxe colorée pour
  les commandes `archives-tool montrer ...`)

**Frontend :**
- Jinja2 + HTMX pour les interactions
- Tailwind CSS compilé via la CLI npm (pas de CDN). `npm install` une
  fois ; `npm run watch:css` en dev. `output.css` est gitignoré.
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

### Profils d'import

Les profils d'import YAML sont chargés et validés dans
`src/archives_tool/profils/` (schéma Pydantic + loader). Ils décrivent
comment lire un tableur existant et une arborescence de scans pour
amorcer une collection. Référence complète dans
[`docs/profils.md`](docs/profils.md). Fixtures représentatives sous
`tests/fixtures/profils/`.

Le module `profils/generateur.py` produit des squelettes YAML
commentés :
- `generer_squelette` : profil minimal avec placeholder à remplir.
- `analyser_tableur` : profil pré-rempli des colonnes détectées,
  avec heuristique pour les champs structurants (cote, titre, date,
  URI Dublin Core, ...).

CLI : `archives-tool profil init` et `archives-tool profil analyser`.
Guide utilisateur : [`docs/profils_creation.md`](docs/profils_creation.md).

### Importer

Le pipeline d'import est découpé en quatre modules sous
`src/archives_tool/importers/` :

- `lecteur_tableur.py` : lit un CSV/Excel avec pandas en `dtype=str`,
  normalise NFC + strip, convertit les sentinelles nulles en `None`.
- `transformateur.py` : fonction pure ligne → `ItemPrepare`, applique
  mapping, valeurs par défaut, décompositions, transformations.
- `resolveur_fichiers.py` : cherche les fichiers sur disque selon
  le motif template ou regex du profil.
- `ecrivain.py` : orchestre, écrit en base sous transaction avec
  dry-run par défaut, journalise dans `OperationImport`.

CLI : `archives-tool importer <profil>` (Typer). Référence
complète dans [`docs/importer.md`](docs/importer.md).

### Exports canoniques

`src/archives_tool/exporters/` regroupe les trois formats canoniques
(xlsx/csv, Dublin Core XML, CSV Nakala) plus les utilitaires communs :

- `selection.py` : `CritereSelection` + streaming via yield_per.
- `mapping_dc.py` : source de vérité des correspondances champs
  internes → URI Dublin Core Terms.
- `rapport.py` : rapport de pré-export (items incomplets, valeurs
  non canoniques).
- `excel.py`, `dublin_core.py`, `nakala.py` : producteurs par format.

CLI : `archives-tool exporter <format> --collection ... --sortie ...`.
Dry-run et mode strict disponibles. Référence complète dans
[`docs/exports.md`](docs/exports.md).

### Affichage CLI

`src/archives_tool/affichage/` regroupe le sous-groupe de commandes
`archives-tool montrer ...` (Rich) :

- `console.py` : instance Console partagée, thème (états colorés,
  succès/avertissement/erreur), helper `silencer_pour_tests`.
- `formatters.py` : utilitaires `formater_date`, `formater_etat`,
  `formater_taille_octets`, `tronquer`, `barre_progression`.
- `collections.py`, `items.py`, `fichiers.py`, `statistiques.py` :
  un module par vue. Lecture seule, pas d'écriture en base.

Commandes : `montrer collections`, `montrer collection COTE`,
`montrer item COTE`, `montrer fichier ID`, `montrer statistiques`.
Référence complète dans
[`docs/commandes_montrer.md`](docs/commandes_montrer.md).

### Contrôles de cohérence

`src/archives_tool/qa/` regroupe les contrôles de cohérence
base ↔ disque (lecture seule, jamais d'écriture) :

- `controles.py` : quatre fonctions pures session → `RapportControle`
  (fichiers manquants sur disque, orphelins disque, items sans
  fichier, doublons par hash) plus un orchestrateur `controler_tout`.
- `rapport.py` : dataclasses des anomalies et du rapport global.
- `affichage.py` : rendu Rich par contrôle.

CLI : `archives-tool controler [--collection ...] [--recursif]
[--check ...] [--extensions ...] [--limite-details N]`. Exit 0
si aucune anomalie, 1 sinon. Référence complète dans
[`docs/controles.md`](docs/controles.md).

### Renommage transactionnel

`src/archives_tool/renamer/` orchestre le renommage en quatre temps :

- `template.py` : évaluation d'un template Python (`str.format`)
  avec les variables d'un fichier et de son item.
- `plan.py` : construction du plan, détection des conflits
  (collisions intra-batch, externes) et des cycles (résolus, pas
  bloqués).
- `execution.py` : exécution en deux phases (`src→tmp`, `tmp→dst`)
  sur disque et en base, avec rollback compensateur en cas d'erreur
  mid-batch. La contrainte `UNIQUE(racine, chemin_relatif)` impose
  ce passage par un nom temporaire pour les cycles.
- `annulation.py` : retour en arrière d'un batch via son `batch_id`,
  idempotent.
- `historique.py` : vue agrégée des batchs `OperationFichier`.

CLI : `archives-tool renommer appliquer --template ... [--collection
COTE | --item COTE | --fichier-id ID]`, `archives-tool renommer
annuler --batch-id UUID`, `archives-tool renommer historique`.
Dry-run par défaut. Référence complète dans
[`docs/renamer.md`](docs/renamer.md).

### Génération de dérivés

`src/archives_tool/derivatives/` produit vignettes et aperçus pour
les fichiers actifs :

- `chemins.py` : convention de stockage `<racine_cible>/<taille>/<chemin_source>.jpg`.
- `generateur.py` : Pillow pour les formats raster, PyMuPDF (fitz)
  pour les PDF (1ère page à 200 dpi). RGBA composé sur fond blanc.
- `rapport.py` : dataclasses + `StatutDerive` (StrEnum).
- `affichage.py` : rendu Rich.

Tailles par défaut : vignette 300 px, aperçu 1 200 px (côté long,
ratio préservé). Idempotent : `derive_genere=True` est ignoré sauf
`--force`.

CLI : `archives-tool deriver appliquer [--collection|--item|--fichier-id]
[--recursif] [--force] [--dry-run] [--racine-cible miniatures]`,
`archives-tool deriver nettoyer ...`. Référence dans
[`docs/derivatives.md`](docs/derivatives.md).

### Interface web

`src/archives_tool/api/` (FastAPI) et `src/archives_tool/web/`
(Jinja2 + Tailwind compilé) constituent le socle de l'UI.
V0.6.0 livre dashboard + vue collection (3 onglets) + vue item
avec visionneuse OpenSeadragon, en lecture seule.

- `api/main.py` : application FastAPI, mount `/static`, inclusion
  des routers.
- `api/templating.py` : instance Jinja2Templates partagée, filtres
  (libelle_phase, libelle_etat, temps_relatif, taille_humaine).
  La route `/collection/{cote}/{onglet}` branche directement sur
  `HX-Request` pour servir soit le wrapper `pages/collection.html`
  soit le partiel seul.
- `api/deps.py` : session SQL par requête (engine + sessionmaker
  cachés via lru_cache), identité utilisateur, racines, base
  courante. `ARCHIVES_DB` (variable d'environnement) prime sur la
  base par défaut.
- `api/routes/` : `dashboard.py`, `collection.py`, `item.py`,
  `derives.py`.
- `api/services/` : logique métier pure (`dashboard.py`,
  `collection.py`, `item.py`, `sources_image.py`).
- `web/templates/components/` : 10 composants Claude Design
  (badge_etat, avancement, cellule_modifie, phase_chantier,
  cartouche_metadonnees, panneau_colonnes, tableau_collections,
  tableau_items, bandeau_item, panneau_fichiers) + composants
  antérieurs (header, tabs, metric_card, breadcrumb,
  collection_header). Le bundle handoff est la **référence visuelle
  de vérité** ; détails dans [`docs/composants_ui.md`](docs/composants_ui.md).
- `web/templates/{base.html,pages/,partials/}` : layout commun, pages
  pleines pour accès direct, partiels pour swap HTMX.
- `web/static/css/{input.css,output.css}` : Tailwind compilé via
  npm. Tokens étendus du bundle : `state-info/warn/ok/err`,
  `seg-brouillon/a-verifier/verifie/valide/a-corriger`,
  `border-{tertiary,secondary,primary}` (opacité du noir).
- `web/static/js/visionneuse.js` : init OpenSeadragon, écoute les
  clicks dans `[data-panneau-fichiers]` sur `[data-fichier-id]`,
  fallback sur `open-failed`.
- `web/static/js/panneau_fichiers.js` : bascule `data-state`
  collapsed/hover/pinned (panneau gauche escamotable de la vue item).
- `web/static/js/vendor/openseadragon/` : bundle vendor copié
  depuis `node_modules` (gitignoré comme output.css).

**Architecture multi-sources** (`api/services/sources_image.py`) :
priorité IIIF Nakala > DZI local > aperçu local. Le résultat est
embarqué en JSON dans la page item, le JS appelle `viewer.open(...)`
au click sur une vignette.

CLI : `archives-tool demo init [--sortie data/demo.db] [--force]` crée
une base SQLite peuplée pour explorer l'interface (5 collections, ~360
items, anomalies synthétiques). Référence dans
[`docs/interface_web.md`](docs/interface_web.md).

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

Entités principales — détails dans [`schema.md`](schema.md).

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

- **OperationImport** : journal des imports YAML (un par exécution
  réelle). Lié aux OperationFichier produites pendant l'import.

- **PreferencesAffichage** : ordre des colonnes choisi par utilisateur
  dans une vue tabulaire. Structure prête pour V0.6 (édition de
  vues), pas encore alimentée par l'UI.

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
├── schema.md                  # Référence du modèle de données
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
│       ├── api/               # FastAPI : routes, deps, services
│       ├── web/               # Templates Jinja2 + assets statiques
│       ├── demo/              # Génération de la base de démonstration
│       └── cli.py             # Commandes Typer
├── profiles/                  # Profils d'import par collection (YAML)
├── tests/
├── data/                      # .db et dérivés (gitignoré)
├── scripts/
└── docs/                      # Références par module (importer.md, exports.md, …)
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

### V1 — Socle utilisable pour un premier chantier

**Modèle de données, migrations, CLI minimale** :

- Création de collection, sous-collection, item, rattachement de
  fichier depuis la CLI.
- Import depuis profil YAML (voir session dédiée).
- ✅ Renommage transactionnel avec aperçu et journal.
- Résolution des chemins via racines configurables.
- ✅ Génération de dérivés (vignettes, aperçu moyen).

**Interface web (FastAPI + HTMX + Tailwind)** :

- ✅ Tableau de bord simple (inventaire, alertes) — V0.5.
- ✅ Vue collection avec onglets Sous-collections / Items / Fichiers
  (lecture seule) — V0.6.0.
- ✅ Vue item trois zones (fichiers, visionneuse, métadonnées) en
  lecture seule — V0.6.0.
- ✅ Visionneuse OpenSeadragon (multi-sources : IIIF Nakala > DZI > aperçu local) — V0.6.0.
- ✅ Tri des colonnes des tableaux via HTMX — V0.6.1.
- ✅ Filtre / recherche dans les tableaux items + fichiers (drawer
  latéral, query string) — V0.6.1.
- ✅ Pagination du tableau de fichiers (50/page par défaut) — V0.6.1.
- Sélection persistée des colonnes du tableau d'items via le panneau
  Colonnes du bundle (drag-drop, `PreferencesAffichage`) — V0.6.2.
- Script de résolution Nakala (peuplement `Fichier.iiif_url_nakala`) — V0.7.
- Édition des métadonnées item — V0.7.
- Édition structurelle des champs personnalisés d'une collection
  (créer, renommer, déprécier) depuis l'UI — V0.7.
- Édition des vocabulaires contrôlés depuis l'UI — V0.7.
- Rattachement de fichiers à un item depuis l'UI (ajout depuis
  disque, copie ou déplacement selon la convention) — V0.7.

**Exports canoniques** (fait) :

- ✅ Export Excel / CSV d'une collection (granularité item ou fichier).
- ✅ Export Dublin Core XML (agrégé ou un fichier par item).
- ✅ Export CSV de dépôt Nakala.
- ✅ Rapport de préparation avant export (champs manquants, valeurs
  non mappées vers URI canoniques).
- Export JSON-LD avec contextes COAR et Nakala (reporté).

**Contrôles de cohérence de base** (fait) :

- ✅ Fichiers référencés sans fichier sur disque.
- ✅ Fichiers sur disque sans référence en base.
- ✅ Items sans fichier.
- ✅ Doublons potentiels (même hash).

### V2 — Confort du chantier vivant

- Refactoring de métadonnées en masse (scinder un champ en deux,
  normaliser des valeurs, remplacer en lot avec aperçu).
- Vue tableau éditable type tableur pour saisie rapide (composant
  à choisir : AG Grid, Handsontable, ou équivalent).
- Journal de bord auto-généré par collection, consultable, avec
  possibilité d'annoter les entrées.
- Création en série d'items (pattern + incrément).
- « Feuille de scan » : flux rapide avec raccourcis clavier.
- Consultation Nakala (API REST + IIIF) pour vérification croisée
  et import de notices.

### V3 — Finition et interop

- Versionnement des fichiers (remplacement avec historique).
- Opérations sur scans (rotation persistante, recadrage, scission
  d'un scan multi-pages, fusion).
- Dépôt vers Nakala depuis l'outil.
- OCR intégré.
- Empaquetage distribuable (PyInstaller ou équivalent).

### Hors scope prévisible

- Multi-utilisateurs simultanés avec résolution de conflits.
- Authentification, rôles, droits.
- Déploiement cloud.
- Import direct par glisser-déposer de fichiers externes dans le
  navigateur.

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

### Double granularité item / fichier

Le modèle `Item 1..n Fichier` supporte nativement deux vues qui sont
des concepts de premier ordre dans l'outil :

- **Granularité item** : unité de catalogage (un numéro, un volume,
  une loi, un document archivistique). Vue principale pour la
  consultation bibliothéconomique.
- **Granularité fichier** : unité de numérisation (une page, un scan,
  un fac-similé). Vue principale pour les opérations techniques
  (renommage, dérivés, intégrité) et pour les exports
  Nakala-compatibles.

Les profils d'import déclarent une granularité source (`item` ou
`fichier`). L'interface et la CLI exposeront les deux vues.

### Hiérarchie archivistique

Les collections peuvent être imbriquées via `Collection.parent_id`.
Cas d'usage : fonds d'archives avec séries et sous-séries, éditeur
avec plusieurs revues, bibliothèque avec sous-ensembles thématiques.

Règles :

- Collection racine : `parent_id = NULL`.
- La cote reste unique globalement (pas de cote relative au parent).
- Un item peut être rattaché à une collection à n'importe quel niveau
  de l'arbre.
- Pas d'héritage automatique des métadonnées parent → enfant
  (cohérent avec le principe d'autonomie).
- Pas de limite de profondeur dans le schéma. 2–3 niveaux attendus
  en pratique.
- Validation anti-cycle au niveau applicatif (listener SQLAlchemy
  `before_flush` dans `models/collection.py` — SQLite ne supporte
  pas les CHECK récursifs).
- Cascade de suppression complet : parent → enfants → items des
  enfants.

En complément, certaines collections expriment aussi une hiérarchie
**interne** dans la cote elle-même (exemple : fonds avec cote type
`FA-AA-00-01` encodant fonds/sous-fonds/série/numéro). Cette
hiérarchie interne est parsée à l'import via regex du profil et
stockée dans `Item.metadonnees.hierarchie`. Les deux mécanismes
cohabitent sans se remplacer : `parent_id` exprime l'arborescence
de collections, `metadonnees.hierarchie` décompose la cote d'un
item individuel.

### Conventions de valeur nulle

Les tableurs sources utilisent des sentinelles variées pour
représenter l'absence de valeur : `"none"`, `"n/a"`, `"s.d."`, chaîne
vide, NaN pandas.

Les profils d'import déclareront une liste `valeurs_nulles`
configurable. Ces valeurs sont converties en `NULL` avant toute autre
transformation.

En revanche, les **dates archivistiques incertaines** (`"s.d."`,
`"vers 1964"`, `"1923 ?"`) sont conservées telles quelles dans un
champ texte (format EDTF tolérant), sans normalisation forcée qui
perdrait l'information.

### Nakala comme première classe

Les DOI Nakala sont stockés dans des colonnes dédiées sur `Item` et
`Collection`, pas dans `metadonnees` JSON. Cela permet :

- Une contrainte d'unicité pour détecter les doubles imports.
- Un index pour les requêtes rapides lors de la consultation.
- Une assise claire pour les liens externes riches (V2+ via
  `SourceExterne` / `RessourceExterne` / `LienExterneItem`).

Colonnes :

- `Collection.doi_nakala` : UNIQUE, le DOI de la collection publiée.
- `Item.doi_nakala` : UNIQUE, le DOI de l'item publié.
- `Item.doi_collection_nakala` : non-unique, rattachement à une
  collection Nakala partagée par plusieurs items.

### Identité simplifiée

L'outil ne gère pas d'utilisateurs structurés. Chaque poste est
configuré avec un nom libre dans la config locale
(`utilisateur: "Marie"`). Ce nom est copié comme chaîne de caractères
dans les champs d'audit (`cree_par`, `modifie_par`, `ajoute_par`,
`execute_par`). Aucune contrainte d'unicité, aucune FK.

Si une personne change de nom, ou si deux personnes ont le même nom,
ce n'est pas un problème technique — l'information reste uniquement
informative, pas une clé métier.

### Descriptions publiques vs internes

Les entités structurantes (`Collection`, `ChampPersonnalise`,
`Vocabulaire`, `ValeurControlee`) portent deux types de descriptions :

- `description` : public / catalographique, destinée aux exports
  et aux consultations externes.
- `description_interne` : équipe / chantier, destinée à documenter
  les choix et les conventions pour les catalogueurs qui reprennent
  le travail.

Les deux sont libres (TEXT), aucune structure imposée.

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
- [ ] Faut-il un champ `Collection.ordre` pour ordonner les enfants
      d'un même parent dans la navigation, ou l'ordre alphabétique
      de la cote suffit-il ?
- [ ] Pour la création en série d'items (V2+), où stocker le pattern
      de génération (profil YAML, champ `Collection`, autre) ?
- [ ] Choix du composant de vue tableau éditable pour V2 (AG Grid
      community, Handsontable community, tabulator.js, autre). À
      évaluer en amont de V2.
- [ ] Stratégie d'implémentation des refactorings de métadonnées
      (scinder / fusionner / renommer un champ personnalisé) :
      opération directe avec journal, ou migration applicative avec
      état `a_migrer` temporaire ?
- [ ] Journal de bord : vue calculée pure à partir des tables
      existantes (`ModificationItem`, `OperationFichier`), ou table
      `NoteCollection` pour entrées libres additionnelles ?
- [ ] Intégration FTS5 sur `item` (titre, description, métadonnées).
      **À concevoir après le premier import réel**, pour indexer ce
      qui s'avère utile en pratique — ne pas anticiper. SQL et
      triggers de référence rédigés dans l'historique du projet.
      **Piège à retenir** : `render_as_batch=True` reconstruit la
      table pour certains `ALTER` SQLite et peut perdre les triggers.
      Prévoir `alembic/helpers.py` avec `drop_fts_triggers()` /
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

# Lancer l'application en dev (deux processus)
npm install                          # une fois pour Tailwind
npm run watch:css                    # recompile le CSS à chaque édition
uv run uvicorn archives_tool.api.main:app --reload --port 8000

# Base de démonstration pour explorer l'UI
uv run archives-tool demo init
ARCHIVES_DB=data/demo.db uv run uvicorn archives_tool.api.main:app --reload

# CLI
uv run archives-tool --help

# Import d'un profil (dry-run par défaut)
uv run archives-tool importer profils/ma_collection.yaml

# Import réel avec journal
uv run archives-tool importer profils/ma_collection.yaml \
    --no-dry-run --utilisateur "Marie" --verbose

# Exports canoniques
uv run archives-tool exporter xlsx --collection RDM --sortie inventaire.xlsx
uv run archives-tool exporter dc-xml --collection FA --recursif --sortie fa.xml
uv run archives-tool exporter nakala-csv --collection RDM --etat valide \
    --sortie depot.csv --licence "CC-BY-4.0" --strict

# Aide à la création d'un profil d'import
uv run archives-tool profil analyser inventaire.xlsx --sortie mon_profil.yaml
uv run archives-tool profil init --cote HK --titre "Hara-Kiri" \
    --tableur inventaire.xlsx --sortie squelette.yaml

# Contrôles de cohérence (lecture seule)
uv run archives-tool controler
uv run archives-tool controler --collection HK --recursif
uv run archives-tool controler --check items-vides --check doublons

# Génération de dérivés (vignettes + aperçus)
uv run archives-tool deriver appliquer --collection HK --recursif
uv run archives-tool deriver appliquer --item HK-1960-01 --force
uv run archives-tool deriver nettoyer --collection HK

# Renommage transactionnel
uv run archives-tool renommer appliquer \
    --template "{cote}-{ordre:02d}.{ext}" --collection HK
uv run archives-tool renommer appliquer \
    --template "{cote}.{ext}" --collection HK --no-dry-run --utilisateur "Marie"
uv run archives-tool renommer annuler --batch-id <UUID> --no-dry-run
uv run archives-tool renommer historique

# Visualisation (lecture seule, Rich)
uv run archives-tool montrer collections
uv run archives-tool montrer collections --recursif
uv run archives-tool montrer collection FA
uv run archives-tool montrer item HK-1960-01 --metadonnees-completes
uv run archives-tool montrer fichier 142
uv run archives-tool montrer statistiques

# Migration base
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# Lint / format
uv run ruff check .
uv run ruff format .
```
