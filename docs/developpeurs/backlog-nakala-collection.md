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
