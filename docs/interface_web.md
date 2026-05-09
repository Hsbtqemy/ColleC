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
- `components/` : fragments réutilisables (voir « Bibliothèque de
  composants » ci-dessous).
- `dashboard.html` : page complète, étend `base.html`.

Filtres Jinja exposés par `templating.py` :

| Filtre              | Effet                                           |
| ------------------- | ----------------------------------------------- |
| `libelle_phase`     | `PhaseChantier` → libellé français lisible.     |
| `libelle_etat`      | `EtatCatalogage` → libellé (« vérifié », …).    |
| `temps_relatif`     | `datetime` → « il y a 3h » approximatif.        |
| `taille_humaine`    | octets → « 4.2 MB » via `formater_taille_octets`.|

## Bibliothèque de composants

Les dix composants Jinja2 de [`docs/composants_ui.md`](composants_ui.md)
sont la **référence visuelle de vérité** (validés en design). Aucune
réinterprétation : si une décision de markup ou de classe Tailwind
semble inhabituelle, elle est intentionnelle.

| Macro                  | Fichier                                        | Usage                                  |
| ---------------------- | ---------------------------------------------- | -------------------------------------- |
| `badge_etat`           | `components/badge_etat.html`                   | Badge état item ou fichier             |
| `avancement_compact`   | `components/avancement.html`                   | Stack chart 6 px (dashboard)           |
| `avancement_detaille`  | `components/avancement.html`                   | Stack chart 8 px + légende (collection)|
| `cellule_modifie`      | `components/cellule_modifie.html`              | Cellule « Marie · il y a 2h »          |
| `phase_chantier`       | `components/phase_chantier.html`               | Sous-titre phase                       |
| `cartouche_*`          | `components/cartouche_metadonnees.html`        | Cartouche style Zotero                 |
| `panneau_colonnes`     | `components/panneau_colonnes.html`             | Drawer config colonnes (V0.7+)         |
| `tableau_collections`  | `components/tableau_collections.html`          | Dashboard, sous-collections            |
| `tableau_items`        | `components/tableau_items.html`                | Onglet items d'une collection          |
| `bandeau_item`         | `components/bandeau_item.html`                 | En-tête vue item                       |
| `panneau_fichiers`     | `components/panneau_fichiers.html`             | Panneau gauche escamotable             |

Composants existants antérieurs (`header.html`, `breadcrumb.html`,
`metric_card.html`, `collection_header.html`, `tabs.html`,
`collection_row.html`) sont conservés. `collection_row.html` n'est
plus référencé après le refactor V0.6.0.1 mais reste disponible.

Schémas attendus, exemples d'usage et détails des hooks `data-…` :
voir [`docs/composants_ui.md`](composants_ui.md).

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

## Vues V0.6.0

### Vue collection — `/collection/{cote}/...`

Trois onglets, une route par onglet. Pattern « même route, deux modes » :
- accès direct → page complète (bandeau + onglets + contenu) ;
- accès via HTMX (en-tête `HX-Request`) → uniquement le contenu, prêt
  à être swappé dans `#tab-content`.

Les liens d'onglets utilisent `hx-get`, `hx-target="#tab-content"`,
`hx-push-url="true"` : navigation fluide, URL synchronisée et
bookmarkable, fallback complet si JS désactivé.

| Route                                          | Onglet            |
| ---------------------------------------------- | ----------------- |
| `/collection/{cote}` (redirige)                | → /items          |
| `/collection/{cote}/items`                     | Items             |
| `/collection/{cote}/sous-collections`          | Sous-collections  |
| `/collection/{cote}/fichiers`                  | Fichiers          |

### Vue item — `/item/{cote}`

Bandeau au-dessus (`bandeau_item`) puis trois zones horizontales :

1. **Panneau fichiers escamotable** (gauche, `panneau_fichiers`) —
   trois états : `collapsed` (32 px, label vertical), `hover`
   (220 px en overlay, déclenché par survol après 250 ms),
   `pinned` (220 px qui pousse le layout, déclenché par clic).
2. **Cartouche métadonnées** (largeur fixe 460 px, `cartouche_*`) —
   sections Identification / Identifiants externes / Champs
   personnalisés / Description.
3. **Visionneuse** (flex-1, à droite) — OpenSeadragon, bandeau
   supérieur avec le nom du fichier actif. Source résolue côté
   serveur (voir « Architecture multi-sources » ci-dessous).

L'ordre est validé en design — les métadonnées sont à gauche de la
visionneuse, pas à droite.

Paramètres :
- `?collection=COTE` désambiguïse une cote item non unique ;
- `?fichier=ID` pré-sélectionne un fichier à l'ouverture.

JS associé :
- `web/static/js/visionneuse.js` — pilote OpenSeadragon, écoute les
  clicks sur `[data-fichier-id]` dans `[data-panneau-fichiers]`.
- `web/static/js/panneau_fichiers.js` — bascule `data-state`
  collapsed/hover/pinned du panneau gauche.

## Architecture multi-sources de la visionneuse

`api/services/sources_image.py:resoudre_source_image(fichier)` produit
un objet `SourceImage` avec `primary` et `fallback`, en suivant cette
priorité :

1. **IIIF Nakala** (`Fichier.iiif_url_nakala`) — pour les items déposés
   ou importés depuis Nakala. Tile source `iiif`.
2. **DZI local** (`Fichier.dzi_chemin`) — réservé V2+, jamais rempli
   en V0.6.
3. **Aperçu local** (`Fichier.apercu_chemin`) — JPEG 1200 px sous
   `/derives/`. Tile source `image`.

Le serveur embarque la résolution de tous les fichiers d'un item dans
un `<script id="sources-fichiers" type="application/json">`.
`web/static/js/visionneuse.js` :

- instancie OpenSeadragon une fois sans source ;
- au click sur une vignette, lit la source correspondante et appelle
  `viewer.open(...)` ;
- gère l'événement `open-failed` pour basculer sur `fallback` (typique :
  timeout IIIF Nakala) ;
- met à jour l'URL via `history.replaceState` (`?fichier=ID`).

## Pattern « même route, deux modes »

La route `/collection/{cote}/{onglet}` branche directement sur
`HX-Request` :

- accès direct : rend `pages/collection.html` (wrapper unique :
  bandeau + onglets + contenu) en chargeant en plus
  `collection_detail` pour le bandeau ;
- accès HTMX : rend `partials/collection_<cle>.html` seul, sans
  recharger le détail (économie : 4 requêtes d'agrégat par swap).

Une seule URL par onglet, à la fois bookmarkable et fluide.

## Tri (V0.6.1)

Toutes les en-têtes triables des trois tableaux (collections du
dashboard, items, fichiers) émettent `hx-get` + `hx-target` +
`hx-push-url="true"`. Le swap est en `outerHTML` sur le wrapper du
tableau (`#dashboard-collections`, `#tableau-items`,
`#tableau-fichiers`), ce qui re-render aussi les en-têtes (chevron
asc/desc à jour).

**Whitelist par tableau** dans `services/tri.py` :

| Tableau           | Clés admises                                              |
| ----------------- | --------------------------------------------------------- |
| `collections`     | `cote`, `titre`, `items`, `fichiers`, `modifie`           |
| `items`           | `cote`, `titre`, `type`, `date`, `etat`, `fichiers`, `modifie` |
| `fichiers`        | `item`, `nom`, `ordre`, `type`, `taille`, `etat`          |

Toute valeur hors whitelist retombe sur le tri par défaut, sans
erreur — pas de SQL injection possible (jamais d'`order_by`
construit depuis la chaîne client).

Helper Jinja `url_tri` : compose l'URL avec inversion d'ordre si la
colonne cliquée est déjà active, ou `asc` sinon. Reset systématique
de `page=1` (un nouveau tri repagine).

## Pagination (V0.6.1)

Composant `components/pagination.html` réutilisable, alimenté par un
`Listage[T]` (services/tri.py) avec `page`, `par_page`, `total`,
`pages`. Pages visibles compactées via `pages_visibles(courante,
total)` exposé en global Jinja : `[1, …, cur-1, cur, cur+1, …, N]`.

Pagination active sur les onglets `items` (50/page) et `fichiers`
(50/page). Le tableau de fichiers couvre le cas Aínsa
(~12 845 fichiers, ~257 pages).

## Filtres (V0.6.1)

Drawer latéral droit `components/panneau_filtres.html`, ouvert via
le bouton « Filtrer » présent dans la barre d'actions de chaque
tableau filtrable. Form GET natif submit la page avec les filtres
en query string : bookmarkable, lisible, pas d'état JS à
synchroniser.

**Items** : `etat` (multi), `type` (COAR multi, options DISTINCT
sur la collection), `annee_debut`/`annee_fin`, `q` (LIKE titre).

**Fichiers** : `etat` (multi), `type_page` (multi), `format`
(multi), `q` (LIKE nom_fichier).

Validation par whitelist côté Python : valeurs inconnues
silencieusement ignorées (pas de 400). Le COUNT(*) de la pagination
applique les mêmes filtres pour rester cohérent.

Toggle JS minimal (`static/js/panneau_filtres.js`, ~30 lignes) :
ouvre sur clic `[data-action="filter"]`, ferme sur croix / Escape.
Pas de framework introduit.

## OpenSeadragon

Installé via npm (`openseadragon`). Build vendor :

```bash
npm install
npm run vendor:osd     # copie node_modules/openseadragon/build/openseadragon/* vers web/static/js/vendor/openseadragon/
npm run watch:css
```

Le bundle vendor (`openseadragon.min.js` + images) est gitignoré comme
`output.css`. Recompilation à la volée pendant le dev.

## Sélection des colonnes du tableau d'items (V0.6.3)

Module `services/preferences.py` :
- `lire_preferences_colonnes(db, utilisateur, collection_id, vue)` :
  retourne les préférences sauvegardées ou les défauts
  (`COLONNES_DEFAUT_ITEMS`).
- `sauvegarder_preferences_colonnes(...)` : upsert dans
  `PreferencesAffichage`. Validation par whitelist : dédiées
  (`COLONNES_DEDIEES_ITEMS`) + métadonnées disponibles pour la
  collection. `cote` est obligatoire — réinjectée si absente.
  Dédoublonnage en préservant l'ordre.
- `reinitialiser_preferences_colonnes(...)` : supprime la ligne ;
  le prochain `lire` retombe sur les défauts.

**Champs métadonnées dynamiques** :
`champs_metadonnees_disponibles(db, collection_id, limite=50)` parcourt
les `Item.metadonnees` (JSON) de la collection et retourne les clés
les plus fréquentes. Approche Python — acceptable jusqu'à quelques
milliers d'items. Bascule SQLite JSON1 (`json_each`) à prévoir au-delà.

**Endpoints** (router `routes/preferences.py`) :

| Méthode + URL                                            | Effet                       |
| -------------------------------------------------------- | --------------------------- |
| GET  `/preferences/colonnes/items/{collection_id}`       | Modale (form HTMX)          |
| POST `/preferences/colonnes/items/{collection_id}`       | Sauvegarde + tableau swap   |
| POST `/preferences/colonnes/items/{collection_id}/reset` | Reset défauts + tableau swap|

Le POST émet `HX-Trigger: panneau-colonnes-ferme` que le JS écoute
pour fermer la modale après save réussi.

**Stack JS** : Sortable.js (CDN cdnjs, hash SRI verrouillé) pour le
drag-drop. `web/static/js/panneau_colonnes.js` câble l'instanciation,
les boutons `−` (retirer une colonne active), le clic sur disponibles
(ajouter), Escape, overlay click. Pas de framework introduit, ~120
lignes JS.

**Pour ajouter une colonne dédiée** : étendre
`COLONNES_DEDIEES_ITEMS` dans `services/preferences.py`, ajouter un
elif dans la macro `_cell` de `components/tableau_items.html` (rendu
spécifique au type), et — si la colonne nécessite un champ pas
encore projeté — ajouter le champ Item à la SELECT de `lister_items`.

## Création et édition de collection (V0.7.x)

**Création** :
- `GET /collections/nouvelle[?parent=COTE]` rend le formulaire ;
  `?parent=COTE` pré-remplit la collection parente (silencieusement
  ignorée si la cote n'existe pas).
- `POST /collections` valide côté serveur et redirige (303) vers
  `/collection/{cote}` au succès. Re-rend la page avec status 400
  + erreurs préservées en cas d'échec.

**Édition** :
- `GET /collection/{cote}/modifier` rend le formulaire pré-rempli
  via `services.collections_creation.formulaire_depuis_collection`.
- `POST /collection/{cote}/modifier` valide via
  `valider_modification` (qui ne re-vérifie pas la cote — verrouillée
  par design — et accepte le DOI inchangé). Redirige vers
  `/collection/{cote}/items` au succès.

La cote est un input `disabled` avec aide explicative — toute
tentative de la modifier via le POST est silencieusement ignorée
(la valeur du model est utilisée).

## Fil d'Ariane (breadcrumb)

Composant `components/breadcrumb.html` accepte une liste
`crumbs = [{label, href, mono?}]`. Le dernier élément est rendu
non cliquable (page courante).

Helper `services/collection.fil_ariane_collection(col, *,
page_courante=None)` remonte la hiérarchie `parent_id` jusqu'à la
racine et préfixe par « Tableau de bord ». Pour les pages dérivées
d'une collection (ex. « Modifier »), passer `page_courante='Modifier'`
ajoute une feuille non cliquable supplémentaire.

Pages équipées : dashboard (implicite, racine sans breadcrumb),
collection (3 onglets), nouvelle collection, modifier, import
placeholder, vue item (via `bandeau_item`).

## Collaborateurs (V0.8.0)

La page de modification d'une collection inclut une section
Collaborateurs sous le formulaire principal. Elle est en dehors du
`<form>` parent : ses actions sont sauvegardées indépendamment via
HTMX (un texte explicatif l'indique sous le titre de section).

**Vocabulaire** : enum fermée `RoleCollaborateur` (numérisation,
transcription, indexation, catalogage). Une personne peut porter
plusieurs rôles ; elle apparaît alors dans plusieurs groupes —
l'affichage est groupé par rôle, pas par personne.

**Routes** (toutes sous `/collection/{cote}/collaborateurs/...`) :
- `GET .../collaborateurs` : section complète (cible du swap après
  ajout/modif/suppression).
- `GET .../collaborateurs/nouveau` : fragment formulaire vide.
- `GET .../collaborateurs/{id}/modifier` : fragment formulaire
  pré-rempli (rôles existants pré-cochés).
- `POST .../collaborateurs` : ajoute, retourne la section.
- `POST .../collaborateurs/{id}` : modifie, retourne la section.
- `POST .../collaborateurs/{id}/supprimer` : supprime
  (`hx-confirm` natif), retourne la section.

Le routeur `collaborateurs` est enregistré **avant** `collection`
dans `api/main.py` car ses URLs partagent le préfixe
`/collection/{cote}/...` : sinon `/collection/{cote}/{onglet}` (avec
`onglet` typé `Literal["items", "sous-collections", "fichiers"]`)
matche d'abord et retourne 422.

**Anti-confused-deputy** : chaque POST sur un id donné vérifie que
le collaborateur appartient à la collection identifiée par `cote`
(404 sinon). Sans cette vérification, un POST sur
`/collection/HK/collaborateurs/{id_dans_FA}` muterait un
collaborateur d'une autre collection.

**Stockage des rôles** : JSON sur `CollaborateurCollection.roles`
(liste de chaînes). Pas de filtre SQL natif transverse possible —
acceptable pour V0.8.0, à revoir si une recherche « toutes
collections où Marie a fait de la numérisation » devient utile.

**HTMX** : la lib est chargée via CDN (unpkg + SRI) sur la page
`collection_modifier.html` uniquement. Le reste de l'app n'utilise
HTMX qu'au niveau serveur (header `HX-Request`).

## Empty states

- Collection sans item ET sans sous-collection : grosse boîte
  proactive avec « Importer un tableur » → `/import?collection={cote}`
  et « Ajouter un item manuellement » (désactivé V0.8).
- Onglet sous-collections vide : « Créer une sous-collection » →
  `/collections/nouvelle?parent={cote}`.
- Si la collection a des sous-collections mais pas d'items, l'onglet
  items affiche un message court (l'utilisateur a un onglet à
  explorer).

## Limites V0.6.3

- Lecture seule : aucune édition possible depuis l'UI (V0.7).
- Panneau de colonnes uniquement sur le tableau d'items
  (fichiers / sous-collections : V0.7+ si besoin).
- Pas de filtres avancés (dates EDTF, ranges sur tailles, etc.).
- Pas de filtres sur les champs personnalisés des items (variabilité
  par collection trop grande pour V0.6).
- Tri / filtres sur le tableau de sous-collections : pas câblé
  (faible volume, V2+ si besoin).
- Script de résolution Nakala (interrogation API pour remplir
  `iiif_url_nakala`) : V0.7. En V0.6, le champ est rempli à la main
  ou laissé null.
- DZI local : V2+, le champ existe en base mais aucune génération
  associée.
- Boutons « Rechercher » et « Importer » du dashboard restent
  placeholders.
