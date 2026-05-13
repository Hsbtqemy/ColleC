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

## D — Navigation et tableaux ⏳

- [x] Dashboard : entêtes non-cliquables (tri pas implémenté côté service, commit b7bc259)
- [ ] Page Collection : trier les colonnes du tableau d'items (HTMX swap partial)
- [ ] Page Collection : ouvrir drawer **Filtrer**, cocher 2 états → tableau filtré, pastilles actives en haut
- [ ] Retirer une pastille de filtre individuellement → tableau ré-élargi
- [ ] Pagination : page 2, vérifier que les filtres sont préservés dans les liens
- [ ] Page Collection : modale **Colonnes**, drag-drop pour réordonner, valider → ordre persisté après reload
- [ ] Page Fonds : section Collaborateurs → ajouter une personne avec 2 rôles, sauver, retirer

---

## E — Visionneuse OpenSeadragon ⏳

- [ ] Charge sans erreur 403 sur les dérivés
- [ ] Zoom molette + boutons +/- du controlbar
- [ ] Boutons Précédent/Suivant dans le bandeau
- [ ] Recharger avec `?fichier_courant=3` directement → ouvre sur le 3e

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

## G — CLI ⏳

- [ ] `archives-tool montrer fonds` → liste lisible
- [ ] `archives-tool montrer item COTE --fonds X --format json` → JSON valide, structure stable
- [ ] `archives-tool controler --strict` → exit code propre (0 si RAS, 1 sinon)
- [ ] `archives-tool exporter dublin-core COTE_MIROIR --fonds X --sortie /tmp/out.xml` → XML valide DC
- [ ] `archives-tool exporter nakala COTE --fonds X --licence "CC-BY-4.0"` → CSV ouvrable, UTF-8 BOM
- [ ] `archives-tool exporter xlsx COTE --fonds X` → s'ouvre sans warning

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

## I — Cas tordus ⏳

- [ ] Cote avec `é`, `ï`, espace, parenthèse → tout marche-t-il ?
- [ ] Fichier avec chemin contenant `é` (NFD Mac vs NFC Windows)
- [ ] Importer 2 fois le même profil → idempotent ou doublons ?
- [ ] Cote `HK-001` partagée entre 2 fonds → désambiguïsation `--fonds` partout
- [ ] `lecture_seule: true` dans config → routes POST renvoient 423, bouton « Modifier » remplacé
- [ ] Tuer uvicorn pendant un save inline → reprendre, base intacte ?
- [ ] `alembic upgrade head` sur vraie base → ne casse rien ?

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

---

## Bilan final (à remplir à la fin du test)

- **Frictions bloquantes** :
- **Frictions gênantes** :
- **Cosmétiques** :
- **Surprises positives** :
- **Top 3 backlog Phase 2** :
