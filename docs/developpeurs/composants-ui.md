# Composants UI

Les pages web de ColleC sont composées de macros Jinja2
réutilisables dans
[`web/templates/components/`]({{ repo_tree }}/src/archives_tool/web/templates/components).
Cette page liste les composants disponibles et leur rôle, pour
faciliter la création d'une nouvelle page cohérente avec
l'existant.

## Conventions de design

- **Tailwind compilé** via la CLI npm (`npm run build:css`),
  jamais via CDN. `output.css` est gitignoré.
- **HTMX** pour les interactions dynamiques (tri, filtres,
  drag-drop, swap partiel).
- **Pas de framework JS** au-delà : Sortable.js pour le drag-drop,
  OpenSeadragon pour la visionneuse riche (V2+, V0.9.0 utilise
  un `<img>` direct).
- **Tokens** : `border-tertiary`, `border-secondary`,
  `border-primary` pour les opacités du noir ; `state-info`,
  `state-warn`, `state-ok`, `state-err` pour les sémantiques.
- **Densités** : *aérée* (16 px de padding vertical) pour le
  dashboard et les bandeaux ; *dense* (12 px) pour les tableaux
  et cartouches.

## Composants par catégorie

### États et indicateurs

| Macro                  | Fichier                                | Rôle                                                     |
| ---------------------- | -------------------------------------- | -------------------------------------------------------- |
| `badge_etat`           | `badge_etat.html`                      | Badge état item ou fichier (point coloré sur fond gris). |
| `phase_chantier`       | `phase_chantier.html`                  | Sous-titre phase de chantier d'une collection.           |
| `cellule_modifie`      | `cellule_modifie.html`                 | Cellule « *Marie* · il y a 2h » dans un tableau.         |
| `avancement` (compact / detaillé) | `avancement.html`           | Stack chart de la répartition d'états (collection).      |

### Tableaux

| Macro                  | Fichier                                | Rôle                                                     |
| ---------------------- | -------------------------------------- | -------------------------------------------------------- |
| `tableau_fonds`        | `tableau_fonds.html`                   | Liste des fonds (dashboard).                             |
| `tableau_collections`  | `tableau_collections.html`             | Liste des collections d'un fonds.                        |
| `tableau_items`        | `tableau_items.html`                   | Liste des items (page collection).                       |
| `pagination`           | `pagination.html`                      | Contrôles de pagination (prev/next, sauter à la page).   |

### Filtres et préférences

| Macro                       | Fichier                                | Rôle                                                |
| --------------------------- | -------------------------------------- | --------------------------------------------------- |
| `panneau_filtres`           | `panneau_filtres.html`                 | Drawer latéral (filtre/recherche).                  |
| `panneau_colonnes`          | `panneau_colonnes.html`                | Drawer config colonnes (drag-drop Sortable.js).     |
| `panneau_colonnes_modale`   | `panneau_colonnes_modale.html`         | Variante modale du panneau colonnes.                |
| `_ligne_colonne_active`     | `_ligne_colonne_active.html`           | Ligne d'une colonne sélectionnée (drag-drop).       |
| `_ligne_colonne_dispo`      | `_ligne_colonne_dispo.html`            | Ligne d'une colonne disponible (drag-drop).         |

### Layout et navigation

| Macro                  | Fichier                                | Rôle                                                     |
| ---------------------- | -------------------------------------- | -------------------------------------------------------- |
| `header`               | `header.html`                          | Barre de navigation supérieure.                          |
| `breadcrumb`           | `breadcrumb.html`                      | Fil d'Ariane (Accueil → Fonds → Collection).             |
| `tabs`                 | `tabs.html`                            | Onglets (utilisé sur la page Fonds).                     |
| `metric_card`          | `metric_card.html`                     | Carte de métrique (chiffre + label, dashboard).          |
| `collection_header`    | `collection_header.html`               | Bandeau d'en-tête d'une collection.                      |
| `collection_row`       | `collection_row.html`                  | Ligne d'une collection (legacy V0.6, conservé).          |

### Spécifique par entité

| Macro                       | Fichier                                | Rôle                                                |
| --------------------------- | -------------------------------------- | --------------------------------------------------- |
| `_collection_transversale`  | `_collection_transversale.html`        | Variante d'affichage pour les transversales (fonds représentés). |
| `section_collaborateurs`    | `section_collaborateurs.html`          | Section collaborateurs (groupage par rôle).         |
| `menu_importer`             | `menu_importer.html`                   | Menu déroulant « Importer » sur la page Fonds.      |

### Formulaires

| Macro                  | Fichier                                | Rôle                                                     |
| ---------------------- | -------------------------------------- | -------------------------------------------------------- |
| `_champ_form`          | `_champ_form.html`                     | Champ générique (label + input + erreurs Pydantic).      |

## Conventions d'usage

- **Une macro = un fichier** dans `components/`. Le nom du fichier
  correspond à la macro principale.
- **Préfixe `_`** sur les fichiers réservés à un usage interne
  (composition par d'autres macros, pas par les pages).
- **Paramètres** : une macro accepte typiquement un seul objet
  métier (passé depuis Python) ou un dict de contexte.
  Évitez les chaînes de paramètres positionnels.
- **Pas de logique métier dans les templates** : les calculs
  (formatage, tris, agrégations) se font dans les services
  Python, pas dans Jinja.

## Ajouter une nouvelle page

1. **Service** : fonction de composition dans
   `api/services/dashboard.py` (ou un nouveau fichier de service)
   qui retourne une dataclass de contexte.
2. **Route** : nouvelle route dans `api/routes/`. Le rôle de la
   route est de récupérer la session, appeler le composeur,
   rendre le template.
3. **Template** : `web/templates/pages/<nom>.html`. Hériter de
   `base.html`. Importer les composants nécessaires depuis
   `components/`.
4. **Test** : `tests/test_<domaine>_routes.py` pour la route,
   `tests/test_<domaine>_services.py` pour le composeur.

## Voir aussi

- [Architecture](architecture.md) — couches du code.
- [Services](services.md) — patterns des composeurs.
- [Interface web](../guide/interface-web.md) — vue côté
  utilisateur.
- Code source des composants :
  [`web/templates/components/`]({{ repo_tree }}/src/archives_tool/web/templates/components).
