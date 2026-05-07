# Interface web

Squelette FastAPI + Jinja2 + Tailwind compilé. Lecture seule en V0.5
(tableau de bord et service des dérivés). L'édition arrive en V0.7.

## Lancement en dev

Deux processus à lancer en parallèle :

```bash
# 1. compiler le CSS Tailwind en mode watch
npm install              # une fois pour installer tailwindcss
npm run watch:css        # recompile à chaque modification de template

# 2. lancer le serveur FastAPI
uv run uvicorn archives_tool.api.main:app --reload --port 8000
```

Pour tester sur la base de démonstration sans toucher à la base de
production :

```bash
uv run archives-tool demo init             # crée data/demo.db
ARCHIVES_DB=data/demo.db uv run uvicorn archives_tool.api.main:app --reload
```

`ARCHIVES_DB` prime sur `data/archives.db`. Sans cette variable, la
base par défaut est utilisée.

## Architecture

```
src/archives_tool/
├── api/
│   ├── main.py          # app FastAPI, mounts, filtres Jinja
│   ├── deps.py          # session DB, utilisateur courant, racines
│   ├── routes/          # un fichier par groupe de routes
│   │   ├── dashboard.py
│   │   └── derives.py
│   └── services/        # logique métier pure (testable sans HTTP)
│       └── dashboard.py
└── web/
    ├── templates/       # Jinja2 (base, components, dashboard)
    └── static/
        ├── css/
        │   ├── input.css      # source Tailwind
        │   └── output.css     # compilé (gitignoré)
        └── js/
```

Les services renvoient des dataclasses ; les routes ne font qu'appeler
les services et passer les données au template. Aucun calcul métier
dans les routes ou les templates.

## Conventions templates

- `base.html` : layout commun (header, contenu).
- `components/` : fragments réutilisables (`metric_card.html`,
  `collection_row.html`, `header.html`).
- `dashboard.html` : page complète, étend `base.html`.

Filtres Jinja exposés par `main.py` :

| Filtre              | Effet                                           |
| ------------------- | ----------------------------------------------- |
| `libelle_phase`     | `PhaseChantier` → libellé français lisible.     |
| `temps_relatif`     | `datetime` → « il y a 3h » approximatif.        |
| `taille_humaine`    | octets → « 4.2 MB » via `formater_taille_octets`.|

## Service des dérivés

`GET /derives/{racine}/{chemin}` sert un fichier sous une racine
configurée dans `config_local.yaml`. Garde-fous :

- racine inconnue → 403,
- chemin contenant `..` ou absolu → 403,
- chemin résolu hors de la racine (suit les symlinks) → 403,
- fichier absent → 404.

L'URL miroite la convention de stockage du module
[derivatives](derivatives.md) : `/derives/miniatures/vignette/HK/01.jpg`
sert `<racine miniatures>/vignette/HK/01.jpg`.

## Ajouter une nouvelle page

1. **Service** : nouvelle fonction dans `api/services/<domaine>.py`,
   pure, testable. Retourne des dataclasses.
2. **Route** : nouveau fichier `api/routes/<domaine>.py` avec un
   `APIRouter()`. Importer les dépendances de `api/deps.py`. Pas de
   logique métier ici.
3. **Template** : `web/templates/<domaine>.html` étendant `base.html`.
   Réutiliser les composants quand possible.
4. **Tests** : `test_<domaine>_services.py` (pur Python) et
   `test_<domaine>_routes.py` (TestClient FastAPI).
5. **Inclure le routeur** dans `main.py`
   (`app.include_router(<domaine>.router)`).

## Limites V0.5

- Lecture seule : aucune édition possible depuis l'UI.
- Pas de visionneuse OpenSeadragon (V0.6).
- Boutons « Rechercher » et « Importer » sont des placeholders.
- Liens « Tout voir → » et « Lancer un contrôle complet → » pointent
  vers `#`, vraies cibles en V0.6.
- Tri des colonnes du tableau pas encore interactif (V0.6 via HTMX).
