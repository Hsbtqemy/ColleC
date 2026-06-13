# Backlog — Nakala niveau collection (tableur + pull)

> Exclu du build MkDocs (dossier `developpeurs/`). Suivi d'avancement des
> tickets. Voir le cadrage global dans
> [`nakala-depot-future.md`](nakala-depot-future.md).

## Contexte

Né d'un usage réel : extraire vers un tableur toutes les métadonnées de
4 collections Nakala (Armonía Somers, Julio Cortázar, Fernando Aínsa,
José Mora Guarnido), d'abord via un script jetable réutilisant le client
`external/nakala`. On en fait une fonctionnalité de premier ordre, en deux
volets confirmés :

1. **Export tableur** (lecture seule) — collection Nakala → CSV/xlsx, au
   choix niveau **donnée** (1 ligne/donnée) ou **fichier** (1 ligne/fichier,
   métadonnées de la donnée recopiées + colonnes techniques fichier).
2. **Pull collection en base** — collection Nakala → Fonds + miroir + N
   Items (+ Fichiers), en étendant le `rapatrier` unitaire (P1).

### Décisions actées

- La granularité donnée/fichier **ne concerne que le tableur**. Le pull en
  base produit toujours 1 Item portant N Fichiers (granularité native).
- CSV : séparateur `;` par défaut, encodage `utf-8-sig`, `--sep`
  configurable, valeurs multiples jointes ` | `.
- Le listing de collection renvoie déjà les `files` complets → **pas de
  N+1** pour le niveau fichier.
- Aínsa = 6163 données → xlsx en `write_only`, CSV en flux.

## Dépôt UI — phase 1 (réservation des DOI) en tâche de fond ◀ PLAN ACTIF

Compléter l'UI pour que le **dépôt** (création sur Nakala) soit cliquable, pas
seulement CLI. Surface le geste **phase 1** du workflow deux-temps voulu :

1. **Phase 1 — déposer / réserver les DOI** : crée les dépôts Nakala
   (`pending`), Nakala renvoie les identifiants `10.34847/nkl.xxxx`, le service
   les **mappe** sur `Item.doi_nakala` (+ collection sur `Collection.doi_nakala`).
   *Manque uniquement en UI* (déjà en CLI `deposer-collection`).
2. **Phase 2 — pousser les données** (DOI = adresse) : déjà en UI
   (`/nakala/pousser-collection`) + publication. Rien à faire.

### Décisions actées (cette session)

- **Réutiliser `deposer_collection` tel quel** (pas de mode « réserve
  minimale »). Argument décisif : les fichiers ne montent qu'à la **création**
  du dépôt — aucun push de fichiers en phase 2 (c'est le versioning #4, futur).
  Donc phase 1 = upload complet, obligatoirement. La phase 1 est l'étape lourde.
- **DOI = adresse** : on n'inscrit pas les DOI dans les métadonnées (renvois
  croisés) — plus complexe, peu utile ici ; le design laisse la porte ouverte.
- **Exécution en tâche de fond** (1ʳᵉ du projet) + **reprise idempotente**
  (orthogonale, héritée de `deposer` : un item déjà déposé est sauté). L'onglet
  est libre, une page de suivi poll l'avancement ; si la tâche meurt, relancer
  reprend où ça s'était arrêté. Léger : thread in-process + dict en mémoire,
  **aucune nouvelle dépendance**, pas de broker. Sûr grâce à la reprise (aucun
  état critique perdu : `doi_nakala` commité par item, dépôts durables côté Nakala).
- **Aperçu dry-run** avant tout lancement (principe n°3).
- **Bouton** : page fonds, quand la miroir n'a **pas** de `doi_nakala`
  (dichotomie nette avec « Pousser »/« Publier » qui n'apparaissent qu'**après**).

### Tickets

- [x] **D1 — Hook de progression (service)** : `deposer_collection(...,
  progress=None)` callback `(cote, index, total)` appelé par item, **après**
  son traitement quelle que soit l'issue (déposé / sauté / non-déposable /
  erreur). Strictement additif (défaut `None` préserve l'existant). 3 tests
  dans `test_nakala_depot.py` : appels en ordre avec total constant sur 3
  items (1 déposable, 1 non-déposable, 1 erreur preflight) ; 2ᵉ run sur
  collection déjà créée + items déjà déposés → callback fire quand même
  mais tous remontent en `sautes`, aucun appel client ; sans `progress`
  → comportement identique avant D1.
- [x] **D2 — Runner + registre mémoire** : `api/services/nakala_depot_jobs.py`
  avec `EtatJobDepot` dataclass mutable, `_JOBS: dict[str, EtatJobDepot]`,
  `_lock: threading.Lock`, `_id_actuel: str | None` pour la garde
  anti-concurrent. `reserver_job(fonds_cote, collection_cote, total)` →
  réserve atomiquement, lève `JobConcurrent` si un autre tourne.
  `executer_depot_collection(job_id, *, chemin_db, collection_id,
  config_nakala, racines, …)` est la **fonction pure synchrone** — la
  route D3 fera `Thread(target=executer_..., daemon=True).start()` ;
  les tests appellent directement. Gère engine dédié (dispose en fin),
  capture `BaseException` (libère `_id_actuel` même sur `KeyboardInterrupt`
  qui propage). Hook D1 alimente `cote_courante` + `faits` sous lock.
  Finalisation atomique : `statut=termine` + `collection_doi` + listes
  finales d'une seule mutation sous lock. 9 tests :
  - `reserver_job` : uuid hex, garde concurrente lève `JobConcurrent`,
    libération via `_id_actuel = None` (vérification fixture
    `_reset_pour_tests`).
  - `_make_progress` : MAJ `cote_courante` + `faits` ; silencieux si
    registre nettoyé.
  - `executer_depot_collection` : succès marque `termine`+libère
    `_id_actuel` ; collection inconnue → `echec` + erreur_globale +
    libération ; reprise idempotente sur DOI pré-posés (aucun appel
    client, items en `sautes`, callback fire quand même).
  - Smoke test lock : 100 lectures concurrentes pendant un finaliseur,
    aucun snapshot ne voit un état partiellement écrit (statut=termine
    sans collection_doi, ou inverse).
- [x] **D3 — Routes** (`nakala_web.py`) : 4 routes ajoutées en fin de
  fichier, conventions héritées (`_ecriture_configuree`,
  `_resoudre_collection_ou_404`, `_redirect_fonds_erreur`, `_fermer`).
  - `GET /nakala/deposer-collection?cote=X&fonds=Y` : aperçu dry-run
    (`deposer_collection(dry_run=True)` rendu via le template D4
    `nakala_deposer_collection_apercu.html`). Garde défensive : refuse
    si `collection.doi_nakala` posé (utiliser « Pousser » à la place).
  - `POST /nakala/deposer-collection` : `reserver_job` + thread daemon
    `threading.Thread(target=executer_depot_collection, ..., daemon=True)`
    avec `chemin_db=chemin_base_courant()`, `collection_id`,
    `config_nakala=config.nakala`, `racines=dict(racines)`. Sur
    `JobConcurrent` → redirect erreur (pas de 409 JSON — cohérent
    avec le reste du module qui utilise `_redirect_fonds_erreur`).
    Bloqué 423 par middleware lecture seule.
  - `GET /suivi/{job_id}` : page de suivi (`nakala_deposer_suivi.html`),
    redirect erreur si job inexistant.
  - `GET /statut/{job_id}` : fragment HTMX
    (`partials/nakala_deposer_statut.html`), 404 si inexistant.
  Tests (12 dans `test_nakala_web_deposer.py` avec fixture autouse
  `reset_registre` + patch de `executer_depot_collection` en stub
  no-op pour ne pas toucher à Nakala) :
  - apercu 200 + contient AS-001 + form action ;
  - sans api_key → redirect erreur ;
  - DOI déjà posé → redirect refuse ;
  - POST → 303 vers `/suivi/{job_id}` + runner appelé avec les bons
    kwargs (collection_id, cree_par, config_nakala) ;
  - POST garde concurrente : 2e POST quand `_id_actuel` posé →
    redirect erreur sans nouvel appel runner ;
  - POST en lecture seule → 423 + pas de réservation ;
  - POST sans api_key → redirect erreur ;
  - GET suivi avec job réservé → 200 avec wrapper HTMX ;
  - GET suivi job inconnu → redirect vers /nakala ;
  - GET statut avec progression posée → 200 avec `faits/total` +
    `cote_courante` rendus ;
  - GET statut job inconnu → 404 (HTMX gère côté client) ;
  - GET statut quand job=termine → markup sans `every 2s` (le
    polling s'arrête, sinon le browser garderait un cycle infini).
- [ ] **D4 — Templates** : `nakala_deposer_collection_apercu.html` (miroir du
  push : plan + avertissement de durée appuyé + « gros fonds → CLI ») +
  `nakala_deposer_suivi.html` (barre N/total + journal par item + bouton
  **« Reprendre »** si job interrompu + lien fonds à la fin). Bouton « Déposer
  sur Nakala (réserver les DOI) » sur `fonds_lecture.html` (si miroir sans DOI).
- [ ] **D5 — Doc + décision d'archi** : noter dans `CLAUDE.md` (section
  *Décisions d'architecture notables*) l'introduction de la **1ʳᵉ tâche de fond**
  (scope, sûreté par reprise idempotente, pas de broker) ; cocher ce backlog ;
  `nakala-depot-future.md`.
- [ ] **D6 (option) — validation live apitest** : smoke `-m integration` du
  dépôt collection **via la route web** sur un petit lot (réutilise apitest +
  le pattern `test_nakala_web_push_integration.py`), avec cleanup des dépôts
  pending.

### Limites assumées (v1)

- Le bouton ne s'affiche que si la miroir n'a pas de DOI. Déposer des items
  **nouvellement ajoutés** à une collection déjà déposée passe par le CLI
  (`deposer-collection` re-joué, idempotent) — UI de « complément » = futur.
- Progression **en mémoire** : perdue si le serveur redémarre (la reprise
  couvre la donnée, pas la barre). Un seul job à la fois.
- Très gros fonds : viable mais long ; l'aperçu recommande le CLI au-delà d'un
  seuil. Pas d'annulation en cours de route (futur).

## Lot 1 — Export tableur (lecture seule)

- [x] **T1.1** Itérateur `external/nakala/collection.py`
  (`iterer_donnees_collection`) + tests `test_nakala_collection.py` (4).
- [x] **T1.2** Aplatisseur `external/nakala/tableur.py`
  (`lignes_niveau_donnee`, `lignes_niveau_fichier`, `TableurNakala`) +
  tests `test_nakala_tableur.py` (6).
- [x] **T1.3** Écrivains `ecrire_csv` / `ecrire_xlsx` (openpyxl write_only)
  dans `tableur_io.py` + tests `test_nakala_tableur_io.py` (4).
- [x] **T1.4** CLI `nakala exporter-tableur` (granularité, format, sep,
  sortie) + tests `test_cli_nakala_tableur.py` (6). Validé réel sur José
  Mora (65 données → 155 lignes fichier).
- [x] **T1.5** Doc : `CLAUDE.md` + `nakala-depot-future.md` (pas de page
  MkDocs : le CLI nakala n'y figure pas encore — chantier doc à part).

## Lot 2 — Pull collection en base

- [x] **T2.1** Service `rapatrier_collection` (services/nakala.py) + tests
  `test_nakala_pull_collection.py` (6). Crée Fonds + miroir (DOI posé) + N
  Items en bouclant `rapatrier` ; dry-run ; erreurs par donnée collectées ;
  `doi_collection_nakala` posé sur chaque Item.
- [x] **T2.2** CLI `nakala rapatrier-collection` (dry-run par défaut) +
  tests `test_cli_nakala_collection.py` (4).
- [x] **T2.3** `rafraichir-collection` — `archives-tool nakala
  rafraichir-collection <doi> [--no-dry-run]` : re-pull, diff par item lié
  (boucle `rafraichir`), dry-run par défaut. Données sans item ColleC →
  `non_lies` (signalées, pas erreur). Champs documentaires seulement (pas de
  re-sync fichiers, cohérent avec `rafraichir`). 4 service + 2 CLI tests.
- [x] **T2.4** Doc Lot 2 (CLAUDE.md, nakala-depot-future, backlog).

### Matérialisation des fichiers

- [x] **T2.5** **Matérialiser les fichiers Nakala en `Fichier`** —
  `files/nakala.py::construire_source_fichier_nakala` bâtit l'URL depuis
  `(base_url, doi, sha1)` (info.json pour les images, data URL sinon, même
  convention que l'import) ;
  `services/nakala.py::materialiser_fichiers_nakala` crée les `Fichier`
  depuis le JSON brut (clés réelles `name/sha1/size/extension/mime_type`).
  Câblé dans `rapatrier(base_url=...)` → bénéficie au pull collection **et**
  au `rapatrier` unitaire (CLI passe `client.base_url`). `sha1` rangé en
  `metadonnees` (pas dans `hash_sha256` — algo différent). Pas de
  re-matérialisation sur déjà-existant (pas de doublon). +3 tests (image
  info.json, PDF data URL, no-dup) + 2 unitaires builder.
  **Non couvert** : re-sync des fichiers à `rafraichir` (champs
  documentaires seuls) — à voir si besoin.

## Commodités transverses

- [x] **URL → DOI** : `client.normaliser_identifiant_nakala` extrait le DOI
  d'une saisie (URL `nakala.fr/collection/…`, `…/datas/…`, `doi:…`, ou DOI
  nu). Appliqué en tête des 6 commandes `nakala` → on peut coller une URL de
  collection/donnée directement. Best-effort (pas de motif → saisie rendue
  telle quelle, 404 propre). Tests unitaires + câblage CLI.

## P3 — Round-trip métadonnées (livré)

Push des modifications de métadonnées vers un dépôt existant + publication.
Pendant symétrique de `rafraichir` (pull→local). **Sans** versioning fichiers
(choix utilisateur). Réutilise toute la chaîne P2 (mapper 57 champs +
preflight).

- [x] **T1** `write_client.modifier_depot(id, *, metas, status=None)`
  (`PUT /datas/{id}`, remplace les metas ; `status="published"` publie). Tests.
- [x] **T2** `nakala_depot` (suite) : `diff_push` (par propertyUri, multiset
  value/lang, **canonicalise les créateurs** — voir ci-dessous) +
  `pousser_item` (re-pull → diff + dérive, dry-run, PUT + refresh cache) +
  `publier_item` (statut published) + `pousser_collection`. Tests
  (idempotent → diff vide, modif titre, dérive, sans-DOI → erreur).
- [x] **T3** CLI `nakala pousser <cote> --fonds X [--no-dry-run]`,
  `nakala publier …` (irréversible), `nakala pousser-collection …`.
- [x] **T4** `tests/test_nakala_push_integration.py` (`-m integration`) :
  round-trip idempotent (déposer → re-lire → diff vide) + modif titre, **validé
  live sur apitest**. doc (cette section, nakala-depot-future, CLAUDE.md).

**Découverte du test d'intégration (fidélité #3)** : Nakala **enrichit les
créateurs** au stockage (`{givenname, surname}` → `{authorId, fullName,
givenname, orcid: null, surname}`). Sans correctif, chaque push aurait vu un
faux changement de créateur. `diff_push` canonicalise donc les créateurs sur
les seuls champs identifiants (`surname`/`givenname`/`orcid` non nul).

**Métadonnées de collection (livré, complément P3)** :
`write_client.modifier_collection` (`PUT /collections/{id}` → 204) +
`nakala_depot.pousser_metadonnees_collection` (réutilise `diff_push` ; **pas
de dérive** — collections Nakala sans `modDate`). `pousser-collection` pousse
désormais **l'entité collection puis ses items**. Round-trip validé live.

**Fusion, pas remplacement** : ColleC ne modélise que **titre + description**
d'une collection (`_PROPRIETES_COLLECTION_GEREES`), et `PUT` remplace tout →
on **fusionne** (préserve les metas Nakala hors champs gérés — sujet/créateur
d'une collection créée hors ColleC — et ne remplace que titre+description).
Sans ça, un push effacerait ces metas non modélisées.

Sondage apitest : `typeUri` remis à `null` au stockage (sans impact,
`diff_push` l'ignore). Nuances : ColleC possède titre+description (description
vide en local → effacée sur Nakala) ; pas de langue de titre de collection
(`lang=None`). Le dry-run montre tout avant écrasement.

**Hors scope → futur** : versioning fichiers (#4, SHA-1↔SHA-256).

## UI web de push (livré)

Surfaçage du push/publication P3 dans l'UI web, en parité avec le pull du
Lot 3 (`/nakala`, bouton « Rafraîchir »). Même schéma : **aperçu dry-run en
GET** (lecture seule OK) → **confirmation POST** (bloquée 423 en lecture
seule). Les aperçus de publication sont **rouges** (irréversible).

- [x] **U1** `nakala_depot.publier_collection` (boucle `publier_item` :
  `publies` / `non_lies` / `erreurs`) + CLI `nakala publier-collection <cote>
  [--fonds] [--no-dry-run]`. Tests service + CLI.
- [x] **U2** routes push **item** (`nakala_web.py`) : `_client_ecriture_ou_none`
  (None si `api_key` absent) ; `GET/POST /nakala/pousser` (aperçu diff +
  dérive → PUT) ; `GET/POST /nakala/publier` (aperçu rouge irréversible).
- [x] **U3** routes push **collection** : `GET/POST /nakala/pousser-collection`
  (diff entité + récap items) ; `GET/POST /nakala/publier-collection`. Le
  redirect de retour pointe sur le **fonds** (`fonds or cote`) — la cote de la
  miroir peut différer de celle du fonds.
- [x] **U4** points d'entrée + 4 templates d'aperçu :
  - `item_fiche.html` : si `item.doi_nakala` → « Pousser vers Nakala » +
    « Publier » (rouge) ; flash `nakala_pousse` / `nakala_publie` /
    `nakala_erreur`.
  - `fonds_lecture.html` : à côté de « Rafraîchir », si `doi_nakala_miroir`
    → « Pousser vers Nakala » + « Publier la collection »
    (`detail.miroir_resume.cote`) ; flash `nakala_pousse_items` /
    `nakala_publie_items` / `nakala_erreur`.
  - aperçus `nakala_pousser_apercu` / `nakala_publier_apercu` /
    `nakala_pousser_collection_apercu` / `nakala_publier_collection_apercu`,
    confirmation masquée en lecture seule + mini-script « En cours… ».
- [x] **U5** `tests/test_nakala_web_push.py` (18 tests, clients lecture+
  écriture mockés) : aperçu diff, POST → PUT, publication → `status=
  published`, push/publication collection, **POST bloqué 423 en lecture
  seule**, sans `doi`/`api_key` → message, boutons présents/absents. doc.
- [x] **U6 — validation live + fix #422** (`tests/test_nakala_web_push_integration.py`,
  `-m integration`) : pilote les vraies routes `/nakala/pousser` et
  `/nakala/publier` via `TestClient` + **vrais clients** sur apitest (dépôt →
  modif titre → push → vérif distant ; publication derrière
  `NAKALA_ALLOW_PUBLISH=1`). **Bug découvert** : langue stockée en ISO 639-3
  (`spa`) émise telle quelle alors que Nakala type `dcterms:language` en
  RFC5646 (`es`) → dépôt/push **rejeté 422** (latent : aucun test n'avait
  déposé de langue). **Fix** : `mapper.langue_vers_nakala` convertit la valeur
  `dcterms:language` + l'attribut `lang` des littéraux, dans `item_vers_slugs`.
  Reliquat : `exporters/nakala.py` (CSV bulk) émet aussi la langue brute —
  même bug, chemin séparé, à traiter après validation du format bulk.

**Hors scope → futur** : versioning fichiers (#4, SHA-1↔SHA-256) ; fix langue
de l'export CSV bulk.

## P2 — Dépôt (écriture) vers Nakala (livré)

Premier chemin d'**écriture** : créer la collection Nakala + y déposer ses
items. Moteur porté de `plugins-madbot/madbot_nakala_submission` (couplage
madbot retiré). Statut `pending`/`private` + dry-run par défaut (réversible).

- [x] **A1** `external/nakala/write_client.py` — `NakalaEcritureClient`
  (uploader_fichier, creer_depot, creer_collection, rattacher_a_collection,
  supprimer_depot/upload/collection) + `extraire_doi`. Clé API obligatoire.
  13 tests (httpx mocké).
- [x] **A2** `external/nakala/depot_mapper.py` — `SLUG_TO_NAKALA` (57 champs)
  + `slugs_vers_metas` + parse_creator/created + DCSV spatial/temporal +
  sentinels. `MetaInvalide` (local). 12 tests.
- [x] **A3** `external/nakala/preflight.py` — `preflight_appliquer` (cascade
  créateur/date, promotion `dcterms:*`→`nkl:*`). 6 tests.
- [x] **A4** `api/services/nakala_depot.py` — `item_vers_slugs` (réutilise
  le savoir de `exporters/nakala.py`) + `deposer_item` (résout fichiers
  locaux via `files/paths.resoudre_chemin`, dry-run, cleanup orphelins,
  garde déjà-déposé / sans-fichier). 9 tests.
- [x] **A5** CLI `archives-tool nakala deposer <cote> --fonds X [--statut]
  [--collection DOI] [--no-dry-run]`.
- [x] **B1+B2** `creer_collection` + `deposer_collection` (POST /collections
  → pose `Collection.doi_nakala`, boucle `deposer_item` ; erreurs/non-
  déposables/sautés collectés).
- [x] **B3** CLI `archives-tool nakala deposer-collection <cote> --fonds X
  [--statut-donnee] [--statut-collection] [--no-dry-run]`.
- [x] **C1** `tests/test_nakala_depot_integration.py` (`-m integration`,
  opt-in, clé publique apitest) : round-trip réel upload+depot+collection+
  lecture+cleanup. Marqueur `integration` déclaré (pyproject, exclu par
  défaut).
- [x] **C2** doc (cette section, `nakala-depot-future.md`, `CLAUDE.md`).

**Hors P2 → P3** : publication (`published` + DOI DataCite), round-trip
`PUT /datas/{id}` + versioning fichiers (conflit/fraîcheur), UI web de dépôt.
**Limite** : seuls les Items avec fichiers **locaux** sont déposables
(Nakala-only non re-déposable). `dcterms:*` extras coercés best-effort.

## Lot 3 — UI web (livré)

Page autonome `/nakala` (lien header) + bouton « Rafraîchir depuis Nakala »
sur les fonds dont la miroir porte un DOI. Router
`api/routes/nakala_web.py`. Pull/rafraîchir **synchrones** avec aperçu
dry-run (GET, lecture seule OK) + confirmation POST (bloquée 423 en lecture
seule par le middleware) + bouton qui se désactive au submit (« en cours… »,
couvre le blocage). Pas d'infra async (principe n°6). DOI ou URL accepté.

- [x] **T3.0** Router + `GET /nakala` (`pages/nakala.html`, 3 formulaires) ;
  message si `nakala:` non configuré.
- [x] **T3.1** `GET /nakala/tableur` → téléchargement CSV/xlsx (variantes
  mémoire `tableur_io.{vers_csv_bytes,vers_xlsx_bytes}` + MIME). GET =
  autorisé en lecture seule.
- [x] **T3.2** `GET /nakala/rapatrier` (aperçu dry-run) +
  `POST /nakala/rapatrier` (exécution → redirect `/fonds/<cote>` + flash).
- [x] **T3.3** `GET/POST /nakala/rafraichir` (aperçu + exécution) + bouton
  « Rafraîchir depuis Nakala » sur `fonds_lecture.html`
  (`FondsDetail.doi_nakala_miroir` ajouté au composer).
- [x] **T3.4** Lien header, spinner submit, doc. Tests `test_nakala_web.py`
  (11). Validé live sur José Mora (export 65 lignes, pull 65 items/155
  fichiers, bouton + flash sur le fonds, aperçu rafraîchir « inchangés »).
