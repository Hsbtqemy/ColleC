# Backlog Nakala API — actions issues du sondage live

> Document interne, exclu du build MkDocs. **Backlog exécutable** : tickets
> actionnables issus de l'approfondissement de l'API Nakala (sondes live
> `apitest.nakala.fr`, 2026-06-15) consigné dans
> [`nakala-savoir-api.md`](nakala-savoir-api.md). Chaque ticket est
> auto-suffisant : constat → changement → critères d'acceptation → pièges.
> Aucun n'est encore commencé.
>
> Convention statut : `☐ à faire` · `▷ en cours` · `✓ fait`. Priorité
> P1 (valeur/risque élevés) → P3. Effort en sessions approximatives.

---

## T1 — Clarifier l'obligation créateur/date (ColleC ≠ Nakala) `✓` · P2 · risque faible

> **✓ LIVRÉ (option A — règle conservée, clarifiée).** Décision actée :
> garder la règle stricte (alignée sur *autonomie des items* / qualité
> catalographique), et corriger ce qui était trompeur. Sans changement de
> comportement. Réalisé : docstring + les **3 messages `MetaInvalide`** de
> `preflight.py` disent désormais « Règle ColleC : Nakala accepterait le
> dépôt sans, ColleC l'exige pour la qualité catalographique » ; commentaires
> « obligatoires niveau dépôt » corrigés dans `depot_mapper.py` (×2) et
> `mapper.py`. Tests `test_nakala_preflight.py` : les 2 cas « lève »
> asserent maintenant que le message mentionne « ColleC » + « Nakala » (6/6
> verts). Le callout `nakala-savoir-api.md` (title+type seulement) était déjà
> posé. **`forcer=` non ajouté** (YAGNI / principe n°6 — aucun appelant ;
> à introduire seulement si un besoin réel d'échappatoire émerge).

**Constat (live 2026-06-15).** Nakala n'exige au dépôt que **`nkl:title` +
`nkl:type`** ; omettre `creator`, `created` ou `license` → `201` accepté
(422 sinon, avec `payload.validationErrors:["The metadata <uri> is
required."]`). Or `external/nakala/preflight.py` impose un créateur
(`_cascade_createur` lève `MetaInvalide` sans `dcterms:creator`/`contributor`)
**et** une date (`_cascade_created` lève sans `dcterms:date` W3CDTF). Ces
règles sont **propres à ColleC**, pas des exigences de l'API — mais les
messages d'erreur et les docstrings les présentaient comme « obligatoires
niveau dépôt », ce qui est trompeur.

**Décision à prendre** (la seule vraie question de ce ticket) :

- **(A) Garder la règle stricte** — recommandé. Elle sert les principes du
  projet (autonomie des items, notice auto-suffisante, qualité
  catalographique avant export). Action = **documentation seulement** :
  reformuler docstrings + messages d'erreur de `preflight.py` pour dire
  « exigé par ColleC, Nakala l'accepterait sans » (le callout §3 de
  `nakala-savoir-api.md` est déjà posé).
- **(B) Assouplir** — `preflight_appliquer` n'émet plus que des
  avertissements (pas de `MetaInvalide`) quand créateur/date manquent ;
  laisser Nakala arbitrer (il acceptera). À ne faire que si un cas d'usage
  réel réclame de déposer des items sans créateur.

**Changement proposé (option A).**
- `preflight.py` : docstring module + messages des deux `raise MetaInvalide`
  → préciser « règle ColleC (traçabilité), non requise par Nakala ».
- Éventuel `forcer: bool=False` sur `preflight_appliquer` pour
  court-circuiter la cascade (échappatoire sans changer le défaut).

**Critères d'acceptation.**
- Les messages `MetaInvalide` mentionnent explicitement « ColleC » / « non
  exigé par Nakala ».
- Test existant de la cascade inchangé (option A ne change pas le
  comportement) ; si `forcer` ajouté, un test couvre le court-circuit.

**Pièges.** Option B ouvre la porte à des dépôts sous-documentés — contraire
à la posture qualité du projet. Ne pas l'appliquer par défaut.

---

## T2 — Push fichiers granulaire (`POST/DELETE …/files`) au lieu du `PUT files[]` `✓` · P1 · risque élevé

> **✓ LIVRÉ.** `pousser_fichiers_item` réécrit en opérations granulaires :
> upload → `POST /datas/{id}/files` (additif, avant suppression) → `DELETE
> /datas/{id}/files/{sha1}` (modifies-anciens + orphelins + non_actifs) →
> **`PUT files[]` de réordonnancement construit depuis l'état distant relu**
> (`_reordonner_files`, tri par `Fichier.ordre`, gère les doublons sha1 via
> une file par sha1). Le PUT réémet exactement les sha1 présents → **aucun
> drop silencieux**. Client : `NakalaEcritureClient.ajouter_fichier` /
> `supprimer_fichier_donnee`. Tous les garde-fous conservés (fantôme,
> backfill, publié, orphelins, plan vide). **Atomicité partielle assumée**
> (N appels) : ajout-avant-suppression + reprise idempotente ; cleanup
> `supprimer_upload` des seuls uploads non encore attachés. Validé : 1752
> tests unitaires + 3 d'intégration live (apitest). Reste **futur** :
> versioning fichiers (#4 SHA-1), embargo/description par fichier (le corps
> `File` les accepte, cf. §2 savoir-api).
>
> **Passe de revue 2026-06-15** (revue multi-angles) : confirmé que le risque
> #1 « DELETE collatéral sur sha1 dupliqués » est **moot** (Nakala refuse les
> doublons de sha1, sonde → 422). Ajouté un **garde-fou pré-vol
> `ContenuDuplique`** (refus propre avant toute mutation si le set final
> contient deux sha1 identiques — sinon échec partiel au 2ᵉ POST ; handler
> CLI dédié). **Doc d'atomicité tempérée** : la reprise après échec partiel
> n'est pas « transparente » (orphelins distants possibles à confirmer).
> Cleanup mineurs non retenus (3ᵉ `lire_depot` du cache, `plan.sort`).

**Constat (live 2026-06-15).** `pousser_fichiers_item`
(`api/services/nakala_fichiers.py:1021`) modifie les fichiers via
`modifier_depot(doi, files=files_cible)` → `PUT /datas/{id}` qui **remplace
intégralement** `files[]` (H1). Toute la complexité défensive du service
(catégories `orphelins_distants`, `fichiers_fantomes`, `non_actifs_a_retirer`,
exceptions `OrphelinsDetectes`/`FichierFantomeDistant`/`BackfillIncomplet`,
reconstruction d'une liste cible complète incluant les `nakala_only`) existe
**uniquement** parce qu'un PUT incomplet supprime silencieusement les
fichiers omis.

Nakala expose des endpoints **granulaires** (catalogue OpenAPI `/doc.json`),
dont **`POST /datas/{id}/files` confirmé ADDITIF** (vérifié live : un dépôt à
`[A]` + POST `B` → `[A, B]`) et `DELETE /datas/{id}/files/{fileIdentifier}`.
Les utiliser supprimerait le risque de drop silencieux à la racine.

**Sonde préalable — ✓ faite (live apitest 2026-06-15,
`scripts/explorer_files_granulaire_nakala.py`).**
- **`{fileIdentifier}` = le sha1.** `DELETE /datas/{id}/files/{sha1}` →
  **204**, retrait ciblé, les autres fichiers intacts. La donnée fichier
  n'expose **aucun id distinct du sha1** (clés : `name`, `sha1`, `size`,
  `mime_type`, `extension`, `embargoed`, `humanReadableEmbargoedDelay`,
  `description`, `puid`, `format`). → mapping direct sur le
  `Fichier.sha1_nakala` déjà stocké, **aucune colonne nouvelle**.
- **`POST /datas/{id}/files` est additif et NE contrôle PAS l'ordre.** Corps
  = `{sha1}` seul (le schéma `File` n'a **pas** de `name` — le nom est repris
  de l'upload ; le corps accepte aussi `description` et `embargoed`). Réponse
  **200** `{code:200, message:"File added"}`. Ordre relu = **LIFO** (le dernier
  POSTé passe devant), confirmé sur **8 essais dont 4–7 décisifs** (où un tri
  par sha1 aurait prédit l'inverse — ordre indépendant du sha1) → **garder un
  `PUT files[]` final pour fixer l'ordre canonique** (le PUT respecte l'ordre
  envoyé, H5).
- **Cas limites (sondes E/F/G).**
  - **DELETE du dernier fichier → 403, refusé** : impossible de vider un dépôt
    de tous ses fichiers (cohérent avec `PUT files=[]` ignoré, H3). → le
    garde-fou « préserver ≥1 fichier » sur `--retirer-orphelins` est correct.
  - **POST d'un sha1 jamais uploadé / fantôme → 500** « File not found on
    server » (≠ le **404** du `PUT`, H4 — asymétrie entre endpoints). → valider
    en amont que chaque sha1 vient d'un upload réussi.
  - **Re-POST d'un fichier déjà présent → 409 OU 500** selon l'état du stockage
    temporaire (409 si l'upload temp existe encore, **500 « File not found on
    server »** si l'upload a été consommé — cas du `deposer_item`). **Aucun
    effet destructif** (le fichier reste, pas de doublon), mais **code non
    fiable** → faire la détection « déjà présent » **côté client** avant le
    POST, ne pas se reposer sur le code HTTP.
- **Dépôt publié — ✓ sondé (gaté, 2026-06-15).** Nakala **accepte**
  techniquement `POST`/`DELETE` de fichiers sur un dépôt publié (200 / 204,
  sans créer de version) → le garde-fou `DepotPublie` de ColleC est une
  **politique** (protéger les citations DataCite), pas une nécessité technique
  — **confirmé pertinent à garder**. Détail : savoir-api §13.

**Changement proposé.**
- `external/nakala/write_client.py` : `ajouter_fichier(doi, sha1)`
  → `POST /datas/{id}/files` corps `{sha1}` (nom hérité de l'upload) ;
  `supprimer_fichier_donnee(doi, sha1)` → `DELETE /datas/{id}/files/{sha1}`
  (le `{fileIdentifier}` **est** le sha1, donc `Fichier.sha1_nakala`).
- `pousser_fichiers_item` réécrit en opérations ciblées :
  `nouveaux` → `ajouter_fichier` ; `modifies` → `ajouter_fichier` puis
  `supprimer_fichier_donnee` de l'ancien ; `orphelins_distants` (si
  `retirer_orphelins`) → `supprimer_fichier_donnee` ; `nakala_only` et
  `inchanges` → **ne rien faire** (plus besoin de les renvoyer).
- Conséquence : la catégorie `fichiers_fantomes` n'est plus *bloquante*
  (un sha1 fantôme ne casse plus une liste complète) — réévaluer son rôle.

**Critères d'acceptation.**
- Smoke live opt-in (apitest) : dépôt 3 fichiers → modifier 1, ajouter 1,
  retirer 1 via endpoints granulaires → relecture conforme, **les fichiers
  non touchés intacts**.
- Tests unitaires des nouvelles méthodes client (httpx mocké).
- `Fichier.sha1_nakala` mis à jour comme avant ; cache `RessourceExterne`
  invalidé.
- Garde-fou orphelins conservé (intention explicite via `retirer_orphelins`),
  mais ré-exprimé en « je vais DELETE ces N fichiers » plutôt que « je
  reconstruis la liste sans eux ».

**Pièges.**
- **Atomicité** : N appels au lieu d'1 → un échec à mi-parcours laisse un
  état intermédiaire. Prévoir ordre sûr (ajouter avant de supprimer) +
  idempotence à la reprise.
- **Perf** sur gros items (N round-trips) — acceptable, mais à mesurer.
- **Ordre** : confirmé **LIFO** (sonde C) — l'additif ne préserve **pas**
  l'ordre voulu. Finir par un `PUT files[]` pour fixer l'ordre canonique
  (H5 garantit que le PUT respecte l'ordre envoyé).
- **Doublon sha1 / sha1 fantôme** : re-POST d'un fichier déjà présent →
  **409 ou 500** selon l'état du stockage temporaire ; sha1 jamais uploadé →
  **500**. Codes non fiables et non destructifs → **détecter « déjà présent »
  et valider les sha1 côté client** avant le POST, ne pas se reposer sur le
  code HTTP de Nakala.
- Ne pas casser le journal `OperationPushNakala` (passe 24) qui snapshot le
  `files[]` avant/après.

---

## T3 — Surfacer `payload.validationErrors` dans les erreurs client `✓` · P2 · risque faible

> **✓ LIVRÉ.** Helper partagé `client.detail_erreur_nakala(reponse)` qui annexe
> `payload.validationErrors` (le détail par champ d'un 422) au message
> générique. Branché dans les **deux** `_verifier_statut` (lecture `client.py`
> + écriture `write_client.py`) — factorisé plutôt que dupliqué. Défensif :
> payload absent / non-dict / liste vide / corps non-JSON → message générique
> seul. Tests : helper direct (cas défensifs) + 422 avec/sans validationErrors
> côté écriture ET lecture (466 tests nakala verts).

**Constat (live 2026-06-15).** Un `422` Nakala porte le détail par champ dans
**`payload.validationErrors`** (ex. `["The metadata http://nakala.fr/terms#title
is required."]`). Or `write_client._verifier_statut`
(`external/nakala/write_client.py:120-130`) ne lit que
`charge.get("message") or charge.get("error")` → l'utilisateur voit le
message générique « Data could not be submitted because of invalid data »,
sans savoir **quel champ** pose problème.

**Changement proposé.**
- Dans `_verifier_statut` (et son jumeau lecture `client.py` si pertinent),
  après extraction de `detail`, lire `charge.get("payload", {}).get(
  "validationErrors")` (liste) et l'annexer au message de
  `NakalaSoumissionInvalide` quand elle est présente.

**Critères d'acceptation.**
- Test unitaire : réponse 422 mockée avec `payload.validationErrors` → le
  message de l'exception **contient** les libellés de champ.
- Réponse 4xx sans `validationErrors` → comportement inchangé (robustesse).

**Pièges.** `payload` peut être absent ou non-dict ; rester défensif. Ne pas
logguer de PII (les libellés sont des URIs de propriété, sans donnée).

---

## Opportunités secondaires (repérées au sondage, à arbitrer plus tard)

Plus légères, pas de ticket détaillé tant qu'un besoin concret n'émerge pas :

- **S1 — Vocabulaires comme source de vérité** (`P2`) — ✓ **sonde de parité
  faite (2026-06-15, `scripts/verifier_parite_vocabulaires_nakala.py`,
  lecture seule) : RAS.** 29/29 types COAR du snapshot ColleC acceptés au
  dépôt, toutes les projections `type_coar_pour_nakala` ⊆ `depositTypes`, et
  les 57 `propertyUri` de `SLUG_TO_NAKALA` ⊆ les 60 de `/vocabularies/
  properties` (⚠️ utiliser `/properties` — 60 URIs complètes — et **non**
  `/properties/details` dont la clé `uri` = le namespace). ✓ **Promue en test
  de non-régression** : `tests/test_nakala_vocabulaires_integration.py`
  (opt-in `-m integration`, 3 assertions ⊆ live). Rejouer après toute évolution
  de `SLUG_TO_NAKALA` / `TYPES_COAR_OPTIONS` / du snapshot COAR.
- **S2 — Liens sortants autoritatifs** — ✓ **LIVRÉ** (réinterprété). Le `uri`
  fourni par Nakala (`doi.org/{doi}` pour une **donnée**,
  `nakala.fr/collection/{doi}` pour une **collection**) est trivialement
  reconstructible — la valeur réelle était la **cohérence/justesse** des liens
  construits. Audit : `lien_doi` (donnée → `doi.org/{doi}`) correct, mais
  `synthese_fonds.html` liait une **collection** vers `nakala.fr/{doi}`
  (manque `/collection/` → route vers une donnée, lien cassé). Corrigé vers
  `nakala.fr/collection/{doi}` (forme du `uri` que `GET /collections` renvoie,
  savoir-api §3) + garde-fou test (`test_synthese_fonds_doi_visible_dans_rendu`
  qui asseyait l'ancienne forme cassée — inversé). Aucun autre lien sortant
  fautif (audit `grep` complet). **Capturer le champ `uri` est inutile**
  (redondant avec la reconstruction) — non fait à dessein.
- **S3 — Lire `collectionsIds` au pull** — ✓ **LIVRÉ.**
  `DepotNakala.collections_ids` capte le champ ; `rapatrier` réconcilie via
  `_reconcilier_collections_nakala` : pour chaque DOI, lie l'item à la
  Collection ColleC dont `doi_nakala` matche (junction `ItemCollection`,
  idempotent, sans commit propre → atomique avec le cache ; rejoue au re-pull
  d'un item déjà présent). **Ne crée aucune Collection** : un DOI sans miroir
  ColleC ressort en `collections_inconnues` (signalé, jamais auto-créé — scope
  lecture). Surfacé dans `RapportRapatriement` + CLI `nakala rapatrier`
  (texte + JSON). **Passe de revue** : matching DOI **normalisé des deux
  côtés** (`_resoudre_collections_par_doi` — tolère un `doi_nakala` stocké en
  forme URL) ; **miroir du fonds exclue** du rapport (déjà liée par
  `creer_item`, sinon bruit ×N sur un pull collection) ; **aperçu dry-run**
  (résolution lecture seule, le preview liste ce qui serait rattaché) ;
  **additif assumé** (rejoue l'appartenance Nakala, préserve les
  appartenances ColleC-only, ne retire jamais — une appartenance retirée
  manuellement mais toujours sur Nakala réapparaît au pull). Tests : mapper +
  6 tests pull (connu/inconnu, idempotence sans doublon + persistance,
  aperçu dry-run, exclusion miroir, normalisation URL↔nu).
- **S4 — `GET /datas/{id}/citation`** — ✓ **LIVRÉ.** Citation
  bibliographique prête à l'emploi surfacée des **deux** côtés :
  `ClientLectureNakala.citation(doi)` (tolère chaîne JSON / texte / vide) ;
  CLI `nakala citer <doi> [--format text|json]` + ligne « Citation » dans
  `nakala montrer` (chargée seulement si le dépôt est `published`) ; fiche
  web `/item/<cote>` = section « Citation Nakala » chargée **à la demande**
  via HTMX (route `GET /nakala/item/<cote>/citation`, partial
  `nakala_citation.html`) car Nakala est lent (~3-5 s) — pas de fetch à
  chaque rendu. Best-effort (toute erreur Nakala → message, jamais 500).
  Tests : client (4) + CLI (4) + web (4).
- **S5 — `PUT /datas/{id}/status/{status}`** — ✓ **sondé (gaté), décision :
  garder l'actuel.** L'endpoint dédié **fonctionne** : `PUT
  /datas/{id}/status/published` (sans corps) → **204**, publie et
  **préserve les metas** (`av.metas == ap.metas`, re-sondé 2026-06-15). Il
  découple publication / écriture de metas. Mais `publier_item` re-pousse
  volontairement les metas locales (`PUT /datas {metas, status}`) — aligné
  sur le **principe n°1** (la base locale fait foi → on publie ce que ColleC
  a). **Décision : ne pas basculer** (la bascule publierait l'état distant
  tel quel, possiblement périmé vs local). Bonus du run : publier ne crée
  pas de version, et muter les fichiers d'un dépôt publié est techniquement
  accepté par Nakala (→ garde-fou `DepotPublie` = politique, pas nécessité —
  à garder). Cf. savoir-api §13.

---

## #4 Versioning fichiers — caractérisé (pas de chantier ColleC)

Le « versioning fichiers » longtemps listé comme chantier ouvert est
**résolu par l'observation** (cycle live 2026-06-15, dépôt sacrifié
`10.34847/nkl.66bc6vvi`) : **Nakala versionne automatiquement**. Sur un
dépôt **publié**, chaque mutation de fichier (`POST`/`DELETE …/files`) crée
une version `.vN` (`version` incrémenté, `/versions` enrichi) ; les éditions
de **metas** mutent en place (pas de version) ; sur **pending**, rien ne
versionne. Les versions snapshotent les **fichiers** (les metas sont
partagées sur toutes les versions). Détail : savoir-api §7.

**Conséquence** : ColleC n'a **pas** à construire de gestion de versions —
Nakala s'en charge. Le seul point d'attention est que `pousser_fichiers_item`
en mode granulaire crée **une version par opération** (POST + DELETE + PUT
réordonnancement) sur un dépôt publié → le garde-fou `DepotPublie` (défaut)
évite la prolifération de `.vN`. **Améliorations possibles si besoin réel**
(non prioritaires) : exposer l'historique `/versions` en lecture sur la
fiche item ; sur le chemin `--force-published`, regrouper en un seul
`PUT files[]` pour ne créer qu'une version.

---

## Référence

- Savoir API complet (constats, endpoints, vocabulaires) :
  [`nakala-savoir-api.md`](nakala-savoir-api.md).
- Architecture / phasage : [`nakala-depot-future.md`](nakala-depot-future.md).
- Backlog niveau collection : [`backlog-nakala-collection.md`](backlog-nakala-collection.md).
- Code : `src/archives_tool/external/nakala/`,
  `src/archives_tool/api/services/nakala_depot.py`, `nakala_fichiers.py`.
