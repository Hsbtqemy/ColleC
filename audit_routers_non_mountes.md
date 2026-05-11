# Audit des routers non mountés dans `api/main.py`

État : V0.9.2-gamma (post-passe simplify, 529 tests verts, commit non créé).

`api/main.py` ne monte que 3 routers :

```python
app.include_router(dashboard.router)
app.include_router(preferences.router)
app.include_router(derives.router, prefix="/derives")
```

Quatre fichiers `routes/*.py` existent sur disque mais ne sont PAS
inclus dans l'application :

| Fichier | Lignes | Statut V0.9.0 | Effort de mount |
|---------|--------|---------------|-----------------|
| `routes/collaborateurs.py` | 194 | Compatible (services V0.9.0) | **Léger** |
| `routes/import_assistant.py` | 24 | Compatible (placeholder, pas de DB) | **Trivial** |
| `routes/collection.py` | 163 | **Incompatible** (V0.6 model) | **Lourd / à supprimer** |
| `routes/collections.py` | 178 | **Incompatible** (V0.6 model) | **Lourd / à supprimer** |

Le brief demandait `collaborateurs` et `import_assistant` ; les deux
autres sont inclus pour exhaustivité (ils étaient mentionnés dans
le commentaire d'origine de `main.py` parmi « les routers à
ré-introduire »).

---

## 1. `routes/collaborateurs.py`

Routes HTMX de gestion des **CollaborateurCollection** (V0.8.0 —
collaborateurs attachés à une *collection*, distinct des
CollaborateurFonds attachés à un *fonds* qui sont déjà dans
`routes/dashboard.py:755+`).

URLs exposées : `GET/POST /collection/{cote}/collaborateurs[/...]`.

### 1.1 Code existe ?

Oui — [`src/archives_tool/api/routes/collaborateurs.py`](src/archives_tool/api/routes/collaborateurs.py)
(194 lignes). 7 endpoints : section, formulaire nouveau, formulaire
modifier, ajouter, modifier, supprimer.

### 1.2 Modèle V0.6 ou V0.9.0 ?

**Compatible V0.9.0**. Aucune référence à `Item.collection_id`,
`cote_collection`, ou `parent_id`. Le code utilise :

- `CollaborateurCollection.collection_id` (FK vers `Collection.id`,
  inchangée entre V0.6 et V0.9.0).
- `RoleCollaborateur` enum (V0.8.0, toujours valide).

### 1.3 Services à jour ?

`services/collaborateurs.py` (175 lignes) — **OK V0.9.0**. Aucune
référence problématique. Coexiste proprement avec
`services/collaborateurs_fonds.py` (V0.9.0-alpha pour les
collaborateurs au niveau fonds, déjà branché côté dashboard).

### 1.4 Tests ?

[`tests/test_collaborateurs.py`](tests/test_collaborateurs.py) existe.
**Dans `collect_ignore`** (`tests/conftest.py:36`). Mais à
l'inspection :

- La fixture `col` (ligne 38) utilise déjà `Collection(cote="HK", ...)`
  (V0.9.0 style — pas `cote_collection`).
- Aucune occurrence de `cote_collection` dans le fichier (vérifié
  par grep).
- Les tests de routes (lignes 287+) appellent `client.get("/collection/HK/collaborateurs")`
  sur la base demo.

L'exclusion semble être une **précaution de quarantaine V0.9.0-alpha**
non révisée depuis. Un essai concret (pytest hors quarantaine)
révélerait si des cassures subsistent.

### 1.5 Bloqueur identifié

[`routes/collaborateurs.py:20`](src/archives_tool/api/routes/collaborateurs.py#L20)
importe `from archives_tool.api.routes.collections import charger_collection_ou_404`.

Or `routes/collections.py` (V0.6, voir §4) référence `cote_collection`
partout — l'import déclencherait l'évaluation du module et casserait
au load. **À découpler avant de mounter.**

### 1.6 Effort estimé : **Léger** (~30 minutes)

1. Extraire `charger_collection_ou_404` (~10 lignes) vers un module
   helper non-legacy — par ex. `routes/_helpers.py` ou inline dans
   `routes/collaborateurs.py`. Le helper n'a besoin que de
   `services/collection.py:charger_collection`. **Attention** :
   `services/collection.py` est lui aussi legacy V0.6 (730 lignes,
   utilise `cote_collection` et `Item.collection_id`). Préférer
   `services/collections.py:lire_collection_par_cote` (V0.9.0) ou
   un nouveau helper qui charge via `Collection.cote` + désambiguïsation
   `?fonds=`.
2. Ajouter `app.include_router(collaborateurs.router)` dans `main.py`.
3. Retirer `"test_collaborateurs.py"` de `collect_ignore`.
4. Lancer `pytest tests/test_collaborateurs.py` — adapter les
   éventuels tests qui cassent (probablement la résolution de
   collection par cote ambiguë HK fonds vs HK miroir).
5. Brancher la section dans le template `collection_lecture.html`
   (actuellement la page collection V0.9.2-beta n'inclut PAS la
   section collaborateurs ; à voir si le brief l'exige).

**Risque résiduel** : la cote `HK` est ambiguë (fonds et sa miroir
ont la même cote). Le router `collaborateurs.py` accepte juste
`{cote}` sans `?fonds=` — il faut soit forcer la résolution par
miroir du fonds, soit ajouter `?fonds=` aux URLs. Dette à
documenter.

---

## 2. `routes/import_assistant.py`

Placeholder `/import` (V0.7-alpha) — page statique qui guide
l'utilisateur vers la CLI en attendant l'assistant complet.

### 2.1 Code existe ?

Oui — [`src/archives_tool/api/routes/import_assistant.py`](src/archives_tool/api/routes/import_assistant.py)
(24 lignes). Un seul endpoint : `GET /import`.

### 2.2 Modèle V0.6 ou V0.9.0 ?

**Aucune référence au modèle**. Le route ne touche pas à la base de
données (pas de `Depends(get_db)`, pas d'import depuis
`archives_tool.models`). Il sert juste un template statique.

### 2.3 Services à jour ?

**Aucun service requis**. Le template `pages/import_placeholder.html`
existe déjà ([`web/templates/pages/import_placeholder.html`](src/archives_tool/web/templates/pages/import_placeholder.html),
70 lignes — référence un breadcrumb et la doc MkDocs).

Note : le modèle `SessionImport` existe ([`models/session_import.py`](src/archives_tool/models/session_import.py))
mais aucun service ne l'utilise actuellement. Il est en attente de
l'assistant complet (V0.7+).

### 2.4 Tests ?

**Aucun**. Pas de `tests/test_import_assistant.py`.

`tests/test_importer.py` existe (210 lignes) mais teste
`importers/ecrivain.py` (CLI), pas le router web. Il n'est pas dans
`collect_ignore` et passe en V0.9.0.

### 2.5 Effort estimé : **Trivial** (~2 minutes)

1. Importer `from archives_tool.api.routes import import_assistant`
   dans `main.py`.
2. Ajouter `app.include_router(import_assistant.router)`.

C'est tout. Aucune adaptation nécessaire. Le menu déroulant
« Importer » du dashboard pointe déjà vers `/import` — actuellement
404. Mounter rendrait le placeholder accessible.

Recommandation immédiate : à mounter dans la prochaine passe.

---

## 3. `routes/collection.py` (legacy V0.6)

Vue détail d'une collection avec 3 onglets (items, sous-collections,
fichiers). **Remplacée** par `routes/dashboard.py:page_collection`
(V0.9.2-beta) qui rend `pages/collection_lecture.html`.

### 3.1 Code existe ?

Oui — [`src/archives_tool/api/routes/collection.py`](src/archives_tool/api/routes/collection.py)
(163 lignes).

### 3.2 Modèle V0.6 ou V0.9.0 ?

**V0.6 — incompatible**. Réfère :

- `Collection.parent_id` ([`collection.py:134`](src/archives_tool/api/routes/collection.py#L134)) —
  champ supprimé en V0.9.0.
- Concept de « sous-collections » via `Collection.parent_id` —
  remplacé par la junction N-N `ItemCollection` en V0.9.0.
- `svc.lister_sous_collections`, `svc.fil_ariane_collection`,
  `svc.collection_detail` — méthodes du service legacy.

### 3.3 Services à jour ?

`services/collection.py` (730 lignes) — **obsolète**. 13 occurrences
de `cote_collection` (lignes 121, 151, 158, 174, 184, 190, etc.)
+ usage de `Item.collection_id`. Coexiste avec `services/collections.py`
(V0.9.0-alpha, au pluriel) qui est le service canonique utilisé par
le dashboard.

### 3.4 Tests ?

`tests/test_collection_routes.py` et `tests/test_collection_services.py`
— **dans `collect_ignore`** (`tests/conftest.py:38-39`). Construits
pour le modèle V0.6.

### 3.5 Effort estimé : **Lourd / à supprimer**

La fonctionnalité (vue détail collection avec onglets) est
**déjà couverte** par `routes/dashboard.py:page_collection` qui rend
`pages/collection_lecture.html` avec items + bandeau enrichi
(V0.9.2-beta + drawer V0.9.2-beta.3). Il n'y a pas d'onglet
« sous-collections » en V0.9.0 (la notion n'existe plus).

**Recommandation** : suppression complète.

- Supprimer `routes/collection.py` (163 lignes)
- Supprimer `services/collection.py` (730 lignes)
- Supprimer `tests/test_collection_routes.py`, `tests/test_collection_services.py`
- Supprimer les templates legacy : `pages/collection.html`,
  `partials/collection_items.html` ancien (déjà adapté V0.9.0),
  `partials/collection_fichiers.html`, `partials/collection_sous_collections.html`
- Retirer les entrées du `collect_ignore`

À traiter en passe **V0.9.2-finale** (passe globale de nettoyage
avant V0.9.1).

---

## 4. `routes/collections.py` (legacy V0.6)

Création / édition de collections. Distinct du `routes/collection.py`
(singulier). **Remplacé** par les endpoints `POST /collection/{cote}/modifier`
et helpers de création dans `routes/dashboard.py`.

### 4.1 Code existe ?

Oui — [`src/archives_tool/api/routes/collections.py`](src/archives_tool/api/routes/collections.py)
(178 lignes).

### 4.2 Modèle V0.6 ou V0.9.0 ?

**V0.6 — incompatible**. Référence `cote_collection` ligne 55, 95,
132, 154, 164. Utilise `services/collections_creation.py` (231 lignes,
V0.6, références à `cote_collection`, `parent_id`).

### 4.3 Services à jour ?

`services/collections_creation.py` (231 lignes) — **obsolète**. 6+
références à `cote_collection`, 1 usage de `parent_id` (ligne 186).

Le service canonique V0.9.0 est `services/collections.py` (au
pluriel) qui expose `creer_collection_libre`, `modifier_collection`,
`ajouter_items_a_collection`, `lire_collection_par_cote`. Déjà
utilisé par `routes/dashboard.py:soumettre_modification_collection`.

### 4.4 Tests ?

`tests/test_collections_creation.py` — **dans `collect_ignore`**.

### 4.5 Effort estimé : **Lourd / à supprimer**

La fonctionnalité (création/édition de collections) est **déjà
couverte** par `routes/dashboard.py` (formulaire de création vide,
soumettre modification, ajouter/retirer items via picker). Pas de
plus-value à mounter cette route legacy.

**Recommandation** : suppression complète, comme §3.

- Supprimer `routes/collections.py` (178 lignes)
- Supprimer `services/collections_creation.py` (231 lignes)
- Supprimer `tests/test_collections_creation.py`
- Vérifier que `helpers.charger_collection_ou_404` (importé par
  `routes/collaborateurs.py`) est déplacé ailleurs avant suppression
  (cf §1).

À traiter en passe **V0.9.2-finale**.

---

## Synthèse et plan d'action recommandé

### À mounter rapidement

| Router | Effort | Quand |
|--------|--------|-------|
| `import_assistant` | 2 min | **Maintenant** — débloque le menu Importer du dashboard, pas de risque |
| `collaborateurs` | 30 min | Mini-session dédiée, après découplage du helper `charger_collection_ou_404` |

### À supprimer (pas mounter)

| Router | Volume code mort | Quand |
|--------|------------------|-------|
| `routes/collection.py` + `services/collection.py` + 4 tests + 4 templates | ~1600 lignes | **V0.9.2-finale** |
| `routes/collections.py` + `services/collections_creation.py` + 1 test | ~410 lignes | **V0.9.2-finale** |

### Dette technique signalée pour `collaborateurs`

Avant de mounter, **arbitrer** :

1. **Cote ambiguë** : la route `routes/collaborateurs.py` accepte
   `/collection/{cote}/collaborateurs` sans `?fonds=`. Or `HK` est
   à la fois un fonds et sa miroir — la résolution silencieuse
   peut surprendre. Ajouter `?fonds=` aux liens et au template
   ou imposer la désambiguïsation.

2. **Branchement UI** : le composant
   `web/templates/components/section_collaborateurs.html` existe
   mais n'est inclus dans **aucune page V0.9.2** (vérifié par grep).
   La page Collection V0.9.2-beta a perdu sa section collaborateurs
   par rapport à V0.8.0. Question d'arbitrage :

   - **Option A** : la section collaborateurs revient sur la page
     `collection_modifier.html` (cohérent avec V0.8.0).
   - **Option B** : on traite tout au niveau Fonds via les routes
     `/fonds/{cote}/collaborateurs/...` déjà branchées dans
     `routes/dashboard.py` et on archive `CollaborateurCollection`
     comme dette V0.8.0 obsolète.

   L'option B simplifie le modèle (CollaborateurFonds = source
   unique) mais perd la granularité collaborateur-par-collection.
   À trancher avant de mounter.

### Bonus : `SessionImport` modèle dormant

[`models/session_import.py`](src/archives_tool/models/session_import.py)
existe (table créée par les migrations) mais **aucun service ni
route ne l'utilise** actuellement. C'est l'infrastructure attendue
pour l'assistant d'import V0.7+. À garder tel quel — pas de dette
active, juste de l'anticipation.
