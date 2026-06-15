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

## T1 — Clarifier l'obligation créateur/date (ColleC ≠ Nakala) `☐` · P2 · ½ session · risque faible

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

## T3 — Surfacer `payload.validationErrors` dans les erreurs client `☐` · P2 · ¼ session · risque faible

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
- **S2 — Réutiliser le `uri` doi.org** : la réponse `GET /datas` fournit
  `uri = https://doi.org/{doi}` ; l'utiliser pour les liens sortants au lieu
  de reconstruire.
- **S3 — Lire `collectionsIds` au pull** : réconcilier l'appartenance d'un
  item aux collections Nakala (aujourd'hui ignoré au mapping).
- **S4 — `GET /datas/{id}/citation`** : afficher une citation prête à
  l'emploi sur la fiche item d'un dépôt publié.
- **S5 — `PUT /datas/{id}/status/{status}`** — ✓ **sondé (gaté, 2026-06-15)** :
  l'endpoint dédié **fonctionne** (→ 204, statut `published`). Sémantiquement
  plus clair que le `PUT /datas {status}` actuel, mais les deux marchent —
  bascule possible si on veut, sans urgence. Bonus du même run : publier ne
  crée pas de version, et la mutation de fichiers sur un dépôt publié est
  techniquement acceptée par Nakala (→ garde-fou `DepotPublie` = politique,
  pas nécessité — à garder). Cf. savoir-api §13.

---

## Référence

- Savoir API complet (constats, endpoints, vocabulaires) :
  [`nakala-savoir-api.md`](nakala-savoir-api.md).
- Architecture / phasage : [`nakala-depot-future.md`](nakala-depot-future.md).
- Backlog niveau collection : [`backlog-nakala-collection.md`](backlog-nakala-collection.md).
- Code : `src/archives_tool/external/nakala/`,
  `src/archives_tool/api/services/nakala_depot.py`, `nakala_fichiers.py`.
