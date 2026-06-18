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
Fonds/Collection/Item/Fichier, CLU + UI complètes, recherche FTS5,
intégration **Nakala quasi-bouclée** (lecture + écriture + round-trip
métadonnées **et** fichiers + S7 transcription par fichier). Base livrée
**V0.10.0** ; la branche `dev` est +8 (palier Nakala S7 + recadrage OCR),
**1811 tests verts**. Mode actuel : **local mono-utilisateur**.

## Principe de séquencement (décidé 2026-06-18)

1. **ShareDocs en 1er chantier** — dé-risqué par l'outil sœur `BD_ditor`,
   autonome (utile au catalogage sans OCR), concrétise le modèle
   « remote-first ».
2. **OCR / recherche plein-texte avant V1.0** — corpus et recherche
   d'abord ; **toute la diffusion en dépend** (un site/portail sans
   recherche est tiède).
3. **V1.0 (déploiement + multi-utilisateurs) ensuite** — à déclencher
   quand l'accès distant/à plusieurs devient un vrai besoin.
4. **Diffusion après l'OCR.**
5. **Confort / interop** (V2/V3) en opportuniste.

---

## Horizon 0 — Consolidation (en cours / continu)

- **FF `main`** pour promouvoir le palier S7 (`dev` +8).
- **Quick wins** : S6 (validation licence SPDX au preflight/export) ;
  `notebooks-sdk` (page-guide — l'API publique existe déjà, ne dépend de
  rien, tirable n'importe quand).
- **Passif / bloqué externe** : smoke S7 live + sonde S8 (vocabulaire des
  `type` de relation) dès qu'**apitest** revient (LB up, backend down au
  2026-06-18) ; **audit de parité apitest ↔ prod** quand on dispose d'une
  **clé d'un vrai compte Huma-Num** + accord pour un dépôt sacrificiel.

---

## Chantier 1 — Ingestion remote-first ShareDocs ⭐ (premier build)

**Pourquoi en premier** : indépendant de l'OCR (importer des fichiers de
travail depuis le partage institutionnel **sans montage** sert le
catalogage de base), **dé-risqué** (code éprouvé + audité + testable
hors-ligne dans BD_ditor), et il donne à ColleC un **2ᵉ adaptateur
distant** (avec Nakala) — un jalon de capacité autonome.

**Ce qui est dé-risqué (port quasi-direct depuis BD_ditor)** : le **client
WebDAV** lui-même (`pipeline/sharedocs.py` : PROPFIND/GET/PUT, anti-SSRF,
creds RAM-only, testé via httpx `MockTransport`). L'audit de BD_ditor
fournit les **2 correctifs à appliquer** : garde **HTTPS** explicite +
**normalisation anti-traversal** (`..`).

**Ce qui est du travail ColleC (spécifique)** :

- service `external/` ColleC (re-implémenté au style ColleC ; **aucune
  dépendance ni couplage runtime à BD_ditor** — copie → possession →
  divergence) ;
- **branchement ingestion** : un fichier téléchargé de ShareDocs
  atterrit dans une **racine locale** (miroir/cache, intrant régénérable)
  puis devient un `Fichier` normal — **décision actée** : télécharger
  dans une racine plutôt que référencer à distance (ColleC reste capable
  de travailler/indexer hors-source ; cohérent avec « DB = source de
  vérité ») ;
- **UI** : panneau « parcourir ShareDocs → sélection → importer vers un
  fonds/collection » ;
- tests via `MockTransport` (pas de réseau réel).

**Renvois** : `deploiement-future.md` (modèle ShareDocs monté, à compléter
par ce client) ; emprunts tracés cf. `ocr-module-future.md` (révision
text-first, § Emprunts BD_ditor) et mémoire `bd-ditor-sibling`.

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

**Renvois** : `deploiement-future.md`.

---

## Chantier 4 — Diffusion / consommation aval

Débloqué par le Chantier 2 (recherche). Incarne la décision « ColleC
interne, consommation **aval** ».

- **`notebooks-sdk`** — page-guide avec recettes (l'API existe ; ne dépend
  de rien → **tirable dès H0** si envie).
- **`sites-statiques`** — export arbre Markdown (Quarto phase 1, Hugo
  phase 3) ; sortie publique **figée**, légère.
- **`portail-public`** — consommateur **dynamique** (FastAPI + Meilisearch
  + IIIF), **système séparé** ; le plus loin (corpus + OCR + IIIF requis).

**Renvois** : `notebooks-sdk-future.md`, `sites-statiques-future.md`,
`portail-public-future.md`.

---

## Chantier 5 — Confort & interop (V2/V3, opportuniste)

- Vue **tableau éditable** (composant à choisir) ; **refactoring de
  métadonnées en masse** ; **journal de bord** par collection.
- **`contribution-fichiers-structures`** (TEI/XML) ; **`zotero`** —
  sur demande concrète.
- **Versioning fichiers**, opérations sur scans, **packaging distribuable**
  (V3).
- `vocabulaire-scoping` T4, `plan-de-chantier` (onglet Avancement),
  `idees-ui-vrac` — à interleaver.

**Renvois** : docs `*-future.md` correspondants + `idees-ui-vrac.md`.

---

## Transverse / continu

- **Dette technique** : verrou optimiste sur `Fichier` (colonne `version`
  non câblée), re-caractérisation binaire complète post-push (`format`/
  dimensions), etc.
- **Audit de parité Nakala apitest ↔ prod** (quand clé Huma-Num).
- Tests verts, doc + mémoire à jour, git propre.

---

## Hors scope (rappel des décisions structurantes)

Multi-utilisateurs simultanés avec résolution de conflits ; édition
d'image / OCR **producteur** intégrés (restent amont) ; **portail public
comme extension de ColleC** (c'est un système séparé) ; gestion de projet
prévisionnelle (reste en outil tiers). Cf. `CLAUDE.md` § *Hors scope
prévisible* et *Décisions d'architecture notables*.
