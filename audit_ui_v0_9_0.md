# Audit UI V0.9.0 — écart par rapport à V0.6.0.1 (Claude Design)

**Date :** 2026-05-10  
**Branche :** `main` (commit `887cd1e`)  
**Périmètre :** lecture seule, aucune modification de code.

Audit déclenché par le constat que la refonte modèle V0.9.0-beta a
livré des templates simplifiés qui n'exploitent qu'une fraction des
composants riches développés en V0.6.0.1. Cette page recense les
écarts pour planifier une session de restauration ergonomique.

## 1. Composants : présents / orphelins / absents

Inventaire de `src/archives_tool/web/templates/components/` (22
fichiers) confronté au **bundle Claude Design V0.6.0.1** mentionné
dans `CLAUDE.md`.

### Composants présents et **effectivement utilisés**

| Composant                          | Macro / type        | Utilisé par                                                                       |
| ---------------------------------- | ------------------- | --------------------------------------------------------------------------------- |
| `header.html`                      | include direct      | `base.html` (tous les rendus pleins).                                             |
| `metric_card.html`                 | include direct      | `dashboard.html` (×5 cartes : Fonds, Collections, Items, Fichiers, Validés).      |
| `tableau_fonds_enrichi.html`       | include direct      | `dashboard.html` (par fonds).                                                     |
| `_collection_transversale.html`    | include direct      | `dashboard.html` (par transversale).                                              |
| `cellule_modifie.html`             | macro `cellule_modifie` | `dashboard.html` (activité), `tableau_fonds_enrichi`, `_collection_transversale`. |
| `avancement.html`                  | macro `avancement_compact` | `tableau_fonds_enrichi`, `_collection_transversale`. **`avancement_detaille` orphelin.** |
| `_champ_form.html`                 | macros `champ`, `textarea`, `selecteur`, `cases_a_cocher` | tous les formulaires d'édition (`fonds_modifier`, `collection_modifier`, `item_modifier`, etc.). |
| `breadcrumb.html`                  | include direct      | `pages/collection_nouvelle.html`, `pages/import_placeholder.html`.                |
| `badge_etat.html`                  | macro `badge_etat`  | **`partials/collection_fichiers.html` uniquement** — partial relié à `pages/collection.html` qui est dead code (voir plus bas). |
| `tableau_collections.html`         | macro `tableau_collections` | `partials/dashboard_collections.html`, `partials/collection_sous_collections.html`. |
| `tableau_items.html`               | macro `tableau_items` | `partials/collection_items.html`.                                                |
| `panneau_colonnes.html`            | macro `panneau_colonnes` | `partials/collection_items.html`.                                              |
| `pagination.html`                  | include direct      | `partials/collection_fichiers.html`.                                              |

### Composants présents mais **orphelins** (zéro callsite)

| Composant                          | Statut                                                                                |
| ---------------------------------- | ------------------------------------------------------------------------------------- |
| `phase_chantier.html`              | macro `phase_chantier` jamais appelée. Or les fonds/collections ont un `phase`.       |
| `avancement.html` (`avancement_detaille`) | la variante détaillée (avec légende) n'est appelée nulle part — seule la compacte.   |
| `collection_row.html`              | legacy V0.6, plus aucun include.                                                      |
| `panneau_colonnes_modale.html`     | aucun include dans le projet (la V0.7 a basculé sur le drawer non-modal).             |
| `panneau_filtres.html`             | uniquement appelé dans `pages/collection.html` qui n'est pas routée (voir §3).        |
| `tabs.html`, `collection_header.html` | idem : appelés uniquement dans `pages/collection.html` (dead).                     |
| `section_collaborateurs.html`      | aucun include trouvé. La page fonds gère les collaborateurs en HTML inline.           |
| `_ligne_colonne_active.html`, `_ligne_colonne_dispo.html` | partials internes du panneau colonnes (V0.7) — utilisés via HTMX, pas par include direct. À conserver. |

### Composants **absents** du dossier

Le bundle Claude Design V0.6.0.1 a documenté plusieurs macros qui
**n'existent plus** dans `templates/components/` :

| Composant attendu                  | Statut       | Conséquence                                                                                         |
| ---------------------------------- | ------------ | --------------------------------------------------------------------------------------------------- |
| `cartouche_metadonnees.html`       | ❌ absent     | Item.lecture affiche les métadonnées en `<dl>` brut (item_lecture.html:63-85) — pas de cartouche style Zotero. |
| `bandeau_item.html`                | ❌ absent     | Item.lecture utilise un `<header>` direct sans bandeau riche (titre + cote + état + collections).   |
| `panneau_fichiers.html`            | ❌ absent     | Item.lecture rend le tableau des fichiers en HTML direct sans panneau gauche escamotable.           |

## 2. Visionneuse OpenSeadragon : statut actuel

### Infrastructure présente

- ✅ **JS vendor** : `web/static/js/vendor/openseadragon/openseadragon.js` (v4.1.1, ~250 KB).
- ✅ **Service de résolution** : `api/services/sources_image.py` calcule la `SourceImage` à passer (priorité IIIF Nakala → DZI local → aperçu local).
- ✅ **Modèle** : `Fichier.iiif_url_nakala` (pour Nakala) + `Fichier.dzi_chemin` (réservé V2+) + `Fichier.apercu_chemin` (utilisé).
- ✅ **Endpoint statique** : `/derives/{racine}/{chemin}` sert les binaires via la route `derives.py`.

### Ce qui manque / est désactivé

- ❌ **Aucun template ne charge `openseadragon.js`** : `grep openseadragon templates/` ne retourne rien.
- ❌ **`pages/item_lecture.html` utilise un `<img>` direct** (lignes 145-163) avec fallback message+download pour les formats non supportés navigateur (TIFF, PDF…). Le service `sources_image.resoudre_source_image` n'est **jamais appelé** par les routes ; rien ne le branche.
- ❌ **Aucun générateur DZI dans `derivatives/`** : `archives-tool deriver` produit uniquement vignette + aperçu (`derivatives/generateur.py`). `Fichier.dzi_chemin` est réservé V2+ par convention, jamais peuplé.

### Conclusion

La visionneuse riche est **(b) désactivée par omission**. L'infrastructure
JS + service + champs DB est en place mais aucun chemin dans les
routes ne l'instancie. La page item rend un `<img>` plat, ce qui est
volontaire pour V0.9.0-beta.3 (cf. `CLAUDE.md` §Interface web —
*« V0.9.0-beta.3 utilise un `<img>` direct ; le pipeline IIIF Nakala
/ OpenSeadragon est prévu pour V2 »*) mais hérite d'une fenêtre de
visualisation appauvrie pour TIFF, multi-pages, zoom haute résolution.

## 3. Pages : écart par rapport à V0.6.0.1

### 3.a Dashboard — **largement restauré**

Page : `templates/dashboard.html` (route `/`).

| V0.6.0.1 attendu               | V0.9.0 (commit 887cd1e)              | Statut |
| ------------------------------ | ------------------------------------ | ------ |
| Cartes statistiques globales   | 5 `metric_card` (Fonds, Collections, Items, Fichiers, Validés) | ✅ restauré V0.9.1-dev |
| Arborescence Fonds dépliable   | `tableau_fonds_enrichi`              | ✅      |
| Avancement par fonds           | `avancement_compact` par fonds       | ✅      |
| Avancement par collection      | `avancement_compact` par collection  | ✅      |
| Cellule modifié par fonds      | `cellule_modifie` (par + temps relatif) | ✅   |
| Phase chantier (badge)         | rendu textuel inline (`{{ col.phase | libelle_phase }}`) | ⚠️ partiel — le composant `phase_chantier.html` n'est pas utilisé |
| Section transversales          | `_collection_transversale` enrichi   | ✅      |
| Activité récente               | section conditionnelle, 10 dernières | ✅      |

**Verdict :** dashboard rétabli en V0.9.1-dev. **Léger écart** : le
composant `phase_chantier` n'est pas employé alors qu'il existe. La
phase est affichée en texte simple. Cosmétique.

### 3.b Page Fonds (lecture) — **dépouillée**

Page : `templates/pages/fonds_lecture.html` (route `/fonds/{cote}`).

| V0.6.0.1 attendu              | V0.9.0 réel                                    | Statut |
| ----------------------------- | ---------------------------------------------- | ------ |
| Bandeau métadonnées riche     | `<header>` avec `<dl>` HTML direct             | ⚠️ pas de composant — à ré-extraire |
| Liste collections du fonds    | `<ul>` HTML inline, pas de `tableau_collections` | ⚠️ écart — composant existe (utilisé sur dashboard partial) |
| Avancement par collection     | absent                                         | ❌      |
| Cellule modifié par collection| absent                                         | ❌      |
| Items récents                 | `<table>` inline                               | ⚠️ écart — pas de réutilisation `tableau_items` |
| Phase chantier                | absent                                         | ❌      |
| Section collaborateurs        | rendu HTML inline (formulaire de création), pas de `section_collaborateurs.html` | ⚠️ orphelin |

**Verdict :** la page fonds est **fonctionnelle mais pauvre
visuellement**. Aucune barre d'avancement, aucune cellule modifié.
La liste de collections devrait pouvoir réutiliser `tableau_collections`.

### 3.c Page Collection (lecture) — **dépouillée**

Page **active** : `templates/pages/collection_lecture.html` (route
`/collection/{cote}` dans `dashboard.py:270`).

| V0.6.0.1 attendu              | V0.9.0 réel                                    | Statut |
| ----------------------------- | ---------------------------------------------- | ------ |
| `collection_header`           | `<header>` HTML inline                         | ⚠️ écart |
| Onglets (`tabs.html`)         | absent (page mono-section)                     | ❌      |
| Filtre via `panneau_filtres`  | `<form>` HTML inline (filtre par état seul)    | ⚠️ panneau existe mais inutilisé |
| Configurateur colonnes (`panneau_colonnes`) | absent                          | ❌      |
| Tableau items (`tableau_items`)               | `<table>` HTML inline           | ⚠️ macro existe et est utilisée par `partials/collection_items.html` mais la page active ne l'utilise pas |
| Pagination (`pagination.html`)| `<nav>` inline                                 | ⚠️ écart — composant existe |
| Avancement de la collection   | absent                                         | ❌      |
| Cellule modifié par item      | `temps_relatif` sans `cellule_modifie`         | ⚠️ écart |

**Verdict critique** : il existe **deux pages collection** :

- `pages/collection_lecture.html` (V0.9.0, active, simple) — **rendue par dashboard.py:309**.
- `pages/collection.html` (V0.6.0.1, riche, avec tabs/panneaux) — référencée par `routes/collection.py:163` mais **ce router n'est pas inclus dans `api/main.py`**. Donc dead code.

→ Le code riche existe mais n'est pas branché. Restaurer = soit
brancher l'ancien router (rapide mais peut casser le V0.9.0), soit
adapter `collection_lecture.html` pour utiliser les composants.

### 3.d Page Item (lecture) — **dépouillée**

Page : `templates/pages/item_lecture.html` (route `/item/{cote}` dans
`dashboard.py:541`).

| V0.6.0.1 attendu              | V0.9.0 réel                                    | Statut |
| ----------------------------- | ---------------------------------------------- | ------ |
| Bandeau item (`bandeau_item.html`) | `<header>` HTML inline                    | ❌ composant absent du dossier |
| Cartouche métadonnées (`cartouche_metadonnees`) | `<dl>` HTML direct                | ❌ composant absent |
| Visionneuse OpenSeadragon     | `<img>` direct (V0.9.0-beta.3 documenté)       | ❌ JS présent mais non chargé |
| Panneau gauche fichiers (`panneau_fichiers`) | `<table>` inline               | ❌ composant absent |
| Liste collections d'appartenance | `<ul>` HTML inline avec badges manuels      | ⚠️ pas de composant dédié |

**Verdict :** la page item est la **plus dépouillée** des 4. Trois
composants riches du bundle V0.6.0.1 (`bandeau_item`,
`cartouche_metadonnees`, `panneau_fichiers`) sont **absents du dossier**.

## 4. Plan de restauration estimé

Effort en heures Claude Code, ventilé par catégorie de travail :

### Niveau 1 — Travail simple (réutilisation de macros existantes)

| Tâche                                                                                | Page concernée   | Effort  |
| ------------------------------------------------------------------------------------ | ---------------- | ------- |
| Brancher `phase_chantier(col.phase)` au lieu du rendu texte sur le dashboard         | `dashboard.html` | 15 min  |
| Réutiliser `tableau_collections` pour la liste collections sur la page fonds         | `fonds_lecture`  | 1-2h    |
| Ajouter `avancement_compact` + `cellule_modifie` sur la liste collections du fonds   | `fonds_lecture`  | 1h      |
| Réutiliser `tableau_items` + `pagination` sur la page collection                     | `collection_lecture` | 1-2h |
| Ajouter `avancement_detaille` en tête de page collection                             | `collection_lecture` | 30 min |

**Sous-total niveau 1** : ~4-6h. Bénéfice immédiat : dashboard +
fonds + collection cohérents visuellement avec le bundle d'origine.

### Niveau 2 — Travail moyen (adaptation données service ↔ macro)

| Tâche                                                                                | Page concernée   | Effort  |
| ------------------------------------------------------------------------------------ | ---------------- | ------- |
| Brancher `section_collaborateurs.html` (orphelin) sur la page fonds                  | `fonds_lecture`  | 2-3h    |
| Brancher `panneau_filtres` + `panneau_colonnes` sur la page collection (les rebrancher proprement, sans casser la page active) | `collection_lecture` | 3-4h |
| Service `composer_page_fonds` enrichi avec `repartition_etats` + `modifie_*` par collection (pour réutilisation des macros enrichies du dashboard) | `services/dashboard.py` | 2h |

**Sous-total niveau 2** : ~7-9h.

### Niveau 3 — Travail complexe (recréation de composants absents)

| Tâche                                                                                | Page concernée   | Effort  |
| ------------------------------------------------------------------------------------ | ---------------- | ------- |
| Recréer `bandeau_item.html` (titre + cote + état + collections en bandeau riche)     | `item_lecture`   | 3-4h    |
| Recréer `cartouche_metadonnees.html` (style Zotero, sections collapsibles, hooks `data-edit-field`) | `item_lecture` | 6-8h |
| Recréer `panneau_fichiers.html` (panneau gauche escamotable avec liste fichiers, liens HTMX vers visionneuse) | `item_lecture` | 4-6h |
| Brancher OpenSeadragon (charger le JS, instancier la visionneuse, câbler `sources_image.resoudre_source_image`, gérer fallback) | `item_lecture` | 6-8h |
| Ajouter générateur DZI dans `derivatives/` (V2+ — pyvips) pour les très grandes images | `derivatives/`  | 4-6h    |

**Sous-total niveau 3** : ~23-32h.

### Total estimé

| Plan                                                                                 | Effort approx | Résultat                                            |
| ------------------------------------------------------------------------------------ | ------------- | --------------------------------------------------- |
| **Restauration ciblée** (niveaux 1 + 2)                                              | 11-15h        | Dashboard + Fonds + Collection cohérents avec V0.6.0.1. Item reste dépouillé. |
| **Restauration complète** (niveaux 1 + 2 + 3 sans DZI)                              | 28-39h        | Toutes pages restaurées y compris bandeau item et cartouche métadonnées riche, plus visionneuse OpenSeadragon basique (zoom + tuiles JPEG via aperçu). |
| **Restauration complète + DZI**                                                      | 32-45h        | Idem + génération de tuiles DZI pour zoom haute résolution sur les TIFF lourds. |

## 5. Recommandation

**Plan recommandé : restauration ciblée (niveaux 1 + 2), ~12-15h.**

Justifications :

1. **ROI maximal sur les pages quotidiennes.** Dashboard + Fonds +
   Collection sont les pages les plus consultées. Les rendre
   cohérentes visuellement avec le bundle d'origine restaure
   l'ergonomie sur 80% des sessions de travail.

2. **Item reste fonctionnel.** La page item rend les métadonnées,
   les fichiers, et un `<img>` qui marche pour les formats web
   natifs (PNG/JPG/GIF/WebP/SVG = la majorité des aperçus). Le
   fallback download couvre TIFF/PDF.

3. **OpenSeadragon = piège chronophage.** L'infrastructure existe
   mais le câblage est non-trivial (gestion des 3 sources iiif/dzi/
   image, événement `open-failed`, fallback). À reporter en V2+
   quand le besoin de zoom haute résolution sera réel sur un fonds
   d'usage.

4. **`bandeau_item` + `cartouche_metadonnees` = ré-engineering.** Ces
   composants sont absents du dossier et le bundle Claude Design
   d'origine n'est plus accessible. Les recréer demande de
   redessiner — pas un simple « brancher la macro ». Risque
   d'écart par rapport à l'intention initiale.

### Plan de session « restauration ciblée » V0.9.2-alpha

Cible : 1-2 sessions, 6h chacune. Clôturée par un bump V0.9.2.

**Session 1 (6h)** — Pages Fonds + Collection :

- Enrichir `composer_page_fonds` avec `repartition_etats` + `modifie_*`
  par collection (pattern déjà appliqué au dashboard, à généraliser).
- Brancher `tableau_collections` (avec avancement) sur la page fonds.
- Brancher `tableau_items` + `pagination` sur la page collection.
- Ajouter `avancement_detaille` en tête de page collection.
- Brancher `phase_chantier` sur dashboard et page fonds.
- Tests d'intégration des routes (vérifier non-régression du
  rendu HTML).

**Session 2 (6h, optionnelle)** — Filtres et collaborateurs :

- Brancher `panneau_filtres` sur la page collection (filtre étendu :
  date, langue, type COAR au lieu du seul filtre par état).
- Brancher `panneau_colonnes` sur la page collection (drag-drop
  Sortable.js déjà en JS vendor).
- Brancher `section_collaborateurs.html` sur la page fonds (en
  remplacement du HTML inline actuel).

### Hors scope (à reporter)

- **Item refait riche** — V0.9.3 ou V1.0 selon priorité.
- **OpenSeadragon** — V2 quand le besoin de zoom haute résolution
  sera identifié sur un fonds réel.
- **Suppression du dead code** (`pages/collection.html`,
  `routes/collection.py`, `partials/collection_items.html` si non
  réutilisés, `panneau_colonnes_modale.html`, `collection_row.html`)
  — à faire en passe de simplification, pas en session de
  restauration.

## Annexe — fichiers consultés

- `src/archives_tool/web/templates/components/` (22 fichiers).
- `src/archives_tool/web/templates/pages/` (13 fichiers).
- `src/archives_tool/web/templates/partials/` (6 fichiers).
- `src/archives_tool/web/static/js/vendor/openseadragon/openseadragon.js`.
- `src/archives_tool/api/routes/dashboard.py` (routes registrées).
- `src/archives_tool/api/routes/collection.py` (router non inclus dans `main.py`).
- `src/archives_tool/api/services/sources_image.py`.
- `src/archives_tool/derivatives/generateur.py`.
- `CLAUDE.md` §Interface web (référence du bundle Claude Design).
