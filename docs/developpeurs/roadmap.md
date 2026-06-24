# Roadmap ColleC

!!! warning "Document de travail interne"
    Page non publiée sur le site MkDocs (exclue via `exclude_docs`). Elle
    fixe le **séquencement forward-looking** du projet, par logique de
    dépendances — pas par numéro de version. Tenue à jour au fil des
    décisions. L'**historique livré détaillé** reste dans la section *Plan
    de développement (phasage)* de `CLAUDE.md` ; ce doc, lui, dit **dans
    quel ordre on attaque la suite et pourquoi**.

## État de départ (2026-06-18)

ColleC est un **outil de catalogage local mature** : modèle
Fonds/Collection/Item/Fichier, CLI + UI complètes, recherche FTS5,
intégration **Nakala quasi-bouclée** (lecture + écriture + round-trip
métadonnées **et** fichiers + S7 transcription par fichier) et désormais
un **2ᵉ adaptateur distant : ShareDocs** (Chantier 1 livré — cf. plus
bas). Base livrée **V0.10.0** ; la branche `dev` porte le palier Nakala S7,
le recadrage OCR **et tout le Chantier 1 ShareDocs**, ~1900 tests verts.
Mode actuel : **local mono-utilisateur**.

## Principe de séquencement (décidé 2026-06-18)

1. **ShareDocs en 1er chantier** — dé-risqué par l'outil sœur `BD_ditor`,
   autonome (utile au catalogage sans OCR), concrétise le modèle
   « remote-first ». ✅ **Livré** (cf. Chantier 1).
2. **OCR / recherche plein-texte avant V1.0** — corpus et recherche
   d'abord ; **toute la diffusion en dépend** (un site/portail sans
   recherche est tiède).
3. **V1.0 (déploiement + multi-utilisateurs) ensuite** — à déclencher
   quand l'accès distant/à plusieurs devient un vrai besoin.
4. **Diffusion après l'OCR.**
5. **Confort / interop** (V2/V3) en opportuniste.

> **Chantier UI⁺** (surfaçage de l'existant + polissage du front) — ajouté au
> point d'approfondissement du 2026-06-22, **mini-chantier resserré livré le
> jour même** (traçabilité + autocomplete + étiquettes). Sans dépendance dure
> (interleavable). Détail, reste et évaluation valeur/coût dans sa section
> dédiée plus bas.

---

## Horizon 0 — Consolidation (en cours / continu)

- **FF `main`** pour promouvoir le palier S7 **+ le Chantier 1 ShareDocs**
  (y compris le durcissement UX de l'import web — cf. Chantier 1).
- **Quick wins** : ✅ S6 (validation licence SPDX au preflight/export, livré) ;
  ✅ `notebooks-sdk` (page-guide **déjà livrée** — [`guide/notebook.md`](../guide/notebook.md),
  dans la nav MkDocs). Les deux quick wins d'Horizon 0 sont faits.
- **Passif / bloqué externe** : **apitest revenu le 2026-06-18** → suite
  d'intégration relancée (12 passed), **smoke S7 live FAIT** + sonde
  omit-vs-wipe résolue (→ WIPE, cf. `nakala-savoir-api.md` H12) + **sonde
  S8/V1 résolue** (strictesse `type` de relation → **STRICT** : vocabulaire
  fermé de 38 types, sensible à la casse ; une sonde antérieure avait conclu
  « LAX » **à tort** — cible déjà reliée → faux négatif de dédup, corrigé via
  `explorer_relations_type_nakala.py`, cf. V1 du backlog). **Audit de parité
  apitest ↔ prod FAIT (2026-06-20, clé d'un vrai compte Huma-Num)** : Volets A
  (lecture) + B (écriture item + collection) + parité vocab — parité totale du
  contrat d'API, seules divergences attendues (citation réelle prod, rôles).
  Cf. `backlog-nakala-api.md` § *Audit de parité*.

---

## Chantier 1 — Ingestion remote-first ShareDocs ⭐ ✅ LIVRÉ

**Pourquoi en premier** : indépendant de l'OCR (importer des fichiers de
travail depuis le partage institutionnel **sans montage** sert le
catalogage de base), **dé-risqué** (code éprouvé + audité + testable
hors-ligne dans BD_ditor), et il donne à ColleC un **2ᵉ adaptateur
distant** (avec Nakala) — un jalon de capacité autonome.

**Livré en 5 tranches** (chacune avec passe de revue à 2 relecteurs) :

- **T1 — client WebDAV** `external/sharedocs/client.py` : PROPFIND/GET,
  `EntreeShareDocs`, hiérarchie d'exceptions. Anti-SSRF (HTTPS exigé,
  liste blanche d'hôtes, rejet IP interne + `userinfo`, redirections non
  suivies), anti-traversal (`..`), creds en paramètres explicites
  (*resolver-ready* pour la V1.0). Testé via httpx `MockTransport`.
- **T2 — service ingestion** `api/services/sharedocs.py` :
  `importer_depuis_sharedocs` télécharge vers `<racine>/<cote>/<nom>` →
  `Fichier`. **Décision actée** : matérialiser dans une racine locale
  (intrant régénérable) plutôt que référencer à distance (cohérent « DB =
  source de vérité »). Écriture atomique, **idempotence**, **adoption**
  auto-réparante d'un binaire orphelin, **succès partiel** par fichier.
- **T4 — CLI** `archives-tool sharedocs {lister, importer}` : dry-run par
  défaut, `--format json`, codes 0/1/2.
- **T3a — page web** `/sharedocs` : connexion (creds **RAM only**,
  validés par PROPFIND avant mémorisation), parcours + fil d'Ariane.
- **T3b — UI import** : sélection (cases) + cible (fonds/item/racine) +
  aperçu dry-run → confirmation (bloqué 423 en lecture seule).

**Sécurité des identifiants** : jamais sur disque, jamais en config,
jamais loggés, jamais renvoyés au client. CLI = variables d'env
(`COLLEC_SHAREDOCS_USER/_PASS`) ; web = RAM (perdu au redémarrage). Le
coffre chiffré multi-comptes scopés par espace reste **V1.0** (Chantier 3).

**Aucune dépendance ni couplage runtime à BD_ditor** (copie → possession
→ divergence). Tests entièrement hors-ligne (`MockTransport`).

**Doc** : [`guide/cli/sharedocs.md`](../guide/cli/sharedocs.md).
**Renvois** : `deploiement-future.md` (modèle ShareDocs monté) ; emprunts
tracés cf. `ocr-module-future.md` (§ Emprunts BD_ditor) et mémoire
`bd-ditor-sibling`.

**Smoke live ✅ FAIT (2026-06-21)** : connexion + parcours + import validés
contre le vrai partage `sharedocs.huma-num.fr` (le dernier angle jamais
exercé ; tout le reste restait couvert via `MockTransport`). Plus aucun
« reste » bloquant sur le Chantier 1.

**Durcissement UX de l'import web (2026-06-21)** — relevé au test d'usage :
cibles assistées (selects fonds/item, item rechargé en HTMX) + création
inline (fonds/item depuis la page, création au POST seulement) + « Tout
sélectionner » ; **import en tâche de fond** (2ᵉ tâche de fond : module
`sharedocs_jobs`, garde mono-job indépendante, barre de progression HTMX) +
**annulation coopérative** (arrêt entre fichiers, partiel conservé, reprise).
Cf. `CLAUDE.md` § Chantier 1. **Dette confirmée** : la garde mono-job de
`sharedocs_jobs` est, comme celle de Nakala, per-process et non isolée
per-utilisateur → à factoriser au Chantier 3 (cf. § Transverse, isolation
des états module-globaux).

---

## Chantier UI⁺ — Surfaçage de l'existant & polissage du front (interleavable)

**Origine** : point d'approfondissement du 2026-06-22 (revue de l'UI/front +
cartographie des écarts CLI ↔ UI, 2 explorations). **Statut** : **Paniers A et
B entièrement livrés** (mini-chantier resserré 2026-06-22 + hygiène
transversale B-hyg-1/2/3 le 2026-06-24, sur `dev`) — traçabilité, inline +
autocomplete, étiquettes + filtrage, QA / comparer-fichiers, quick-actions,
tokens CSS, a11y de base, états vides. **Reste optionnel** : a11y large +
Panier C (net-new). Sans dépendance dure (interleavable avec/avant le
Chantier 2).

!!! success "Livré (chantier UI⁺, 2026-06-22)"
    **Lot 1** page `/journal` (suppressions + push Nakala + renommages) ·
    **Lot 2** historique des modifications sur la fiche item (`ModificationItem`,
    modèle qui était **dormant** → producteur livré) · **Lot 3** autocomplete
    des valeurs existantes sur les champs libres (l'inline étendu était déjà
    en place) · **Lot 4 + 4c** étiquettes colorées de chantier (modèle +
    page de gestion + étiquetage HTMX sur la fiche + filtrage drawer/pastilles).
    ~+90 tests ; suite à 2045 verts. Chaque lot revu (a trouvé du réel à
    chaque fois : branches non testées, cascades, injection JS, round-trip).

**Constat** : le back/CLI/Nakala a pris une avance nette sur le front. Logique
métier ~90 % couverte, CLI ~100 %, **UI web ~50 %** des capacités et **~7/10
de finition** (« fonctionnel, pas poli » ; accessibilité ~40 %). Une partie de
l'écart est **assumée** (masse / admin / audit = power-user CLI, cf. décision
« UI = workflow catalogage récurrent »), mais le différentiel sert mal deux
piliers du positionnement : *traçabilité / capitalisation de la connaissance
tacite* et *préparation de la confiance multi-utilisateurs (V1.0)*.
L'investissement le plus rentable ici n'est **pas du net-new** mais
**(A) surfacer en UI ce qui existe déjà côté service** et **(B) polir le
front**.

!!! note "Correctifs de cartographie (déjà livrés en UI — ne pas recompter)"
    Création **en série d'items** (`/collection/{cote}/items/serie`), création
    de **collection libre** (`/collections/nouvelle`), **édition page
    complète** (`/{item,collection,fonds}/{cote}/modifier` GET+POST), et
    **ShareDocs web** (`/sharedocs` + tâche de fond) existent bien — une sonde
    automatique les avait à tort signalés comme manquants.

### Panier A — Surfacer l'existant (back prêt, ROI max, risque min)

Données déjà journalisées, services de lecture déjà écrits → essentiellement
des **pages read-only** à brancher.

| Piste | Back disponible | Valeur | Coût | État |
| --- | --- | --- | --- | --- |
| Vues **journal/audit** : suppressions (`OperationEntite`), push Nakala (`OperationPushNakala`), historique renommage | `montrer suppressions` / `montrer push-nakala` / `renommer historique` | Traçabilité (pilier) ; prépare V1.0 | Faible | ✅ Lot 1 |
| Onglet **« Historique »** sur l'item (`ModificationItem`) | journal déjà alimenté | Transparence « qui/quoi/quand » | Faible | ✅ Lot 2 |
| Page **QA `controler`** (santé base, read-only) | `qa/orchestrateur` | Nettoyage = opération de 1er ordre | Moyen | ✅ page `/controler` (base \| fonds) |
| **`comparer-fichiers` Nakala** en diagnostic sur la fiche item | `nakala_fichiers.comparer_fichiers_item` | Pré-visualiser un push, non destructif | Moyen | ✅ lazy-load HTMX sur la fiche (lecture seule) |

**Resté CLI volontairement** (principe n°6) : renommage batch, dérivés en
masse, import profil YAML complet, push de fichiers binaires Nakala — un bouton
« renommer 7500 fichiers » dans un onglet navigateur n'en vaut pas le risque.

### Panier B — Polir le front (augmentation > prolifération)

| Piste | Pourquoi | Valeur | Coût | État |
| --- | --- | --- | --- | --- |
| **Édition inline étendue** (tous champs simples fonds/collection) + **autocomplete** des valeurs existantes | mécanique existante à propager ; `idees-ui-vrac` favori #2 | Quotidien | Faible | ✅ Lot 3 (inline déjà fait + autocomplete livré) |
| **Étiquettes colorées** libres (≠ `etat_catalogage`) + **filtrage** | marquage workflow ; table dédiée (jamais exportée) + filtre drawer ; favori #1 | Quotidien | Faible-moyen | ✅ Lot 4 + 4c |
| **Quick actions au survol** des lignes | petit, visible ; favori #3 | Confort | Faible | ✅ changement d'état inline (`<select>` au survol du tableau collection) |
| **Hygiène transversale** : états vides explicites, pagination visible, validation client légère, **tokens CSS** (couleurs en dur → variables), **a11y de base** (landmarks, aria tableaux/pagination, focus-trap modales) | passe « fonctionnel → poli » ; a11y ~40 % | Large, diffus | Faible→moyen par lots | ✅ B-hyg-1/2/3 (2026-06-24) |

### Panier C — Net-new ambitieux (différer, souvent meilleur après l'OCR)

Command palette (Ctrl+K étendu), preview pane, **vue Avancement consolidée**
(`plan-de-chantier`), modes comparaison / similaires / diaporama. Payback plus
incertain ; la recherche plein-texte (Chantier 2) les rend plus puissants. →
relèvent du **Chantier 5** / `idees-ui-vrac.md`.

### Suite (mini-chantier resserré FAIT)

- **Fait (2026-06-22)** : le mini-chantier resserré — Panier A (traçabilité)
  + Panier B (inline déjà fait, autocomplete, étiquettes + filtrage) — est
  livré. Il comblait le trou le plus visible (la traçabilité existait en base
  mais était invisible dans le navigateur) et prépare la confiance V1.0.
- **Complément (2026-06-22)** : **quick-action « changement d'état inline »**
  au survol du tableau de collection — déclencheur ▾ discret (`group-hover`)
  → éditeur `<select>` des 5 états en HTMX (GET ouvre / lit la version
  fraîche, POST applique via `modifier_item` donc journalisé + verrou
  optimiste, GET `?annuler` reswap le badge). Workflow de vérification en
  série sans ouvrir chaque fiche. Masqué en lecture seule (trigger caché +
  POST bloqué 423). Conflit de version → badge rechargé (pas de 409
  invisible). `routes/etat_rapide.py` + `components/cellule_etat.html` ;
  16 tests. **Reste du favori #3** (étiqueter / dupliquer / supprimer au
  survol) volontairement différé : étiqueter demande une colonne étiquette
  dans le tableau, dupliquer un service inexistant, supprimer contredirait
  le gating par recopie de cote.
- **Panier A complété (2026-06-22)** : **page QA `/controler`** (bilan de
  santé, base \| fonds, lecture seule — surface les 14 contrôles `qa`) +
  **diagnostic `comparer-fichiers`** en lazy-load HTMX sur la fiche item
  (pré-visualise un push : nouveaux / modifiés / orphelins / fantômes /
  transcriptions ; appel réseau à la demande, best-effort sans 500). Panier A
  est désormais **entièrement livré**.
- **Reste, opportuniste** : hygiène transversale / a11y / tokens CSS
  (Panier B) ; Panier C après l'OCR. Aucun n'est bloquant.
- **Hors scope ici** : l'isolation per-user des états module-globaux reste un
  **prérequis V1.0 (Chantier 3)**, pas du polish UI (cf. § Transverse).

#### Panier B « hygiène transversale » — ✅ LIVRÉ (2026-06-24)

**Panier A : terminé.** **Panier B : terminé** — les trois lots d'hygiène
transversale livrés en une passe (commits `f2021fd`, `81b1b58`, `d4ee5f2`
sur `dev`) :

- **B-hyg-1 — Tokens CSS ✅.** Les 5 couleurs sémantiques (~74 hex dupliqués
  en styles inline, dicts Jinja et chaînes JS) centralisées en custom
  properties CSS dans `input.css` `:root` (`--state-info/warn/ok/err/neutral`) ;
  les tokens Tailwind `state-*` pointent dessus → source unique partagée par
  les classes utilitaires ET les usages inline/JS. Changer une couleur = une
  ligne. Zéro changement visuel.
- **B-hyg-2 — a11y de base ✅.** Lien d'évitement (`.skip-link`) →
  `<main id="contenu">` ; `<nav aria-label="Navigation principale">` (header,
  `class="contents"` = zéro impact flex) ; `scope="col"` + `<caption>` sr-only
  sur `tableau_items`/`tableau_collections` ; `<nav aria-label="Pagination">`.
  **Focus-trap** : nouvel utilitaire partagé `static/js/focus_trap.js`
  (`window.ColleCFocusTrap`) réutilisé par les deux overlays — drawer filtres
  (`role=dialog` + `inert` à l'état fermé) et modale colonnes (`role=dialog`,
  focus rendu au déclencheur à la fermeture).
- **B-hyg-3 — états vides ✅.** Ligne d'état vide for-else sur `tableau_items`
  (cas filtres-actifs-sans-résultat, avant : corps vide muet) et
  `tableau_collections` ; état vide + CTA import + a11y sur `fonds_liste`. La
  validation client (`required`) était déjà fournie par les macros
  `_champ_form` ; la pagination déjà visible (compteur + nav). 4 tests
  (`test_etats_vides`).

Reste optionnel/opportuniste : la couverture a11y plus large (tous les
formulaires hérités, contraste, gestion du focus sur swaps HTMX) et les tokens
CSS non-sémantiques (gris, chips) — non bloquants, à puiser au gré des
opportunités.

**Panier C : différé** (command palette, preview pane, vue Avancement
consolidée `plan-de-chantier`, modes comparaison/diaporama) — meilleur après
le **Chantier 2 (OCR / recherche plein-texte)**, dont il décuple la valeur.
Relève du **Chantier 5** / [`idees-ui-vrac.md`](idees-ui-vrac.md).

**Alternative au polish** : basculer directement sur le **Chantier 2 (OCR
text-first)** — le prochain saut de valeur dans l'ordre des dépendances. Le
Panier B reste opportuniste et interleavable.

**Renvois** : `idees-ui-vrac.md` (paniers B/C), `plan-de-chantier.md` (vue
Avancement), `annotations-image-future.md` (l'autocomplete vocab y prépare le
terrain).

---

## Chantier 2 — OCR / recherche plein-texte (text-first)

Recadré **text-first** (2026-06-17, cf. `ocr-module-future.md` révision en
tête). Voie dominante = **extraction de couche texte**, pas OCR-moteur.

- **A — Indexation texte** : `PyMuPDF` (déjà dépendance) extrait
  `texte_brut` par page des PDF à couche texte → modèle `OcrPage` +
  migration → colonne FTS `ocr_text` (réconciliée avec
  `description_externe`) → recherche FTS5. **Zéro ML / ALTO / outil
  externe** ; validable tout de suite sur le corpus PF (PDF à couche
  texte, disponibles en local comme simili).
- **B — Crop pour illustrer** : recherche → région → crop net (coords
  PyMuPDF + primitive de crop serveur + Annotorious + IIIF region). Pattern
  emprunté à BD_ditor (`region_crop_png`).
- **Backfill** des notices PF importées (rafraîchir pour enrichir ; piège :
  `rafraichir` ne re-synchronise pas les fichiers).
- **Plus tard** : voie image-OCR (El País & co.) via moteur **externe**
  (Tesseract/ABBYY) → texte/ALTO ingéré ; ALTO en **export** (interop).

**Garde-fous techniques** (cf. révision du doc) : DB = source de vérité
(texte primaire, recherche hors-source) ; pas de table `OcrMot` au départ ;
triggers FTS sur la table OCR reconstruisant la ligne complète + bypass à
l'ingestion bulk + poids `bm25`.

**Renvois** : `ocr-module-future.md` (révision text-first + Phase A).

---

## Chantier 3 — Déploiement & multi-utilisateurs (V1.0)

À déclencher quand l'accès distant / à plusieurs devient un vrai besoin.

- Auth simple (attribution, pas sécurité forte) + droits + session ;
  table `Utilisateur` + middleware ; `ARCHIVES_MODE` local/serveur.
- Docker multi-stage + Caddy/nginx ; mount WebDAV (davfs2) ; TLS
  Let's Encrypt ; **sauvegarde quotidienne** (restic).
- **Tranche d'un coup plusieurs questions ouvertes** : auth, droits par
  collection, stratégie de sauvegarde, verrou optimiste sur suppression,
  empaquetage final.
- **Credentials Huma-Num multi-comptes, scopés par espace** (ShareDocs +
  Nakala) : coffre chiffré + résolveur *collection → espace → creds*,
  rattaché aux comptes ColleC. Prérequis : auth durcie (≠ simple
  attribution). Cf. `deploiement-future.md` § *Credentials Huma-Num
  multi-comptes*. **D'ici là** (Chantier 1) : creds en RAM (web) / env
  (CLI), clients *resolver-ready* (creds en paramètres explicites).

**Renvois** : `deploiement-future.md`.

---

## Chantier 4 — Diffusion / consommation aval

Débloqué par le Chantier 2 (recherche). Incarne la décision « ColleC
interne, consommation **aval** ».

- **🔑 Keystone `exporters/iiif_presentation.py`** — manifeste IIIF
  Presentation 3.0 (Manifest/item + Collection/collection). **Prérequis
  partagé** de toute la diffusion image : débloque **Canopy** (SSG
  image-first), rend réel le `iiif_manifest:` du pivot Quarto + son viewer
  (OSD/UV/Mirador), et porte les annotations W3C déjà produites.
  **Nécessaire** car Nakala n'expose **pas** la Presentation API (Image API
  seul — vérifié `nakala-savoir-api.md` §13). À faire **en premier** dans ce
  chantier ; valeur indépendante de Canopy.
- **`notebooks-sdk`** — page-guide avec recettes (l'API existe ; ne dépend
  de rien → **tirable dès H0** si envie).
- **`sites-statiques`** — deux cibles **complémentaires** (choix par
  occasion) : **Quarto/Hugo** = réponse **éditoriale** (pivot Markdown,
  narratif) ; **Canopy IIIF** = réponse **image-first** (pivot Manifest,
  feuilletage/facettes/recherche clé-en-main). Sortie publique **figée**,
  légère.
- **`portail-public`** — consommateur **dynamique** (FastAPI + Meilisearch
  + IIIF), **système séparé** ; le plus loin (corpus + OCR + IIIF requis).

**Renvois** : `notebooks-sdk-future.md`, `sites-statiques-future.md`
(§ Candidat Canopy + keystone), `portail-public-future.md`.

---

## Chantier 5 — Confort & interop (V2/V3, opportuniste)

- Vue **tableau éditable** (composant à choisir) ; **refactoring de
  métadonnées en masse** ; **journal de bord** par collection.
- **`contribution-fichiers-structures`** (TEI/XML) ; **`zotero`** —
  sur demande concrète.
- **Versioning fichiers**, opérations sur scans, **packaging distribuable**
  (V3).
- `vocabulaire-scoping` T4, `plan-de-chantier` (onglet Avancement),
  `idees-ui-vrac` — à interleaver. **Les pistes UI/front à fort ROI
  (surfaçage traçabilité, inline étendu, étiquettes) sont remontées dans le
  *Chantier UI⁺*** ; ne restent ici que le confort lourd ou tardif (vue
  tableau éditable, modes comparaison/graphe, packaging).

**Renvois** : docs `*-future.md` correspondants + `idees-ui-vrac.md`.

---

## Transverse / continu

- **Dette technique** (relevée à la revue générale 2026-06-18) :
  - **Isolation per-user des états module-globaux** — `sharedocs_session
    ._session` (creds ShareDocs en RAM) et `nakala_depot_jobs._JOBS` /
    `_id_actuel` sont partagés par toutes les requêtes. Inoffensif en
    mono-utilisateur, mais **c'est le refactor V1.0 le plus structurant** :
    ces registres doivent devenir per-utilisateur/session **avant** tout
    déploiement multi-utilisateurs (Chantier 3). Déjà anticipé dans les
    commentaires de code.
  - **Garde mono-job non extensible** — `nakala_depot_jobs._id_actuel` ne
    protège que le dépôt collection. À revoir au **Chantier 2** : l'OCR /
    extraction texte sera une 2ᵉ tâche de fond mutant des `Fichier`/`OcrPage`
    → la garde mono-job actuelle ne suffira plus (condition de remise en
    cause déjà documentée dans CLAUDE.md § *Tâches de fond*).
  - **Parité FK `Fichier.item_id`** (R5) **✅ résolu (2026-06-22)** —
    `ondelete="CASCADE"` posé au niveau SQL (migration `v0z1a2b3c4d5`), en
    parité avec les FK sœurs ; défense en profondeur contre un futur
    `delete()` bulk. Cf. `backlog-revue-generale.md` R5.
  - **Verrou optimiste `Fichier`** (colonne `version` non câblée, ≠ Item/
    Collection/Fonds). Risque réel limité aujourd'hui (ShareDocs ne fait que
    *créer* des Fichier, le push fichiers est CLI-only, `IncoherenceFichierORM`
    couvre déjà la pire course). À câbler **avec V1.0** ; audit des tests qui
    n'incrémentent pas `version` en prérequis.
  - **Re-caractérisation binaire incomplète** post-push (`format`/`largeur_px`/
    `hauteur_px` PIL obsolètes ; `hash_sha256`/`taille_octets`, eux, recalculés)
    → V2+ (calcul async).
- **Doctrine des secrets distants — asymétrie assumée** : le mot de passe
  ShareDocs (= identité complète du compte) n'est **jamais** sur disque
  (RAM web / env CLI) ; la clé API Nakala (**révocable et scopée**) vit, elle,
  dans `config_local.yaml`. Différence justifiée par la nature des secrets, à
  **unifier** dans le coffre chiffré multi-comptes du Chantier 3
  (`deploiement-future.md`). À garder en tête : d'ici là, ColleC met *un*
  secret Huma-Num sur disque (Nakala), pas *aucun*.
- **Backlog revue générale (2026-06-18)** — 5 tickets résiduels d'une revue
  en profondeur, dans
  [`backlog-revue-generale.md`](backlog-revue-generale.md) : **R1** renamer
  cycles/compensation **✅ couvert** (8 tests, aucun bug code), **R2** config
  blast-radius **✅ corrigé** (section `nakala`/`sharedocs` invalide
  désactivée seule, `lecture_seule`/`racines` préservés), **R3** collision
  plan.py disque-seul vs base **✅ corrigé** (garde base au plan), **R4**
  **R4** mkdir orphelins au rollback **✅ corrigé (2026-06-22 : cleanup
  `rmdir` des répertoires créés en phase 2, best-effort, préserve les
  préexistants)**, **R5** `Fichier.item_id` sans `ON DELETE CASCADE` **✅
  corrigé (2026-06-22, migration `v0z1a2b3c4d5` + parité FK testée)**.
  **Backlog revue générale entièrement soldé** (R1–R5). Sécurité +
  invariants vérifiés sains (aucun ticket).
- **Audit de parité Nakala apitest ↔ prod** ✅ **FAIT (2026-06-20)** — clé
  d'un vrai compte Huma-Num ; Volets A (lecture) + B (écriture item +
  collection) + parité vocab ; parité totale du contrat d'API. Cf.
  `backlog-nakala-api.md` § *Audit de parité*.
- Tests verts, doc + mémoire à jour, git propre.

---

## Hors scope (rappel des décisions structurantes)

Multi-utilisateurs simultanés avec résolution de conflits ; édition
d'image / OCR **producteur** intégrés (restent amont) ; **portail public
comme extension de ColleC** (c'est un système séparé) ; gestion de projet
prévisionnelle (reste en outil tiers). Cf. `CLAUDE.md` § *Hors scope
prévisible* et *Décisions d'architecture notables*.
