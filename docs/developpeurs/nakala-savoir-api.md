# Nakala — comportement réel de l'API (savoir validé)

> Document interne, exclu du build MkDocs. **Référence opérationnelle de
> l'API Nakala**, par opposition au document de **conception/architecture**
> [`nakala-depot-future.md`](nakala-depot-future.md) (le « pourquoi » et le
> phasage) et au **guide d'usage** [`../guide/cli/nakala.md`](../guide/cli/nakala.md)
> (le « comment s'en servir »).
>
> **Orientation de ce document.** Le protagoniste est le **comportement réel
> de l'API Nakala** — endpoints, payloads, codes, quirks, ce qui a été
> *découvert et testé en live*. C'est la **Partie I**, dense et autonome :
> elle se lit comme une référence API, indépendamment de ColleC. La
> **Partie II** regroupe **comment ColleC exploite ce savoir** (mappers,
> garde-fous, colonnes, CLI, tâches de fond) — présente et complète, mais
> subordonnée. Quand une section de la Partie I a une incidence côté ColleC,
> un renvoi `→ côté ColleC` pointe vers le chapitre correspondant de la
> Partie II.
>
> Origine du savoir : sondes live `scripts/explorer_put_files_nakala.py`
> (hypothèses H1-H11 contre `apitest.nakala.fr`), `scripts/explorer_files_
> granulaire_nakala.py` (POST/DELETE granulaires), `scripts/verifier_parite_
> vocabulaires_nakala.py` (parité vocab), les tests d'intégration opt-in
> `tests/test_nakala_*_integration.py`, le code client
> `src/archives_tool/external/nakala/`, et la spec OpenAPI `GET /doc.json`.
> Validé pour la dernière fois contre apitest le **2026-06-15**.

---

## Résumé — trois comportements de l'API qui ont coûté du sang

Trois quirks de l'API Nakala, non documentés explicitement côté Huma-Num,
découverts en live et qui structurent tout le reste :

1. **Langue typée en RFC5646 (bug #422)** — Nakala type `dcterms:language`
   en **RFC5646 / ISO 639-1** (`es`), pas en ISO 639-3 (`spa`). Déposer une
   valeur 639-3 → **rejet 422**. Cf. §5 (Vocabulaires) et §4 (typeUri).
2. **Enrichissement des créateurs au stockage** — Nakala réécrit
   `{givenname, surname}` en `{authorId, fullName, givenname, orcid:null,
   surname}` au stockage. Une relecture diffère donc de ce qui a été envoyé
   → **faux diff à chaque push** si on ne canonicalise pas. Cf. §8.
3. **`PUT /datas` remplace intégralement `files[]`** — sémantique
   « remplace », pas « ajoute » : omettre un fichier le **supprime** (H1).
   Les endpoints granulaires `POST/DELETE …/files` sont la voie sûre. Cf.
   §2 et §8.

---
---

## Partie I — Le comportement de l'API Nakala

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
- **Écriture** : clé *obligatoire*.
- **Compte de test public Huma-Num** (non secret, pour apitest) :
  `01234567-89ab-cdef-0123-456789abcdef`.
- **Lenteur** : Nakala est lent sur cache froid et les uploads sont longs —
  prévoir des timeouts généreux (ColleC retient 30 s en lecture, 60 s en
  écriture).

> **→ côté ColleC** : section `nakala: { base_url, api_key, timeout }` du
> `config_local.yaml` ; `NakalaEcritureClient` échoue à la construction si
> la clé manque (fail-fast). Variables d'env de test `NAKALA_API_KEY`,
> `NAKALA_HOST`, `NAKALA_ALLOW_PUBLISH=1`. Cf. Partie II.

## 2. Endpoints

### Lecture

| Endpoint | Rôle | Notes |
|---|---|---|
| `GET /datas/{id}` | Lire un dépôt | renvoie `metas`, `files`, `status`, `identifier`, `version` (+ ~16 autres champs, cf. §4) |
| `GET /collections/{id}` | Lire une collection | `metas`, `status` (`private`/`public`), `uri`, droits, feature site web |
| `GET /collections/{id}/datas?page=N&limit=M` | Lister les données d'une collection (paginé) | renvoie **déjà les `files` complets → pas de N+1** |
| `POST /users/datas/{scope}` | Lister ce que la clé voit | **POST qui lit**, corps `{}` ; `scope` = readable/owned/deposited |
| `POST /users/collections/{scope}` | Idem pour les collections | idem |
| `GET /data/{id}/{fileId}` | Télécharger le binaire d'un fichier | `{fileId}` = sha1 |

### Écriture

| Endpoint | Rôle | Notes |
|---|---|---|
| `POST /datas/uploads` | Upload multipart (champ `file`) | renvoie `{name, sha1}` — le sha1 est la poignée du fichier ; **usage unique** (cf. ci-dessous) |
| `POST /datas` | Créer un dépôt | corps `{status, files:[{sha1,name}], metas:[…], collectionsIds?}` → **201**, DOI dans `payload.id` |
| `PUT /datas/{id}` | Modifier un dépôt | chaque clé du corps optionnelle ; **omise = préservée** (H2A). `files[]` = **remplacement total** (H1) |
| `POST /datas/{id}/files` | Ajouter **un** fichier | **additif** ; corps `{sha1}` ; → **200** (cf. ci-dessous) |
| `DELETE /datas/{id}/files/{sha1}` | Retirer **un** fichier | par sha1 → **204** ; refus du dernier fichier → **403** |
| `POST /collections` | Créer une collection | corps `{status, metas:[], datas?:[doi…]}` → **201** |
| `PUT /collections/{id}` | Modifier une collection | **renvoie 204** ; remplace les metas |
| `POST /datas/{id}/collections` | Rattacher un dépôt à des collections | additif (corps = liste de DOI) |
| `PUT /datas/{id}/status/{status}` | Changer le statut (p.ex. publier) | → **204** (alternative au `PUT /datas {status}`) |
| `DELETE /datas/{id}` | Supprimer un dépôt | **pending uniquement** |
| `DELETE /collections/{id}` | Supprimer une collection | private/pending |
| `DELETE /datas/uploads/{sha1}` | Nettoyer un upload orphelin | du stockage temporaire (best-effort) |

### Upload & ajout de fichiers — comportements validés en live

- **Upload à usage unique** : un fichier du stockage temporaire
  (`POST /datas/uploads`) est **consommé** quand il est attaché à un dépôt ;
  réutiliser le même `sha1` pour un 2ᵉ dépôt → **422**. Chaque dépôt a ses
  propres uploads.
- **Rejeu d'un contenu identique → 500** : rejouer un **contenu identique**
  entre deux exécutions (donc même sha1) déclenche un **500** au
  `POST /datas`, pas seulement un 422 (observé live 2026-06-15) — d'où le
  salage uuid du contenu dans les sondes (sha1 frais à chaque run).
- **`POST /datas/{id}/files` est additif** (sondé live 2026-06-15) : ajoute
  un fichier sans toucher les autres (contrairement au `PUT files[]` qui
  remplace, H1). Corps = `{sha1}` — schéma `File` = `sha1` + `description?`
  + `embargoed?`, **pas de `name`** (le nom est repris de l'upload). Réponse
  **200** `{code:200, message:"File added"}`.
- **Ordre des ajouts = LIFO** : le dernier fichier POSTé passe **devant**
  (confirmé sur 8 essais dont 4–7 décisifs où un tri par sha1 aurait prédit
  l'inverse — l'ordre est indépendant du sha1). Pour fixer l'ordre
  d'affichage, **finir par un `PUT files[]`** qui, lui, respecte l'ordre
  envoyé (H5).
- **`DELETE /datas/{id}/files/{fileIdentifier}`** : le `{fileIdentifier}`
  **est le sha1** — la donnée fichier n'expose aucun id distinct du sha1.
  DELETE par sha1 → **204**, retrait ciblé, les autres fichiers intacts.
  **Mais retirer le *dernier* fichier → 403 (refusé)** : un dépôt ne peut
  pas être vidé de tous ses fichiers (cohérent avec `PUT files=[]` ignoré,
  H3).
- **Erreurs des endpoints granulaires (codes non fiables, non destructifs)** :
  - sha1 jamais uploadé / « fantôme » au `POST …/files` → **500** « File not
    found on server » (≠ le **404** du `PUT`, H4 — asymétrie entre endpoints) ;
  - re-`POST` d'un fichier déjà présent → **409 ou 500** selon l'état du
    stockage temporaire (409 si l'upload temp existe encore, **500** si
    l'upload a été consommé). Aucun effet destructif (le fichier reste, pas
    de doublon), mais **code non fiable** → la détection « déjà présent »
    doit se faire **côté client** avant le POST.

> **→ côté ColleC** : couplés, `POST` + `DELETE` granulaires forment la voie
> de modification **sûre** des fichiers (ajout-avant-suppression + `PUT
> files[]` de réordonnancement reconstruit depuis l'état distant relu).
> C'est ce qu'emploie `pousser_fichiers_item` (ticket T2). Cf. Partie II
> §13 et §15.

### Pièges de structure de réponse

- **DOI à la création** : `POST /datas` peut renvoyer le DOI sous plusieurs
  formes (`payload.id`, `payload.identifier`, ou `identifier` au premier
  niveau) → extracteur tolérant requis.
- **Listing paginé de collection** : forme **réelle** (relevée live
  2026-06-15) = `{ data, currentPage, lastPage, limit, total }` — la clé des
  éléments est **`data` au singulier** (pas `datas`), et c'est
  **`currentPage`** (pas `page`) avec un `total` en plus. Pagination
  1-based, `limit` max 100. Même dialecte pour `/versions` (§7). ⚠️ **Trois
  dialectes de listing distincts** — voir le tableau en §4.
- **La réponse de lecture est bien plus riche que les 4 champs habituels**
  (≈ 21 champs côté donnée, dont droits, modération, propriétaire…) et
  **diffère selon l'endpoint** (3 projections) : détail en §4.

### Catalogue complet (56 endpoints)

Référence autoritative : **`GET /doc.json`** (spec OpenAPI / Swagger 2.0).
ColleC n'en utilise qu'une douzaine ; le reste, par tag (`datas`,
`collections`, `users`, `groups`, `vocabularies`, `search`) :

- **datas — granulaire** : `…/metadatas` (GET/POST/DELETE *une* meta),
  `…/files` (GET/POST/DELETE *un* fichier), `…/relations`
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

> Le « non utilisé par ColleC » est consigné en §9 (surface au-delà du
> périmètre) — où chaque capacité existante mais inexploitée est bornée
> honnêtement.

## 3. Codes & corps d'erreur (relevés live 2026-06-15)

| Code | Quand | Corps |
|---|---|---|
| 200 | `POST …/files` OK, lecture OK | `{code:200, message:"File added"}` pour l'ajout |
| 201 | création OK (`POST /datas`, `/collections`) | `{code:201, message:"Data created", payload:{id:"<doi>"}}` |
| 204 | `PUT /collections/{id}`, `DELETE …/files/{sha1}`, `PUT …/status/{status}` | vide |
| 401 | clé absente / invalide | `{message:"Request is missing required authentication credential … X-API-KEY …"}` |
| 403 | retrait du **dernier** fichier d'un dépôt | refusé (un dépôt ne peut être vidé) |
| 404 | ressource inconnue ; `PUT` avec sha1 fantôme (H4) | `{code:404, message:"No route found for \"GET …\""}` |
| 409 / 500 | re-`POST …/files` déjà présent ; sha1 jamais uploadé → 500 | codes non fiables (cf. §2) |
| 415 | `/iiif/.../info.json` sur fichier **non-image** | Unsupported Media Type |
| 422 | metas / fichiers refusés ; sha1 dupliqué ; upload réutilisé | `{message:"Data could not be submitted …", payload:{validationErrors:[…]}}` |

Le **détail par champ** d'un 422 vit dans **`payload.validationErrors`**
(liste, ex. `["The metadata http://nakala.fr/terms#title is required."]`).
Le `message` de premier niveau reste générique (« Data could not be
submitted because of invalid data ») — sans lire `validationErrors`, on ne
sait pas *quel* champ pose problème.

> **→ côté ColleC** : `client.detail_erreur_nakala` annexe
> `payload.validationErrors` au message dans les deux clients (lecture +
> écriture), défensif si `payload` absent / non-dict (ticket T3). Cf. Partie
> II §13.

## 4. Modèle de données

### Donnée (data) vs fichier (file)

Une **donnée** Nakala porte **N fichiers**. La granularité donnée/fichier
n'est qu'une option d'aplatissement d'un tableur d'export ; le modèle natif
reste « 1 donnée → N fichiers ».

> **→ côté ColleC** : une donnée = un **Item**, un fichier = un **Fichier** ;
> un pull produit toujours 1 Item portant N Fichier.

### Structure d'une « meta » (cœur du modèle)

```json
{
  "propertyUri": "http://nakala.fr/terms#title",
  "value": "…",        // str | dict | null
  "lang": "fr",         // optionnel — multilingue, RFC5646 / ISO 639-1
  "typeUri": "…"        // optionnel — indice de type (XSD / DC : W3CDTF, Period, Point, Box…)
}
```

PropertyUri repérés :

- **Champs `nkl:*`** : `http://nakala.fr/terms#type` (type COAR), `#title`,
  `#creator`, `#created`, `#license`.
- **Dublin Core (`dcterms:*`)** :
  `http://purl.org/dc/terms/description`, `/subject`, `/language`,
  `/spatial`, `/temporal`, `/contributor`, `/relation`, etc.

> ⚠️ **Champs obligatoires au dépôt : `nkl:title` + `nkl:type` SEULEMENT**
> (vérifié live 2026-06-15 par `POST /datas` avec metas incomplètes).
> Omettre `creator`, `created` ou `license` → **201 accepté**. Le 422 nomme
> le champ manquant : `{"payload":{"validationErrors":["The metadata
> http://nakala.fr/terms#title is required."]}}`.
>
> **→ côté ColleC** : la cascade « créateur + date obligatoires » de
> `preflight.py` est donc une règle ColleC **plus stricte que Nakala** (choix
> de qualité catalographique), pas une exigence de l'API. Cf. Partie II §11.

### typeUri & encodage des valeurs (ce que Nakala attend à l'écriture)

Au-delà du `propertyUri`, chaque meta peut porter un **`typeUri`** (indice
de type) et Nakala attend une **forme** précise selon le champ. Vocabulaire
des `typeUri` observés :

| `typeUri` | Pour |
|---|---|
| `http://www.w3.org/2001/XMLSchema#anyURI` | `nkl:type` (URI COAR) |
| `http://www.w3.org/2001/XMLSchema#string` | texte (titre, description, sujet, la plupart des `dcterms:*`) |
| `http://purl.org/dc/terms/RFC5646` | **`dcterms:language`** — confirme que Nakala type la langue en RFC5646 (origine du bug #422) |
| `http://purl.org/dc/terms/W3CDTF` | dates (`dcterms:date`, `issued`, `modified`, `created`…) |
| `…/Period`, `…/Point`, `…/Box` | structures temporal / spatial |

**Encodage DCSV (spatial / temporal)** — le point le plus piégeux : Nakala
attend un objet **aplati en chaîne** `clé=valeur` jointe par `; `, le
`typeUri` portant la sémantique :

- `temporal` : chaîne brute → `typeUri=W3CDTF` ; objet `{start, end, name}`
  → `start=…; end=…; name=…` + `typeUri=Period`.
- `spatial` : `{kind:"Point", east, north, elevation, name}` →
  `east=…; north=…; …` + `typeUri=Point` ; `{kind:"Box", northlimit,
  southlimit, eastlimit, westlimit, uplimit, downlimit, units, zunits,
  projection, name}` → DCSV + `typeUri=Box`. L'attribut `lang` est repris de
  l'objet s'il est présent.

**Multiplicité** : un champ multilingue produit **une meta par littéral**
(chacune avec son `lang`) ; un champ à valeurs multiples (créateurs,
langues, contributeurs, identifiants, relations) produit **N metas**.

> **→ côté ColleC** : la carte de vérité `SLUG_TO_NAKALA` (57 champs)
> implémente cette forme à la main (cf. Partie II §11). La source
> autoritative côté Nakala est `GET /vocabularies/properties/details`
> (`allowedTypes` + `languageAuthorized`, cf. §5).

### Créateur

Objet `{surname, givenname, orcid?}`. Sentinelles anonymes (`[s.n.]`,
`anonyme`) → `null`. ⚠️ **Enrichi + normalisé au stockage** (sondé live
2026-06-15) : Nakala réécrit `{givenname, surname}` en `{authorId, fullName,
givenname, orcid:null, surname}`, **normalise l'ORCID en URL**
(`0000-0001-2345-6789` → `https://orcid.org/0000-0001-2345-6789`) et
**réordonne les créateurs** (tri par nom observé : envoyé [Somers, Cortázar]
→ relu [Cortázar, Somers]). La réponse **brute** diffère donc de l'envoi sur
ces trois axes. Côté ColleC, le mapper neutralise deux des trois : il ignore
l'enrichissement et **ramène l'ORCID à la forme nue** (`normaliser_orcid`,
partagé par la lecture ET `diff_push`). Reste l'**ordre**, perdu côté Nakala
— inoffensif au push (`diff_push` multiset) mais visible à la lecture. Donc
le **round-trip ColleC est fidèle sauf l'ordre des créateurs**. Cf. §13/§16.

### Fichier (dans une réponse `GET /datas`)

Jeu complet des 10 champs confirmé live (relecture `GET /datas`, 2026-06-15) :

```json
{
  "name": "scan_0001.jpg",
  "sha1": "da39a3ee…",          // 40 hex — poignée du fichier
  "size": 12345,                 // octets
  "mime_type": "image/jpeg",     // API expose "mime_type" (le code ColleC accepte aussi "mime")
  "embargoed": "2099-12-31T00:00:00+01:00"|null,  // datetime + fuseau Europe/Paris
  "humanReadableEmbargoedDelay": "…",  // délai d'embargo lisible (texte)
  "extension": "jpg",
  "puid": "fmt/43",              // PRONOM (optionnel)
  "format": "JPEG",             // PRONOM label (optionnel)
  "description": "…"            // optionnel (cf. H11 — transcription par fichier)
}
```

**Métadonnées par fichier — périmètre exact (sondé live 2026-06-15).** Les
seuls champs **inscriptibles** par fichier sont **`name`, `sha1`,
`embargoed`, `description`** (schémas OpenAPI : `File5` = input `PUT` le plus
riche ; `File` = input granulaire `{sha1, description, embargoed}` ; `File3`
= `{name, sha1}` ; `File2/4/6` = lecture, 9 champs dont `puid`/`format`
calculés). **Tout champ extra est silencieusement ignoré** : `champLibre`,
`title`, et même un `metas[]` *par fichier* envoyés au dépôt → **droppés**.
Nakala **ne gère donc aucune métadonnée structurée au niveau fichier**
au-delà de `description` (texte libre) + `embargoed` — le Dublin Core riche
vit uniquement au niveau **donnée** (`metas[]`).

- **`description` round-trip à l'identique** (unicode/accents/guillemets) →
  **viabilité du backlog « transcription par fichier »** (`Fichier.description_externe`)
  confirmée.
- **Enrichissement APRÈS dépôt, sans re-upload** ✓ : un `PUT /datas
  {files:[{même sha1, +description, +embargoed}]}` **ajoute/modifie** ces
  champs sur un fichier déjà déposé (mêmes octets, pas de re-upload). →
  workflow viable : déposer les scans, transcrire/embargoer plus tard.
- **Embargo par défaut = date du dépôt** : un fichier sans `embargoed`
  explicite reçoit `embargoed = aujourd'hui` (donc embargo expiré →
  disponible immédiatement).

### Dates

Format **W3CDTF** : `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM:SS`
avec timezone `Z`/`±HH:MM`. Sentinelle `[s.d.]`/`inconnue` → null.

### DOI / identifiant

Format `10.34847/nkl.xxxxxxxx` (registrant Huma-Num), variante versionnée
`…​.vN` (cf. §7). Un DOI nu matche la regex `10\.\d+/[^\s/?#]+`.

> **→ côté ColleC** : `normaliser_identifiant_nakala` extrait le DOI d'une
> URL (`nakala.fr/collection/…`), d'un `doi:…` ou d'un DOI nu ; best-effort,
> sinon saisie rendue telle quelle (404 propre en aval).

### Réponse de lecture complète (≈ 21 champs)

`GET /datas/{id}` renvoie **≈ 21 champs** ; un consommateur minimal n'en lit
souvent que **4** (`metas`, `files`, `status`, `identifier`). Relevé live sur
dépôts publics apitest (2026-06-15) :

| Champ | Contenu |
|---|---|
| `identifier` | DOI `10.34847/nkl.…` |
| `metas` / `files` | métadonnées / fichiers |
| `status` | `pending` / `published` / … |
| `uri` | **URL résolvable `https://doi.org/{doi}`** (≠ URL API) |
| `version` | entier (cf. §7) |
| `creDate` / `modDate` | datetimes +TZ (`modDate` = date de dernière modif, sert à détecter la dérive) |
| `collectionsIds` | DOIs des collections d'appartenance |
| `relations` | relations inter-données (**vide sur 30/30 sondés — rare**, car gated par la publication, cf. §6) |
| `fileEmbargoed` | booléen niveau-donnée : ≥ 1 fichier sous embargo (1/30 sondés) |
| `owner` / `depositor` | objet user `{id (UUID), name, type, username, givenname, surname, photo}` |
| `isAdmin`/`isDepositor`/`isEditor`/`isOwner` | **droits relatifs à l'appelant** (tous `false` avec une clé non-propriétaire) |
| `lastModerator` / `lastModerationDate` / `lastModerationRequestDate` / `moderationRequester` | workflow de **modération** Nakala (null hors modération) |

**3 projections de donnée distinctes** (même donnée, champs différents selon
l'endpoint — piège pour qui parse) :

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
souvent `null`** (les collections n'ont pas de dérive, §8), `owner` (avec
sous-liste `users`), `depositor`, droits `isXxx`, `haveData` /
`haveAccessibleData`, et une **feature site web** : `websiteEnabled`,
`websitePrefix`, `websitePublished`.

**Trois dialectes de listing paginé** :

| Endpoint(s) | Forme |
|---|---|
| `/collections/{id}/datas`, `/datas/{id}/versions` | `{data, currentPage, lastPage, limit, total}` |
| `/search` | `{datas, totalResults}` (clé `datas` au pluriel, pas de curseur de page) |

**Trois hôtes Nakala distincts** : `api[test].nakala.fr` (API REST),
`[test.]nakala.fr` (UI web humaine — cible des `uri` de collection et des
sites), `doi.org` (résolveur DOI — cible du `uri` de donnée).

> **→ côté ColleC** : le mapper ne consomme aujourd'hui que `metas`/`files`/
> `status`/`identifier` (+ `collectionsIds` depuis S3, `version`/`modDate`
> partiellement). Tout le reste est ignoré. Cf. Partie II §11.

## 5. Vocabulaires (`GET /vocabularies/*`)

Nakala expose ses vocabulaires en **lecture publique** (pas d'auth) — source
autoritative à privilégier sur tout snapshot vendorisé.

| Endpoint | Contenu |
|---|---|
| `/vocabularies/depositTypes` | **29 types COAR acceptés au dépôt**, `{uri, en, fr, es, definition}` (trilingue + définition). C'est *la* liste de référence pour `nkl:type` |
| `/vocabularies/datatypes` | les mêmes 29 types, URIs nues |
| `/vocabularies/dcmitypes` | 12 types DCMI (`…/dcmitype/Collection`, `Dataset`, `Image`…) |
| `/vocabularies/dataStatuses` | **5 statuts de donnée** : `pending`, `published`, `deleted`, `old` (version supersédée), `moderated` |
| `/vocabularies/collectionStatuses` | 2 : `public`, `private` |
| `/vocabularies/licenses` | **620 licences = liste SPDX complète** `{code, name, url}` pointant `spdx.org` |
| `/vocabularies/languages` | langues `{id, label}` (id en ISO 639-3 pour la longue traîne ; cf. bug #422) |
| `/vocabularies/countryCodes` | codes pays ISO 3166 alpha-2 (⚠️ pas `/countries`) |
| `/vocabularies/properties` | **60 propertyUri complètes** (liste plate de chaînes) — la **bonne** référence pour un check de parité des `propertyUri` |
| `/vocabularies/properties/details` | **55 entrées** riches (`allowedTypes` + `languageAuthorized`) ⚠️ la clé `uri` y est le **namespace** (`http://purl.org/dc/terms/`) + un `term` séparé, **pas** l'URI complète — ne pas l'utiliser tel quel pour comparer des propertyUri |
| `/vocabularies/metadatatypes` + `/metadatatypes/details` | types de métadonnées (XSD/DC) |
| `/vocabularies/lcsh` | concepts LCSH (Library of Congress Subject Headings) |

### Langues ⚠️ (origine du bug #422)

- **Nakala** type `dcterms:language` en **RFC5646 / ISO 639-1** pour les
  majeurs (`fr`, `en`, `es`) + 639-3 pour la longue traîne.
- Déposer une valeur 639-3 (`spa`) → **rejet 422** : la valeur n'est pas
  dans le vocabulaire RFC5646 que Nakala attend.

> **→ côté ColleC** : ColleC stocke en ISO 639-3 ; il faut ponter dans les
> deux sens (`langue_vers_nakala` à l'écriture, table `_ISO1_VERS_ISO3` à la
> lecture). Cf. Partie II §11 (pont) et §13 (bug #422).

### Types COAR

Le set accepté au dépôt Nakala = **29 types** (`/vocabularies/depositTypes`).
Un audit a révélé que plusieurs URIs « COAR » couramment recopiées sont
fausses ou mal étiquetées — p.ex. `c_12cd` = « carte géographique », pas
« vidéo » (la vidéo = `c_12ce`). La liste `depositTypes` fait foi.

> **→ côté ColleC** : vocabulaire interne riche (32 types = 29 Nakala + 3
> extras) + projection `type_coar_pour_nakala()` vers le set Nakala à
> l'export + migration de remap `r6v7w8x9y0z1`. Cf. Partie II §11.

### Licences

`GET /vocabularies/licenses` → **620 entrées** = **liste SPDX intégrale**
(confirmé live, cf. §9), pas un sous-ensemble propre à Nakala. ✅ **Résolu
(sonde écriture 2026-06-15)** : `nkl:license` est **validé contre le set
SPDX** — `CC-BY-4.0`, `MIT`, `CC0-1.0`, `etalab-2.0`, `GPL-3.0-only` acceptés
au dépôt ; un code bidon (`NOT-A-LICENSE-XYZ`) ou vide → **422
« unauthorized »**. Nuance : la licence **omise** passe (non requise, cf.
§4) ; **présente mais invalide** → rejet. Donc ColleC peut contraindre son
vocabulaire d'export aux codes SPDX en sécurité (son défaut `CC-BY-4.0` est
valide).

## 6. Statuts & cycle de vie

Vocabulaire des statuts (`/vocabularies/dataStatuses`,
`/vocabularies/collectionStatuses`) :

| Entité | Statuts | Sémantique |
|---|---|---|
| Donnée | `pending` | **brouillon** — modifiable, supprimable (`DELETE /datas/{id}`) |
| | `published` | **irréversible** — DOI DataCite minté (en prod), **non supprimable**, **pas de dé-publication** |
| | `old` | version supersédée |
| | `deleted`, `moderated` | supprimée / en modération |
| Collection | `private` | brouillon de collection |
| | `public` | collection publiée |

**Publier** : `PUT /datas/{id} {status:"published"}` **ou** le endpoint dédié
`PUT /datas/{id}/status/published` (→ **204**) — **les deux fonctionnent**
(sondé live, gaté). Bascule le statut **en place** (pas de version).

**Mutation d'un dépôt PUBLIÉ : techniquement ACCEPTÉE par Nakala** (sondé
gaté 2026-06-15) — `POST …/files` → 200, `DELETE …/files/{sha1}` → 204,
`PUT /datas {metas}` → 200. Nakala n'empêche **pas techniquement** d'altérer
un dépôt publié. ⚠️ Mais la mutation des **fichiers** d'un publié **crée une
version** `.vN` (cf. §7) — contrairement aux **metas**, éditées en place.
C'est la raison du garde-fou ColleC `DepotPublie` (les citations DataCite
peuvent diverger ; le versioning fichiers prolifère).

**Cycle de vie des collections** (sondé live 2026-06-15, pending/private,
zéro pollution) :
- les collections **ne versionnent pas** (aucun champ `version` dans la
  réponse) ; `PUT metas` édite en place ;
- `POST /collections {datas:[doi…]}` **rattache** les données à la création ;
  détacher = `DELETE /datas/{id}/collections` (corps = liste de DOI) → 200 ;
- **passer une collection en `public` est REFUSÉ (422)** tant qu'elle
  contient une donnée `pending` — il faut publier les données d'abord.

**Relations entre données** (`relations[]`, `…/relations` ; sondé live
2026-06-15) — **gated par la publication** :
- une relation n'est acceptée que si la **source est publiée** (ou modérée) :
  sur `pending` → **422** « Only published or moderated data can have
  relations to other data published in NAKALA ».
- structure : `{type, repository, target, comment?}` (ex. `type="IsPartOf"`,
  `repository="nakala"`, `target="10.34847/nkl.…"`). En lecture s'ajoutent
  `date`, `uri`, `isInferred`.
- **cible Nakala : existence VALIDÉE** — `target` doit être un DOI Nakala
  **publié existant** (source publiée → cible publiée → 200) ; un DOI Nakala
  **inexistant → 422** (« The identifier … »). **Pas de référence en avant
  possible** vers une donnée Nakala pas encore là.
- **cible externe : NON validée** — `repository="hal"` (ou autre) + un
  identifiant externe → **200**, accepté tel quel (Nakala ne vérifie pas les
  entrepôts tiers). Liens externes en forme libre.
- **unidirectionnel** : poser B→A ne crée pas A→B (pas d'inférence du revers
  observée ; `isInferred` reste `false`).

> **→ côté ColleC** : l'appartenance hiérarchique passe par `collectionsIds`
> (qui marche **dès le dépôt, même `pending`**). Des **relations
> donnée↔donnée** (ex. « numéro `IsPartOf` périodique ») ne sont **pas**
> posables pendant un batch de dépôts `pending` : il faudrait une **3ᵉ passe
> post-publication** (déposer tout → publier tout → poser les relations entre
> données publiées). ColleC ne gère pas les relations aujourd'hui — ce
> constat dit pourquoi c'est non-trivial.

> **→ côté ColleC** : refuser par défaut d'éditer un dépôt publié est une
> **politique de qualité** (garde-fou `DepotPublie`, flag `--force-published`),
> pas une nécessité technique — **confirmé pertinent à garder**. Cf. Partie
> II §12 (difficulté #2).

## 7. Versioning (DOI `…​.vN`)

La machinerie de versions est présente côté Nakala :

- chaque version porte un **`versionIdentifier`** = `{doi}.vN` ;
- `GET /datas/{doi}.vN` résout une **version précise** (200) ; un `.vN`
  inexistant → 404 ;
- `GET /datas/{doi}/versions` **liste** les versions (paginé, dialecte
  `{total, currentPage, lastPage, limit, data:[{version, versionIdentifier,
  creDate, modDate}]}`).

**Déclencheur — résolu en live (cycle complet 2026-06-15, dépôt sacrifié
`10.34847/nkl.66bc6vvi`) :**

| Opération | Crée une version ? |
|---|---|
| Éditer un dépôt `pending` (fichiers ou metas) | ❌ écrase en place, reste `v1` |
| Publier (`pending → published`) | ❌ bascule le statut en place |
| **Modifier les metas d'un dépôt publié** (`PUT /datas {metas}`) | ❌ mutation **en place** (200) |
| **Muter les fichiers d'un dépôt publié** — granulaire (`POST`/`DELETE …/files`) | ✅ **+1 version par opération** |
| **Muter les fichiers d'un dépôt publié** — `PUT /datas {files[]}` | ✅ **+1 version par PUT** (quel que soit le nombre de fichiers changés) |

Sur le cycle observé : ajout d'un fichier → `version` 1→**2** ; suppression
d'un fichier → 2→**3**. Le champ `version` = le numéro de version-fichiers
courant ; `/versions` les liste toutes. **Granularité de versionnement =
l'appel HTTP** : un `PUT files[]` ajoutant 2 fichiers ne crée qu'**une**
version (delta +1) ; un remplacement de contenu (même nom, nouveau sha1)
itou. C'est la base du conseil « regrouper en un `PUT` » pour le push sur
publié (vs N versions en granulaire).

Détail par version : `GET /datas/{doi}.vN` renvoie `version=N`, **son propre
jeu de fichiers** (snapshot) et ses `creDate`/`modDate` propres.

⚠️ **Suppression de fichier = logique, pas physique.** Un fichier retiré
d'une version reste **téléchargeable par son sha1** via le DOI de base
(`GET /data/{doi}/{sha1}` → 200) **et** via le DOI versionné
(`/data/{doi}.vN/{sha1}`). Les octets sont archivés / adressés par contenu —
« retirer » ne détruit rien (un retrait via push n'entraîne donc pas de perte
de donnée côté Nakala).

⚠️ **Nuance majeure : les versions snapshotent les FICHIERS, pas les
métadonnées.** Résoudre `.v1`/`.v2`/`.v3` renvoie pour chacune un **jeu de
fichiers distinct** (l'état figé à ce moment), mais **les mêmes métadonnées
courantes** (le titre modifié après coup apparaît sur *toutes* les versions,
y compris `.v1`). Donc : fichiers = versionnés et immuables par version ;
métadonnées = partagées et mutables sur l'ensemble des versions.

> **→ côté ColleC** : conséquence pour `pousser_fichiers_item` sur un dépôt
> **publié** (sous `--force-published`) : son pipeline granulaire (POST +
> DELETE + PUT de réordonnancement) crée **une version par opération** →
> potentiellement plusieurs `.vN` pour un seul push (vs un seul `PUT files[]`
> = 1 version). C'est une raison de plus de garder le garde-fou `DepotPublie`
> par défaut. ColleC ne pilote pas l'historique des versions ; la
> réconciliation fichier ColleC ↔ Nakala reste par SHA-1. Cf. Partie II §12.

## 8. Comportements d'écriture validés en live ⭐

`scripts/explorer_put_files_nakala.py` a sondé `PUT /datas` contre apitest.
Conclusions **confirmées** :

| # | Question testée | Comportement réel de Nakala |
|---|---|---|
| **H1** | `PUT` avec un seul fichier dans `files[]` | **Remplace intégralement** le tableau — l'autre fichier est retiré. Sémantique « remplace », pas « append » |
| **H2A** | `PUT` sans clé `metas` | Métadonnées **préservées** (les clés omises du corps ne sont pas touchées) |
| **H3** | `PUT files=[]` (liste vide) | **Silencieusement ignoré** — impossible de vider un dépôt de ses fichiers via PUT ; il faut `DELETE` |
| **H4** | `PUT` avec un sha1 inconnu (jamais uploadé, ou « fantôme ») | **HTTP 404 explicite** (≠ le **500** du `POST …/files`, asymétrie entre endpoints) |
| **H5** | Ordre des fichiers dans `files[]` | **Préservé** tel qu'envoyé → on contrôle l'ordre d'affichage côté Nakala |
| **H6** | Re-`PUT` identique | **Idempotent**, no-op silencieux → reprise après crash sans risque de doublon |
| **H7** | Même sha1, `name` différent | **Renommage gratuit** : Nakala propage le nouveau nom sans re-upload du binaire |
| **H10** | Lecture immédiate après `PUT` | **Consistant** (read-after-write) → on peut chaîner `PUT` → lecture sans sleep |
| **H11** | Champ `description` par fichier | **Accepté, préservé, restitué** au `POST` et au `PUT` → ouvre la voie aux transcriptions par fichier |

> Note : la numérotation H1-H11 a des trous (pas de H2B, H8, H9 publiés) —
> hypothèses non posées ou non concluantes, non consignées.

**Autres comportements d'écriture confirmés :**

- **Unicité du sha1 par dépôt** (sondé live, revue T2) : Nakala **refuse
  deux fichiers de même sha1** dans un dépôt — `POST /datas` avec
  `files=[{X,a},{X,b}]` → **422**, et re-`POST …/files` d'un sha1 déjà
  attaché → **409/500**.
- **`POST /datas` multi-fichiers à l'échelle** : 20 fichiers envoyés en
  ordre **inversé** → 20/20 conservés, **ordre inverse préservé** (H5 vaut
  aussi au POST de création, pas seulement au PUT).
- **Enrichissement des créateurs au stockage** (quirk) : `{givenname,
  surname}` → `{authorId, fullName, givenname, orcid:null, surname}`. Une
  relecture diffère de l'envoi → faux diff au push sans canonicalisation.
- **Metas de collection** : `PUT /collections/{id}` → **204** ; les
  collections **n'ont pas de `modDate`** (pas de détection de dérive) ;
  Nakala **remet `typeUri` à null** au stockage des metas de collection.

> **→ côté ColleC** : `diff_push` canonicalise les créateurs (sur
> `surname/givenname/orcid` non-nul) et ignore le `typeUri` nullifié ; les
> garde-fous fichiers (`OrphelinsDetectes`, `fichiers_fantomes`,
> `ContenuDuplique`) découlent de H1/H3/H4 + unicité sha1. Cf. Partie II §12,
> §13, §15.

## 9. Surface d'API au-delà du périmètre ColleC

ColleC ne consomme qu'une fraction de l'API. Sondes **lecture seule** menées
contre `apitest.nakala.fr` le **2026-06-15** pour borner honnêtement ce qui
existe mais n'est pas (encore) exploité :

| Capacité | Statut | Détail |
|---|---|---|
| **OAI-PMH** | ✅ existe | `/oai2` (OAI 2.0, `earliestDatestamp=2015-01-01`, `granularity=YYYY-MM-DD`, `deletedRecord=persistent` ; `/oai`→301). **4 formats** : `oai_dc`, `qdc` (DC qualifié), `oai_datacite`, `oai_isidore` (agrégateur Huma-Num). **Les sets = les collections** (`setSpec=doi_10.34847_nkl.<id>`) → on peut moissonner une collection précise |
| **API de recherche** | ✅ existe | `GET /search?q=…&page=&limit=` → 200, JSON, **sans auth**. Renvoie des DOI de données publiques. Utile pour **découvrir** des DOI (pull par DOI connu sinon) |
| **Vocabulaire licences** | ✅ = SPDX complet | `GET /vocabularies/licenses` → **620 entrées** `{code, name, url}` pointant `spdx.org`. C'est bien la liste SPDX intégrale, pas un sous-ensemble Nakala |
| **IIIF Image API** | ✅ v3.0 | `info.json` d'un fichier image → 200, `application/ld+json; profile=image/3`. Fichier **non-image → 415** (Unsupported Media Type) |
| **IIIF Presentation (manifeste)** | ❌ non exposé | `/iiif/{doi}/manifest`, `.../manifest.json`, `/iiif/{doi}` → tous 404, même pour un data image publié. Pas de manifeste par-donnée aux chemins conventionnels |
| **SPARQL** | ❌ absent | `GET /sparql` → 404 (du moins à ce chemin) |
| **Embargo par fichier au dépôt** | ✅ accepté | `POST /datas` avec `files:[{sha1, name, embargoed:"2099-12-31"}]` accepté ; date seule **normalisée** par Nakala en `2099-12-31T00:00:00+01:00` (datetime + fuseau Europe/Paris), restituée avec un champ compagnon `humanReadableEmbargoedDelay` |
| **`POST /datas` multi-fichiers** | ✅ à l'échelle | 20 fichiers, ordre inverse préservé (cf. §8). Pas de plafond dur recherché (marteler un serveur partagé serait abusif) |
| **Citation** | ✅ sondée (S4) | `GET /datas/{id}/citation` → **chaîne JSON** (citation prête à l'emploi). **Sur apitest, jamais citable** : pending → **200** `"Test deposit, therefore not citable."`, publié → **403** même message (pas de DOI DataCite minté sur le serveur de test → la vraie citation nécessite la **prod**). ColleC avale le 403 (`NakalaAccesInterdit ⊂ ErreurNakala`, best-effort). Consommée : `client.citation()`, CLI `nakala citer` + ligne dans `montrer`, fiche web (lazy HTMX) |
| **Publication via `PUT …/status/{status}`** | ✅ sondée (S5) | `PUT /datas/{id}/status/published` (sans corps) → **204**, publie et **préserve les metas** (`av.metas == ap.metas`). Découple publication / écriture de metas, contrairement à `publier_item` qui re-pousse les metas locales (choix ColleC, principe n°1). ColleC garde l'approche actuelle (cf. §7) |
| **`GET /users/me`, `/resourceprocessing/{id}`** | ✅ existent | identité de la clé ; état d'indexation ElasticSearch + DataCite (latence post-publication) — non sondés |
| **Versioning (DOI `…​.vN`)** | ✅ déclencheur résolu | cf. §7 : **mutation de fichiers sur dépôt publié** = +1 version ; metas/pending/publication = en place. Versions = snapshot des **fichiers** (metas partagées) |

### Non testé / non testable

- **Plafond dur du nombre de fichiers** par dépôt / par `PUT files[]` : non
  recherché volontairement (impliquerait des centaines d'uploads sur un
  serveur de test partagé). On sait que ≥ 20 passe sans souci.
- **Taille max d'upload, rate limiting** : non testables proprement sans
  marteler l'API — à **documenter depuis la doc Huma-Num** plutôt que par
  sonde (blanc factuel, fermable sans probe).
- **Licences réellement acceptées** sur `nkl:license` (cf. §5) : nécessite
  une sonde d'écriture (codes valides/invalides).

---
---

## Partie II — Côté ColleC : exploitation du savoir

---

> Ce que ColleC fait du comportement décrit en Partie I. ColleC possède son
> propre chemin Nakala **lecture + écriture** (sans couplage madbot),
> couvrant le cycle complet : **lire → rapatrier → déposer → pousser
> métadonnées → pousser fichiers → publier**.

## 10. Carte du code

| Sujet | Fichier |
|---|---|
| Client lecture + helpers DOI/erreur | `src/archives_tool/external/nakala/client.py` |
| Client écriture | `src/archives_tool/external/nakala/write_client.py` |
| Mappers (lecture `mapper.py`, écriture `depot_mapper.py`) | `external/nakala/{mapper,depot_mapper}.py` |
| Preflight (cascade créateur/date) | `external/nakala/preflight.py` |
| Itérateur + aplatisseur tableur collection | `external/nakala/{collection,tableur,tableur_io}.py` |
| Services dépôt / push métadonnées | `api/services/nakala_depot.py` |
| Service push fichiers / comparaison | `api/services/nakala_fichiers.py` |
| Runner tâche de fond (dépôt collection) | `api/services/nakala_depot_jobs.py` |
| Journal des push fichiers | `api/services/operations_push_nakala.py` |
| Helpers IIIF / URLs | `src/archives_tool/files/nakala.py` |
| Routes web | `api/routes/nakala_web.py` |
| CLI | `cli.py` (sous-app `nakala`) |

## 11. Mappers & forme d'écriture

La **carte de vérité** est `SLUG_TO_NAKALA` (**57 champs**, vérifié par
import) dans `depot_mapper.py` (portée du plugin madbot puis découplée).
Lecture inverse : `PROPERTY_URI_TO_SLUG` dans `mapper.py`. Elle ne se
contente pas de mapper `slug → propertyUri` : elle porte le `typeUri` et
impose la **forme** par champ (cf. Partie I §4) — **5 catégories** :

1. **Multilingue** — liste `[{value, lang}]` (titre, description, sujet,
   coverage + ~15 DC qualifiés) → une meta par littéral.
2. **Liste de chaînes** — `nkl_creator`, `dcterms_language`,
   `dcterms_contributor` → N metas.
3. **Tableau de chaînes** — identifiants / relations (`isPartOf`,
   `references`…) / dates → N metas.
4. **Scalaire** — `nkl_type`, `nkl_created`, `nkl_license` → une meta.
5. **Structures** — `dcterms_temporal`, `dcterms_spatial` (DCSV, cf. §4).

**Créateur** : format strict `"Nom, Prénom [ORCID]"` (regex ORCID
`\d{4}-\d{4}-\d{4}-\d{3}[\dX]`) → `{surname, givenname, orcid?}`. Sentinelles
→ `null` : `[s.n.]`/`anonyme` (créateur), `[s.d.]`/`inconnue` (date).

**Convention ColleC** : `nkl_creator` et `nkl_created` émettent **toujours au
moins une meta** (valeur `null` si anonyme/inconnu) pour alimenter la cascade
`preflight` — Nakala n'exige que `nkl:title`+`nkl:type` (Partie I §4). Tous
les autres champs absents (`None`) → **aucune meta**. Les slugs inconnus de la
carte sont ignorés silencieusement (`slugs_inconnus` les remonte à
l'utilisateur).

**Cascade preflight** (`preflight.py`) : si `nkl:creator` résout à null,
ColleC tente de le promouvoir depuis `dcterms:creator` bien formé ; à défaut
exige au moins un `dcterms:creator`/`dcterms:contributor`, sinon
`MetaInvalide`. Même logique pour la date. ⚠️ Règle **propre à ColleC** —
Nakala accepte sans (Partie I §4).

**Pont langues** (bug #422) : `depot_mapper.langue_vers_nakala` (639-3 →
639-1) à l'écriture, appliqué à la **valeur** ET à l'attribut **`lang`** des
littéraux dans `item_vers_slugs` ; table `_ISO1_VERS_ISO3` dans `mapper.py`
à la lecture.

**Types COAR** : vocabulaire interne riche (**32 types** = 29 Nakala + 3
extras Chapitre de livre / Document de travail / Photographie) + projection
`COAR_INTERNE_VERS_NAKALA` + `type_coar_pour_nakala()` (ramène les extras
vers une cible Nakala à l'export) + migration `r6v7w8x9y0z1` (remap de
l'existant, non bijective, pas de downgrade).

**Parité vérifiée (sonde S1, lecture seule)** —
`scripts/verifier_parite_vocabulaires_nakala.py` confronte les cartes ColleC
au live : **29/29** types COAR du snapshot acceptés au dépôt, toutes les
projections `type_coar_pour_nakala` ⊆ `depositTypes`, et les **57
`propertyUri`** émises ⊆ les 60 de `/vocabularies/properties`. Promue en test
de non-régression (`tests/test_nakala_vocabulaires_integration.py`).

## 12. Les 4 difficultés structurelles & parades

1. **Conflit / fraîcheur** — Nakala **n'expose pas de verrou optimiste**
   (Partie I). Parade : détection de dérive via `modDate` + **diff &
   confirmation avant overwrite** (dry-run par défaut sur toute écriture) ;
   à défaut, last-writer-wins explicite. ✅ **`modDate` validé en live
   (2026-06-15)** comme base de dérive : **bumpe à chaque mutation** (metas,
   ajout/suppression de fichier), **monotone croissant**. Deux nuances :
   (a) **`None` sur un dépôt frais** (seul `creDate` est posé ; modDate
   apparaît à la 1ʳᵉ modif → ColleC gère le baseline `None` : pas de fausse
   dérive) ; (b) **granularité 1 seconde** → deux mutations dans la même
   seconde partagent un `modDate` (une dérive survenant dans la seconde du
   pull baseline peut échapper — angle mort théorique).
2. **Publié vs pending** — sur publié, métadonnées éditables et fichiers
   techniquement mutables (Partie I §6), mais **pas de dé-publication**.
   Parade : statut modélisé + garde-fou `DepotPublie` (flag
   `--force-published`) = **politique**, pas nécessité technique.
3. **Fidélité du round-trip** — une carte unique lecture+écriture
   (`SLUG_TO_NAKALA`), validée par round-trip idempotent
   (`diff_push(distant, envoyé) == []` après dépôt et après modif, sur
   dépôts ET collections).
4. **Identité fichiers** — réconciliation par **SHA-1** (Nakala = SHA-1 ;
   `Fichier.hash_sha256` = SHA-256, algos différents) → colonne dédiée
   `Fichier.sha1_nakala` (migration `s7w8x9y0z1a2`, backfill idempotent).

## 13. Quirks de l'API gérés côté ColleC

- **Bug #422 — langue** (Partie I §5). Latent car aucun test ne déposait de
  langue jusqu'à la validation live. ✅ **Corrigé sur les deux chemins** :
  `item_vers_slugs` (dépôt/push) **et** `exporters/nakala.py` (CSV bulk,
  chemin manuel séparé) convertissent via `langue_vers_nakala` (valeur
  `dcterms:language` + `langTitle`).
- **Canonicalisation des créateurs** (Partie I §8) : `diff_push`
  canonicalise sur `surname/givenname/orcid` non-nul seuls → plus de faux
  diff au push. ✅ **ORCID normalisé (2026-06-15)** : Nakala normalise l'ORCID
  en **URL** (`https://orcid.org/…`) ; ColleC le dépose/affiche **nu**.
  `mapper.normaliser_orcid` ramène à la forme nue — **source unique partagée**
  par la lecture (`_format_createur` → un créateur rapatrié garde l'ORCID nu)
  ET la comparaison (`diff_push` → plus de faux diff au push). Sans ça, tout
  créateur avec ORCID cassait l'idempotence du push **et** divergeait au
  round-trip (reproduit puis corrigé live). Le **réordonnancement** des
  créateurs par Nakala (tri par nom) est inoffensif au push (diff multiset)
  mais reste visible à la lecture (l'ordre d'origine est perdu côté Nakala).
- **`files[]` = remplacement total** (H1) : d'où le garde-fou
  `OrphelinsDetectes` / flag `--retirer-orphelins`, et la notion de
  **« fichiers fantômes »** (`sha1_nakala` désynchronisé) qui bloque le push.
- **Unicité du sha1 par dépôt** (Partie I §8) : garde-fou pré-vol
  `ContenuDuplique` qui refuse **avant toute mutation** si le set final a un
  sha1 dupliqué (sinon, en granulaire, échec partiel au 2ᵉ POST). La
  machinerie défensive « doublons sha1 distants » du comparateur (`pop(0)` /
  file par sha1, deque de `_reordonner_files`) défend un état que Nakala ne
  crée pas — **défense morte**, conservée pour d'éventuelles données legacy.
- **IIIF non-image → 415** (Partie I §3/§9) : garde sur l'extension à
  l'import (`_est_extension_image_iiif`) de toute façon.
- **Fusion (pas remplacement) des metas de collection** : ColleC ne gère que
  titre + description → préserve les metas Nakala non modélisées (sujet,
  créateur de collection…) au lieu de les écraser.
- **Push de fichiers journalisé** : un push qui retire des fichiers
  (DELETE granulaire ou PUT de réordonnancement) échappait à
  `OperationFichier` (qui ne couvre que le disque local). ✅ **Résolu**
  (passe 24) : table `OperationPushNakala` (migration `t8x9y0z1a2b3`) +
  `journaliser_push_fichiers` insère un snapshot avant/après dans la **même
  transaction** que les mutations DB. Consultation : `archives-tool montrer
  push-nakala`.
- **Erreurs `validationErrors` surfacées** (T3) : `detail_erreur_nakala`
  annexe le détail par champ d'un 422 au message des deux clients.

## 14. Helpers IIIF / URLs (`files/nakala.py`)

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

## 15. Les 14 commandes CLI

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

Détail d'usage : [`../guide/cli/nakala.md`](../guide/cli/nakala.md).

**`comparer-fichiers`** classe les fichiers d'un item vs le dépôt distant en
**7 catégories** (`RapportComparaisonFichiers`) : les 5 de base `nouveaux`,
`modifies`, `inchanges`, `nakala_only_sans_local`, `orphelins_distants`,
plus 2 de diagnostic/refus — `non_actifs_a_retirer` (Fichier en
CORBEILLE/REMPLACE, exclu du plan ; consultatif tant que la corbeille UI
n'existe pas) et `fichiers_fantomes` (`sha1_nakala` ne matche plus aucun
fichier distant → **refus** `FichierFantomeDistant`, sinon 404 au push). La
réconciliation est prioritaire par SHA-1 recalculé à la volée, fallback sur
`sha1_nakala` stocké. Garde-fou supplémentaire : `BackfillIncomplet` si un
`nakala_only_sans_local` n'a pas de `sha1_nakala` peuplé.

**`pousser-fichiers`** (push granulaire, ticket T2) : upload nouveaux/modifiés
→ `POST …/files` (additif) → `DELETE …/files/{sha1}` (anciens modifiés,
orphelins, non-actifs) → `PUT files[]` de **réordonnancement** reconstruit
depuis l'état distant relu (fixe l'ordre, aucun drop silencieux). Six
garde-fous : `fichiers_fantomes`, `BackfillIncomplet`, `DepotPublie`,
`OrphelinsDetectes`, `PushImpossible` (plan vide), `ContenuDuplique`.

**Décision P2** : les fichiers ne montent **qu'à la création** du dépôt
(`deposer`) ; le push de fichiers ultérieur passe par `pousser-fichiers`. On
n'inscrit pas les DOI dans les métadonnées (« DOI = adresse »).

## 16. Exemples réels testés

| Collection | Volume | Validé sur |
|---|---|---|
| José Mora Guarnido | 65 données → 155 fichiers | `exporter-tableur`, `rapatrier-collection` |
| Fernando Aínsa | 6163 données | export xlsx (`write_only`), CSV en flux |
| Armonía Somers / Julio Cortázar | collections | dépôt / push |
| Por Favor (PF) | 173 items, 7454 scans Nakala-only | import, IIIF, recherche |

**Round-trip end-to-end via les services ColleC (2026-06-15)** — capstone :
`deposer_item` (Item + 2 fichiers locaux → apitest) → `rapatrier` (DB fraîche,
`base_url` → matérialise les fichiers) → comparaison de l'Item reconstruit.
**Fidèle sur tout** : titre, date (`1984-03`), langue (`spa`→`es`→`spa`),
description, type_coar, sujets, **2 fichiers** avec URLs IIIF `info.json`
correctes. Seule divergence : l'**ordre des créateurs** (Nakala réordonne par
nom, irrécupérable — sans impact sur l'idempotence du push). L'ORCID, lui,
round-trip nu après le fix `mapper.normaliser_orcid` (§13).

## 17. Tâches de fond (dépôt collection)

Première tâche de fond du projet : **`threading.Thread` daemon + registre
mémoire thread-safe**, **pas de broker** (cf. CLAUDE.md *Tâches de fond :
runner mémoire + reprise idempotente*). Une tâche concurrente à la fois
(`JobConcurrent`). **Sûreté par reprise idempotente** : les DOI sont
persistés au fil de l'eau → un crash mid-run laisse les items créés intacts,
et relancer saute ceux qui ont déjà un DOI. État volatile : un restart du
processus perd le registre (page de suivi 404 sur job inconnu) mais la base
reste cohérente.

## 18. Observabilité

- Loggers : `archives_tool.api.services.nakala_depot` et `…​.nakala_fichiers`
  (events INFO / WARNING / DEBUG ; sha1 tronqués, aucun secret ni PII).
  `publier_item` logge un WARNING (appel **irréversible et payant**).
- ✅ Les **7 services d'écriture** de `nakala_depot.py` (`deposer_item`,
  `deposer_collection`, `pousser_item`, `publier_item`,
  `pousser_metadonnees_collection`, `pousser_collection`,
  `publier_collection`) ont tous le logging structuré (résolu passe 21).

## 19. Où vit ce savoir

| Sujet | Fichier |
|---|---|
| Conception / architecture / phasage | [`nakala-depot-future.md`](nakala-depot-future.md) |
| **Backlog actionnable (issu de ce savoir)** | [`backlog-nakala-api.md`](backlog-nakala-api.md) |
| Backlog niveau collection | [`backlog-nakala-collection.md`](backlog-nakala-collection.md) |
| Guide d'usage CLI | [`../guide/cli/nakala.md`](../guide/cli/nakala.md) |
| **Sondes live** | `scripts/explorer_put_files_nakala.py` (PUT `files[]`, H1-H11), `scripts/explorer_files_granulaire_nakala.py` (POST/DELETE granulaires, T2), `scripts/verifier_parite_vocabulaires_nakala.py` (parité vocab S1, lecture seule) |
| Tests d'intégration (opt-in `-m integration`) | `tests/test_nakala_*_integration.py` |
| Découvertes accumulées | section Nakala de `CLAUDE.md` |
