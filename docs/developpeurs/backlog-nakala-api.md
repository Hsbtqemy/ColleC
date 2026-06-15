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

## T2 — Push fichiers granulaire (`POST/DELETE …/files`) au lieu du `PUT files[]` `☐` · P1 · 1–2 sessions · risque élevé

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

**Sonde préalable (à faire avant d'implémenter — ~30 min sur apitest).**
- Que vaut `{fileIdentifier}` dans `DELETE /datas/{id}/files/{fileIdentifier}` —
  le **sha1** ou un id propre ? (déterminant pour le mapping.)
- Le `POST …/files` préserve-t-il / contrôle-t-il l'**ordre** ? (le `PUT
  files[]` garantit l'ordre, H5 ; l'additif risque d'imposer l'ordre
  d'arrivée — si oui, garder un `PUT` final pour réordonner.)
- Comportement sur un dépôt **publié** (cohérence avec le garde-fou
  `DepotPublie`).

**Changement proposé.**
- `external/nakala/write_client.py` : `ajouter_fichier(doi, {sha1, name})`
  → `POST /datas/{id}/files` ; `supprimer_fichier_donnee(doi, fileId)`
  → `DELETE /datas/{id}/files/{fileId}`.
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
- **Ordre** : si l'additif ne préserve pas l'ordre voulu, conserver un `PUT
  files[]` final pour le réordonnancement (le meilleur des deux).
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

- **S1 — Vocabulaires comme source de vérité** (`P2`) : régénérer / valider
  `TYPES_COAR_OPTIONS` et `SLUG_TO_NAKALA` contre `GET /vocabularies/
  depositTypes` (29 types) et `/properties/details` (55 propriétés +
  `allowedTypes`) plutôt que de maintenir des snapshots à la main. Un test
  de parité « notre carte ⊆ Nakala » suffirait déjà à attraper les dérives.
- **S2 — Réutiliser le `uri` doi.org** : la réponse `GET /datas` fournit
  `uri = https://doi.org/{doi}` ; l'utiliser pour les liens sortants au lieu
  de reconstruire.
- **S3 — Lire `collectionsIds` au pull** : réconcilier l'appartenance d'un
  item aux collections Nakala (aujourd'hui ignoré au mapping).
- **S4 — `GET /datas/{id}/citation`** : afficher une citation prête à
  l'emploi sur la fiche item d'un dépôt publié.
- **S5 — `PUT /datas/{id}/status/{status}`** : vérifier si publier via cet
  endpoint dédié est préférable au `PUT /datas` avec `status` (sémantique
  plus claire, à confirmer par sonde).

---

## Référence

- Savoir API complet (constats, endpoints, vocabulaires) :
  [`nakala-savoir-api.md`](nakala-savoir-api.md).
- Architecture / phasage : [`nakala-depot-future.md`](nakala-depot-future.md).
- Backlog niveau collection : [`backlog-nakala-collection.md`](backlog-nakala-collection.md).
- Code : `src/archives_tool/external/nakala/`,
  `src/archives_tool/api/services/nakala_depot.py`, `nakala_fichiers.py`.
