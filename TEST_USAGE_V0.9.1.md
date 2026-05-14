# Test d'usage V0.9.1 — checklist

Document de travail pour le test d'usage manuel sur la base de
démonstration puis sur un vrai mini-fonds. Sections coches à mesure.
Frictions notées en fin de section avec niveau de sévérité.

**Setup recommandé** (PowerShell sous Windows) :

```powershell
$env:ARCHIVES_DB="data/demo.db"
.venv\Scripts\uvicorn.exe archives_tool.api.main:app --reload
```

La config sœur `data/demo_config.yaml` est détectée automatiquement
(phase 0 de cette campagne). Pas besoin de set `ARCHIVES_CONFIG`.

---

## A — Sanity de la démo ✅

- [x] Header en haut affiche `démo` (pas `anonyme`)
- [x] Dashboard montre 5 fonds, compteurs cohérents
- [x] Cliquer chaque fonds → page Fonds ouvre sans 500
- [x] Cliquer une collection → page Collection ouvre
- [x] Cliquer un item → page Item ouvre, visionneuse affiche le placeholder

**Validé.**

---

## B — Panneau fichiers escamotable ✅

- [x] Panneau collapsé : 36px, libellé vertical visible
- [x] Hover ~200ms → s'élargit, libellé vertical disparaît
- [x] Hover-out → fermeture immédiate (plus de latence)
- [x] Clic sur l'épingle → ouverture immédiate
- [x] Cliquer un fichier dans la liste → page recharge sur `?fichier_courant=N`, fichier surligné
- [x] **Persistance de l'épingle entre navigations** (commit 4d97949)

**Validé.**

---

## C — Édition inline ✅

- [x] Clic sur Titre → input pré-rempli
- [x] Entrée ou clic ailleurs → save, version meta incrémente
- [x] **Escape** → input se ferme, valeur d'origine restaurée (commit 59c6adb)
- [x] Clic sur Titre puis clic ailleurs sans typer → pas de save
- [x] Clic sur Description → textarea 3 lignes, Ctrl+Enter sauve
- [x] Clic sur Cote → rien (data-editable=0)
- [x] Clic sur Langue → `<select>` avec 17 langues + option vide
- [x] Sélectionner « Français » → cellule affiche « Français » (pas « fra »)
- [x] Re-cliquer Langue → select s'ouvre déjà sur « Français »
- [x] **Space dans select** → dropdown s'ouvre normalement (commit 3e79fe7)
- [x] Sélectionner option vide (—) → champ effacé, affiche « non renseigné »
- [x] Idem pour Type COAR
- [x] Conflit 2 onglets → bandeau « Conflit v N en base · Recharger »

**Validé.** Bugs corrigés : Escape blur parasite, Space dropdown parasite.

---

## D — Navigation et tableaux ✅

- [x] Dashboard : entêtes non-cliquables (tri pas implémenté côté service, commit b7bc259)
- [x] Page Collection : trier les colonnes du tableau d'items (HTMX swap partial) — 4 bugs corrigés ce jour, voir frictions
- [x] Page Collection : ouvrir drawer **Filtrer**, cocher 2 états → tableau filtré, pastilles actives en haut
- [x] Retirer une pastille de filtre individuellement → tableau ré-élargi
- [x] Tri après filtre → filtre préservé dans `cible_url` (vu via logs uvicorn)
- [x] Bouton Filtrer après tri → ouvre toujours (délégation document)
- [x] Pagination : page 2 préserve les filtres dans tous les liens (`?fonds=…&etat=valide&page=N`, 23 items en CONC-1789/valide réparti sur 3 pages)
- [x] Page Collection : modale **Colonnes** — pipeline GET modal + POST save + reload persisté validé via curl. Drag-drop visuel via Sortable.js à confirmer au navigateur (rien de cassé côté code).
- [x] Page Fonds : section Collaborateurs → ajouter une personne avec 2 rôles, sauver, retirer (bug d'affichage corrigé ce jour, voir frictions)

**Validé.**

---

## E — Visionneuse OpenSeadragon ✅

- [x] Charge sans erreur 403 sur les dérivés (après backfill DB, voir frictions)
- [x] Zoom molette + boutons +/- du controlbar
- [x] Boutons Précédent/Suivant dans le bandeau
- [x] Recharger avec `?fichier_courant=3` directement → ouvre sur le 3e

**Validé.**

---

## F — Import réel ⏳

Le test qui compte. Sur un vrai mini-fonds (30-50 items minimum).

1. Choisir un tableau Excel/CSV et une arbo de scans existants.
2. `archives-tool profil analyser inventaire.xlsx --sortie monfonds.yaml` ou écrire le profil à la main.
3. Lancer `archives-tool importer monfonds.yaml` (dry-run).
4. Lire le rapport — quels champs ne sont pas mappés ? quelles colonnes ignorées ?
5. Corriger le profil, relancer dry-run.
6. Quand le rapport est propre : `--no-dry-run`.

### Vérifications post-import

- [ ] Nombre d'items créé = nombre de lignes du tableur
- [ ] Cotes uniques, pas de NULL
- [ ] Items rattachés à la miroir du fonds
- [ ] Fichiers résolus sur disque (compter les warnings FILE-MISSING via `controler`)
- [ ] Aucun fichier orphelin sur disque (FILE-ITEM-VIDE)
- [ ] Métadonnées custom remontées dans `Item.metadonnees`

### Re-tester C, D, E avec les vraies données

- [ ] L'inline edit fonctionne sur des cotes/titres réels avec accents
- [ ] Le tableau d'items avec 30-50 lignes répond bien
- [ ] La visionneuse charge des vrais scans (pas des placeholders)

---

## G — CLI ✅ (sur base demo)

- [x] `archives-tool montrer fonds --db-path data/demo.db` → 5 fonds listés (CONC-1789, FA, HK, MAR, RDM)
- [x] `archives-tool montrer item HK-001 --fonds HK --format json --db-path data/demo.db` → JSON valide (type=item_detail, 40 fichiers, structure stable)
- [x] `archives-tool controler --strict --format json --db-path data/demo.db` → exit 1 (333 items, 14 contrôles). **Text Rich plante en PowerShell cp1252** — voir frictions.
- [x] `archives-tool exporter dublin-core HK --fonds HK --sortie data/x.xml --db-path data/demo.db` → XML valide DC, 1 notice de tête + 40 items
- [x] `archives-tool exporter nakala HK --fonds HK --licence "CC-BY-4.0" --sortie data/x.csv --db-path data/demo.db` → CSV `;`-séparé, 40 lignes, UTF-8 BOM
- [x] `archives-tool exporter xlsx HK --fonds HK --sortie data/x.xlsx --db-path data/demo.db` → 1 sheet × 46×12, openpyxl ouvre sans warning

**Validé.** Note : `--db-path` est un flag par sous-commande, pas global. `ARCHIVES_DB` ne s'applique qu'à l'API web.

---

## H — Renommage transactionnel ⏳

**Sur le mini-fonds importé uniquement.** Pas sur la démo (chemins fictifs).

- [ ] `archives-tool renommer appliquer --template "..." --fonds X` (dry-run) → plan affiché, conflits visibles
- [ ] Provoquer un conflit volontaire → rapport clair
- [ ] Template propre : `--no-dry-run` → fichiers renommés disque + base
- [ ] `archives-tool renommer historique` → batch listé
- [ ] `archives-tool renommer annuler --batch-id UUID --no-dry-run` → retour à l'état d'origine
- [ ] `derive_genere` remis à False après rename
- [ ] `archives-tool deriver appliquer --fonds X` → dérivés régénérés

---

## I — Cas tordus ⏳ (partiel — reste à voir avec F)

- [ ] Cote avec `é`, `ï`, espace, parenthèse → **reporté à F** (testable seulement à l'import)
- [ ] Fichier avec chemin contenant `é` (NFD Mac vs NFC Windows) → **reporté à F** (démo = chemins fictifs)
- [ ] Importer 2 fois le même profil → idempotent ou doublons ? → **reporté à F**
- [x] Cote `HK-001` partagée entre 2 fonds → désambiguïsation `--fonds` partout : `/item/FA-CORRESP-001` sans `?fonds=` → 422, avec bon fonds → 200, avec mauvais → 404. Désambiguïsation côté route OK. Cote effectivement partagée pas testée (la démo n'en a pas, à revoir à F).
- [x] `lecture_seule: true` dans config → routes POST renvoient 423 ✓, bannière s'affiche ✓, **bouton « Modifier » PAS remplacé** ✗ (voir frictions). Middleware seul est solide ; couverture UI partielle.
- [ ] Tuer uvicorn pendant un save inline → **non testé** (peu d'apport : SQLAlchemy COMMIT atomique = soit le save passe, soit rien ; pas de demi-état possible).
- [ ] `alembic upgrade head` sur vraie base → **reporté à F** (pas de migration en attente sur la démo)

---

## J — WebDAV ⏳

À faire seulement pour cocher complètement V0.9.1.

- [ ] Suivre `docs/premiers-pas/installation-locale-webdav.md`
- [ ] Monter ShareDocs en WebDAV
- [ ] Lancer ColleC avec `data/` sur le partage
- [ ] 5 saves rapides depuis 2 postes différents → WAL + verrou tiennent-ils ?

---

## Frictions observées

Format pour chaque entrée :

```
### [Date] [Section] [Sévérité: bloquant|gênant|cosmétique]
Ce qui s'est passé : ...
Ce que j'attendais : ...
Hypothèse / cause supposée : ...
Fix appliqué : commit XXXXX ou (à faire)
```

### 2026-05-13 — A — cosmétique → fixé

Logs polluées par `GET /favicon.ico 404`. Pas un bug, juste du bruit.
**Fix** : commit 2e8991b — stub `/favicon.ico` répond 204.

### 2026-05-13 — B — gênant → fixé

Panneau fichiers : label vertical « FICHIERS · 1 » restait visible quand
le panneau était hover-ouvert, dupliquant le `<h3>` horizontal. Aussi
fermeture aussi lente que l'ouverture (200ms) contredisant le commentaire
qui disait « immédiat à la fermeture ».
**Fix** : commit e0da7e1 — label hidden via opacity, transition-delay
uniquement sur `:hover` (entrée), pas sur la sortie.

### 2026-05-13 — B — gênant → fixé

Épingle du panneau perdue quand on clique sur un autre fichier (la page
recharge, la checkbox client-side reset).
**Fix** : commit 4d97949 — petit script qui persiste l'état pin en
`localStorage`.

### 2026-05-13 — C — gênant → fixé

Press Space sur un `<select>` Langue/Type COAR fermait l'édition avant
qu'on puisse choisir. Cause : la popup native du dropdown prend
brièvement le focus, le navigateur tire un `blur` parasite sur le
select.
**Fix** : commit 3e79fe7 — pour les selects, on n'écoute plus `blur` ;
détection du clic outside via `mousedown` sur document.

### 2026-05-13 — C — gênant → fixé

Escape ne restaurait pas la valeur après saisie : `annuler()`
réinjectait le DOM via `innerHTML`, ce qui détachait l'input focusé →
`blur` synchrone → `envoyer()` envoyait la valeur tapée.
**Fix** : commit 59c6adb — `envoye=true` posé avant le `innerHTML`.

### 2026-05-13 — D — bloquant → fixé

Cliquer une colonne du dashboard provoquait l'imbrication de la page :
HTMX faisait `hx-get` sur la même URL (`cible_url` non fournie),
récupérait le HTML complet du dashboard, et l'injectait dans la div
du tableau.
**Fix** : commit b7bc259 — `tableau_collections` rend les entêtes non
cliquables si `ctx.cible_url` n'est pas fourni.

### 2026-05-14 — D — bloquant → fixé

Même bug d'imbrication sur la page **Collection** : entêtes du tableau
d'items envoyaient `hx-get` à `/collection/{cote}?...&tri=...&ordre=...`,
la route renvoyait la page complète, HTMX l'injectait dans `#tableau-items`.
Aucun handler `HX-Request` dans `api/`. Pagination affectée par le même
mécanisme.
**Fix** : `page_collection` détecte `HX-Request: true` → renvoie
`partials/collection_items.html` seulement.

### 2026-05-14 — D — bloquant → fixé

Même bug d'imbrication sur la page **Fonds** : table `tableau_collections`
recevait `cible_url='/fonds/{cote}'` mais la route ne gère ni `tri`,
ni `ordre`, ni partial — donc tout click ramenait la page entière.
**Fix** : `cible_url` retiré de l'appel `tableau_collections` dans
`fonds_lecture.html` → entêtes non cliquables (cohérent avec le
fait que le service ne supporte pas le tri).

### 2026-05-14 — D — bloquant → fixé

Drawer **Filtrer** ne s'affichait pas : `<aside style="...transform:translateX(100%);...">`
en inline (poids 1000) gagnait sur `<style> #panneau-filtres[data-ouvert="true"] { transform: translateX(0); }`
(spécificité ~21). Le clic flippait bien `data-ouvert="true"` mais le
drawer restait offscreen.
**Fix** : `transform` initial déplacé dans la règle `<style>` → la
règle `[data-ouvert="true"]` peut maintenant la surcharger.

### 2026-05-14 — D — bloquant → fixé

Submit du drawer Filtrer renvoyait **422 Unprocessable Content** dès
qu'au moins un état était coché (n'importe quelle collection). Cause :
les inputs `<input type="number" name="annee_de">` envoient
`annee_de=&annee_a=` quand vides, et `int | None = Query(None, ge=...)`
ne parse pas la chaîne vide.
**Fix** : route accepte `str | None`, helper `_annee_int_ou_none`
coerce silencieusement (vide / non-numérique / hors plage → None).
Cohérent avec la philosophie « validation silencieuse » de
`parser_filtres_collection`.

### 2026-05-14 — D — gênant → fixé

Bouton **Filtrer** mort après un tri colonne. Cause : `panneau_filtres.js`
attachait un click listener directement sur chaque
`[data-action="filter"]` au chargement de page. HTMX swappait
`#tableau-items` au tri/pagination → nouveau bouton sans listener.
**Fix** : délégation `document.addEventListener("click", ...)` qui
capture les clics sur tout `[data-action="filter"]` actuel et futur,
survit aux swaps. Idem pour `[data-panneau-filtres-fermer]`.
Cache-bust ajouté sur `panneau_filtres.js` et `panneau_colonnes.js`
(`static_url()` au lieu de `url_for`) pour éviter d'avoir à
hard-refresh à chaque édition.

### 2026-05-14 — D — cosmétique → fixé

Compteur de filtres affichait « 1 actifs » (pluriel forcé).
**Fix** : `(nb_f|string ~ (' actif' if nb_f == 1 else ' actifs'))` dans
`partials/collection_items.html`.

### 2026-05-14 — D — bloquant UX → fixé

Page Fonds, section Collaborateurs : une personne avec N rôles
apparaissait N fois (groupement par rôle), avec un bouton **Supprimer**
à chaque occurrence — mais tous pointaient vers le même endpoint
qui supprimait la ligne entière (tous les rôles d'un coup).
Cliquer Supprimer sous « Numérisation » pour quelqu'un aussi
catalogueur le retirait des deux sections sans avertissement.
**Fix** : `FondsDetail.collaborateurs` (liste plate) ajouté comme
field, `collaborateurs_par_role` passe en `@property` dérivée
(CLI `montrer fonds` toujours fonctionnel). Template `fonds_lecture.html`
refait — une ligne par personne avec rôles en chips et un seul
bouton Supprimer.

### 2026-05-14 — G — bloquant Windows → ouvert

`archives-tool controler` (sortie text Rich) plante en PowerShell par
défaut avec `UnicodeEncodeError: 'charmap' codec can't encode character
'✓'`. Cause : Python détecte stdout comme cp1252 sur Windows
console historique.
**Workaround** : `$env:PYTHONIOENCODING="utf-8"` avant d'appeler la
CLI, ou utiliser `--format json`.
**Fix code envisagé** : forcer `sys.stdout.reconfigure(encoding="utf-8")`
au démarrage CLI, ou que Rich utilise un encodage safe.

### 2026-05-14 — G — cosmétique → ouvert

Ligne récap de `archives-tool exporter nakala ...` affiche
`⚠ Items incomplets : 40` (échappement littéral) au lieu de
`⚠ Items incomplets : 40`. Probablement un `str.encode(...,
errors='backslashreplace')` ou un `repr()` quelque part dans le
formatteur de rapport d'export.

### 2026-05-14 — I — gênant UX → ouvert

`lecture_seule: true` : le middleware retourne bien 423 sur tous les
POST/PUT/DELETE et la bannière s'affiche en haut de chaque page,
mais les **boutons « Modifier »** restent visibles sur les pages
Fonds, Collection, Item. L'utilisateur clique, atterrit sur le
formulaire (où les inputs sont grisés grâce à `_champ_form.html`),
peut quand même soumettre, et obtient un 423 abrupt.

Côté code : `est_lecture_seule()` n'est consommé que par `base.html`
(bannière) et `_champ_form.html` (inputs disabled). Aucun guard sur
les boutons d'entrée vers les formulaires.

**Fix proposé** (pas appliqué dans cette session) : entourer chaque
bouton « Modifier » (Fonds, Collection, Item, sections collab) d'un
`{% if not est_lecture_seule() %} ... {% endif %}` ou afficher une
version désactivée. Ou un seul guard global dans un macro `bouton_modifier`.

### 2026-05-14 — E — bloquant local → contourné

La visionneuse OSD affichait « Aucun aperçu disponible » sur tous
les items de la démo. Diagnostic en deux temps :

1. `data/demo_derives/{vignette,apercu}.jpg` + `data/demo_config.yaml`
   manquants — la `data/demo.db` datait d'avant le commit `fa47242`
   (placeholders JPEG + config auto). Régénérés via
   `_generer_placeholders` + `_ecrire_config_demo` sans toucher la DB.
2. Insuffisant : les 1298 entrées `fichier` avaient `apercu_chemin = NULL`,
   `vignette_chemin = NULL`, `derive_genere = 0`. Le seed les remplit à la
   création mais l'ancien snapshot ne les avait pas. Backfill SQL
   idempotent : `UPDATE fichier SET apercu_chemin=...,
   vignette_chemin=..., derive_genere=1`.

**Recommandation pour la suite** : si quelqu'un d'autre teste sur une
demo.db antérieure à `fa47242`, lui faire passer
`archives-tool demo init --force` (chemin officiel, perd les données
de test) ou un backfill équivalent. À documenter dans le README ?

---

## Bilan final (à remplir à la fin du test)

- **Frictions bloquantes** :
- **Frictions gênantes** :
- **Cosmétiques** :
- **Surprises positives** :
- **Top 3 backlog Phase 2** :
