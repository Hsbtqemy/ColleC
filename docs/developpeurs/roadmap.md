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

---

## Horizon 0 — Consolidation (en cours / continu)

- **FF `main`** pour promouvoir le palier S7 **+ le Chantier 1 ShareDocs**.
- **Quick wins** : S6 (validation licence SPDX au preflight/export) ;
  `notebooks-sdk` (page-guide — l'API publique existe déjà, ne dépend de
  rien, tirable n'importe quand).
- **Passif / bloqué externe** : smoke S7 live + sonde S8 (vocabulaire des
  `type` de relation) dès qu'**apitest** revient (LB up, backend down au
  2026-06-18) ; **audit de parité apitest ↔ prod** quand on dispose d'une
  **clé d'un vrai compte Huma-Num** + accord pour un dépôt sacrificiel.

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

**Reste possible (non bloquant)** : smoke test contre un vrai partage
ShareDocs (jamais exercé en live — tout est validé via `MockTransport`),
le jour où un accès Huma-Num est disponible.

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
