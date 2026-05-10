# Architecture

Vue d'ensemble de l'organisation du code de ColleC. Pour les
concepts métier, voir [Concepts](../guide/concepts.md).

## Couches

ColleC suit une architecture en couches classique :

```
┌─────────────────────────────────────────────────┐
│  CLI (typer)         │  Web UI (FastAPI/Jinja)  │
├─────────────────────────────────────────────────┤
│           Services métier (api/services/)       │
├─────────────────────────────────────────────────┤
│           Modèle ORM (SQLAlchemy / SQLite)      │
├─────────────────────────────────────────────────┤
│  files     │  importers  │  exporters  │  qa    │
│  renamer   │  derivatives                        │
└─────────────────────────────────────────────────┘
```

- **CLI** et **Web UI** sont des couches fines : elles parsent
  les entrées, appellent les services, formatent la sortie.
  Aucune logique métier dans les routes ou les commandes.
- **Services métier** encapsulent toute la logique : validation
  Pydantic, invariants, transactions. Ils sont composables
  depuis du code Python (cf. [Services](services.md)).
- **Modèle ORM** exprime les invariants en CHECK constraints
  et `ondelete` quand SQLite le permet ; les invariants plus
  riches sont en code (services + contrôles qa).
- **Modules transversaux** (`files`, `importers`, `exporters`,
  `qa`, `renamer`, `derivatives`) encapsulent des
  responsabilités métier transverses appelées par les services
  et les CLI.

## Arborescence

```
src/archives_tool/
├── api/
│   ├── routes/         # FastAPI routes web
│   ├── services/       # Logique métier (couche centrale)
│   ├── deps.py         # Sessions, racines, identité
│   └── templating.py   # Jinja2 + filtres
├── cli.py              # Commandes typer
├── config.py           # Chargement config_local.yaml
├── db.py               # Engine SQLite + pragmas WAL/FK
├── derivatives/        # Génération vignettes/aperçus
├── exporters/          # Dublin Core, Nakala CSV, xlsx
├── files/              # Résolution chemins + hash
├── importers/          # Profils v2 + écrivain transactionnel
├── models/             # SQLAlchemy ORM par domaine
├── profils/            # Schéma Pydantic + loader + générateur
├── qa/                 # 14 contrôles de cohérence
├── renamer/            # Renommage transactionnel + annulation
└── web/                # Templates Jinja2 + statiques
```

## Patterns systématiques

ColleC suit quelques patterns transverses :

- **Pydantic Form models** pour toutes les saisies (CLI et UI).
  Ex. `FormulaireFonds`, `FormulaireItem`, `FormulaireCollection`.
- **Erreurs métier hiérarchiques** dans `services/_erreurs.py` :
  `EntiteIntrouvable`, `FormulaireInvalide`, `OperationInterdite`.
- **Pattern PRG** (Post-Redirect-Get) pour les formulaires web.
- **Périmètre dataclass** (`renamer.Perimetre`) pour les CLI qui
  ciblent des fonds/collections/items/fichiers, partagé entre
  `renommer` et `deriver`.
- **Invariants explicites** vérifiés par tests dédiés et par les
  [contrôles qa](../reference/controles.md).
- **Idempotence** systématique sur les services destructifs
  (suppression, retrait d'item d'une collection, etc.).

Pour le détail de chaque couche : [Modèle](modele.md),
[Services](services.md), [Tests](tests.md).

## Choix techniques

| Composant            | Choix                                                                  |
| -------------------- | ---------------------------------------------------------------------- |
| Base de données      | SQLite (mode WAL pour concurrence en lecture)                          |
| Gestion dépendances  | uv                                                                     |
| Validation           | Pydantic v2                                                            |
| Web                  | FastAPI + Jinja2 + HTMX + Tailwind compilé                             |
| Visionneuse          | OpenSeadragon (V2+ ; V0.9.0 utilise un `<img>` direct)                 |
| CLI                  | Typer + Rich pour le rendu                                             |
| Documentation        | MkDocs Material + Mermaid                                              |
| Tests                | pytest + ruff                                                          |
| ORM                  | SQLAlchemy 2.x style                                                   |
| Migrations           | Alembic                                                                |

## Boundaries

Les conventions à respecter :

- Les **services** ne font pas d'écriture sur le système de
  fichiers — réservé aux modules `files/`, `derivatives/`,
  `renamer/`.
- Les **modules transversaux** ne dépendent pas des services
  (sauf cas justifiés : `importers/ecrivain.py` réutilise
  `creer_fonds`, `creer_item` pour ne pas dupliquer la logique
  d'invariant).
- Les **routes web** délèguent immédiatement aux services et
  rendent un template — pas de logique conditionnelle au-delà
  du flux GET/POST.
- Les **CLI** délèguent immédiatement aux services et formatent
  via Rich — pas de SQL direct.
