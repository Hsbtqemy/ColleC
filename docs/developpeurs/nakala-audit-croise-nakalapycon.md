# Nakala — audit croisé avec NakalaPycon

> Document interne, exclu du build MkDocs. **Confrontation du savoir Nakala
> de ColleC** (validé live, cf. [`nakala-savoir-api.md`](nakala-savoir-api.md))
> **au code d'une autre bibliothèque cliente, NakalaPycon** — wrapper Python
> de l'API Nakala écrit par Michael Nauge (Université de Poitiers), audité
> ligne par ligne en `0.0.9` (audit `nakalapycon/AUDIT.md`, mai-juin 2026).
>
> **Pourquoi ce document.** NakalaPycon est un client Nakala **indépendant**
> de ColleC. Le confronter à notre savoir live a une triple valeur :
>
> 1. **Confirmations mutuelles** — là où deux audits indépendants (le nôtre,
>    par sonde live ; le sien, par lecture de code + spec Swagger) tombent
>    d'accord, notre confiance monte (§1).
> 2. **Ce que notre savoir révèle dans NakalaPycon** — des quirks Nakala que
>    *nous* avons découverts en live et que son audit (faute de sondes
>    d'écriture) a manqués, et qui sont autant de pièges pour tout wrapper
>    naïf — dont le nôtre s'il dévie (§2).
> 3. **Ce que son audit apporte à ColleC** — NakalaPycon couvre des endpoints
>    que ColleC n'exploite pas (groups, users, authors/search, vocabulaires
>    complets) ; son audit en documente des comportements **hors de notre
>    périmètre de sonde** (§3).
>
> Sources : `nakalapycon/AUDIT.md` (8 bugs 🔴, ~16 🟠, ~17 🟡 + 11 sections de
> vérification §8.1-§8.11) et le code `nakalapycon/src/*.py` v0.0.9.
> Confronté le **2026-06-25** au savoir ColleC daté apitest 2026-06-15 →
> parité prod 2026-06-20.

---

## 0. Ce qu'est NakalaPycon (en une page)

Architecture : une classe `NklTarget` (cible test/prod + clé API) + une
classe `NklResponse` (réponse unifiée `isSuccess`/`code`/`message`/`dictVals`)
servent de socle à des modules par tag (`nklAPI_Datas`, `_Collections`,
`_Groups`, `_Users`, `_Vocabularies`, `_Search`) plus des utilitaires
(`nklUtils`, `nklPullCorpus`, `nklDf2Dic`) et un dictionnaire de constantes.
Le **boilerplate HTTP** (`headers → NklResponse() → try/requests/status_code/
json.loads/except`) est copié-collé ~30 fois.

C'est, en somme, **ce que ColleC aurait pu être** s'il n'avait pas son propre
client lecture+écriture (`external/nakala/`). Le comparer revient à confronter
deux implémentations du **même contrat d'API** — exactement l'exercice qui
durcit notre compréhension de Nakala.

> **Verdict d'ensemble (de son audit) :** architecture saine, large couverture
> fonctionnelle fidèle, docstrings systématiques — mais plusieurs **bugs
> fonctionnels avérés** (paramètres de requête ignorés, URL corrompue par des
> caractères invisibles, conditions pandas erronées), pas de `timeout`, gestion
> d'erreur fragile, « tests » non automatisés (appels réseau réels à l'import).
> **ColleC ne devrait pas adopter NakalaPycon** : notre client est plus sûr
> (dry-run, garde-fous, round-trip idempotent prouvé). Ce document exploite
> NakalaPycon comme **miroir de connaissance**, pas comme dépendance candidate.

---

## 1. Confirmations mutuelles (notre savoir ✓ recoupé indépendamment)

Chaque ligne : un fait Nakala que **ColleC a établi par sonde live** ET que
**l'audit NakalaPycon a établi par lecture de spec/code**. Convergence = ces
faits sont solides.

| Fait Nakala | Savoir ColleC | Audit NakalaPycon | Verdict |
|---|---|---|---|
| `POST /datas/{id}/files` → **200** (pas 201) | savoir-api §2/§3 (`{code:200,"File added"}`) | §3.5 + §8.2 : code 200 conforme, **le commentaire « 201 » du code est faux** | ✅ concordant |
| `DELETE /datas/{id}/files/{sha1}` → **204** | savoir-api §2/§3 | §2.4 + §8.2 : NakalaPycon teste `200` → **bug** (la branche succès ne se déclenche jamais) | ✅ concordant (et confirme un bug chez eux) |
| **29** types COAR au dépôt (`/vocabularies/depositTypes`) | savoir-api §5 (29) | §3.15 + §8.5 : `VOCABTYPE` fige **30** types, dont **5 disparus** côté serveur | ✅ concordant (29 = vérité ; eux en ont 1 de trop net) |
| Dates typées **W3CDTF** (`dcterms:*` date) | savoir-api §4 (`…/W3CDTF`) | §3.16 + §8.5 : typer `created` en `xsd:string` (leurs exemples) non conforme | ✅ concordant |
| `/search` : **pas de curseur de page** (`lastPage`/`currentPage` absents/`null`), seul `totalResults` | savoir-api §4 (dialecte `{datas, totalResults}`) | §3.20 + §8.11 : `lastPage`/`currentPage` = `null` en live ; pagine via `size`+`totalResults` | ✅ concordant (sonde live des deux côtés) |
| Créateur = `{givenname, surname}` (obligatoires), **enrichi au stockage** en `{authorId, fullName, …}` | savoir-api §4/§8 | §8.8/§8.9 : `Author={givenname,surname,orcid,authorId,fullName}`, `givenname`+`surname` requis ; données réelles `{"givenname":"Claudie","surname":"Marcel-Dubois"}` | ✅ concordant |
| `DELETE /datas/{id}` succès = **202 ou 204** | (non détaillé côté ColleC — DELETE pending) | §3.5 + §8.2 : NakalaPycon teste `204` seul → **ignore un succès `202`** | ➕ précision utile (cf. §3) |

> **Lecture ColleC.** Notre `mapper`/`depot_mapper` et nos garde-fous reposent
> sur exactement ces faits. Qu'un audit indépendant, par une méthode
> différente (spec Swagger + lecture), retombe dessus est une **validation
> croisée gratuite** — surtout sur les codes de statut (200/204) et la forme
> du listing `/search`, là où une erreur de notre part coûterait un faux
> succès ou une pagination cassée.

---

## 2. Ce que notre savoir live révèle dans NakalaPycon

Ces quirks, **nous** les avons payés en sang (savoir-api « trois comportements
qui ont coûté du sang »). L'audit NakalaPycon ne les voit pas — il s'est arrêté
à la spec et au code, sans sonde d'écriture. Résultat : NakalaPycon les
**subit silencieusement**. C'est la partie la plus instructive : elle montre
ce qu'un wrapper paie à ne pas avoir sondé l'écriture, et **rappelle pourquoi
ColleC, lui, les gère**.

### 2.1 🔴 Langue — bug #422 non géré (pass-through brut)

**Notre savoir** (savoir-api §5, résumé #1) : Nakala type `dcterms:language`
en **RFC5646 / ISO 639-1** (`fr`, `es`, `en`) pour les langues majeures, et
réserve l'ISO 639-3 à la longue traîne. Déposer `spa` (639-3) → **rejet 422**.
C'est `langue_vers_nakala` (639-3 → 639-1) côté ColleC qui ponte ce trou.

**Côté NakalaPycon** (vérifié 2026-06-25) : **aucune** conversion de langue
nulle part dans le code. La valeur du champ `lang` est transmise **telle
quelle** :

- chemin « dictionnaire brut » (`post_datas`, `put_datas`, `post_datas_metadatas`)
  → la `lang` fournie par l'appelant part dans le JSON sans contrôle ;
- chemin « tableur » (`nklDf2Dic.dfDatasFiles2ListDic`) → la `lang` est lue de
  la colonne `Nkl-lang` et recopiée (`nklDf2Dic.py:151-158`).

**Pourquoi c'est un piège réel et non théorique.** NakalaPycon expose
`get_vocabularies_languages` (le endpoint `/vocabularies/languages`) — dont les
`id` sont en **ISO 639-3 pour la longue traîne** (savoir-api §5). Un
utilisateur qui pioche un `id` de langue dans la sortie de cette fonction et le
place dans une meta `lang` **obtient un 422** pour ces langues — sans aucun
indice côté librairie.

> ⚠️ **Interaction avec leur bug §2.6.** Leur audit a trouvé que le test de
> langue du chemin tableur est *toujours faux* (`not(str(<bool>))`,
> `nklDf2Dic.py:154`) → la `lang` y est **actuellement jamais affectée** (reste
> `""`). Le bug #422 est donc *masqué* sur ce chemin tant que §2.6 n'est pas
> corrigé ; le jour où ils corrigent §2.6, le piège #422 **se réveille**. Sur
> le chemin « dictionnaire brut », il bite déjà.
>
> **Leçon ColleC :** notre pont langue n'est pas un détail d'implémentation —
> c'est la seule chose qui sépare un dépôt accepté d'un 422. À ne jamais
> retirer ni court-circuiter (cf. quirk géré, savoir-api §13).

### 2.2 🔴 `put_datas` — sémantique « `files[]` = remplacement total » (H1) jamais documentée

**Notre savoir** (savoir-api §8, H1 ; résumé #3) : `PUT /datas` a une
sémantique **« remplace »**, pas « ajoute ». Omettre un fichier de `files[]`
le **supprime** silencieusement. C'est *la* raison d'être de tout l'appareil
défensif de ColleC (`OrphelinsDetectes`, « fichiers fantômes », reconstruction
de la liste cible complète, puis bascule vers le push **granulaire** `POST`/
`DELETE …/files` en T2).

**Côté NakalaPycon** : `put_datas(nklTarget, identifier, dictVals)`
(`nklAPI_Datas.py:91`) transmet `dictVals` **brut** en `PUT`. Sa docstring
décrit « les informations à modifier » mais **n'avertit nulle part** que
fournir une clé `files` partielle **détruit** les fichiers omis. Un appelant
qui veut « juste changer un fichier » en envoyant `{"files":[{nouveau}]}`
**efface tous les autres**. NakalaPycon n'offre aucun chemin granulaire **sûr**
en regard : son `delete_datas_files` est par ailleurs cassé (URL polluée par
2× U+200B **et** code testé `200` au lieu de `204`, audit §2.4) et son
`post_datas_files` (additif, → 200) n'est pas présenté comme la voie de
modification sûre.

> **Leçon ColleC :** notre choix T2 (push **granulaire** `POST` additif →
> `DELETE` ciblé → `PUT files[]` de **réordonnancement reconstruit depuis
> l'état distant relu**) est exactement la parade que NakalaPycon n'a pas. La
> tentation « un seul PUT, c'est plus simple » est un piège à perte de données
> silencieuse. Confirmé par H12 (savoir-api) : même le champ `description`
> omis d'un `files[i]` au PUT est **effacé** → notre règle anti-wipe est
> nécessaire.

### 2.3 🟠 `post_datas_metadatas` — doublon sur scalaire non documenté

**Notre savoir** (savoir-api §2, *Métadonnées granulaires*, sondé 2026-06-19) :
`POST /datas/{id}/metadatas` est **additif**. Sur une propriété **scalaire**
(`nkl:title`), il **ne remplace pas — il crée un DOUBLON** (le dépôt se
retrouve avec deux titres). Modifier un scalaire impose donc **DELETE puis
POST**. (C'est précisément le piège documenté dans notre ticket T4.)

**Côté NakalaPycon** : `post_datas_metadatas` (`nklAPI_Datas.py:633`) est
documenté « Ajout d'une nouvelle métadonnée à une donnée » et teste `201`
(conforme). Mais **rien** n'avertit qu'employer cette fonction pour
« corriger » un titre **ajoute un second titre** au lieu de le remplacer. Un
utilisateur qui veut éditer un champ scalaire via cet endpoint corrompt sa
notice sans erreur.

> **À l'inverse, `delete_datas_metadatas` (`nklAPI_Datas.py:704`) est correct
> et utile** : il accepte un **filtre** dans le corps (ex. `{"lang":"en",
> "propertyUri":".../subject"}`) → suppression **granulaire à la valeur**,
> exactement le comportement que nous avons sondé (DELETE granulaire → 200).
> NakalaPycon est donc, de fait, une **implémentation de référence du chemin
> granulaire métadonnées** que ColleC envisage en **T4** (`backlog-nakala-api.md`)
> — y compris le piège du doublon-sur-scalaire qui justifie le « POST-new puis
> DELETE-old » de T4. Bon point d'appui le jour où T4 est arbitré.

### 2.4 🟠 Cas limites d'écriture que NakalaPycon ne couvre pas

Notre sonde granulaire (savoir-api §2, codes §3) a établi des cas limites que
NakalaPycon ne gère pas (son audit ne les mentionne pas, faute de sonde
d'écriture) :

| Cas limite (savoir ColleC) | Comportement Nakala | Risque côté NakalaPycon |
|---|---|---|
| Retrait du **dernier** fichier d'un dépôt | **403 refusé** (un dépôt ne peut être vidé) | `delete_datas_files` ne distingue pas ce 403 — message d'erreur opaque |
| **Unicité du sha1 par dépôt** | 2 fichiers même sha1 → **422** ; re-`POST …/files` → 409/500 | aucune détection côté client avant POST → échec brut |
| sha1 jamais uploadé / fantôme | `POST …/files` → **500** ; `PUT` → **404** (asymétrie) | codes avalés tels quels, pas de validation amont |
| Re-`POST` d'un fichier déjà présent | **409 ou 500** selon l'état du stockage temp (**non fiable**) | impossible de se reposer sur le code HTTP — NakalaPycon le fait pourtant |
| Mutation de **fichiers** d'un dépôt **publié** | acceptée mais **crée une version `.vN`** (savoir-api §7) | NakalaPycon n'a pas de garde-fou « publié » type `DepotPublie` |

> **Leçon ColleC :** nos garde-fous (`ContenuDuplique` avant toute mutation,
> validation des sha1 issus d'un upload réussi, `DepotPublie` par défaut,
> détection « déjà présent » **côté client**) répondent un à un à ces cas
> NakalaPycon ne couvre pas. La règle d'or qu'illustre NakalaPycon : **ne
> jamais faire confiance au code HTTP de Nakala sur les endpoints granulaires
> de fichiers** (409/500 interchangeables, non destructifs mais trompeurs).

---

## 3. Ce que l'audit NakalaPycon apporte à ColleC

NakalaPycon couvre des tags d'API que **ColleC n'exploite pas** (savoir-api §9
« surface au-delà du périmètre »). Son audit en documente des comportements
**hors de notre périmètre de sonde** — utiles si ColleC élargit un jour son
empreinte, et bons à archiver dans notre savoir.

### 3.1 Groupes (`POST`/`PUT /groups`) — schéma `users[]`

L'audit (§3.17, §8.7) a résolu contre la spec le corps `users` de
`POST`/`PUT /groups` : c'est un **`array<{username, role}>`** (définition
`MinimalUserInfo` / `PostAndPutGroup.users`), `role ∈ [ROLE_OWNER, ROLE_ADMIN,
ROLE_USER]`, exemple `[{"username":"pdupont","role":"ROLE_OWNER"}]`. NakalaPycon
lui-même envoie (à tort) une **liste de chaînes** `["unakala1", …]` → non
conforme. ColleC ne touche pas aux groupes aujourd'hui ; à archiver si la
gestion fine des droits/groupes entre un jour au périmètre.

### 3.2 Droits sur donnée (`POST /datas/{id}/rights`) — enum `Role`

L'audit (§3.18, §8.7) : l'enum `Role` du corps des POST de droits sur data =
**`[ROLE_ADMIN, ROLE_EDITOR, ROLE_READER]`** ; **`ROLE_OWNER` n'est PAS
assignable** via l'API (le propriétaire ne s'attribue pas). À distinguer des
rôles de **groupe** (§3.1, qui inclut `ROLE_OWNER`/`ROLE_USER`) — **deux enums
de rôles distincts** selon le contexte (groupe vs droit-sur-donnée). Bon à
savoir si ColleC expose un jour la gestion de droits par data.

### 3.3 `/authors/search` — paramètres non exposés

L'audit (§2.2, §3.12, §8.4) : `/authors/search` accepte `order`, `page`,
`limit` **et** `searchOperator` / `searchField`. Le tri de l'index auteurs est
**primaire par `givenname`** (`order=asc`, confirmé live §8.10) — cohérent
avec notre constat que l'API auteurs « part du prénom ». Pour ColleC, c'est une
voie de **découverte d'auteurs** complémentaire à `/search` (que nous utilisons
déjà pour découvrir des DOI) — non exploitée à ce jour.

### 3.4 ⭐ `authorId` — sémantique de dédoublonnage (write-test live)

C'est l'apport le plus riche : l'audit NakalaPycon a mené des **sondes
d'écriture dédiées** à l'`authorId` (§8.9, §8.11 — data *pending* créées puis
supprimées), qui **complètent** notre savoir-api §4/§8 (où l'on note
l'enrichissement `{authorId, fullName, …}` et le réordonnancement par nom, mais
**pas** la sémantique de dédoublonnage). Résultats prouvés :

| Constat (audit §8.9/§8.11) | Détail |
|---|---|
| **Dédup sur le couple ordonné exact** | même `(givenname, surname)` → **même `authorId`** ; couple **inversé** → `authorId` **différent** (pas de normalisation, pas d'usage du `fullName`) |
| **Recalcul dynamique au `PUT`** | `put_datas` **recalcule** l'`authorId` à chaque écriture sur le couple courant, **sans mémoire** de l'ancien |
| **Réparabilité** | corriger une inversion via `PUT` rattache réellement la donnée à la **bonne** fiche d'auteur (l'`authorId` corrigé == celui d'une création correcte) ; pas de fantôme résiduel sur la donnée corrigée |

> **Pourquoi c'est précieux pour ColleC.** Notre round-trip « perd l'ordre des
> créateurs » (Nakala réordonne par nom, savoir-api §16) — on s'en accommode
> car `diff_push` est un multiset. Ces sondes ajoutent une garantie qu'on
> n'avait pas formalisée : puisque l'`authorId` est **déterministe sur le
> couple** et **recalculé à chaque PUT**, **nos pushes ne créent pas de
> fiches-auteur fantômes**. Tant que ColleC envoie `{givenname, surname}`
> stables et corrects (ce que garantissent nos deux champs séparés, là où
> NakalaPycon découpe une chaîne unique par regex et **peut intervertir** —
> audit §3.11), l'identité d'auteur côté Nakala reste propre. À verser dans
> savoir-api §4 (note « dédup déterministe + recalcul au PUT ») si l'on veut
> tracer ce comportement.
>
> **Le contre-exemple NakalaPycon (à ne pas reproduire).** Son
> `creatorsValuesToDic` découpe `"Nom, Prénom"` par regex et **lit en fait
> « Nom, Prénom »** alors que sa docstring annonce « prénom, nom » (audit
> §3.11) → inversion silencieuse ; **sans virgule, le créateur est omis**
> (`"Marie Curie"` ne matche pas) ; espace parasite après `@orcid`. Combiné à
> la dédup-sur-couple ci-dessus, une inversion **fragmente** l'auteur en
> plusieurs `authorId` (audit §8.9). **ColleC évite ce piège par conception**
> (champs `givenname`/`surname` séparés, jamais une chaîne à re-découper).

---

## 4. Checklist du wrapper Nakala robuste (grille réutilisable)

Synthèse **actionnable** des deux audits : les invariants qu'un client Nakala
doit tenir. Conçue pour être **passée sur n'importe quel client** — y compris
le nôtre (`external/nakala/`) en auto-revue — pas seulement comme constat sur
NakalaPycon. Chaque ligne : l'invariant, le risque si manqué, la référence
Nakala, et où le vérifier côté ColleC.

### Réseau / HTTP

| ✔ | Invariant | Risque si manqué | Réf. | Côté ColleC |
|---|---|---|---|---|
| ☐ | **`timeout` sur tout appel** réseau | une connexion suspendue bloque le script indéfiniment | savoir-api §1 (« Nakala lent sur cache froid ») | 30 s lecture / 60 s écriture (`config_local.yaml`) |
| ☐ | **Query-params via `params={…}`**, jamais par concaténation | espaces / `:` dans `q` cassent l'URL ; tri/pagination silencieusement perdus (cf. NakalaPycon §2.1-2.3 de l'audit) | — | httpx `params=` |
| ☐ | **`response.json()` protégé** contre un corps non-JSON | 502/504/maintenance → page HTML → `JSONDecodeError` non capturée | savoir-api §3 | `detail_erreur_nakala` défensif (T3) |
| ☐ | **Codes de statut mappés *par endpoint*** (pas un 200 générique) | un succès traité comme erreur (ou l'inverse) | savoir-api §3 ; cross-audit §1 | `_verifier_statut` par opération |

Mapping de référence (savoir-api §3, cross-audit §1) : `POST /datas` **201** ·
`PUT /datas` **204** · `DELETE /datas` **202 ou 204** · `POST …/files` **200** ·
`DELETE …/files/{sha1}` **204** · `PUT /collections` **204** · `POST …/metadatas`
**201** · `DELETE …/metadatas` **200**.

### Conformité Nakala (écriture)

| ✔ | Invariant | Risque si manqué | Réf. | Côté ColleC |
|---|---|---|---|---|
| ☐ | **Langue 639-3 → 639-1 (RFC5646)** avant envoi, sur la **valeur ET l'attribut `lang`** | **rejet 422** sur les codes 639-3 (longue traîne de `/vocabularies/languages`) | savoir-api §5 (#422) ; cross-audit §2.1 | `langue_vers_nakala` + `_ISO1_VERS_ISO3` (§13) |
| ☐ | **`PUT /datas` = remplacement total de `files[]`** : ne jamais envoyer une liste partielle | perte **silencieuse** des fichiers omis (et `description` omise effacée, H12) | savoir-api §8 (H1/H12) | push **granulaire** POST→DELETE→PUT réordonnancement (T2) |
| ☐ | **Modifier un scalaire en granulaire = DELETE puis POST** | `POST …/metadatas` seul **duplique** le champ (2 titres) | savoir-api §2 ; cross-audit §2.3 | `PUT metas[]` (remplace) aujourd'hui ; T4 si granulaire |
| ☐ | **Unicité du sha1 par dépôt** : refuser **avant** mutation si doublon | échec partiel au 2ᵉ POST ; 422 au `POST /datas` | savoir-api §8 | garde-fou `ContenuDuplique` |
| ☐ | **Créateurs en champs séparés `{givenname, surname}`**, jamais une chaîne unique à re-découper | inversion / omission → **fragmentation de l'`authorId`** | cross-audit §3.4 ; savoir-api §4 | deux champs distincts par conception |
| ☐ | **Canonicaliser les créateurs au diff** (Nakala enrichit `{authorId, fullName, orcid-URL}` au stockage) | faux diff à chaque push, idempotence cassée | savoir-api §8 | `diff_push` + `normaliser_orcid` (§13) |

### Endpoints granulaires de fichiers — codes non fiables

| ✔ | Invariant | Risque si manqué | Réf. |
|---|---|---|---|
| ☐ | **Détecter « déjà présent » côté client** avant `POST …/files` | re-POST → 409 **ou** 500 selon l'état du stockage temp (non destructif mais trompeur) | savoir-api §2/§3 |
| ☐ | **Valider que chaque sha1 vient d'un upload réussi** | sha1 fantôme → 500 (`POST`) / 404 (`PUT`) — asymétrie | savoir-api §2 (H4) |
| ☐ | **Ne jamais vider un dépôt de tous ses fichiers** | retrait du **dernier** fichier → 403 | savoir-api §2 |
| ☐ | **Garde-fou « dépôt publié »** (politique) | muter les fichiers d'un publié → **+1 version `.vN`** par opération | savoir-api §6/§7 |

### Hygiène de bibliothèque

| ✔ | Invariant | Risque si manqué |
|---|---|---|
| ☐ | `logging`, **pas** de `print` en lib | pollution stdout du code appelant |
| ☐ | Arguments par défaut **non mutables** (`None` puis init) | état partagé entre instances |
| ☐ | Clé API par défaut **vide** (`""`), pas une fausse clé | en-tête `X-API-KEY` invalide même en lecture publique → 401 |
| ☐ | **Politiques applicatives ≠ exigences Nakala** clairement séparées | Nakala n'exige que `title`+`type` ; toute règle plus stricte (créateur/date obligatoires) est un choix à assumer/documenter (savoir-api §4) |

> Les colonnes « ✔ » sont là pour cocher lors d'une revue. NakalaPycon v0.0.9
> échoue sur la majorité des lignes « Conformité » et « Réseau/HTTP » (cf. son
> `AUDIT.md`) ; ColleC les couvre — cette grille sert surtout à **garder cet
> écart** au fil des évolutions.

### Résultat de l'auto-revue sur `external/nakala/` (2026-06-25)

Grille ci-dessus passée sur le client ColleC (lecture seule, revue
multi-agents). **Bilan : 13 ✅ · 3 ⚠️ partiel · 1 N/A.** Le client couvre **tous
les pièges Nakala structurants** que NakalaPycon subit (§2) ; les 3 ⚠️ sont de
portée limitée.

| Item ⚠️ | Constat (preuve) |
|---|---|
| **Réponse JSON protégée** | `reponse.json()` **à nu** sur les chemins nominaux 2xx (`client.py:209` `lire_depot`, les 4 `lister_*`, `write_client.py:189` `creer_depot`…) → un 2xx à corps non-JSON lève `JSONDecodeError` brut, pas `ErreurNakala`. Le helper `detail_erreur_nakala` (défensif) n'est branché que sur les **non**-2xx. **Seul correctif réellement recommandé** : envelopper le parse du chemin succès dans le même helper. |
| **Codes de statut par endpoint** | succès = `is_success` (tout 2xx), non discriminant par opération ; compensé par vérification de la **forme du corps** (`uploader_fichier` exige `sha1`, `extraire_doi` tolérant). Choix assumé, défendable — à durcir seulement si besoin. |
| **Détection « déjà présent »** | indirecte (classif `comparer_fichiers_item` + `ContenuDuplique` **intra-plan**) ; pas de contrôle plan-vs-distant-relu → un `modifie` revenant à un sha1 déjà attaché heurterait le 409/500 non fiable (cas rare : rollback). |

**N/A** — « modifier un scalaire = DELETE puis POST » : ColleC pousse les metas
par `PUT metas[]` (remplacement total), donc le piège doublon-sur-scalaire de
`POST …/metadatas` (§2.3) ne s'applique pas. Il guette en revanche le ticket
**T4** si le push métadonnées passe un jour en granulaire.

**Notes mineures** : (a) **asymétrie round-trip langue longue traîne** —
`_ISO1_VERS_ISO3` (lecture) couvre ~14 langues vs ~185 annoncées en docstring
(TODO déjà noté `mapper.py:35-38`) ; (b) **export CSV** : `description`/`subject`
émis sans tag `lang` (limite du format plat, pas un bug) ; (c) **couplage format
créateur** lecture↔écriture (ci-dessous).

**Couverture de test du format créateur** (vérifiée 2026-06-25) : les deux sens
sont unit-testés — écriture `parse_creator` (`test_nakala_depot_mapper.py:23-42`
: structure, ORCID, anonyme, **et invalide → lève**, ce qui prouve la sûreté
anti-inversion) ; lecture `_format_createur` (`test_nakala_mapper.py:71-95` :
dict→chaîne, ORCID URL→nu). La **fidélité bout-à-bout** est couverte par le
round-trip **live** `test_round_trip_depot` (`test_nakala_depot_integration.py:94`,
opt-in réseau). **Manque** : aucun test **offline** ne chaîne `_format_createur`
→ `parse_creator` pour verrouiller le miroir lecture↔écriture sans réseau — une
divergence de format ne serait attrapée que par le test live opt-in. Un test
unitaire de round-trip de format serait un filet bon marché.

---

## 5. Synthèse — ce que ce croisement durcit côté ColleC

1. **Nos quirks live sont réels et coûteux** — un wrapper indépendant qui ne
   les a pas sondés (NakalaPycon) les subit : #422 langue (2.1), perte de
   fichiers au `PUT` (2.2), doublon de scalaire (2.3), cas limites d'écriture
   (2.4). Chacun valide *a contrario* un garde-fou ColleC existant.
2. **Nos faits de lecture sont recoupés** — codes 200/204, 29 types COAR,
   W3CDTF, dialecte `/search` sans curseur : confirmés indépendamment (§1).
3. **Apports nets archivés (2026-06-25)** — schémas `groups.users[]` et enums
   `Role` (data vs groupe), paramètres `/authors/search`, et surtout la
   **sémantique de dédoublonnage de l'`authorId`** (déterministe + recalcul au
   PUT, §3.4) : **versés** dans savoir-api §4 (note créateur) et §9 (ligne
   hors-périmètre).
4. **Ne pas adopter NakalaPycon** comme dépendance : bugs fonctionnels avérés
   en `0.0.9`, pas de `timeout`, gestion d'erreur fragile (`json.loads` non
   protégé sur corps non-JSON), tests à effets de bord réseau. Notre client
   `external/nakala/` est plus sûr et déjà prouvé idempotent en round-trip
   (savoir-api §16).

## 6. Pistes (si jamais un besoin concret émerge)

Aucune n'est un chantier ouvert — à arbitrer seulement sur besoin réel :

- ✅ **Fait (2026-06-25)** — `authorId` dédup-déterministe versé dans
  savoir-api §4 ; schémas hors-périmètre (`groups.users[]`, enums `Role`,
  `/authors/search`) archivés en savoir-api §9.
- **T4 (push métadonnées granulaire)** : garder NakalaPycon en tête comme
  *implémentation de référence* du couple `POST`/`DELETE …/metadatas` — avec le
  piège doublon-sur-scalaire déjà illustré (cf. §2.3).
- **Auto-revue** : passer la checklist §4 sur `external/nakala/` à chaque
  évolution notable du client.

---

## Référence

- Savoir Nakala validé live (la source de vérité de ce croisement) :
  [`nakala-savoir-api.md`](nakala-savoir-api.md).
- Backlog actionnable (T2 fichiers granulaires, T4 métadonnées granulaires) :
  [`backlog-nakala-api.md`](backlog-nakala-api.md).
- Source confrontée : `nakalapycon/AUDIT.md` (audit ligne par ligne v0.0.9) +
  `nakalapycon/src/*.py`. Hors dépôt ColleC.
