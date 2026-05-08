# archives-tool — bibliothèque de composants UI

Bundle handoff pour Claude Code. Dix composants Jinja2 + Tailwind à
intégrer dans les templates existants.

## Contenu

```
handoff/
├── README.md                          ← ce fichier
├── tailwind.config.js                 ← extensions à fusionner
├── docs/
│   └── composants_ui.md               ← guide d'usage de chaque macro
└── templates/components/
    ├── badge_etat.html                ← 1. Badge d'état
    ├── avancement.html                ← 2. Stack chart d'avancement
    ├── cellule_modifie.html           ← 3. Cellule « Modifié » fusionnée
    ├── phase_chantier.html            ← 4. Phase de chantier
    ├── cartouche_metadonnees.html     ← 5. Cartouche style Zotero
    ├── panneau_colonnes.html          ← 6. Configurateur de colonnes
    ├── tableau_collections.html       ← 7. Tableau de collections
    ├── tableau_items.html             ← 8. Tableau d'items
    ├── bandeau_item.html              ← 9. Bandeau d'en-tête
    └── panneau_fichiers.html          ← 10. Panneau fichiers escamotable
```

## Intégration

1. Copier `templates/components/` dans
   `src/archives_tool/web/templates/components/`.
2. Fusionner `tailwind.config.js` dans le fichier existant à la racine
   du repo (les nouvelles entrées sont uniquement sous `theme.extend`).
3. Recompiler le CSS : `npm run build:css`.
4. Mettre à jour les templates de pages selon le tableau en bas de
   `docs/composants_ui.md`.

## Stack respectée

- Python · FastAPI · Jinja2 · Tailwind compilé.
- HTMX pour les interactions (tri, filtres, panneau colonnes).
- Aucune dépendance frontend ajoutée.

## Hors-périmètre (intentionnellement)

- Logique métier (déjà côté Python).
- Interactions complexes — drag-drop des colonnes, édition inline du
  cartouche : le markup expose les hooks `data-…`, le câblage JS est à
  faire dans une passe séparée.
- Visionneuse OpenSeadragon (déjà en place).
- Tests automatisés.

Voir `docs/composants_ui.md` pour les exemples d'usage et les schémas
de données attendus pour chaque macro.
