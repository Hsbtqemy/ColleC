# Nakala — comportement réel de l'API (savoir validé)

> Document interne, exclu du build MkDocs. **Référence opérationnelle** :
> ce que ColleC a *découvert et testé en live* contre l'API Nakala, par
> opposition au document de **conception/architecture**
> [`nakala-depot-future.md`](nakala-depot-future.md) (le « pourquoi » et le
> phasage) et au **guide d'usage** [`../guide/cli/nakala.md`](../guide/cli/nakala.md)
> (le « comment s'en servir »). Ici on consigne le **« comment l'API se
> comporte vraiment »** — endpoints, payloads, quirks, bugs rencontrés.
>
> Origine du savoir : sondes live `scripts/explorer_put_files_nakala.py`
> (hypothèses H1-H11 contre `apitest.nakala.fr`), les 5 tests d'intégration
> opt-in `tests/test_nakala_*_integration.py`, le code client
> `src/archives_tool/external/nakala/`, et les découvertes accumulées dans
> `CLAUDE.md`. Validé pour la dernière fois contre apitest le **2026-06-15**.

---

## En bref

ColleC possède son propre chemin Nakala **lecture + écriture** (sans
couplage madbot), couvrant le cycle complet :
**lire → rapatrier → déposer → pousser métadonnées → pousser fichiers →
publier**. Trois découvertes ont coûté du sang :

1. **Bug langue #422** — Nakala type `dcterms:language` en RFC5646 (ISO
   639-1, `es`) alors que ColleC stocke en ISO 639-3 (`spa`) → dépôt/push
   rejeté en 422.
2. **Canonicalisation des créateurs** — Nakala enrichit les créateurs au
   stockage, créant de faux diffs à chaque push si on ne canonicalise pas.
3. **`PUT /datas` remplace intégralement `files[]`** — sémantique
   « remplace », pas « ajoute » ; omettre un fichier le supprime.

---

## 1. Instances & authentification

| | Test | Production |
|---|---|---|
| Hôte | `https://apitest.nakala.fr` (alias `api-test.nakala.fr`) | `https://api.nakala.fr` |
| DOI | réservables, **aucun mint DataCite** | DOI réels minés |
| Publication | réversible (cleanup possible) | **irréversible** |
| Cleanup | `DELETE` sur pending/private | idem mais publié = définitif |

- **Header d'auth : `X-API-KEY`** (la clé est passée dans l'en-tête HTTP).
- **Lecture** : clé *facultative* pour les dépôts publiés, *obligatoire*
  pour privé / pending / sous embargo.
- **Écriture** : clé *obligatoire* — `NakalaEcritureClient` échoue à la
  construction si elle manque (fail-fast).
- **Compte de test public Huma-Num** (non secret, pour apitest) :
  `01234567-89ab-cdef-0123-456789abcdef`.
- **Config ColleC** : section `nakala: { base_url, api_key, timeout }`.
- **Variables d'env de test** : `NAKALA_API_KEY`, `NAKALA_HOST`,
  `NAKALA_ALLOW_PUBLISH=1` (garde la publication irréversible derrière un
  flag pour ne pas minter à chaque run de test).
- **Timeouts retenus** : **30 s en lecture**, **60 s en écriture** (Nakala
  est lent sur cache froid ; les uploads sont longs).

## 2. Endpoints

### Lecture

| Endpoint | Rôle | Notes |
|---|---|---|
| `GET /datas/{id}` | Lire un dépôt | renvoie `metas`, `files`, `status`, `identifier`, `version` |
| `GET /collections/{id}` | Lire une collection | `metas`, `status` (`private`/`public`) |
| `GET /collections/{id}/datas?page=N&limit=M` | Lister les données d'une collection (paginé) | renvoie **déjà les `files` complets → pas de N+1** |
| `POST /users/datas/{scope}` | Lister ce que la clé voit | **POST qui lit**, corps `{}` ; `scope` = readable/owned/deposited |
| `POST /users/collections/{scope}` | Idem pour les collections | idem |

### Écriture

| Endpoint | Rôle | Notes |
|---|---|---|
| `POST /datas/uploads` | Upload multipart (champ `file`) | renvoie `{name, sha1}` — le sha1 est la poignée du fichier |
| `POST /datas` | Créer un dépôt | corps `{status, files:[{sha1,name}], metas:[…], collectionsIds?}` |
| `PUT /datas/{id}` | Modifier un dépôt | chaque clé optionnelle ; **omise = préservée** |
| `POST /collections` | Créer une collection | corps `{status, metas:[], datas?:[doi…]}` |
| `PUT /collections/{id}` | Modifier une collection | **renvoie 204** |
| `POST /datas/{id}/collections` | Rattacher un dépôt à des collections | additif (corps = liste de DOI) |
| `DELETE /datas/{id}` | Supprimer un dépôt | **pending uniquement** |
| `DELETE /collections/{id}` | Supprimer une collection | private/pending |
| `DELETE /datas/uploads/{sha1}` | Nettoyer un upload orphelin | du stockage temporaire (cleanup best-effort) |

### Pièges de structure de réponse

- **DOI à la création** : `POST /datas` peut renvoyer le DOI sous
  plusieurs formes (`payload.id`, `payload.identifier`, ou `identifier`
  au premier niveau) → extracteur tolérant requis (`extraire_doi`).
- **Listing paginé de collection** : forme **réelle** (relevée live
  2026-06-15) = `{ data, currentPage, lastPage, limit, total }` — la clé
  des éléments est **`data` au singulier** (pas `datas`), et c'est
  **`currentPage`** (pas `page`) avec un `total` en plus. Pagination
  1-based, `limit` max 100 (ColleC utilise 25/50). L'itérateur borne le
  bouclage par `lastPage` (présent → robuste). Même dialecte pour
  `/versions` (cf. §13). ⚠️ **Trois dialectes de listing distincts** —
  voir le tableau en §3.
- **La réponse de lecture est bien plus riche que ce que ColleC en lit**
  (≈ 21 champs côté donnée, dont droits, modération, propriétaire…) et
  **diffère selon l'endpoint** (3 projections) : détail en §3,
  *« Réponse de lecture complète »*.

### Codes & corps d'erreur (relevés live 2026-06-15)

| Code | Quand | Corps |
|---|---|---|
| 201 | création OK (`POST /datas`, `/collections`) | `{code:201, message:"Data created", payload:{id:"<doi>"}}` |
| 204 | `PUT /collections/{id}` OK | vide |
| 401 | clé absente / invalide | `{message:"Request is missing required authentication credential … X-API-KEY …"}` |
| 404 | ressource inconnue | `{code:404, message:"No route found for \"GET …\""}` |
| 422 | metas / fichiers refusés | `{message:"Data could not be submitted …", payload:{validationErrors:["The metadata <uri> is required."]}}` |

Le détail par champ vit dans **`payload.validationErrors`**. ✅ **Surfacé**
(T3 livré) : `client.detail_erreur_nakala` l'annexe au message des deux
clients (lecture + écriture) — l'utilisateur voit le(s) champ(s) en cause, pas
seulement « invalid data ». Défensif si `payload` absent / non-dict.

### Comportements POST / upload (live)

- **Succès POST = HTTP 201**, DOI dans `payload.id`.
- **Upload à usage unique** : un fichier du stockage temporaire
  (`POST /datas/uploads`) est **consommé** quand il est attaché à un dépôt ;
  réutiliser le même `sha1` pour un 2ᵉ dépôt → 422. Chaque dépôt a ses
  propres uploads. ⚠️ Observé live 2026-06-15 : rejouer un **contenu
  identique** entre deux exécutions (donc même sha1) déclenche un **500** au
  `POST /datas`, pas seulement un 422 — d'où le salage uuid du contenu dans
  `scripts/explorer_files_granulaire_nakala.py` (sha1 frais à chaque run).
- **`POST /datas/{id}/files` (sondé live 2026-06-15)** : **additif** — ajoute
  un fichier sans toucher les autres (contrairement au `PUT /datas/{id}`
  `files[]` qui **remplace**, H1). Corps = `{sha1}` (schéma `File` =
  `sha1` + `description?` + `embargoed?`, **pas de `name`** : le nom est repris
  de l'upload). Réponse **200** `{code:200, message:"File added"}`. **Ordre =
  LIFO** (le dernier POSTé passe devant ; confirmé sur 8 essais dont 4–7
  décisifs — ordre indépendant du sha1) → pour fixer l'ordre d'affichage,
  finir par un `PUT files[]` (qui, lui, respecte l'ordre envoyé, H5).
  **Erreurs (non fiables, non destructives)** : sha1 jamais uploadé →
  **500** « File not found on server » (≠ le **404** du `PUT`, H4) ; re-POST
  d'un fichier déjà présent → **409 ou 500** selon l'état du stockage temp
  (500 si l'upload a été consommé). → valider « déjà présent » côté client.
- **`DELETE /datas/{id}/files/{fileIdentifier}` (sondé live 2026-06-15)** : le
  `{fileIdentifier}` **est le sha1** (la donnée fichier n'expose aucun id
  distinct du sha1). DELETE par sha1 → **204**, retrait ciblé, les autres
  fichiers intacts. **Mais retirer le *dernier* fichier → 403 (refusé)** : un
  dépôt ne peut pas être vidé de tous ses fichiers (cohérent avec `PUT
  files=[]` ignoré, H3). Couplés, POST + DELETE granulaires = voie de
  modification **sûre** des fichiers. ✅ **`pousser_fichiers_item` les emploie
  désormais** (ticket T2 livré) : mutations en POST/DELETE par sha1, puis un
  `PUT files[]` de réordonnancement **construit depuis l'état distant relu**
  (réémet exactement les sha1 présents → aucun drop silencieux, ≠ ancien push
  par `PUT files[]`). Cf. ticket **T2** du backlog API.

### Catalogue complet (56 endpoints)

Référence autoritative : **`GET /doc.json`** (spec OpenAPI / Swagger 2.0).
ColleC n'en utilise qu'une douzaine ; le reste, par tag (`datas`,
`collections`, `users`, `groups`, `vocabularies`, `search`) :

- **datas — granulaire, non utilisé** : `…/metadatas` (GET/POST/DELETE *une*
  meta), `…/files` (GET/POST/DELETE *un* fichier), `…/relations`
  (GET/POST/PATCH/DELETE), `…/rights` (GET/POST/DELETE), `…/collections`
  (GET/POST/**PUT**/DELETE — gérer l'appartenance), `…/status` +
  **`PUT …/status/{status}`** (publier proprement), `…/versions`,
  `…/citation`, `GET /data/{id}/{fileId}` (téléchargement binaire).
- **collections — granulaire** : symétrique (`…/metadatas`, `…/rights`,
  `…/status` + `PUT …/status/{status}`, `…/datas` GET/POST/DELETE).
- **users** : `GET /users/me` (utilisateur courant), `…/me/apikey`
  (régénérer / supprimer la clé), `…/datas/{datatypes,statuses,createdyears}`
  et `…/collections/{statuses,createdyears}` (facettes).
- **groups** : `POST/GET/PUT/DELETE /groups…` + `/groups/search` (modèle de
  groupes d'utilisateurs / droits).
- **divers** : `GET /authors/search`, `GET /resourceprocessing/{id}` (état
  dans ElasticSearch + DataCite), `GET /websites` (sites de collections),
  `GET /embed/{id}/{fileId}` (visionneuse Nakala), `GET /iiif/{id}/{fileId}/…`
  (Image API).

## 3. Modèle de données

### Donnée (data) vs Fichier (file)

Une **donnée** Nakala = un **Item** ColleC ; elle porte **N fichiers**. La
granularité donnée/fichier n'est qu'une option d'aplatissement du tableur
d'export ; un pull en base produit toujours **1 Item portant N Fichier**
(granularité native ColleC).

### Structure d'une « meta » (cœur du modèle)

```json
{
  "propertyUri": "http://nakala.fr/terms#title",
  "value": "…",        // str | dict | null
  "lang": "fr",         // optionnel — multilingue, RFC5646 / ISO 639-1
  "typeUri": "…"        // optionnel — W3CDTF, Period, Point, Box…
}
```

PropertyUri repérés :

- **Champs `nkl:*`** : `http://nakala.fr/terms#type` (type COAR), `#title`,
  `#creator`, `#created`, `#license`.
- **Dublin Core (`dcterms:*`)** :
  `http://purl.org/dc/terms/description`, `/subject`, `/language`,
  `/spatial`, `/temporal`, `/contributor`, `/relation`, etc.

> ⚠️ **Obligatoires : `nkl:title` + `nkl:type` SEULEMENT** (vérifié live
> 2026-06-15 par `POST /datas` avec metas incomplètes). Omettre `creator`,
> `created` ou `license` → **201 accepté**. Le 422 nomme le champ manquant :
> `{"payload":{"validationErrors":["The metadata http://nakala.fr/terms#title
> is required."]}}`. La **cascade « créateur obligatoire »** de
> `preflight.py` est donc une règle ColleC **plus stricte que Nakala**, pas
> une exigence de l'API — choix de qualité catalographique, pas une
> contrainte technique.

La **carte de vérité** côté ColleC est `SLUG_TO_NAKALA` (**57 champs**)
dans `external/nakala/depot_mapper.py` (portée du plugin madbot puis
découplée). Lecture inverse : `PROPERTY_URI_TO_SLUG` dans `mapper.py`.
Source autoritative côté Nakala : `GET /vocabularies/properties/details`
(**55 propriétés** avec leurs `allowedTypes` + `languageAuthorized`) — ce
que ColleC réimplémente à la main (cf. §4).

**Parité vérifiée propre (sonde S1, live 2026-06-15)** —
`scripts/verifier_parite_vocabulaires_nakala.py` confronte les cartes ColleC
au live : **29/29** types COAR du snapshot ColleC sont acceptés par Nakala
(aucun fantôme), toutes les projections `type_coar_pour_nakala` tombent dans
`depositTypes`, et les **57 `propertyUri`** émises sont **⊆** les 60 URIs de
`/vocabularies/properties`. Aucune dérive. Réutilisable en test de
non-régression.

### Créateur

Objet `{surname, givenname, orcid?}` ou chaîne `"Nom, Prénom [ORCID]"`.
Sentinelles anonymes (`[s.n.]`, `anonyme`) → `null`.

**Cascade preflight** (`external/nakala/preflight.py`) : si `nkl:creator`
résout à null, ColleC tente de le promouvoir depuis `dcterms:creator` bien
formé ; à défaut exige au moins un `dcterms:creator`/`dcterms:contributor`,
sinon `MetaInvalide`. Même logique pour la date (`nkl:created` ←
`dcterms:date` W3CDTF valide). ⚠️ Rappel : cette obligation est **propre à
ColleC** — Nakala accepte un dépôt sans créateur ni date (cf. callout
ci-dessus).

### Fichier (dans une réponse `GET /datas`)

Jeu complet des 10 champs confirmé live (relecture `GET /datas`, 2026-06-15) :

```json
{
  "name": "scan_0001.jpg",
  "sha1": "da39a3ee…",          // 40 hex — poignée du fichier
  "size": 12345,                 // octets
  "mime_type": "image/jpeg",     // API expose "mime_type" (code accepte aussi "mime")
  "embargoed": "2099-12-31T00:00:00+01:00"|null,  // datetime + fuseau Europe/Paris
  "humanReadableEmbargoedDelay": "…",  // délai d'embargo lisible (texte)
  "extension": "jpg",
  "puid": "fmt/43",              // PRONOM (optionnel)
  "format": "JPEG",             // PRONOM label (optionnel)
  "description": "…"            // optionnel (cf. H11)
}
```

### Dates

Format **W3CDTF** : `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM:SS`
avec timezone `Z`/`±HH:MM`. Sentinelle `[s.d.]`/`inconnue` → null.

### DOI / identifiant

Format `10.34847/nkl.xxxxxxxx` (registrant Huma-Num), variante versionnée
`…​.vN`. `normaliser_identifiant_nakala` extrait le DOI d'une URL
(`nakala.fr/collection/…`), d'un `doi:…` ou d'un DOI nu (regex
`10\.\d+/[^\s/?#]+`) ; best-effort, sinon saisie rendue telle quelle (404
propre en aval).

### Réponse de lecture complète (champs ignorés par ColleC)

`GET /datas/{id}` renvoie **≈ 21 champs** ; le `mapper` ColleC n'en consomme
que **4** (`metas`, `files`, `status`, `identifier`). Relevé live sur dépôts
publics apitest (2026-06-15) :

| Champ | Contenu | ColleC |
|---|---|---|
| `identifier` | DOI `10.34847/nkl.…` | ✅ lu |
| `metas` / `files` | métadonnées / fichiers | ✅ lu |
| `status` | `pending` / `published` / … | ✅ lu |
| `uri` | **URL résolvable `https://doi.org/{doi}`** (≠ URL API) | ignoré |
| `version` | entier (cf. §13) | exporté tableur |
| `creDate` / `modDate` | datetimes +TZ (`modDate` sert à détecter la dérive au push) | partiel |
| `collectionsIds` | DOIs des collections d'appartenance | ✅ lu (S3) → `DepotNakala.collections_ids` ; `rapatrier` réconcilie l'item aux Collections ColleC dont `doi_nakala` matche |
| `relations` | relations inter-données (**vide sur 30/30 sondés — rare**) | ignoré |
| `fileEmbargoed` | booléen niveau-donnée : ≥ 1 fichier sous embargo (1/30 sondés) | ignoré |
| `owner` / `depositor` | objet user `{id (UUID), name, type, username, givenname, surname, photo}` | ignoré |
| `isAdmin`/`isDepositor`/`isEditor`/`isOwner` | **droits relatifs à l'appelant** (tous `false` avec une clé non-propriétaire) | ignoré |
| `lastModerator` / `lastModerationDate` / `lastModerationRequestDate` / `moderationRequester` | workflow de **modération** Nakala (null hors modération) | ignoré |

**3 projections de donnée distinctes** (même donnée, champs différents
selon l'endpoint — piège pour qui parse) :

| Projection | Champs propres |
|---|---|
| `GET /datas/{id}` | `owner`, `depositor`, `isAdmin/isDepositor/isEditor/isOwner`, `fileEmbargoed` |
| item de `/search` | `rights` (liste de rôles), `publicCollectionsIds`, `datestamp` (datetime **sans** fuseau) |
| item de `/collections/{id}/datas` | projection de listing |

Le champ `rights` (projection search) expose le **modèle de rôles Nakala** :
`[{role: "ROLE_DEPOSITOR", id, name, type, username, …}]`.

**`GET /collections/{id}`** a sa propre forme : `identifier`, `status`
(`public`/`private`), `metas`, `uri` (**URL web humaine
`https://[test.]nakala.fr/collection/{doi}`**), `creDate`, **`modDate`
souvent `null`** (confirme empiriquement « collections sans dérive », §6),
`owner` (avec sous-liste `users`), `depositor`, droits `isXxx`,
`haveData` / `haveAccessibleData`, et une **feature site web** :
`websiteEnabled`, `websitePrefix`, `websitePublished`.

**Trois dialectes de listing paginé** :

| Endpoint(s) | Forme |
|---|---|
| `/collections/{id}/datas`, `/datas/{id}/versions` | `{data, currentPage, lastPage, limit, total}` |
| `/search` | `{datas, totalResults}` (clé `datas` au pluriel, pas de curseur de page) |

**Trois hôtes Nakala distincts** : `api[test].nakala.fr` (API REST),
`[test.]nakala.fr` (UI web humaine — cible des `uri` de collection et des
sites), `doi.org` (résolveur DOI — cible du `uri` de donnée).

### Forme d'écriture des metas (`depot_mapper.py`)

La carte de vérité `SLUG_TO_NAKALA` (**57 champs**) ne se contente pas de
mapper `slug → propertyUri` : elle porte aussi un **`typeUri`** (indice de
type XSD/DC transmis dans chaque meta) et impose une **forme** par champ.
Détail non-évident à re-dériver, donc consigné ici.

**Vocabulaire des `typeUri`** émis :

| `typeUri` | Pour |
|---|---|
| `http://www.w3.org/2001/XMLSchema#anyURI` | `nkl:type` (URI COAR) |
| `http://www.w3.org/2001/XMLSchema#string` | texte (titre, description, sujet, la plupart des `dcterms:*`) |
| `http://purl.org/dc/terms/RFC5646` | **`dcterms:language`** — reconfirme l'origine du bug #422 (Nakala type la langue en RFC5646) |
| `http://purl.org/dc/terms/W3CDTF` | dates (`dcterms:date`, `issued`, `modified`, `created`…) |
| `…/Period`, `…/Point`, `…/Box` | structures temporal / spatial (posés par valeur) |

**5 catégories de forme** d'une valeur de slug à l'écriture :

1. **Multilingue** — liste `[{value, lang}]` (titre, description, sujet,
   coverage + ~15 DC qualifiés). Chaque entrée → une meta avec `lang`.
2. **Liste de chaînes** — `nkl_creator`, `dcterms_language`,
   `dcterms_contributor` → N metas (une par item).
3. **Tableau de chaînes** — identifiants / relations (`isPartOf`,
   `references`…) / dates → N metas.
4. **Scalaire** — `nkl_type`, `nkl_created`, `nkl_license` → une meta.
5. **Structures** — `dcterms_temporal`, `dcterms_spatial` (cf. DCSV).

**Encodage DCSV (spatial / temporal)** — le point le plus piégeux : un
objet est **aplati en chaîne** `clé=valeur` jointe par `; `, le `typeUri`
portant la sémantique :

- `temporal` : chaîne brute → `typeUri=W3CDTF` ; objet
  `{start, end, name}` → `start=…; end=…; name=…` + `typeUri=Period`.
- `spatial` : objet `{kind:"Point", east, north, elevation, name}` →
  `east=…; north=…; …` + `typeUri=Point` ; `{kind:"Box", northlimit,
  southlimit, eastlimit, westlimit, uplimit, downlimit, units, zunits,
  projection, name}` → DCSV + `typeUri=Box`. L'attribut `lang` est repris
  de l'objet s'il est présent.

**Créateur** : format strict `"Nom, Prénom [ORCID]"` (regex ORCID
`\d{4}-\d{4}-\d{4}-\d{3}[\dX]`) → `{surname, givenname, orcid?}`.
Sentinelles → `null` : `[s.n.]`/`anonyme` (créateur), `[s.d.]`/`inconnue`
(date).

**Obligatoires de niveau dépôt** : `nkl_creator` et `nkl_created`
émettent **toujours au moins une meta** (valeur `null` si anonyme/
inconnu) ; tous les autres champs absents (`None`) → **aucune meta**. Les
slugs inconnus de la carte sont ignorés silencieusement (`slugs_inconnus`
permet de les remonter à l'utilisateur).

## 4. Vocabulaires — impédances de schéma

### Endpoints de vocabulaires (`GET /vocabularies/*`, live 2026-06-15)

Nakala expose ses vocabulaires en **lecture publique** (pas d'auth) — source
autoritative à privilégier sur les snapshots vendorisés :

| Endpoint | Contenu |
|---|---|
| `/vocabularies/depositTypes` | **29 types COAR acceptés au dépôt**, `{uri, en, fr, es, definition}` (trilingue + définition). C'est *la* liste de référence pour `nkl:type` |
| `/vocabularies/datatypes` | les mêmes 29 types, URIs nues |
| `/vocabularies/dcmitypes` | 12 types DCMI (`…/dcmitype/Collection`, `Dataset`, `Image`…) |
| `/vocabularies/dataStatuses` | **5 statuts de donnée** : `pending`, `published`, `deleted`, `old` (version supersédée), `moderated` |
| `/vocabularies/collectionStatuses` | 2 : `public`, `private` |
| `/vocabularies/licenses` | **620 licences = liste SPDX complète** `{code, name, url}` |
| `/vocabularies/languages` | langues `{id, label}` (id en ISO 639-3 pour la longue traîne ; cf. bug #422) |
| `/vocabularies/countryCodes` | codes pays ISO 3166 alpha-2 (⚠️ pas `/countries`) |
| `/vocabularies/properties` | **60 propertyUri complètes** (liste plate de chaînes, ex. `http://purl.org/dc/terms/description`) — la **bonne** référence pour un check de parité des `propertyUri` |
| `/vocabularies/properties/details` | **55 entrées** riches (`allowedTypes` + `languageAuthorized`) ⚠️ la clé `uri` y est le **namespace** (`http://purl.org/dc/terms/`) + un `term` séparé, **pas** l'URI complète — ne pas l'utiliser tel quel pour comparer des propertyUri. C'est la carte que `SLUG_TO_NAKALA` réimplémente à la main |
| `/vocabularies/metadatatypes` + `/metadatatypes/details` | types de métadonnées (XSD/DC) |
| `/vocabularies/lcsh` | concepts LCSH (Library of Congress Subject Headings) |

### Langues ⚠️ (origine du bug #422)

- **Nakala** type `dcterms:language` en **RFC5646 / ISO 639-1** pour les
  majeurs (`fr`, `en`, `es`) + 639-3 pour la longue traîne.
- **ColleC** stocke en **ISO 639-3** (`fra`, `eng`, `spa`).
- Pont nécessaire dans les deux sens :
  - écriture : `depot_mapper.langue_vers_nakala` (639-3 → 639-1), appliqué
    à la **valeur** ET à l'attribut **`lang`** des littéraux multilingues
    dans `item_vers_slugs` ;
  - lecture : table `_ISO1_VERS_ISO3` dans `mapper.py`.

### Types COAR

Le set accepté au dépôt Nakala = **29 types**. Un audit a révélé **9 URIs
ColleC fausses sur 15** — notamment `c_12cd` étiqueté « Vidéo » alors que
c'est « carte géographique » (la vidéo = `c_12ce`). Corrigé en V0.9.10 :

- vocabulaire interne riche (**32 types** = 29 Nakala + 3 extras :
  Chapitre de livre, Document de travail, Photographie) ;
- projection `COAR_INTERNE_VERS_NAKALA` + `type_coar_pour_nakala()` qui
  ramène les 3 extras vers une cible Nakala à l'export ;
- migration `r6v7w8x9y0z1` (remap de l'existant, non bijective, pas de
  downgrade).

### Licences

`licenses.json` vendorisé ressemble à la liste SPDX complète (~620), **pas
forcément** au sous-ensemble accepté par Nakala. À confirmer avant d'en
faire un vocabulaire d'export contraint.

## 5. Les 4 difficultés structurelles (et parades)

1. **Conflit / fraîcheur** — Nakala **n'expose pas de verrou optimiste**.
   Parade : `fetched_at` + **diff & confirmation avant overwrite** (dry-run
   par défaut sur toute écriture) ; à défaut, last-writer-wins explicite.
2. **Publié vs pending** — sur publié, métadonnées éditables, fichiers via
   versioning, mais **pas de dé-publication**. Parade : statut modélisé +
   garde-fou `DepotPublie` (flag `--force-published`).
3. **Fidélité du round-trip** — une carte unique lecture+écriture
   (`SLUG_TO_NAKALA`), validée par round-trip idempotent.
4. **Identité fichiers** — réconciliation par **SHA-1** (Nakala = SHA-1 ;
   `Fichier.hash_sha256` = SHA-256, algos différents) → colonne dédiée
   `Fichier.sha1_nakala` (migration `s7w8x9y0z1a2`, backfill idempotent).

## 6. Découvertes empiriques validées en live ⭐

`scripts/explorer_put_files_nakala.py` a sondé `PUT /datas` contre apitest.
Conclusions **confirmées** :

| # | Question testée | Comportement réel de Nakala |
|---|---|---|
| **H1** | `PUT` avec un seul fichier dans `files[]` | **Remplace intégralement** le tableau — l'autre fichier est retiré. Sémantique « remplace », pas « append » |
| **H2A** | `PUT` sans clé `metas` | Métadonnées **préservées** (les clés omises du corps ne sont pas touchées). ColleC s'appuie là-dessus au push de fichiers : `modifier_depot` **omet** `metas` quand seul `files` change |
| **H3** | `PUT files=[]` (liste vide) | **Silencieusement ignoré** — impossible de vider un dépôt de ses fichiers via PUT ; il faut `DELETE` (garde-fou `PushImpossible` côté ColleC) |
| **H4** | `PUT` avec un sha1 inconnu (jamais uploadé, ou « fantôme ») | **HTTP 404 explicite** → cleanup des uploads orphelins en cas d'échec, et validation que chaque sha1 vient d'un upload réussi de la session. C'est aussi pourquoi un `sha1_nakala` désynchronisé (« fichier fantôme ») bloque le push en amont (sinon 404 cryptique) |
| **H5** | Ordre des fichiers dans `files[]` | **Préservé** tel qu'envoyé → ColleC contrôle l'ordre d'affichage côté Nakala (push ordonné par `Fichier.ordre`) |
| **H6** | Re-`PUT` identique | **Idempotent**, no-op silencieux → reprise après crash sans risque de doublon |
| **H7** | Même sha1, `name` différent | **Renommage gratuit** : Nakala propage le nouveau nom sans re-upload du binaire |
| **H10** | Lecture immédiate après `PUT` | **Consistant** (read-after-write) → on peut chaîner `PUT` → `lire_depot` sans sleep |
| **H11** | Champ `description` par fichier | **Accepté, préservé, restitué** au `POST` et au `PUT` → ouvre la voie aux transcriptions par fichier (backlog) |

Confirmé en plus par les tests d'intégration :

- **Round-trip métadonnées idempotent** sur dépôts ET collections :
  `diff_push(distant, envoyé) == []` après dépôt et après modif.
- **`PUT /collections/{id}` → 204** ; les collections **n'ont pas de
  `modDate`** (pas de détection de dérive) ; Nakala **remet `typeUri` à
  null** au stockage des metas de collection (ignoré par `diff_push`).
- **Statuts** : `pending` (dépôt brouillon, modifiable/supprimable),
  `private` (collection brouillon), `published` (irréversible, DOI
  DataCite minté, non supprimable).

## 7. Quirks & bugs rencontrés

- **Bug #422 — langue** (voir §4). Latent car aucun test ne déposait de
  langue jusqu'à la validation live. ✅ **Corrigé sur les deux chemins** :
  `exporters/nakala.py` (CSV bulk, chemin manuel séparé) convertit désormais
  la langue via `langue_vers_nakala` (valeur `dcterms:language` + `langTitle`),
  comme le dépôt/push.
- **Canonicalisation des créateurs** : Nakala enrichit au stockage
  `{givenname, surname}` → `{authorId, fullName, givenname, orcid:null,
  surname}`. Sans parade, **chaque push voyait un faux changement**.
  `diff_push` canonicalise sur `surname/givenname/orcid` non-nul seuls.
- **`files[]` = remplacement total** (H1) : omettre un fichier le supprime.
  D'où le garde-fou `OrphelinsDetectes` / flag `--retirer-orphelins`, et la
  notion de **« fichiers fantômes »** (`sha1_nakala` désynchronisé) qui
  bloque le push.
- **Push de fichiers journalisé** : un push qui retire des fichiers côté
  Nakala (DELETE granulaire ou PUT de réordonnancement) échappait à
  `OperationFichier` (qui ne couvre que le disque local). ✅ **Résolu**
  (passe 24) : table `OperationPushNakala` (migration `t8x9y0z1a2b3`) +
  `journaliser_push_fichiers` insère un snapshot avant/après dans la **même
  transaction** que les mutations DB. Consultation : `archives-tool montrer
  push-nakala`.
- **IIIF images uniquement** : Nakala ne sert l'IIIF Image API que pour les
  images (`jpg/png/tif/webp/jp2/…`) ; pour un fichier non-image (CSV, PDF…),
  une URL `/iiif/.../info.json` renvoie **HTTP 415** (Unsupported Media Type
  — vérifié live le 2026-06-15 ; le code ColleC documentait « 404 », c'est
  en réalité 415) → garde sur l'extension à l'import de toute façon.
- **Fusion (pas remplacement) des metas de collection** : ColleC ne gère
  que titre + description → préserve les metas Nakala non modélisées
  (sujet, créateur de collection…) au lieu de les écraser.
- **Unicité du sha1 par dépôt** (sondé live 2026-06-15, revue T2) : Nakala
  **refuse deux fichiers de même sha1** dans un dépôt — `POST /datas` avec
  `files=[{X,a},{X,b}]` → **422**, et re-`POST …/files` d'un sha1 déjà
  attaché → **409/500**. Conséquences : (a) la machinerie défensive
  « doublons sha1 distants » du comparateur (`pop(0)` / file par sha1) et le
  deque de `_reordonner_files` défendent un état que **Nakala ne crée pas**
  (défense morte, conservée pour d'éventuelles données legacy en lecture) ;
  (b) `pousser_fichiers_item` a un **garde-fou pré-vol `ContenuDuplique`** qui
  refuse proprement **avant toute mutation** si le set final a un sha1
  dupliqué (sinon, en granulaire, l'échec arriverait au 2ᵉ POST en laissant un
  état partiel).

## 8. Helpers IIIF / URLs (`files/nakala.py`)

Reconnaissance **stricte** du hostname (`<alphanum-->*.nakala.fr` — bloque
`evil-nakala.fr`, préserve test vs prod). Transformations depuis une URL
Nakala :

| Helper | Produit | Usage |
|---|---|---|
| `vers_iiif_info_json` | `/iiif/<doi>/<sha>/info.json` | source OpenSeadragon |
| `vers_thumb` | `/iiif/<doi>/<sha>/full/!200,200/0/default.jpg` | vignette carrée |
| `vers_data` | `/data/<doi>/<sha>` | téléchargement binaire |
| `remplacer_sha` | même URL, sha remplacé | recalage après push fichiers |
| `construire_source_fichier_nakala` | info.json (image) ou /data (autre) | au rapatriement (on a DOI+sha) |

## 9. Ce qu'on peut faire — les 14 commandes CLI

Toutes les écritures sont en **dry-run par défaut** (`--no-dry-run` pour
appliquer), avec `--format text|json` et codes de sortie **0** (succès /
no-op idempotent), **1** (erreur métier ou garde-fou), **2** (config
`nakala:` absente).

| Flux | Commandes |
|---|---|
| Lecture | `montrer`, `rapatrier`, `rafraichir`, `rapatrier-collection`, `rafraichir-collection` |
| Export | `exporter-tableur` (CSV `;`/UTF-8-BOM ou xlsx ; granularité donnée\|fichier) |
| Dépôt | `deposer`, `deposer-collection` (reprise idempotente : items déjà déposés sautés) |
| Push métadonnées | `pousser`, `pousser-collection` |
| Push / diff fichiers | `comparer-fichiers` (classe en catégories), `pousser-fichiers` |
| Publication | `publier`, `publier-collection` (irréversible) |

**`comparer-fichiers`** classe les fichiers d'un item vs le dépôt distant
en **7 catégories** (`RapportComparaisonFichiers`) : les 5 de base
`nouveaux`, `modifies`, `inchanges`, `nakala_only_sans_local`,
`orphelins_distants`, plus 2 catégories de diagnostic/refus —
`non_actifs_a_retirer` (Fichier en CORBEILLE/REMPLACE, exclu du plan →
serait retiré du distant ; consultatif tant que la corbeille UI n'existe
pas) et `fichiers_fantomes` (`sha1_nakala` ne matche plus aucun fichier
distant → **refus** `FichierFantomeDistant`, sinon 404 au push). La
réconciliation est prioritaire par SHA-1 recalculé à la volée, fallback
sur `sha1_nakala` stocké. Garde-fou supplémentaire : `BackfillIncomplet`
si un `nakala_only_sans_local` n'a pas de `sha1_nakala` peuplé.

**Décision P2** : les fichiers ne montent **qu'à la création** du dépôt
(`deposer`) ; le push de fichiers ultérieur passe par `pousser-fichiers`
(palier P3+c). On n'inscrit pas les DOI dans les métadonnées (« DOI =
adresse »).

## 10. Exemples réels testés

| Collection | Volume | Validé sur |
|---|---|---|
| José Mora Guarnido | 65 données → 155 fichiers | `exporter-tableur`, `rapatrier-collection` |
| Fernando Aínsa | 6163 données | export xlsx (`write_only`), CSV en flux |
| Armonía Somers / Julio Cortázar | collections | dépôt / push |
| Por Favor (PF) | 173 items, 7454 scans Nakala-only | import, IIIF, recherche |

## 11. Tâches de fond (dépôt collection)

Première tâche de fond du projet : **`threading.Thread` daemon + registre
mémoire thread-safe**, **pas de broker** (cf. CLAUDE.md *Tâches de fond :
runner mémoire + reprise idempotente*). Une tâche concurrente à la fois
(`JobConcurrent`). **Sûreté par reprise idempotente** : les DOI sont
persistés au fil de l'eau → un crash mid-run laisse les items créés
intacts, et relancer saute ceux qui ont déjà un DOI. État volatile : un
restart du processus perd le registre (page de suivi 404 sur job inconnu)
mais la base reste cohérente.

## 12. Observabilité

- Loggers : `archives_tool.api.services.nakala_depot` et
  `…​.nakala_fichiers` (events INFO / WARNING / DEBUG ; sha1 tronqués,
  aucun secret ni PII). `publier_item` logge un WARNING (appel
  **irréversible et payant**).
- ✅ Les **7 services d'écriture** de `nakala_depot.py` (`deposer_item`,
  `deposer_collection`, `pousser_item`, `publier_item`,
  `pousser_metadonnees_collection`, `pousser_collection`,
  `publier_collection`) ont tous le logging structuré (résolu passe 21).

## 13. Surface d'API au-delà du périmètre ColleC

ColleC ne consomme qu'une fraction de l'API Nakala. Sondes **lecture
seule** menées contre `apitest.nakala.fr` le **2026-06-15** pour borner
honnêtement ce qui existe mais n'est pas (encore) utilisé :

| Capacité | Statut | Détail |
|---|---|---|
| **OAI-PMH** | ✅ existe | `/oai2` (OAI 2.0, `earliestDatestamp=2015-01-01`, `granularity=YYYY-MM-DD`, `deletedRecord=persistent` ; `/oai`→301). **4 formats** : `oai_dc`, `qdc` (DC qualifié), `oai_datacite`, `oai_isidore` (agrégateur Huma-Num). **Les sets = les collections** (`setSpec=doi_10.34847_nkl.<id>`) → on peut moissonner une collection précise. Non utilisé par ColleC |
| **API de recherche** | ✅ existe | `GET /search?q=…&page=&limit=` → 200, JSON, **sans auth**. Renvoie des DOI de données publiques. ColleC ne s'en sert pas (il pull par DOI connu) ; utile pour découvrir des DOI |
| **Vocabulaire licences** | ✅ = SPDX complet | `GET /vocabularies/licenses` → **620 entrées** `{code, name, url}` pointant `spdx.org`. Résout le « à confirmer » de la §4 : c'est bien la liste SPDX intégrale, pas un sous-ensemble Nakala |
| **IIIF Image API** | ✅ v3.0 | `info.json` d'un fichier image → 200, `application/ld+json; profile=image/3`. Confirme l'approche visionneuse de ColleC. Fichier non-image → **415** (cf. §7) |
| **IIIF Presentation (manifeste)** | ❌ non exposé | `/iiif/{doi}/manifest`, `.../manifest.json`, `/iiif/{doi}` → tous 404 (route API non trouvée), même pour un data image publié. Pas de manifeste par-donnée prêt à consommer aux chemins conventionnels ; ColleC construit sa propre visionneuse depuis les `info.json` par fichier |
| **SPARQL** | ❌ absent | `GET /sparql` → 404. Pas d'endpoint SPARQL public (du moins à ce chemin) |
| **Embargo par fichier au dépôt** | ✅ accepté | sonde écriture sur apitest : `POST /datas` avec `files:[{sha1, name, embargoed:"2099-12-31"}]` accepté ; date seule **normalisée** par Nakala en `2099-12-31T00:00:00+01:00` (datetime + fuseau Europe/Paris), restituée à la relecture avec un champ compagnon `humanReadableEmbargoedDelay`. ColleC ne pose pas encore d'embargo (le flux `deposer_item` n'envoie que `{sha1, name}`) |
| **`POST /datas` multi-fichiers** | ✅ à l'échelle | 20 fichiers envoyés en ordre **inversé** → 20/20 conservés, **ordre inverse préservé** (H5 vaut aussi au POST, pas seulement au PUT). Pas de plafond dur recherché (marteler un serveur partagé serait abusif) |
| **Versioning (DOI `…​.vN`)** | ⚠️ existe, mais ni `pending` ni la publication ne crée de version | machinerie présente côté Nakala (cf. ci-dessous), mais **éditer un dépôt `pending` n'en crée pas de version** (`PUT` fichiers/metas écrase en place, `version` reste `1`) **et publier non plus** (sonde gatée : `.v1` avant et après publication). C'est le cas que `pousser_fichiers_item` traite |

### Versioning Nakala — ce qui existe (sondé 2026-06-15)

La machinerie de versions est bien présente, même si ColleC ne la pilote
pas :

- chaque version porte un **`versionIdentifier`** = `{doi}.vN` ;
- `GET /datas/{doi}.vN` résout une **version précise** (200) ; un `.vN`
  inexistant → 404 ;
- `GET /datas/{doi}/versions` **liste** les versions (paginé) :
  `{total, currentPage, lastPage, limit, data:[{version, versionIdentifier,
  creDate, modDate}]}`.

Sur un dépôt `pending`, après deux `PUT` (fichiers puis metas), `/versions`
ne contient toujours qu'**une** entrée (`version=1`).

**Sonde gatée 2026-06-15 (`NAKALA_ALLOW_PUBLISH=1`, un dépôt publié sacrifié
`10.34847/nkl.f3354s85`)** — résout trois « non vérifié » d'un coup :

- **Publier ne crée PAS de version.** Avant publication : 1 version (`.v1`).
  Après publication : **toujours 1** (`.v1`). La publication bascule le statut
  **en place**, elle ne mint pas de `.vN`. La machinerie `.vN` doit donc
  relever d'un autre déclencheur (édition d'un dépôt déjà publié ?), non
  exploré (faible enjeu).
- **S5 — `PUT /datas/{id}/status/published` fonctionne** : **204**, statut
  relu `published`. Alternative sémantique propre au `PUT /datas {status}`
  (que ColleC utilise aujourd'hui en P3 — les deux marchent).
- **Mutation de fichiers sur dépôt PUBLIÉ : ACCEPTÉE par Nakala** —
  `POST /files` → **200**, `DELETE /files/{sha1}` → **204** sur le dépôt
  publié, **sans créer de version**. Nakala n'empêche donc **pas
  techniquement** d'altérer les fichiers d'un dépôt publié (les citations
  DataCite peuvent silencieusement diverger). Le garde-fou `DepotPublie` de
  ColleC (refus par défaut, `--force-published` pour outrepasser) est ainsi
  une **politique de qualité**, pas une nécessité technique — **confirmé
  pertinent à garder**.

### Non testé / non testable

- **Plafond dur du nombre de fichiers** par dépôt / par `PUT files[]` : non
  recherché volontairement (impliquerait des centaines d'uploads sur un
  serveur de test partagé). On sait que ≥ 20 passe sans souci.
- **Taille max d'upload, rate limiting** : non testables proprement (il
  faudrait soit uploader un binaire énorme, soit marteler l'API) — à
  documenter depuis la doc Huma-Num plutôt que par sonde.

## 14. Où vit ce savoir

| Sujet | Fichier |
|---|---|
| Conception / architecture / phasage | [`nakala-depot-future.md`](nakala-depot-future.md) |
| **Backlog actionnable (issu de ce savoir)** | [`backlog-nakala-api.md`](backlog-nakala-api.md) |
| Backlog niveau collection | [`backlog-nakala-collection.md`](backlog-nakala-collection.md) |
| Guide d'usage CLI | [`../guide/cli/nakala.md`](../guide/cli/nakala.md) |
| Client lecture / écriture / mappers | `src/archives_tool/external/nakala/` |
| Services dépôt / fichiers | `src/archives_tool/api/services/nakala_depot.py`, `nakala_fichiers.py` |
| Helpers IIIF | `src/archives_tool/files/nakala.py` |
| **Sondes live** | `scripts/explorer_put_files_nakala.py` (PUT `files[]`, H1-H11), `scripts/explorer_files_granulaire_nakala.py` (POST/DELETE granulaires, ticket T2), `scripts/verifier_parite_vocabulaires_nakala.py` (parité vocab S1, lecture seule) |
| Tests d'intégration (opt-in `-m integration`) | `tests/test_nakala_*_integration.py` |
| Découvertes accumulées | section Nakala de `CLAUDE.md` |
