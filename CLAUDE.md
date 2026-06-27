# CLAUDE.md

Ce fichier fournit le contexte du projet à Claude Code. Il est lu
automatiquement à chaque session. Tenir à jour au fil des décisions
structurantes.

---

## Vue d'ensemble du projet

**Nom provisoire :** archives-tool (à renommer)

**Objet :** outil interne de gestion de collections numérisées **tous
types de documents** — textes, périodiques, manuscrits, correspondance,
images, photographies, cartes, partitions, son, vidéo, œuvres, données,
etc. (le modèle Fonds/Collection/Item/Fichier est générique, rien n'y
restreint le type). Les périodiques (cas de test Por Favor) ne sont
qu'un exemple parmi d'autres, pas le cœur de cible. Pas un outil de
valorisation publique : l'usage est la constitution, le suivi, la
correction et le contrôle de catalogues d'archives scannées.

**Utilisateurs :** quelques personnes, édition jamais simultanée sur un
même item, consultation possible à plusieurs.

**Statut :** **V0.10.0 livré** (~1900 tests verts + tests d'intégration
opt-in, doc déployée sur <https://hsbtqemy.github.io/ColleC/>).
**Post-V0.10.0 sur `main`** : Chantier 1 **ingestion ShareDocs (WebDAV)**
complet (client + service + CLI + UI parcours/import) et **validation de
licence Nakala au pré-export (S6)** — cf. *Plan de développement* et
`docs/developpeurs/roadmap.md`. Modèle
pivoté Fonds / Collection / Item, CLI complète, interface web complète
(écriture Nakala complète — dépôt + round-trip métadonnées +
publication, CLI et UI — depuis V0.10.0 ; synthèse collection + fonds
avec cartographie cross-collection +
édition inline complète bandeau et identifiants depuis V0.9.6 ;
workflow champs personnalisés + vocabulaires UI bouclé bout-en-bout
depuis V0.9.4 ; recherche FTS5 depuis V0.9.3 ; restauration
ergonomique 4 pages détail depuis V0.9.2 ; renforcement mode local
WAL + verrou optimiste + lecture seule depuis V0.9.1), documentation
utilisateur + référence + développeurs. Mode actuel : local
mono-utilisateur. La V1.0 ajoutera le déploiement VPS et l'auth
multi-utilisateurs simples — voir la section *Roadmap* plus bas et
le document interne
[`docs/developpeurs/deploiement-future.md`](docs/developpeurs/deploiement-future.md)
pour les décisions d'infrastructure.

D'autres décisions structurantes pour la suite du projet sont
préservées sous `docs/developpeurs/` (toutes exclues du build
MkDocs, accessibles aux contributeurs et à Claude Code) :

- [`portail-public-future.md`](docs/developpeurs/portail-public-future.md)
  — évaluation eXist-db / TEI, stack recommandée pour le futur
  portail public consommateur (FastAPI + Meilisearch + IIIF).
- [`annotations-image-future.md`](docs/developpeurs/annotations-image-future.md)
  — module d'annotation d'image (W3C Web Annotations +
  Annotorious sur l'OpenSeadragon existant), sketch technique et
  roadmap V1.x/V2.
- [`workflow-numerisation.md`](docs/developpeurs/workflow-numerisation.md)
  — articulation amont avec scanners, ScanTailor, Tesseract ; les
  trois racines `masters` / `derives_travail` / `vignettes` ; les
  deux scénarios d'entrée dans ColleC.
- [`plan-de-chantier.md`](docs/developpeurs/plan-de-chantier.md)
  — usage de ColleC pour la planification catalographique en
  amont de la numérisation ; manques UX identifiés (création en
  série, onglet Avancement).
- [`sites-statiques-future.md`](docs/developpeurs/sites-statiques-future.md)
  — exporter site statique (Quarto en phase 1, Hugo en phase 3),
  pivot Markdown neutre vis-à-vis du SSG, multi-appartenance par
  duplication, trois modes images. Inspirations OPUS /
  publication-efe et nakala-quarto-view.
- [`notebooks-sdk-future.md`](docs/developpeurs/notebooks-sdk-future.md)
  — usage de ColleC depuis Jupyter / scripts Python. Pas un SDK
  à construire, l'API publique est déjà là (services métier +
  exporters + modèles ORM en lecture). Livrable principal : une
  page guide avec recettes concrètes.
- [`zotero-future.md`](docs/developpeurs/zotero-future.md)
  — intégration Zotero (export BibTeX/RIS en V2/V3, import
  différé sur demande). Mapping centralisé, pas de sync
  bidirectionnel.
- [`nakala-savoir-api.md`](docs/developpeurs/nakala-savoir-api.md)
  — **référence du comportement réel de l'API Nakala** : endpoints,
  payloads, quirks et bugs validés en live contre `apitest.nakala.fr`
  (sondes H1-H11 de `scripts/explorer_put_files_nakala.py` + tests
  d'intégration). Le « comment l'API se comporte vraiment », par
  opposition au « pourquoi » (`nakala-depot-future.md`) et au
  « comment s'en servir » (`docs/guide/cli/nakala.md`). Consolide le
  savoir auparavant éparpillé (bug langue #422, canonicalisation des
  créateurs, `PUT files[]` = remplacement total, etc.).
- [`backlog-nakala-api.md`](docs/developpeurs/backlog-nakala-api.md)
  — **backlog exécutable** issu du sondage live de l'API : 3 tickets
  spécifiés (T1 clarifier obligation créateur/date = règle ColleC ≠
  Nakala ; T2 push fichiers granulaire `POST/DELETE …/files` au lieu du
  `PUT files[]` remplaçant ; T3 surfacer `payload.validationErrors`) +
  opportunités secondaires. **T1, T2, T3 livrés** ; **S1** (parité vocab,
  test offline + intégration live), **S2** (lien collection), **S3**
  (réconciliation `collectionsIds` au pull), **S4** (citation : client +
  CLI `nakala citer` + fiche web HTMX) livrés ; **S5** (endpoint
  `status/{status}`) sondé → décision : garder `publier_item` (re-push
  metas, aligné principe n°1). **Versioning fichiers (#4) caractérisé en
  live** : Nakala versionne automatiquement (mutation de fichiers sur dépôt
  publié = +1 `.vN` ; metas en place ; versions = snapshot des fichiers) →
  pas de chantier ColleC. **Sonde V1 résolue (live apitest 2026-06-20)** :
  le `type` de relation est un vocabulaire **fermé, strict, sensible à la
  casse** (type inconnu → 422 listant les 38 types DataCite ; `ispartof`
  rejeté, `IsPartOf` accepté) ; dédup par cible qui court-circuite la
  validation ; `DELETE …/relations` purge tout. Script
  `scripts/explorer_relations_type_nakala.py` (auto-restaurant).
  **Audit de parité apitest ↔ production — Volets A + B livrés (2026-06-20,
  clé d'un vrai compte Huma-Num).** **Volet A** (lecture,
  `scripts/audit_parite_prod_nakala.py`, GET only) : parité totale du contrat
  d'API (forme `GET /datas` 21 clés + champs modération, vocabulaires licenses
  620/datatypes 29/languages 10, erreurs 404, versions, IIIF, OAI `/oai2`).
  **Volet B** (écriture, via les vrais services ColleC sur ressources
  `pending`/`private` jamais publiées puis supprimées → zéro résidu vérifié) :
  `audit_parite_prod_volet_b.py` (donnée/item) — dépôt + **enrichissement
  créateur** (#2) + **langue spa→es** (#422) + **round-trip `PUT` idempotent**
  (0 diff — risque des faux diffs sur prod levé) + **fichiers granulaires** +
  description par fichier (H11) + embargo ; et
  `audit_parite_prod_volet_b_collection.py` (collection) —
  `deposer_collection` + **`pousser_metadonnees_collection` round-trip
  idempotent** (fusion préservant les metas non modélisées) + `DELETE`. Plus
  `verifier_parite_vocabulaires_nakala.py` contre prod : 29 types + 57 props
  émis ⊆ live (29/60). Tout à l'identique. Seules divergences, **attendues** :
  citation réelle sur prod (200 + DOI DataCite, vs 403 apitest → S4 validé
  prod) et rôles du compte. **Constat opérationnel** : prod transitoirement
  instable (TLS timeouts, un 500 transitoire sur `PUT /collections` non
  reproduit, cohérence éventuelle au DELETE) → prévoir retry 5xx + vérif des
  suppressions par relecture pour les opérations massives. **Hors scope**
  (irréversible, présumé par identité logicielle) : publication réelle,
  relations donnée↔donnée, versioning `.vN` sur prod. Cf.
  `backlog-nakala-api.md` § *Audit de parité*.
- [`nakala-depot-future.md`](docs/developpeurs/nakala-depot-future.md)
  — **dépôt + round-trip Nakala** (ColleC possède le chemin
  lecture/écriture, sans couplage madbot). Architecture pull /
  create / update (`PUT /datas/{id}` + versioning), 4 difficultés
  (conflit, publié/pending, fidélité, identité fichiers), inventaire
  COAR (9/15 types hors set Nakala — corrigé V0.9.10), assets de
  portage depuis `plugins-madbot`. **Tier A + A bis livrés** :
  vocabulaires vendorisés, résolution langue, vocabulaire COAR corrigé
  + projection interne→Nakala + migration de remap. Décision actée :
  deux vocabulaires (interne riche + projection export). **P1a+P1b
  livrés** : `external/nakala/` (client lecture httpx + mapper
  dépôt→`DepotNakala`, config `nakala:`) ; `api/services/nakala.py`
  (cache `RessourceExterne` par DOI + réconciliation `Item.doi_nakala`
  via `LienExterneItem`). P1a = lecture pure (aucune écriture DB) ;
  P1b écrit dans les tables externes (cache + liens) mais ne crée ni
  ne mute aucun Item — il ne fait que le lier. **P1 livré (V0.9.11)** :
  `rapatrier` (crée un Item depuis un dépôt, cache + lien, garde
  déjà-existant, dry-run) + `rafraichir` (re-pull → diff documentaire +
  dry-run par défaut avant overwrite, champs ColleC-only préservés) ;
  CLI `archives-tool nakala {montrer,rapatrier,rafraichir}`. 46 tests.
  **P1.5 — niveau collection (en cours)** : `external/nakala/collection.py`
  (itérateur paginé ; le listing renvoie déjà les `files` complets → pas
  de N+1) + `tableur.py` (aplatisseur pur exhaustif, valeurs multiples
  jointes) + `tableur_io.py` (CSV `utf-8-sig` sép. `;` / xlsx openpyxl
  `write_only`). **P1.5a livré** : `archives-tool nakala exporter-tableur
  <doi_collection> --granularite donnee|fichier --format csv|xlsx`
  (lecture seule, niveau fichier = métadonnées donnée + colonnes techniques
  nom/sha1/mime/taille/embargo). **P1.5b livré** : `archives-tool nakala
  rapatrier-collection <doi> [--fonds COTE] [--no-dry-run]` crée Fonds +
  miroir (DOI posé) + N Items en bouclant `rapatrier` (dry-run par défaut,
  erreurs par donnée collectées). **T2.5 livré** : `rapatrier(base_url=...)`
  matérialise les fichiers Nakala en `Fichier` (`iiif_url_nakala` info.json
  pour images / data URL sinon, `sha1` en `metadonnees`) → items navigables
  dans la visionneuse ; bénéficie au pull collection ET au `rapatrier`
  unitaire (CLI passe `client.base_url`). **P1.5c livré** :
  `archives-tool nakala rafraichir-collection <doi> [--no-dry-run]`
  (re-pull → diff par item lié en bouclant `rafraichir`, dry-run par défaut,
  données non rapatriées signalées, pas de re-sync fichiers). Backlog
  détaillé :
  [`backlog-nakala-collection.md`](docs/developpeurs/backlog-nakala-collection.md).
  **UI web livrée** : page autonome `/nakala` (`api/routes/nakala_web.py`,
  lien header) — export tableur (téléchargement CSV/xlsx), aperçu+rapatriement,
  aperçu+rafraîchissement ; bouton « Rafraîchir depuis Nakala » sur les fonds
  dont la miroir a un DOI. Pull/rafraîchir synchrones (aperçu dry-run GET +
  confirmation POST bloquée en lecture seule) ; DOI ou URL accepté.
  **P2 livré (écriture)** : `external/nakala/write_client.py`
  (`NakalaEcritureClient`) + `depot_mapper.py` (port `SLUG_TO_NAKALA`
  57 champs) + `preflight.py` (cascade créateur/date) +
  `api/services/nakala_depot.py` (`deposer_item`/`deposer_collection` :
  fichiers locaux, statut `pending`/`private`, dry-run par défaut, garde
  déjà-déposé, cleanup orphelins). CLI `archives-tool nakala deposer` +
  `deposer-collection`. Moteur porté de
  `plugins-madbot/madbot_nakala_submission` (couplage retiré).
  **P3 livré (round-trip métadonnées)** : `write_client.modifier_depot`
  (`PUT /datas/{id}`, remplace les metas) + `nakala_depot` : `diff_push`
  (par propertyUri, ordre-insensible, **canonicalise les créateurs** — Nakala
  ajoute `authorId`/`fullName`/`orcid:null` au stockage), `pousser_item`/
  `pousser_collection` (re-pull → diff + dérive, dry-run, PUT + refresh cache),
  `publier_item` (`status=published`, irréversible). CLI `nakala pousser` +
  `publier` + `pousser-collection`. Round-trip idempotent validé live (apitest).
  **P3.5 livré (métadonnées de collection)** : `write_client.modifier_collection`
  (`PUT /collections/{id}` → 204) + `nakala_depot.pousser_metadonnees_collection`
  (réutilise `diff_push` ; pas de dérive — collections sans `modDate` ;
  **fusion** : ColleC ne gère que titre+description → préserve les metas Nakala
  non modélisées au lieu de les écraser) ; `pousser-collection` pousse l'entité
  collection **puis** ses items. Round-trip collection validé live. Tests
  d'intégration opt-in (`-m integration`).
  **UI web de push livrée** : surfaçage du push/publication dans l'UI
  (`nakala_web.py`), parité avec le pull du Lot 3. `_client_ecriture_ou_none`
  et 8 routes `GET/POST /nakala/{pousser,publier,pousser-collection,publier-collection}`
  (aperçu dry-run GET → confirmation POST bloquée 423 en lecture seule ;
  aperçus de publication rouges/irréversibles). `nakala_depot.publier_collection`
  (boucle `publier_item`) + CLI `nakala publier-collection`. Boutons sur la
  fiche item (si `doi_nakala`) et la page fonds (si `doi_nakala_miroir`, via
  `miroir_resume.cote`) ; flash en query string. Le redirect de retour des
  routes collection pointe sur le **fonds** (`fonds or cote` — la cote de la
  miroir peut différer de celle du fonds). 18 tests web (clients mockés).
  **Validation live UI sur apitest (smoke bout-en-bout)** :
  `tests/test_nakala_web_push_integration.py` pilote les vraies routes
  `/nakala/pousser` et `/nakala/publier` via `TestClient` + vrais clients
  (dépôt → modif titre → push → vérif distant ; publication gardée derrière
  `NAKALA_ALLOW_PUBLISH=1` car irréversible). **Bug #422 découvert + corrigé** :
  ColleC stocke les langues en ISO 639-3 (`spa`) mais Nakala type
  `dcterms:language` en RFC5646 (vocab = 639-1 `es`) — le dépôt/push d'un Item
  avec langue était rejeté (latent : aucun test d'intégration ne déposait de
  langue). `mapper.langue_vers_nakala` (inverse de `langue_vers_iso639_3`)
  convertit la **valeur** `dcterms:language` ET l'attribut `lang` des littéraux
  multilingues, appelé dans `item_vers_slugs`. **Reliquat depuis résolu** :
  `exporters/nakala.py` (CSV bulk, chemin séparé/upload manuel) convertit lui
  aussi la langue via `langue_vers_nakala` (valeur `dcterms:language` +
  `langTitle`) — même correction appliquée sur les deux chemins.
  **UI web de dépôt collection livrée** (backlog dépôt UI D1-D6) :
  bouton « Déposer sur Nakala » sur
  `fonds_lecture.html` (si miroir sans DOI, hors lecture seule), 4 routes
  `/nakala/deposer-collection` (GET aperçu / POST lance / GET suivi / GET
  statut) — le POST réserve un job, démarre un `threading.Thread` daemon
  et redirige vers la page de suivi qui polle le statut toutes les 2s
  (`hx-trigger`, arrêt auto en fin de job). Bouton « Reprendre » sur
  statut `echec` (relance le POST normal). Première **tâche de fond** du
  projet — runner mémoire + reprise idempotente (DOI persistés au fil
  de l'eau via `db.commit()` après chaque dépôt item, relance saute les
  items déjà créés), pas de broker. Décision et conditions de remise en
  cause documentées dans la section *Décisions d'architecture notables*
  ci-dessous. Avertissements de durée tiérisés dans l'aperçu (≥10 /
  ≥50 / ≥200 items) avec commande CLI pré-remplie pour les très gros
  fonds.
  **P3+a livré (fondations versioning fichiers)** : colonne dédiée
  `Fichier.sha1_nakala` (String(40), indexée) + migration
  `s7w8x9y0z1a2` (backfill idempotent depuis `metadonnees["sha1"]` pour
  les fichiers déjà matérialisés via `rapatrier`). Capture du sha1 au
  retour d'`uploader_fichier` dans `deposer_item` (persisté avec
  `doi_nakala`) et au pull dans `materialiser_fichiers_nakala` (colonne
  + compat retro `metadonnees["sha1"]`). **Distinct de `hash_sha256`**
  (SHA-256 intégrité disque, algos différents).
  **P3+b livré (détection lecture seule)** : `api/services/nakala_fichiers.py
  ::comparer_fichiers_item` classe les fichiers d'un item vs le dépôt
  distant en 5 catégories — `nouveaux`, `modifies`, `inchanges`,
  `nakala_only_sans_local`, `orphelins_distants`. Réconciliation
  prioritaire par SHA-1 recalculé on the fly (`hashlib` streaming),
  fallback sur `sha1_nakala` connu pour détecter une modification. CLI
  `archives-tool nakala comparer-fichiers <cote> --fonds X
  [--format text|json]`. Aucune écriture base ni distante. **Smoke
  live opt-in apitest** : `test_nakala_fichiers_integration.py` valide
  le cycle complet a+b (dépôt → comparer inchangé → modif binaire local
  → comparer modifié → cleanup) en 8.10s. **Reste futur** : P3+c push
  effectif (`PUT /datas/{id}` avec garde-fous orphelins/Nakala-only) +
  P3+d UI bouton fiche item.
- [`idees-ui-vrac.md`](docs/developpeurs/idees-ui-vrac.md)
  — réserve d'idées UX non formalisées (étiquettes colorées,
  command palette, édition inline étendue, historique navigable,
  etc.). À puiser au gré des opportunités, pas un engagement.
- [`ocr-module-future.md`](docs/developpeurs/ocr-module-future.md)
  — module OCR + indexation textuelle. ALTO format pivot, ABBYY
  FineReader pour le natif, pdfalto pour les corpus PDF externes
  (cas Por Favor Nakala). Stratégie progressive Phase A/B/C
  (baseline / audit confiance / re-OCR ciblée). Couplage explicite
  avec module annotations (pré-segmentation depuis `<Illustration>`
  ALTO, complémentarité sur BDs). Roadmap V1.x/V2 grâce à pdfalto
  qui évite le re-OCR massif.
- [`contribution-fichiers-structures-future.md`](docs/developpeurs/contribution-fichiers-structures-future.md)
  — troisième mode de contribution externe via fichiers XML/TEI
  structurés (Oxygen, VSCode, git), en complément de l'UI web et
  de l'API Python. Round-trip des exporters, `id_persistant`
  comme pré-requis, workflow git optionnel. Pour TEI : option
  par défaut **stay-in-stack** (TEI dans ColleC + CETEIcean ou
  static generation, aucun moteur XML séparé), pattern hybride
  avec eXist+TEI Publisher / BaseX+MaX / EVT uniquement si
  l'usage TEI le justifie réellement. Décision agnostique.
- [`vocabulaire-scoping-future.md`](docs/developpeurs/vocabulaire-scoping-future.md)
  — rattachement many-to-many **vocabulaire ↔ fonds** pour
  filtrer l'autocomplete d'annotations selon le fonds courant.
  Défaut global (vocab non rattaché = visible partout). **T1+T2+T3
  livrés** : table `vocabulaire_fonds`, services attacher/détacher,
  autocomplete `?fichier_id=<id>` filtré, wiring JS, UI
  rattachement (cases à cocher sur `/vocabulaires/<id>` + badges
  « global » / « N fonds » sur la liste). **T4** (enrichissement
  rétroactif `TextualBody.value` → `SpecificResource source=URI`)
  reste ouvert — attendre un cas concret de réattribution avant.

---

## Positionnement de l'outil

Cet outil est un **espace de travail** pour des chantiers de
constitution et d'enrichissement de collections numériques. Il n'est
pas un catalogue bibliothéconomique figé qui attendrait des données
déjà propres.

Conséquences structurantes :

- La création, la restructuration et le nettoyage sont des
  opérations de premier ordre, pas des cas marginaux.
- Les structures de métadonnées (champs personnalisés, vocabulaires)
  évoluent en cours de route. Ajouter, renommer, scinder, fusionner
  un champ doit être possible nativement depuis l'interface.
- Plusieurs personnes peuvent se passer le relais sur la vie longue
  d'une collection. L'outil doit capitaliser la connaissance tacite
  (descriptions internes sur les entités, traçabilité des
  opérations, journal auto-généré consultable).
- L'export vers des formats canoniques (Dublin Core, COAR, Nakala)
  est un aboutissement vérifiable : il permet de sortir le travail
  pour relecture externe, archivage, publication.
- L'import depuis des tableurs existants est un point d'entrée
  utile (amorçage, rapatriement de travail fait ailleurs), mais pas
  la voie royale.

---

## Principes directeurs

Ces principes doivent guider toutes les décisions de conception et de
code. Si une demande les contredit, signaler avant d'exécuter.

1. **La base locale est la source de vérité pendant le travail.** Les
   tableurs Excel et les arborescences de fichiers sont des
   formats d'entrée (import) et de sortie (export), pas la vérité
   courante.

2. **Les données doivent pouvoir sortir de l'outil à tout moment.**
   Exports CSV/Excel et JSON/XML (Dublin Core) sont des fonctions de
   premier ordre. L'utilisateur ne doit jamais se sentir prisonnier.

3. **Ne jamais modifier un fichier utilisateur sans aperçu préalable.**
   Tout renommage, déplacement, écrasement passe par un mode
   « simulation » affichant le diff avant exécution.

4. **Journaliser toutes les opérations destructives.** Renommage,
   déplacement, suppression : table `OperationFichier` avec batch_id
   permettant l'annulation d'un lot.

5. **Portabilité Windows + macOS.** Jamais de chemin absolu stocké en
   base. Jamais de concaténation de chemin par chaîne. Toujours
   `pathlib.Path`. Normalisation Unicode NFC systématique pour les noms
   de fichiers.

6. **La complexité s'ajoute, ne se présume pas.** V1 minimale et
   utilisable avant toute extension. Pas de sur-ingénierie.

7. **Tests d'abord sur les zones à risque.** Importers, renamer,
   rapprochement fichiers / base : tests écrits avant implémentation.

8. **Autonomie des items.** Chaque item stocke ses métadonnées de
   manière complète et autonome. Même si certains champs (responsable
   scientifique, éditeur, auteur de la notice) ont la même valeur pour
   tous les items d'une collection, cette valeur est stockée sur chaque
   item, sans factorisation ni résolution dynamique.

   Justifications :
   - Traçabilité : chaque notice est auto-suffisante, lisible et
     exportable sans contexte.
   - Évolution : un item peut diverger d'un défaut collection sans
     casser la structure.
   - Export propre : les exports Dublin Core et Nakala reflètent ce
     qui est en base.

   Conséquence sur les profils d'import : une clé
   `valeurs_par_defaut` sera prévue pour la commodité de saisie, mais
   elle écrit les valeurs sur chaque item individuellement.

9. **La structure s'adapte au chantier.** Les champs personnalisés
   et les vocabulaires contrôlés ne sont pas figés dans le code. Ils
   se créent, se renomment, se déprécient au fil du travail, via
   l'interface et via des opérations tracées.

---

## Stack technique

**Langage :** Python 3.11+

**Backend :**
- FastAPI (API + rendu serveur via Jinja2)
- SQLAlchemy 2.x (ORM)
- Alembic (migrations, dès la V1)
- SQLite (base locale, mode WAL activé)
- Pydantic 2.x (validation, schemas)
- Typer (CLI)
- Rich (affichage tableaux, panneaux, arbres, syntaxe colorée pour
  les commandes `archives-tool montrer ...`)

**Frontend :**
- Jinja2 + HTMX 1.9.10 pour les interactions partielles. Inclus
  dans `base.html` (chargé sur toutes les pages).
- Tailwind CSS compilé via la CLI npm (pas de CDN). `output.css` est
  gitignoré.
- SortableJS 1.15.2 pour les réordonnancements (drag & drop colonnes
  du tableau d'items, vignettes en V2+). Chargé à la demande sur la
  page collection.
- OpenSeadragon pour la visionneuse d'images de la page Item. Chargé
  sur la page item uniquement. Mode `tileSources: { type: "image",
  url }` pour les aperçus JPEG locaux ; mode IIIF (URL `info.json`)
  quand le fichier a un DOI Nakala publié. Fallback `open-failed` →
  source secondaire puis message + lien télécharger.

Les 3 vendors (HTMX, SortableJS, OpenSeadragon) sont installés via
`npm install` (déclarés en `dependencies` du `package.json`) puis
copiés sous `web/static/js/vendor/{htmx,sortable,openseadragon}/`
par `npm run vendor` (script `scripts/vendor.mjs`, cross-platform).
Le dossier `vendor/` est gitignoré pour ne pas embarquer le code
tiers dans le dépôt — relancer `npm run vendor` après un clone
frais.

**Traitement fichiers :**
- Pillow pour les dérivés simples
- pyvips (via bindings) pour le traitement TIFF lourd si disponible
- PyMuPDF si des PDF sont à manipuler

**Intégrations externes (V2+) :**
- httpx pour les appels API (Nakala, autres entrepôts)
- Support IIIF pour affichage d'images externes

**Outils de développement :**
- uv pour la gestion d'environnement et dépendances
- pytest pour les tests
- ruff pour lint + format
- MkDocs Material pour la documentation (déploiement GitHub Pages
  via `.github/workflows/docs.yml`, build `mkdocs build --strict`
  exigé). Sources sous `docs/`, config racine `mkdocs.yml`. Voir
  [docs/index.md](docs/index.md) et la section « Documentation »
  ci-dessous.

---

## Architecture générale

### Modèle conceptuel

```
Collection (une revue, un fonds)
  └── Item (un numéro, un volume, une unité catalographique)
        └── Fichier (un scan, une page)
```

Une **Collection** porte des métadonnées communes (titre, éditeur,
périodicité, cote de collection) qui peuvent être héritées par ses items.

Un **Item** est l'unité principale de catalogage : une notice complète
avec ses métadonnées Dublin Core étendues.

Un **Fichier** est un scan rattaché à un item, avec un ordre, un type de
page (couverture, page, planche...), un folio.

### Profils d'import

Les profils d'import YAML (format **v2** depuis V0.9.0-gamma.1) sont
chargés et validés dans `src/archives_tool/profils/` (schéma Pydantic +
loader). Le format v2 sépare deux concepts qui étaient confondus en v1 :

- Section **`fonds:`** (obligatoire) : métadonnées du corpus brut
  (cote, titre, éditeur, périodicité, ISSN, dates, descriptions…).
  Le fonds créé est l'entité racine, sa miroir est créée
  automatiquement par le service `creer_fonds`.
- Section **`collection_miroir:`** (optionnelle) : overrides pour la
  miroir auto-créée (titre, descriptions, phase, DOI Nakala). Si
  absente, la miroir hérite intégralement du fonds.

Les profils v1 (avec `collection:` racine) sont rejetés via
`ProfilObsoleteV1` avec un message de migration manuelle. Pas de
migration automatique : la situation est ambiguë (`parent_cote`
disparu, fonds vs collection libre rattachée). Référence complète :
[`docs/reference/profils.md`](docs/reference/profils.md).

Le module `profils/generateur.py` produit des squelettes v2
commentés :
- `generer_squelette` : profil minimal avec placeholder à remplir.
- `analyser_tableur` : profil pré-rempli des colonnes détectées,
  avec heuristique pour les champs structurants.

CLI : `archives-tool profil init` et `archives-tool profil analyser`.
Guide utilisateur dans
[`docs/premiers-pas/premier-import.md`](docs/premiers-pas/premier-import.md).

### Importer

Le pipeline d'import est découpé en quatre modules sous
`src/archives_tool/importers/` :

- `lecteur_tableur.py` : lit un CSV/Excel avec pandas en `dtype=str`,
  normalise NFC + strip, convertit les sentinelles nulles en `None`.
  Expose aussi `analyser_colonnes_tableur` (V0.9.2-import #2) qui
  calcule par colonne `{exemples, valeur_frequente, uniques, remplies,
  total}` — alimente l'aperçu inline de l'étape mapping.
- `transformateur.py` : fonction pure ligne → `ItemPrepare`, applique
  mapping, valeurs par défaut, décompositions, transformations.
- `resolveur_fichiers.py` : cherche les fichiers sur disque selon
  le motif template ou regex du profil.
- `ecrivain.py` : orchestre l'import en réutilisant les services
  métier (`creer_fonds`, `modifier_collection`, `creer_item`) — pas
  de duplication de logique. Dry-run = validation Pydantic + lecture
  tableur + résolution fichiers, sans appel aux services. Journalise
  dans `OperationImport` en mode réel.

CLI : `archives-tool importer <profil>` (Typer). Référence
complète dans [`docs/guide/cli/importer.md`](docs/guide/cli/importer.md).

Assistant web (V0.9.2-import) : l'étape mapping a été refondue en
deux modes coexistants. Le **mode simple** (par défaut, #3) pose
4 questions explicites — cote, granularité, titre, date — et
classe automatiquement le reste des colonnes en métadonnées (item
ou fichier selon la classif statistique). Le **mode avancé** reste
accessible via `?avance=1` ou le lien « Affiner colonne par
colonne » : il expose la grille de 28 sélecteurs historiques, avec
sous chaque colonne un aperçu inline (3 valeurs, taux de remplissage,
uniques — #2), des heuristiques nominatives élargies (#5) pour
`filename`/`hash`/`iiif`/`auteur`/`editeur`/`sujet`/etc., un indice
de **classif par-item / par-fichier** (#1, ≥90 % stables → par-item,
>50 % variables → par-fichier), une **promotion automatique** des
colonnes par-fichier vers `fichier.metadonnees.<slug>`, et une
section **« Anomalies détectées »** (#4) qui signale les conflits
cible ↔ classif avec un bouton client-side de correction sans POST
intermédiaire. Roadmap complète :
[`docs/developpeurs/v092-import-refonte.md`](docs/developpeurs/v092-import-refonte.md).

**Passe correctifs Bug A/B/C + Trou #9 (2026-05-23)** — découverts au
premier test d'usage sur un export Nakala réel (PF, 173 items, 7454
scans Nakala-only) :

- **Bug A** (`importers/ecrivain.py::_fichier_depuis_colonnes`) : en
  granularité fichier sans racine disque ni `fichier.iiif_url_nakala`
  mappé, les Fichier étaient silencieusement jetés par le CHECK SQL
  `ck_fichier_source_au_moins_une`. Fix : `_promouvoir_url_source`
  cherche une URL HTTP plausible dans `fichier.metadonnees.<X>` selon
  une liste de slugs prioritaires (`iiif`/`iiif_url`/`info_json` →
  `data_url` → `embed_url` → `preview_url` → `thumb`), la promeut
  comme source primaire et conserve la valeur dans `metadonnees`.
  Garde `startswith("http")` pour éviter qu'un mapping bizarre
  (`fichier.metadonnees.thumb` ← colonne `hash`) promeuve un hash en
  URL.

- **Bug B** (`api/services/import_web.py::construire_mapping_depuis_simple`) :
  mode simple ne promouvait pas les colonnes non choisies explicitement
  vers leurs cibles dédiées DC, écrasant tout en `metadonnees.<slug>`.
  Fix : pré-calcul `heuristiques: dict` via `proposer_mapping` sur
  les colonnes hors explicites, filtrage des cibles `cote`/`titre`/
  `date` (réservées au choix utilisateur), pré-population des sets de
  slugs avec ceux revendiqués par les heuristiques (anti-collision),
  suivi `cibles_dediees_prises` (défense en profondeur). Sur PF : 11
  champs promus (`doi`→`doi_nakala`, `Langue`→`langue`, `Description`→
  `description`, `Numéro`→`numero`, `author`→`metadonnees.auteur`,
  `Sujet`→`metadonnees.sujet`, `filename`→`fichier.nom_fichier`,
  `hash`→`fichier.hash_sha256`, etc.). `colonnes_champs_avances`
  enrichi pour ne pas signaler de perte sur les colonnes que
  l'heuristique re-détecte.

- **Bug C** (`api/services/dashboard.py::composer_metadonnees_par_section`) :
  la section « Champs personnalisés » de la page item n'itérait que
  les `ChampPersonnalise` formels — or l'importer ne crée pas de
  `ChampPersonnalise`, il dump les clés en JSON libre. Fix : après
  les formels, fallback sur les clés libres de `item.metadonnees`
  non vues, libellé synthétisé (`ancienne_cote` → `Ancienne cote`),
  tri alphabétique, garde anti-shadow (`vus` pré-populé avec les
  clés Identification/Identifiants/Description pour éviter les
  doublons visuels si un mapping pousse `titre`/`cote` en libre).
  Helpers extraits : `_valeur_metadonnee_str` (list→CSV, dict→`k:v`),
  `_libelle_depuis_cle`.

- **Trou #9** (`exporters/mapping_dc.py` + `exporters/nakala.py`) :
  Bug B promeut au SINGULIER (`auteur`/`sujet`/`contributeur`,
  alignement DC), alors que `MAPPING_DC` et le code hardcoded des
  exporters n'attendaient que le PLURIEL (`auteurs`/`sujets`/
  `collaborateurs`). Sans fix, toutes les données promues en mode
  simple disparaissaient silencieusement à l'export DC, Nakala et
  xlsx. Validé sur PF : 173 `<dc:creator>` + 173 `<dc:subject>` à
  l'export (vs 0 avant). `MAPPING_DC` étendu pour reconnaître les
  deux formes ; `_ligne_nakala` et `_verifier_createur` étendus
  symétriquement.

Validation manuelle : `scripts/reimport_pf.py` (re-import via service
direct sans UI) — 173 items, 7454 Fichier, 11 champs promus DC, ~11
clés libres en metadonnees affichées sur la page item.

**Normalisation IIIF Nakala (suivi Bug A, 2026-05-24)** —
`importers/ecrivain.py::_normaliser_url_nakala_vers_iiif` détecte
les URLs Nakala (`data_url`, `embed_url`, ou URL IIIF image type
`/iiif/<doi>/<sha>/full/.../default.jpg`) et les transforme en URL
IIIF info.json (`/iiif/<doi>/<sha>/info.json`). Sans ce normaliseur,
Bug A promouvait l'URL de download binaire en `iiif_url_nakala`, ce
que OpenSeadragon tentait d'ouvrir comme info.json → 404 systématique
→ fallback HTML pour chaque scan. Maintenant le viewer charge depuis
Nakala en streaming progressif (IIIF Image API v3 niveau 2 avec CORS),
zoom natif, aucun download local au-delà des tuiles visibles.

Garde stricte sur le hostname : `<sub>.nakala.fr` (alphanumérique +
`-`), préserve le hostname d'origine dans la cible (`api-test.nakala.fr`
reste `api-test.nakala.fr`, pas redirigé vers `api.nakala.fr`).
Empêche un faux positif sur `evil-nakala.fr` qui aurait été promu
vers la mauvaise origine.

Garde sur l'extension du fichier : Nakala ne sert IIIF Image API que
pour les images (`jpg`/`png`/`tif`/`webp`/`jp2`/etc.). Pour les PDF,
vidéos, archives ou autres non-images, `_est_extension_image_iiif`
filtre — on garde l'URL `data` brute (qui ne donne pas de viewer
fonctionnel, mais reflète l'origine exacte de la donnée et déclenche
proprement le fallback HTML « Télécharger »). Sans cette garde, un
PDF se serait vu attribuer un `iiif_url_nakala` pointant sur un
`/iiif/.../info.json` qui retourne 415 (Unsupported Media Type ;
vérifié live 2026-06-15 — Nakala ne sert l'IIIF Image API que pour
les images, pas 404 comme initialement documenté).

Les helpers Nakala sont centralisés dans
[`files/nakala.py`](src/archives_tool/files/nakala.py) :
`vers_iiif_info_json` (utilisé à l'import) et `vers_data` (utilisé
à l'affichage pour reconstruire l'URL de téléchargement direct
depuis une URL IIIF info.json — cf. ci-dessous).

**Téléchargement direct Nakala depuis la visionneuse (2026-05-24)** —
`api/services/dashboard.py::_url_telechargement_externe` calcule
l'URL de téléchargement à présenter dans le fallback HTML d'OSD
(« Télécharger ... ») pour les Fichier Nakala-only. Sans ce calcul,
le bouton pointait sur la route locale `/item/.../fichiers/<id>`
qui retournait 404 (pas de fichier sur disque). Maintenant : pour
un Fichier Nakala-only dont `iiif_url_nakala` pointe sur Nakala,
reconstruit `/data/<doi>/<sha>` (téléchargement binaire). Pour les
Fichier avec chemin local, retourne `None` — le caller utilise la
route locale. Exposé via `FichierResume.url_telechargement_externe`
consommé par `components/visionneuse_osd.html`.

**Type COAR auto (2026-05-24)** — `api/services/vocabulaires.py`
expose `normaliser_type_coar` qui convertit les libellés textuels
(`journal`, `périodique`, `numéro`, `book`, `chapter`, `photo`,
`map`, `audio`, …) en URI COAR canonique (`http://purl.org/coar/
resource_type/c_XXXX`). Couvre fr + en + variantes communes. Sans
accents (NFD + drop diacritiques) avant lookup.

Heuristique nominative ajoutée dans `profils.generateur._HEURISTIQUES` :
`^type$|^type_coar$|^type_document$|^doctype$` → `type_coar`. La
colonne `Type` d'un export DC/Nakala est désormais reconnue
automatiquement (Trou #2 V0.9.2-import). Ambiguité `Type` →
`type_coar` (Item) vs `type_page` (Fichier) résolue en faveur du
premier (cas dominant sur exports DC). L'utilisateur peut remapper
en mode avancé si le tableur décrit en vrai des types de page.

Application au moment de l'écriture dans
`importers/ecrivain.py::_construire_formulaire_item` : la valeur
brute est convertie via `normaliser_type_coar` ; si pas dans la
table d'alias, la valeur originale est conservée (l'utilisateur
édite via inline). Sur PF : `Type=journal` → `type_coar =
http://purl.org/coar/resource_type/c_2659` (Périodique) sur les
173 items. (Note V0.9.10 : l'URI Périodique était `c_3e5a`, fausse,
corrigée en `c_2659` ; cf. `nakala-depot-future.md` et la migration
`r6v7w8x9y0z1`.)

**DOI collection auto-promu + propagation Collection (2026-05-24)** —
deux fixes complémentaires sur le DOI Nakala collection.

Heuristique élargie dans `profils.generateur._HEURISTIQUES` :
`^doi[\s_-]?collection$|^collection[\s_-]?doi$` (au lieu de
`^doi_collection$|^collection_doi$`). Tolère l'espace et le tiret
entre les mots — sur Nakala, les exports utilisent souvent
`DOI collection` avec espace plutôt qu'un slug. Sans ce match,
`DOI collection` tombait en `metadonnees.doi_collection` libre.

Propagation auto dans
`importers/ecrivain.py::_propager_doi_collection_sur_miroir` :
après création de tous les items, si tous partagent un seul
`doi_collection_nakala` non vide ET que la miroir n'a pas déjà un
`doi_nakala` (le choix utilisateur via `collection_miroir.doi_nakala`
du profil prime), on copie la valeur sur `Collection.miroir.doi_nakala`.
Sémantique Nakala respectée : un DOI collection est une propriété
de la collection elle-même, pas dupliquée 173 fois sur les items.
L'autonomie des items est conservée (chaque item garde aussi sa
valeur — principe doc).

Sur PF : `Item.doi_collection_nakala = 10.34847/nkl.716dhx95` sur
173 items + `Collection.miroir.doi_nakala = 10.34847/nkl.716dhx95`.
metadonnees libres réduits à 5 clés (perte de `doi_collection` libre
absorbée par le champ dédié).

`Collection.doi_nakala` est UNIQUE en SQL : `IntegrityError` swallowed
avec warning si conflit (DOI déjà utilisé par une autre collection).
Les items gardent leur valeur quoi qu'il arrive.

**Miniatures Nakala et filtrage colonnes vides (2026-05-24)** —
deux fixes UX en lot après le test PF.

`files/nakala.py::vers_thumb` reconstruit une URL IIIF Image thumb
carrée (`full/!200,200/0/default.jpg` par défaut) depuis n'importe
quelle URL Nakala. `services/sources_image.py::resoudre_source_image`
l'utilise en fallback quand un Fichier Nakala-only n'a pas de
vignette locale dérivée (`vignette_chemin`) — sinon le panneau
fichiers de la page item affichait juste des numéros de page sans
aperçu, critique sur les items à 39+ scans (cas PF). La vignette
locale prime quand elle existe (offline, plus rapide).

`importers/lecteur_tableur.py::analyser_colonnes_tableur` filtre les
colonnes avec `remplies == 0` du dict retourné. `attacher_tableur`
dérive `colonnes_detectees` depuis `echantillons.keys()` — alignés
automatiquement. Sans ce filtre, mode simple promouvait les
colonnes vides en `metadonnees.<slug>` libres (cas PF : `Unnamed: 15`,
`Unnamed: 15.1`, `description_page`, `collaborateur_journaliste`)
et la page item affichait `Unnamed 15: non renseigné` × 4 par item
— bruit pur. Safe-guard dans `construire_mapping_depuis_simple` :
si `echantillons` est rempli, filtre aussi `colonnes` pour éviter
divergence en cas de désynchronisation `colonnes_detectees` vs
`colonnes_echantillon`.

**Liseuse consultation Lot 1 (2026-05-24)** — page de consultation
distincte de l'édition, complète (pas refonte). Route
`/lire/<fonds_cote>/<cote>?fichier=N` rend
`pages/lire_item.html` avec layout 3 colonnes :
- gauche (280px) : cartouche métadonnées (read-only)
- centre (flex-1) : visionneuse OSD (réutilisée) ou fallback HTML
- droite (200px) : panneau vignettes toujours visible

Bandeau spécifique `bandeau_lire.html` : chip « Consultation » bleu
distinctif, navigation **Page** (← →) séparée de **Item** (← →) —
résout la friction principale identifiée par l'utilisateur (avant,
« Suivant » changeait d'item, pas de fichier). Bouton « Cataloguer »
pour retour `/item/<cote>?fonds=<f>`.

Navigation HTMX : clic sur vignette ou boutons Page → swap simultané
de 3 fragments via `hx-swap-oob` :
- cible principale `#zone-visionneuse` (nouvelle visionneuse)
- OOB `#bandeau-liseuse` (boutons Page rafraîchis pour le nouveau
  fichier courant — sans ce 2e swap, les boutons restaient figés
  après le 1er clic et la navigation cassait)
- OOB `#liste-vignettes-liseuse` (highlight `est_courant` déplacé)

OSD est ré-instancié manuellement après chaque swap (le partial
inclut un script qui appelle `OpenSeadragon()` sur les `.visionneuse-osd`
nouveaux). URL `?fichier=N` mise à jour côté client via `hx-push-url`
pour permettre le bookmark.

Entry points : bouton « Mode consultation » dans le header global
(`components/header.html`) actif sur toutes les pages qui passent
`consultation_url` au contexte — actuellement item, fonds (1er item
alphabétique), collection (1er item de la 1ère page courante).
Sur la liseuse elle-même, le bouton header se transforme en chip
distinctif « Mode consultation actif ».

`liste_vignettes` extraite de `panneau_fichiers.html` comme macro
publique réutilisable, avec param `mode_consultation=True` qui
remplace les hrefs reload par `hx-get` vers le partial.

Limites MVP (Lot 1) :
- PDF / xlsx / autres non-images tombent en fallback « Aucun aperçu
  disponible » avec bouton Télécharger Nakala (Lot 2 = PDF.js + parser xlsx).
- Pas de raccourci clavier ← → ni Esc (Lot 3).
- Pas de loading state pendant le swap OSD (Lot 3).
- Pas de bascule auto vers l'item suivant en fin de séquence
  (choix utilisateur : boutons explicites séparés préférés).

**Liseuse Lot 2 : PDF.js avec text layer (2026-05-24)** — viewer
PDF embarqué pour les fac-similés Nakala (un PDF du numéro entier
par item PF). Composant `visionneuse_pdf.html` + dispatcher
`visionneuse_consultation.html` qui choisit selon `fichier.extension` :
PDF → PDF.js, image → OSD, autres → fallback HTML « Télécharger ».

Vendor : `pdfjs-dist` 5.6 **build legacy** (la build courante utilise
des features ES2024 — Map.prototype.getOrInsertComputed — que les
navigateurs récents-mais-pas-bleeding-edge ne supportent pas). Le
script `scripts/vendor.mjs` copie `pdf.min.mjs`, `pdf.worker.min.mjs`,
et le dossier `wasm/` complet (openjpeg, jbig2, qcms) dans
`static/js/vendor/pdfjs/`.

JP2 critique : les fac-similés Nakala utilisent JPEG 2000 pour les
images de scan. PDF.js a besoin du WASM OpenJPEG pour décoder. Sans
le `wasmUrl: "/static/js/vendor/pdfjs/wasm/"` passé à `getDocument()`,
les pages se chargent mais ne montrent QUE la couche OCR (pas
d'image). Test régression `test_liseuse_pdf_inclut_wasm_url_et_text_layer`.

ESM via import dynamique : `pdfjs-dist` v5+ est ESM uniquement. Les
`<script type="module">` injectés par HTMX swap ne s'exécutent pas
toujours selon les navigateurs ; on utilise `<script>` classique
avec `import("...")` dynamique pour fiabilité cross-swap.

Couche texte OCR : `new pdfjsLib.TextLayer({...})` rend une couche
`<span>` transparente positionnée par-dessus le canvas après chaque
rendu de page. Sélection texte + `Ctrl+F` natif fonctionnent. Pour
les PDF scannés sans OCR, la couche est vide (non-bloquant).

Viewer minimal : barre de contrôles compacte (page ‹ N/M ›, zoom
−/+/ajuster largeur, lien Télécharger). Navigation pages **internes
au PDF** distincte de la navigation `Page ← →` du bandeau liseuse
(qui change de Fichier). Hi-DPI géré via `transform` PDF.js + DPR.

Limites MVP (Lot 2) :
- Pas de cancellation du `textLayer.render()` (race si swap rapide,
  text layer ancien peut rester par-dessus nouveau canvas — mineur).
- xlsx / csv / audio / vidéo restent en fallback (Lot futur).
- Pas de cache-busting sur les assets vendor pdfjs (le browser cache
  `pdf.min.mjs` ; relancer `npm run vendor` + hard refresh quand on
  upgrade pdfjs).

**Liseuse Lot 3 : clavier + loading state + raccourcis discoverable
(2026-05-24)** — polish UX final de la liseuse consultation.

`static/js/liseuse.js` charge sur la page complète (pas les partials
HTMX) un listener global `keydown` :
- `←` → clic sur le bouton « Page précédente » du bandeau (qui
  déclenche le swap HTMX déjà câblé)
- `→` → clic sur « Page suivante »
- `Esc` → clic sur « Cataloguer » (retour `/item/<cote>?fonds=<f>`)
Skip si focus dans input/textarea/contenteditable pour ne pas
casser la sélection texte (notamment PDF.js text layer).

Selection des boutons par `title` exact (`Page précédente`/`Page
suivante`) plutôt que par position : sans ça, sur la page 1 où ‹
est désactivé en `<span>`, `:first-of-type` matchait › et `←`
déclenchait ›.

Loading state HTMX : `liseuse.js` écoute `htmx:beforeRequest` /
`htmx:afterSwap` et toggle `.en-chargement` sur `#zone-visionneuse`
quand le swap cible cette zone. CSS dimme à 55% d'opacité avec
60ms de délai (évite le flash sur swap rapide). Approche JS plutôt
que `hx-indicator` car le bandeau (boutons Page) est hors de
`.layout-liseuse` — l'indicator hérité ne couvrait que les vignettes
du panneau droit.

Pied de page raccourcis discoverable : `[←][→] page · [Esc] retour
catalogage` en `<kbd>` gris pâle stylés. Signale visuellement que
le clavier est utilisable.

Limites Lot 3 :
- Sur la page PDF, `←`/`→` naviguent entre fichiers de l'item (pas
  dans les pages du PDF). Pour naviguer dans le PDF lui-même,
  utiliser les boutons internes ‹/› du PDF.js. Comportement
  cohérent avec le scope « liseuse = entre fichiers » mais peut
  surprendre.
- Pas de raccourci `F` (fullscreen) ni `M` (toggle meta) initialement
  prévus — pas dans ce lot, reportable si besoin.

**Liseuse Lot 4 : viewer PDF en scroll continu (2026-05-24)** —
refonte du composant `visionneuse_pdf.html`. Le mode initial
« 1 page à la fois » du Lot 2 est remplacé par un scroll vertical
continu, plus naturel pour feuilleter un fac-similé (cas PF : 40
pages par numéro).

Architecture : au load, calcul du scale cible (largeur du conteneur
/ largeur native de la page 1). Création de N wrappers `<div>` avec
hauteur estimée (basée sur la page 1, format constant en
fac-similé). Deux `IntersectionObserver` :
- **render lazy** : rootMargin `800px 0px` → render la page quand
  elle est dans ~2 pages d'avance dans le scroll. Évite de monter
  40 canvas au load (PF aurait ~600 Mo en mémoire sinon).
- **compteur visible** : rootMargin `-30% 0px -60% 0px` → la page
  centrée dans le viewport gagne, met à jour le compteur `N / M`
  du bandeau de contrôles.

Boutons :
- `‹/›` → scroll smooth vers la page précédente/suivante (utilisent
  `scrollIntoView({behavior: "smooth"})`)
- `⤢` → recalcule le scale (utile si l'utilisateur a redimensionné
  hors du resize auto) + préserve la page visible avant/après.

Resize fenêtre auto : listener `window.resize` avec debounce 300ms
qui appelle `ajusterLargeur()`. Skip si le viewer n'est plus dans
le DOM (HTMX swap fichier suivant).

Hauteur estimée : sans cette estimation initiale (`min-height` du
wrapper = hauteur réelle prévue × scale), les pages se rendant
progressivement faisaient sauter la position scroll des suivantes.
Critique sur PF qui a 40 pages.

Limites :
- Si l'utilisateur scroll très vite, l'IntersectionObserver
  déclenche le render de toutes les pages traversées qui se
  queueent — mémoire peut grimper. Pas d'unrender automatique des
  pages éloignées (potentielle optim future).
- `Ctrl+F` natif ne cherche que dans les pages déjà rendues
  (limite du DOM ; PDF.js inclut un finder dédié dans son default
  viewer, non-utilisé ici car custom UI).
- Pages au format hétérogène (rares en fac-similé) ne sont pas
  pré-estimées correctement.

### Recherche full-text FTS5 (V0.9.x)

Index full-text via SQLite FTS5, créé par la migration
`m1q2r3s4t5u6_fts5_recherche` :
- `item_fts` : cote, titre, description, notes_internes,
  metadonnees_text (flatten JSON top-level via GROUP_CONCAT json_each)
- `fonds_fts` : cote, titre, description, description_publique,
  description_interne
- `collection_fts` : cote, titre, description, description_publique

Tokeniseur `unicode61 remove_diacritics 2` : `numero` matche `Numéro`
(insensible aux accents), indispensable en archives multilingues.

Mode FTS5 « standard » (pas d'external content) : FTS5 stocke
l'index ET le texte. Permet `snippet()` qui surligne les matchs.
Indispensable parce qu'on indexe une colonne dérivée
(`metadonnees_text` = flatten JSON) qui n'existe pas dans la source
— le mode external content planterait avec « no such column ».
Le mode contentless évite ce plantage mais perd `snippet()`.

Triggers de synchro (insert/update/delete sur item/fonds/collection)
maintiennent l'index automatiquement. SQL centralisé dans
`db._SQL_TRIGGERS_FTS` (source de vérité unique réutilisée par la
migration et par `assurer_tables_fts()` qui couvre les tests / le
startup app).

Helpers `alembic.helpers.drop_fts_triggers()` /
`create_fts_triggers()` : à appeler en début/fin de toute migration
qui ALTER `item`/`fonds`/`collection` via `batch_alter_table`
(sinon les triggers sont perdus à la reconstruction de la table —
piège SQLite).

Service `api/services/recherche.py::rechercher(db, q, scope, types)` :
- `scope` (`Scope`) : `fonds_id` / `collection_id` pour limiter
  géographiquement (None, None = tout l'outil)
- `types` : set d'entités à inclure (`item`, `fonds`, `collection`)
- Échappement automatique des caractères réservés FTS5 via
  `_preparer_requete_fts` (anti-injection)
- Préfix matching (`*`) sur chaque token pour recherche partielle
  ergonomique sur les cotes (`PF-0` matche `PF-001`, `PF-002`…)
- Ranking via `bm25()` natif FTS5

Route `/recherche?q=...&fonds_id=...&collection_id=...&types=...` rend
`pages/recherche.html` : barre de saisie + filtres scope/types +
liste de résultats avec snippets surlignés (`<mark>` HTML-safe).

Barre de recherche globale dans `header.html` (toutes les pages),
raccourci `/` ou `Cmd+K` (focus + select via `recherche_globale.js`).

Sur PF (test réel) : 173 items + 1 fonds + 1 collection indexés.
`Por Favor` → 52 résultats. `Eduardo` (auteur indexé via
`metadonnees.author`) → 50 résultats items. `PF-014` (cote
partielle) → 1 résultat exact.

Limites :
- OCR documents non indexé (roadmap V3 — ajoutera soit `fichier_fts`
  dédié, soit colonne `ocr_text` sur `item_fts`).
- Pas de live-search dropdown (submit GET classique → page résultats).
  Acceptable MVP, à itérer si demandé.
- Pas de surlignage dans la page de l'item lui-même (résultat
  cliqué = navigation classique, sans préserver les termes
  cherchés). À itérer V2 via `?q=` propagé.

### CLI Collections

`archives-tool collections {creer-libre, lister, supprimer}` est le
pendant CLI de l'UI V0.9.0-beta.2.1 pour gérer les collections libres
sans passer par le navigateur :

- `creer-libre COTE TITRE [--fonds COTE | rien (transversale)]
  [--description ...] [--phase ...]`
- `lister [--fonds COTE | --transversales]`
- `supprimer COTE [--fonds COTE] [--yes]` (refuse les miroirs).

### Exports canoniques

`src/archives_tool/exporters/` regroupe les trois formats d'export
de la V0.9.0-gamma.2. **L'unité d'export est la collection** (miroir,
libre rattachée, transversale) — on n'exporte pas un fonds directement,
on exporte sa miroir si on veut tout.

- `_commun.py` : `composer_export(db, collection)` charge items +
  fichiers + fonds d'origine en une seule requête (selectinload + JOIN).
- `mapping_dc.py` : source de vérité des correspondances champs
  internes → URI Dublin Core Terms.
- `rapport.py` : `RapportExport` (items incomplets, valeurs non
  canoniques type_coar/langue, durée).
- `dublin_core.py` (XML), `excel.py` (xlsx), `nakala.py` (CSV bulk) :
  signature uniforme `(session, collection, sortie) → RapportExport`.

CLI : `archives-tool exporter {dublin-core,nakala,xlsx} COTE
[--fonds COTE] [--sortie ...]`. Le `--fonds` désambiguïse une cote
partagée. Pour les transversales, chaque ligne Nakala/xlsx indique
son fonds d'origine via la colonne `fonds_cote` ; en DC, les fonds
représentés sont listés en `dc:source` dans la notice de tête.
Référence complète : [`docs/guide/cli/exporter.md`](docs/guide/cli/exporter.md).

### Affichage CLI

`src/archives_tool/affichage/` regroupe les rendus Rich + formatteurs
neutres (lecture seule) :

- `console.py` : instance Console partagée, `THEME` (succès, avertissement,
  erreur, états par enum), helper `silencer_pour_tests`.
- `formatters.py` : helpers neutres (`formater_etat`,
  `formater_taille_octets`, `temps_relatif`, `panel_kv`, …).
- `montrer.py` : 12 rendus pour la CLI `montrer` — 6 entités/cas
  (fonds liste/détail, collection liste/détail, item détail, fichier
  détail) × 2 formats (text Rich, JSON typé par champ `type`).

CLI `archives-tool montrer {fonds,collection,item,fichier}` :
- `montrer fonds [--cote COTE]` : liste tous les fonds ou détaille
  un fonds (collections, items récents, collaborateurs, traçabilité).
- `montrer collection [--cote COTE] [--fonds COTE]` : liste (filtrable)
  ou détail. Gère les 3 variantes (miroir, libre rattachée, transversale
  avec section fonds représentés).
- `montrer item COTE_ITEM --fonds COTE_FONDS` : détail (métadonnées
  custom, fichiers, modifications, traçabilité).
- `montrer fichier ID` : détail par id global (source, dérivés,
  technique, opérations).

`--format text|json` partagé avec `controler` via l'enum
`_FormatRapport`. Référence complète :
[`docs/guide/cli/montrer.md`](docs/guide/cli/montrer.md).

### Contrôles de cohérence

`src/archives_tool/qa/` regroupe 14 contrôles répartis en 4 familles
(lecture seule, jamais d'écriture en base ni sur disque) :

- `_commun.py` : `Severite`, `Exemple`, `ResultatControle`,
  `PerimetreControle`, `RapportQa`.
- `invariants.py` : INV1-2-4-6 (miroir unique, miroir avec fonds,
  item avec fonds, item dans la miroir).
- `fichiers.py` : FILE-MISSING, FILE-ITEM-VIDE, FILE-HASH-DUPLIQUE
  (agrégation SQL, pas de N+1), FILE-HASH-MANQUANT.
- `metadonnees.py` : META-COTE-INVALIDE (`PATTERN_COTE`),
  META-TITRE-VIDE, META-DATE-INVALIDE (regex EDTF tolérante),
  META-ANNEE-IMPLAUSIBLE (plage configurable).
- `cross.py` : CROSS-COTE-DUPLIQUEE-FONDS, CROSS-FONDS-VIDE.
  Toujours sur la base entière, indépendamment du périmètre.
- `orchestrateur.py` : `composer_perimetre` + `executer_controles`.
- `formatteurs/{text,json}.py` : Rich pour text (couleurs ✓⚠✗ via
  THEME projet), structure JSON stable pour CI.

CLI : `archives-tool controler [--fonds COTE | --collection COTE]
[--format text|json] [--strict] [--max-exemples N]`. Codes :
- 0 : aucune erreur (avertissements/infos OK en non-strict),
- 1 : erreur métier ou `--strict` avec problème ou cote inconnue,
- 2 : saisie invalide.

Référence complète : [`docs/guide/cli/controler.md`](docs/guide/cli/controler.md).

### Renommage transactionnel

`src/archives_tool/renamer/` orchestre le renommage en quatre temps :

- `template.py` : évaluation d'un template Python (`str.format`)
  avec les variables d'un fichier et de son item.
- `plan.py` : construction du plan, détection des conflits
  (collisions intra-batch, externes) et des cycles (résolus, pas
  bloqués).
- `execution.py` : exécution en deux phases (`src→tmp`, `tmp→dst`)
  sur disque et en base, avec rollback compensateur en cas d'erreur
  mid-batch. La contrainte `UNIQUE(racine, chemin_relatif)` impose
  ce passage par un nom temporaire pour les cycles.
- `annulation.py` : retour en arrière d'un batch via son `batch_id`,
  idempotent.
- `historique.py` : vue agrégée des batchs `OperationFichier`.

CLI : `archives-tool renommer appliquer --template ... [--fonds COTE
| --collection COTE [--fonds COTE] | --item COTE --fonds COTE |
--fichier-id ID]`, `archives-tool renommer annuler --batch-id UUID`,
`archives-tool renommer historique`. Dry-run par défaut. Variables
template incluent `{cote_fonds}` / `{titre_fonds}` / `{cote_collection}`
/ etc. Référence complète dans [`docs/guide/cli/renommer.md`](docs/guide/cli/renommer.md).

### Génération de dérivés

`src/archives_tool/derivatives/` produit vignettes et aperçus pour
les fichiers actifs :

- `chemins.py` : convention de stockage `<racine_cible>/<taille>/<chemin_source>.jpg`.
- `generateur.py` : Pillow pour les formats raster, PyMuPDF (fitz)
  pour les PDF (1ère page à 200 dpi). RGBA composé sur fond blanc.
- `rapport.py` : dataclasses + `StatutDerive` (StrEnum).
- `affichage.py` : rendu Rich.

Tailles par défaut : vignette 300 px, aperçu 1 200 px (côté long,
ratio préservé). Idempotent : `derive_genere=True` est ignoré sauf
`--force`.

CLI (V0.9.0-gamma.4.3) : `archives-tool deriver appliquer
[--fonds|--collection|--item|--fichier-id] [--force] [--dry-run]
[--racine-cible miniatures]`, `archives-tool deriver nettoyer ...`.
Périmètre validé via `Perimetre` (réutilisé du module `renamer`),
sélection alignée sur `archives-tool renommer`. Référence dans
[`docs/guide/cli/deriver.md`](docs/guide/cli/deriver.md).

**Invalidation au renommage** : `renamer/execution.py` et
`renamer/annulation.py` remettent `derive_genere = False` (et
nullent `apercu_chemin` / `vignette_chemin`) sur chaque fichier
déplacé, pour forcer la régénération à la prochaine passe
`deriver appliquer`.

### Interface web

`src/archives_tool/api/` (FastAPI) et `src/archives_tool/web/`
(Jinja2 + Tailwind compilé) constituent le socle de l'UI.
V0.6.0 livre dashboard + vue collection (3 onglets) + vue item
avec visionneuse OpenSeadragon, en lecture seule. Le dashboard
a été enrichi en V0.9.1-dev avec : 5 cartes de stats globales
(Fonds, Collections, Items, Fichiers, Items validés), barre
d'avancement par fonds et par collection (composant
`avancement_compact`), traçabilité « modifié par X · il y a Y »
(composant `cellule_modifie`), section « Activité récente »
listant les 10 dernières modifications mélangées
(item / collection / fonds). Service composé en ≤14 requêtes
SQL indépendamment du volume.

**V0.9.2-alpha** : page Fonds restaurée avec les composants
existants. `composer_page_fonds` enrichi (`repartition_etats`,
`modifie_par`/`le` propagé depuis les items, `nb_fichiers` par
fonds et par collection) — coût SQL borné ≤ 10 requêtes par
rendu. Le bandeau du fonds expose un `avancement_detaille` avec
légende + `cellule_modifie`. La liste des collections passe par
`tableau_collections` (réutilisé du bundle V0.6.0.1, restauré
ici) qui rend nativement avancement, traçabilité et phase de
chantier par ligne. Le composant `phase_chantier` est branché
côté dashboard (via `tableau_fonds_enrichi` et
`_collection_transversale`) et côté page Fonds (via
`tableau_collections`). Pages Collection et Item restent
dépouillées — V0.9.2-beta et gamma. Audit complet :
`audit_ui_v0_9_0.md` à la racine du repo.

- `api/main.py` : application FastAPI, mount `/static`, inclusion
  du router `dashboard` (unique depuis V0.9.0-beta : il porte
  dashboard, fonds, collection, item, collaborateurs).
- `api/templating.py` : instance Jinja2Templates partagée, filtres
  (libelle_phase, libelle_etat, libelle_role, temps_relatif,
  taille_humaine, url_tri, url_page).
- `api/deps.py` : session SQL par requête (engine + sessionmaker
  cachés via lru_cache), identité utilisateur, racines, base
  courante. `ARCHIVES_DB` (variable d'environnement) prime sur la
  base par défaut.
- `api/routes/dashboard.py` : routes web — `/`, `/fonds/{cote}[/modifier]`,
  `/collection/{cote}[/modifier|/items|/items/picker|/items/{id}/retirer]`,
  `/item/{cote}[/modifier|/fichiers/{id}]`, `/fonds/{cote}/collaborateurs/...`.
- `api/services/` : logique métier pure (`dashboard.py` pour
  `composer_dashboard / composer_page_fonds / composer_page_collection /
  composer_page_item`, `fonds.py`, `collections.py`, `items.py`,
  `collaborateurs_fonds.py`, `tri.py` (`Listage[T]`),
  `sources_image.py` pour la résolution Nakala/IIIF V0.7+).
- `web/templates/components/` : composants partagés (badge_etat,
  avancement, cellule_modifie, phase_chantier, panneau_colonnes,
  tableau_collections, tableau_items, header, tabs, metric_card,
  breadcrumb, collection_header, _champ_form). Le bundle handoff est
  la **référence visuelle de vérité** ; détails dans
  [`docs/developpeurs/composants-ui.md`](docs/developpeurs/composants-ui.md).
- `web/templates/{base.html,pages/,partials/}` : layout commun, pages
  pleines pour accès direct, partiels pour swap HTMX.
- `web/static/css/{input.css,output.css}` : Tailwind compilé via
  npm. Tokens étendus du bundle : `state-info/warn/ok/err`,
  `seg-brouillon/a-verifier/verifie/valide/a-corriger`,
  `border-{tertiary,secondary,primary}` (opacité du noir).
- `web/static/js/vendor/openseadragon/` : bundle vendor conservé
  pour la visionneuse riche V2 (la V0.9.0-beta.3 utilise un `<img>`
  simple avec navigation par query string).

**Visionneuse (V0.9.0-beta.3)** : `<img>` direct pour les formats
raster supportés nativement (PNG, JPEG, GIF, WebP, SVG) ; message
+ lien de téléchargement pour TIFF, PDF, autres. Navigation
Précédent/Suivant via `?fichier_courant=N` (1-indexé, clampé).
L'endpoint `/item/{cote}/fichiers/{id}?fonds=COTE` sert le binaire
via `FileResponse`, après avoir vérifié l'appartenance
fichier→item→fonds (anti-confused-deputy). Sur la base demo où
les chemins sont fictifs, retourne 404 propre. Le pipeline IIIF
Nakala / OpenSeadragon est prévu pour V2 via `sources_image.py`.

CLI : `archives-tool demo init [--sortie data/demo.db] [--force]` crée
une base SQLite peuplée pour explorer l'interface (5 fonds, ~333
items, ~1300 fichiers, 1 transversale, collaborateurs). Référence
dans [`docs/guide/interface-web.md`](docs/guide/interface-web.md).

### Sources externes (V2+)

Une entité parallèle permet de référencer des ressources consultées dans
des entrepôts externes (Nakala d'abord, éventuellement d'autres).

```
SourceExterne (Nakala, HAL, Gallica...)
  └── RessourceExterne (une notice consultée, avec cache local)
        └── LienExterneItem (rattachement à un item local, optionnel)
```

### Flux de données

```
Tableurs existants  ─┐
Arborescence scans  ─┼─► Import (profils YAML) ─► Base SQLite ─► Export (Excel, DC/XML)
Saisie nouvelle     ─┘                                ▲
                                                      │
                                            Interface FastAPI + HTMX
                                                      ▲
                                                      │
                                            Consultation Nakala (V2+)
```

### Documentation

Le site MkDocs Material est servi sur GitHub Pages, déploiement
automatique depuis `main` via `.github/workflows/docs.yml`.
Build `mkdocs build --strict` (passe en CI) refuse les liens
cassés et les pages orphelines.

Structure :

- `mkdocs.yml` à la racine (config Material + nav).
- `docs/index.md` : page d'accueil.
- `docs/premiers-pas/` : Installation / Configuration / Premier
  import / Workflow type (gamma.5.1, complets).
- `docs/guide/` : Concepts (complet, définition canonique +
  diagramme Mermaid), Interface web, CLI/* (index transversal +
  les 7 sous-commandes complètes).
- `docs/reference/` : Profils d'import, Schéma de données,
  Formats d'export et Contrôles qa, tous complets.
- `docs/developpeurs/` : Architecture, Modèle, Services, Tests,
  Composants UI, Contribuer, tous complets.
- `docs/annexes/` : Changelog (V0.9.0 complète), Limites.

Le plugin `mkdocs-macros-plugin` permet d'utiliser des variables
dans les pages, dont `{{ repo_main }}` pour les liens GitHub
(défini dans `mkdocs.yml` `extra:`). Les anciens fichiers
historiques (`docs/composants_ui.md`, `docs/profils_creation.md`)
ont été supprimés en gamma.5.3 et gamma.5.2 respectivement —
leur contenu utile est intégré dans la nouvelle structure
(`developpeurs/composants-ui.md`, `premiers-pas/premier-import.md`,
`reference/profils.md`).

Tests garde-fous : `tests/docs/test_structure.py` vérifie la
présence et le non-vide des fichiers documentaires essentiels.

Commandes utiles :

```bash
uv run mkdocs serve              # preview locale (live reload)
uv run mkdocs build --strict     # build (échoue sur warnings)
uv run pytest tests/docs/        # garde-fou structure
```

---

## Concepts (V0.9.0-alpha)

Le modèle distingue **trois entités** qui étaient confondues
auparavant :

- **Fonds** — le **corpus brut**, le matériel d'origine. Existe
  avant le travail d'archivage. Nakala ne connaît pas cette notion :
  c'est interne à l'outil.
- **Collection** — un **classement publiable**. Sélection d'items
  pour une présentation, un thème, un export Nakala. Deux espèces :
  - **Miroir** : créée automatiquement avec un fonds, regroupe par
    défaut tous ses items. Toujours rattachée à un fonds (CHECK).
  - **Libre** : créée manuellement. Peut être rattachée à un fonds
    ou rester transversale (`fonds_id IS NULL`) — par exemple
    « Témoignages d'exil » qui pioche dans plusieurs fonds.
- **Item** — une unité de matériel. Appartient à exactement un fonds
  (sa source) et figure dans 0..N collections via la junction
  `item_collection` (la miroir + 0..N libres).

Conséquences :

- La cote n'est plus globalement unique — elle l'est **par fonds**
  pour les items, et **par fonds** pour les collections. Une cote
  de fonds peut volontairement coïncider avec celle de sa miroir.
- Plus de `Collection.parent_id` (la hiérarchie technique avait été
  introduite pour de mauvaises raisons : Nakala est plat).
- Un même item peut figurer dans plusieurs collections (ex. un même
  film dans « Cinéma » et « Œuvres »).

## Modèle de données (résumé)

Entités principales — détails dans [`docs/reference/schema.md`](docs/reference/schema.md).

- **Fonds** (V0.9.0-alpha) : id, cote unique, titre, descriptions,
  champs revue (éditeur, périodicité, ISSN), responsable archives,
  collaborateurs.

- **Collection** (refondue V0.9.0-alpha) : id, cote (unique par
  fonds), titre, type_collection (miroir/libre), fonds_id (NULL pour
  transversale), phase, descriptions, DOI Nakala, etc.

- **Item** (refondu V0.9.0-alpha) : id, fonds_id (obligatoire), cote
  (unique par fonds), titre, date EDTF, type_coar, état_catalogage,
  métadonnées JSON, traçabilité. Multi-appartenance via
  `item_collection`.

- **ItemCollection** : junction N-N (item_id, collection_id, ajoute_le,
  ajoute_par).

- **Fichier** : id, item_id, racine (nom logique), chemin_relatif, hash,
  ordre, type_page, folio, état, largeur, hauteur, format.

- **ProfilImport** : rattaché à une collection, contient mapping colonnes
  tableur → champs, règles de résolution fichiers, template de nommage.

- **ChampPersonnalisé** : permet à une collection d'avoir des champs
  spécifiques en plus du socle DC.

- **OperationFichier** : journal des opérations sur fichiers (rename,
  move, delete). Batch_id pour annulation de lot.

- **ModificationItem** : journal des modifications de métadonnées.

- **OperationImport** : journal des imports YAML (un par exécution
  réelle). Lié aux OperationFichier produites pendant l'import.

- **PreferencesAffichage** : ordre des colonnes choisi par utilisateur
  dans une vue tabulaire.

- **CollaborateurFonds** (V0.9.0-alpha) : personnes ayant contribué
  à un fonds. Usage par défaut.
- **CollaborateurCollection** (V0.8.0) : personnes attachées à une
  collection particulière. Cas spécifiques.
  Vocabulaire commun : `RoleCollaborateur` (numerisation,
  transcription, indexation, catalogage).

- **SourceExterne**, **RessourceExterne**, **LienExterneItem** : V2+,
  pour Nakala.

- **Utilisateur** (table livrée — couche identité Phase 1) : référentiel
  des comptes nommés du futur mode serveur (`id`, `nom` unique, `actif`,
  `peut_editer`). Pas d'auth forte (attribution). **Non consulté en mode
  local** (l'identité vient de `config_local.yaml`) ; sert la session /
  login du mode serveur (Phase 2, à venir). Modèle + service
  (`api/services/utilisateurs.py`) + CLI `archives-tool utilisateurs`
  livrés ; périmètre minimal V1.0 (la matrice scope/invité/expiration
  viendra par migration au besoin). Migration `x2b3c4d5e6f7`.

- **Racine** : nom logique → chemin local (par utilisateur, dans la
  config locale, jamais en base partagée).

---

## Conventions de code

### Structure du dépôt

```
archives-tool/
├── CLAUDE.md
├── README.md
├── schema.md                  # Stub redirige vers docs/reference/schema.md
├── mkdocs.yml                 # Config MkDocs Material (docs/ → site)
├── pyproject.toml
├── alembic.ini
├── alembic/
│   └── versions/
├── src/
│   └── archives_tool/
│       ├── __init__.py
│       ├── config.py          # Chargement config locale
│       ├── db.py              # Session SQLAlchemy, init WAL
│       ├── models/            # Modèles SQLAlchemy
│       ├── schemas/           # Pydantic
│       ├── importers/         # Lecture tableurs + profils YAML
│       ├── exporters/         # Excel, CSV, DC/XML
│       ├── files/             # Résolution chemins, racines, hash
│       ├── renamer/           # Logique de renommage transactionnel
│       ├── derivatives/       # Génération vignettes / aperçus
│       ├── external/          # Connecteurs Nakala, IIIF (V2+)
│       ├── qa/                # Contrôles de cohérence
│       ├── api/               # FastAPI : routes, deps, services
│       ├── web/               # Templates Jinja2 + assets statiques
│       ├── demo/              # Génération de la base de démonstration
│       └── cli.py             # Commandes Typer
├── profiles/                  # Profils d'import par collection (YAML)
├── tests/
├── data/                      # .db et dérivés (gitignoré)
├── scripts/
├── docs/                      # Sources MkDocs (index, premiers-pas/, guide/, reference/, developpeurs/, annexes/)
└── .github/workflows/docs.yml # CI build + deploy GitHub Pages
```

### Règles de code

- **Typage statique systématique.** Tous les paramètres et retours de
  fonction typés. `from __future__ import annotations` en tête.
- **Fonctions courtes, responsabilités uniques.** Une fonction qui
  dépasse 40 lignes doit être questionnée.
- **Pas de logique métier dans les routes FastAPI.** Les routes
  délèguent à des services. Testabilité > concision.
- **Pas de SQL brut** sauf cas très justifiés ; SQLAlchemy ORM ou Core.
- **Chemins : toujours `pathlib.Path`.** Jamais de `os.path.join` ni de
  concaténation. Toujours normaliser Unicode en NFC avant comparaison.
- **Encodage : toujours UTF-8 explicite** à la lecture/écriture de
  fichiers. Détection bienveillante à l'import des tableurs anciens.
- **Docstrings en français** pour les fonctions métier. Anglais ok pour
  les utilitaires bas-niveau.
- **Noms de variables en français** pour les concepts métier (cote,
  item, racine), anglais pour la technique (session, hash, path).

### Tests

- **pytest** avec fixtures.
- **Tests d'intégration pour les importers** avec de vrais petits
  tableurs d'exemple et arborescences de fichiers fictives.
- **Tests de transaction pour le renamer** : simulations de pannes,
  conflits, circuits. Cas limites explicites.
- **Tests de portabilité chemin** : tests paramétrés Windows + POSIX
  (via pyfakefs si pertinent).

---

## Plan de développement (phasage)

> **Séquencement courant (décidé 2026-06-18) → voir
> [`docs/developpeurs/roadmap.md`](docs/developpeurs/roadmap.md).**
> Le forward-looking est désormais organisé **par dépendances**, pas par
> numéro de version : **(1) Ingestion ShareDocs (client WebDAV, dé-risqué
> par BD_ditor) → (2) OCR / recherche plein-texte (text-first) →
> (3) Déploiement + multi-utilisateurs V1.0 → (4) Diffusion (sites
> statiques, portail) → (5) Confort/interop V2/V3.** La section ci-dessous
> reste la **trace de l'historique livré** + le plan V1/V2/V3 d'origine.

> **Chantier 1 ShareDocs ✅ LIVRÉ** (2026-06-18, branche `dev`). ColleC
> a un **2ᵉ adaptateur distant** (avec Nakala) : parcourir un partage
> WebDAV Huma-Num et **importer des fichiers vers un item, sans montage**.
> 5 tranches, chacune revue à 2 relecteurs :
> - `external/sharedocs/client.py` — client WebDAV (PROPFIND/GET,
>   `EntreeShareDocs`, exceptions). Anti-SSRF (HTTPS exigé, liste blanche
>   d'hôtes, rejet IP interne + `userinfo`, redirections non suivies),
>   anti-traversal (`..`), creds en paramètres explicites (*resolver-ready*
>   V1.0). Testé via httpx `MockTransport` (jamais de réseau réel).
> - `api/services/sharedocs.py` — `importer_depuis_sharedocs` télécharge
>   vers `<racine>/<cote>/<nom>` → `Fichier`. **Décision** : matérialiser
>   dans une racine locale (intrant régénérable) plutôt que référencer à
>   distance (cohérent « DB = source de vérité »). Écriture atomique,
>   idempotence, adoption auto-réparante d'orphelin disque, succès partiel.
> - `config.py` — section `sharedocs:` (base_url HTTPS-validée +
>   `hotes_autorises`). **Les identifiants n'y sont JAMAIS** (cf. décision
>   credentials, `deploiement-future.md`).
> - CLI `archives-tool sharedocs {lister, importer}` (dry-run défaut,
>   `--format json`) ; identifiants via env `COLLEC_SHAREDOCS_USER/_PASS`.
> - Web `/sharedocs` (`api/routes/sharedocs_web.py` + `services/
>   sharedocs_session.py`) — connexion (creds **RAM only**, validés par
>   PROPFIND avant mémorisation, jamais réaffichés/loggés), parcours +
>   fil d'Ariane, sélection + cible + aperçu dry-run → confirmation
>   (bloqué 423 en lecture seule). Lien header `ShareDocs`.
>
> **Aucune dépendance ni couplage runtime à BD_ditor** (copie → possession
> → divergence). Doc : `docs/guide/cli/sharedocs.md`.
>
> **Smoke live ✅ FAIT (2026-06-21)** — connexion + parcours + import validés
> contre le vrai partage `sharedocs.huma-num.fr` (le seul angle jamais exercé
> jusque-là ; tout le reste était couvert via `MockTransport`).
>
> **Durcissement UX de l'import web (2026-06-21, suite au test d'usage)** —
> trois manques relevés en conditions réelles, tous comblés :
> - **Cibles assistées + création inline** : le formulaire d'import propose
>   des `<select>` des fonds/items existants (l'item se recharge en HTMX au
>   changement de fonds via `GET /sharedocs/cible-items`) + une sentinelle
>   « ➕ Créer… » qui révèle des champs cote/titre. La création réelle
>   (`creer_fonds`/`creer_item`) n'a lieu qu'au POST de confirmation, jamais
>   au dry-run (principe n°3) ; l'aperçu signale « sera créé » via un item
>   transitoire non persisté. Plus de cote à deviner, plus de « introuvable »
>   après soumission. Case maître « Tout sélectionner » (JS `sharedocs.js`,
>   délégation d'événements pour survivre aux swaps HTMX).
> - **Import en tâche de fond** (2ᵉ tâche de fond du projet après le dépôt
>   Nakala) : `api/services/sharedocs_jobs.py` (registre mémoire + runner
>   synchrone testable + thread daemon + **garde mono-job indépendante** de
>   `nakala_depot_jobs`). Le POST crée la cible (rapide) puis lance le
>   téléchargement (lent) en thread et redirige vers une page de suivi qui
>   polle en HTMX (`every 2s`) une **barre de progression** (rayures animées
>   « barber pole » + spinner tant qu'en cours, respecte
>   `prefers-reduced-motion`). Hook `on_progress` ajouté à
>   `importer_depuis_sharedocs` (rétro-compatible, commit final conservé).
>   Identifiants passés explicitement au thread (jamais lus d'un global).
> - **Annulation coopérative** : drapeau `annule` sur le job + sonde
>   `should_cancel` vérifiée **entre deux fichiers** (on ne coupe pas un
>   download en cours → arrêt après le fichier courant). Le partiel déjà
>   téléchargé est **conservé** (pas de suppression destructive — l'adoption
>   le récupère) ; statut `annule` + bouton « Reprendre » (re-cible l'item
>   existant, adopte le partiel, continue le reste). Route
>   `POST /sharedocs/importer/annuler/{job_id}`.

### V1 — Socle utilisable pour un premier chantier

**Modèle de données, migrations, CLI minimale** :

- Création de collection, sous-collection, item, rattachement de
  fichier depuis la CLI.
- Import depuis profil YAML (voir session dédiée).
- ✅ Renommage transactionnel avec aperçu et journal.
- Résolution des chemins via racines configurables.
- ✅ Génération de dérivés (vignettes, aperçu moyen).

**Interface web (FastAPI + HTMX + Tailwind)** :

- ✅ Tableau de bord simple (inventaire, alertes) — V0.5.
- ✅ Vue collection avec onglets Sous-collections / Items / Fichiers
  (lecture seule) — V0.6.0.
- ✅ Vue item trois zones (fichiers, visionneuse, métadonnées) en
  lecture seule — V0.6.0.
- ✅ Visionneuse OpenSeadragon (multi-sources : IIIF Nakala > DZI > aperçu local) — V0.6.0.
- ✅ Tri des colonnes des tableaux via HTMX — V0.6.1.
- ✅ Filtre / recherche dans les tableaux items + fichiers (drawer
  latéral, query string) — V0.6.1.
- ✅ Pagination du tableau de fichiers (50/page par défaut) — V0.6.1.
- ✅ Sélection persistée des colonnes du tableau d'items via le panneau
  Colonnes du bundle (drag-drop Sortable.js, `PreferencesAffichage`,
  champs métadonnées dynamiques par collection) — V0.6.3.
- ✅ Création de collection vide depuis l'UI + menu Importer
  (placeholder /import) + breadcrumb fil d'ariane — V0.7-alpha.
- ✅ Page de modification de collection + empty state proactif sur
  collection vide + boutons « Modifier » / « Importer dans cette
  collection » sur le bandeau — V0.7.x.
- ✅ Section Collaborateurs sur la page de modification (vocabulaire
  fermé numérisation/transcription/indexation/catalogage, multi-rôles
  par personne, affichage groupé par rôle, formulaire HTMX) — V0.8.0.
- ✅ Refonte modèle Fonds / Collection (miroir + libre) / Item
  (multi-appartenance) — V0.9.0-alpha. UI/CLI dégradés en attendant
  les sessions de polish.
- ✅ Services Fonds / Collection / Item refondus avec bases
  d'erreurs partagées (`EntiteIntrouvable`, `FormulaireInvalide`,
  `OperationInterdite`), création-item auto-rattachée à la miroir
  (invariant 6), liaisons N-N idempotentes — V0.9.0-alpha.1.
- ✅ Demo seeder reconstruit (5 fonds, 10 collections, 333 items,
  ~1300 fichiers, 1 transversale, collaborateurs) — V0.9.0-alpha.2.
- ✅ Refonte des routes web : dashboard fonctionnel avec
  arborescence dépliable fonds→collections, placeholders pour les
  pages détail, précédence cote ambiguë → `/fonds/{cote}` —
  V0.9.0-beta.1.
- ✅ Pages Fonds + Collection détaillées : bandeau métadonnées,
  collections, collaborateurs (CollaborateurFonds avec CRUD),
  items récents, 3 variantes collection (miroir / libre rattachée
  / transversale), édition fonds — V0.9.0-beta.2.
- ✅ Édition collection libres + tableau items paginé sur la page
  lecture + item picker pour ajouter (multi-id idempotent) +
  bouton retrait par ligne (idempotent, permis sur miroir) —
  V0.9.0-beta.2.1.
- ✅ Page item refondue : bandeau métadonnées, collections
  d'appartenance avec badge miroir/libre/transversale, visionneuse
  navigable (Précédent/Suivant + ?fichier_courant=N bookmarkable,
  `<img>` pour PNG/JPG/GIF/WebP/SVG, fallback message + lien pour
  TIFF/PDF), tableau de fichiers cliquable, édition complète
  (PRG, cote+fonds_id verrouillés/silent override), endpoint
  `/item/{cote}/fichiers/{id}?fonds=COTE` (anti-confused-deputy,
  404 si fichier absent du disque) — V0.9.0-beta.3.
- ✅ Importers v2 : profils avec sections `fonds:` (obligatoire)
  + `collection_miroir:` (optionnelle pour overrides). Rejet
  explicite des profils v1 avec message de migration manuelle
  (`ProfilObsoleteV1`). Écrivain réutilise `creer_fonds`,
  `modifier_collection`, `creer_item` (services métier qui
  garantissent les invariants 1, 5, 6). Nouvelle CLI
  `archives-tool collections {creer-libre,lister,supprimer}`
  (pendant CLI de l'UI V0.9.0-beta.2.1). — V0.9.0-gamma.1.
- ✅ Exporters refondus (Dublin Core XML, Nakala CSV, xlsx).
  Granularité = la collection (miroir, libre rattachée, transversale).
  Helper partagé `composer_export(db, collection)` charge items +
  fichiers + fonds d'origine en une requête. Notice de tête pour la
  collection (titre, cote, DOI, fonds représentés via `dc:source`).
  Pour les transversales, chaque ligne Nakala/xlsx indique son fonds
  d'origine. CLI : `archives-tool exporter {dublin-core,nakala,xlsx}
  COTE [--fonds X] [--sortie ...]`. — V0.9.0-gamma.2.
- ✅ Module qa refondu : 14 contrôles répartis en 4 familles
  (invariants, fichiers, métadonnées, cross). Lecture seule, garantie
  de ne jamais écrire en base. CLI `archives-tool controler [--fonds X
  | --collection Y] [--format text|json] [--strict] [--max-exemples N]`
  avec sortie text Rich (couleurs ✓⚠✗) ou JSON stable (intégration CI).
  Codes de sortie : 0 (RAS), 1 (erreur ou strict avec avertissement),
  2 (saisie invalide). — V0.9.0-gamma.3.
- ✅ CLI `montrer` refondue : 4 sous-commandes (`fonds`, `collection`,
  `item`, `fichier`). Liste si pas de `--cote` (sauf `item` et
  `fichier` qui sont uniquement détail). Format `text|json` partagé
  avec `controler` via l'enum `_FormatRapport`. Réutilise les
  composeurs `composer_page_*` de `services/dashboard.py`. Suppression
  des modules legacy `affichage/{collections,items,fichiers,
  statistiques}.py` qui assumaient l'ancien modèle. — V0.9.0-gamma.4.1.
- ✅ CLI `renommer` adaptée : sélection par `--fonds`, `--collection`
  (+ `--fonds` pour désambiguïser), `--item` (+ `--fonds`),
  `--fichier-id`. Le moteur (template + plan + execution + annulation
  + historique) est largement neutre vis-à-vis du modèle ; refonte
  minimale dans `template.py` (ajout `cote_fonds` / `titre_fonds`,
  `Collection.cote` au lieu de `cote_collection`) et `plan.py`
  (sélection N-N via `ItemCollection`, plus de `recursif`). — V0.9.0-gamma.4.2.
- ✅ CLI `deriver` adaptée : périmètre via `Perimetre` (réutilisé
  du module `renamer`), 4 sélecteurs `--fonds`/`--collection`/`--item`/
  `--fichier-id`, plus de `--recursif`. `_selectionner_fichiers` passe
  par `Item.fonds_id` et la junction `ItemCollection`. Le moteur de
  renommage invalide automatiquement `derive_genere` après chaque
  rename FS pour garder la cohérence des dérivés. — V0.9.0-gamma.4.3.
- ✅ Documentation MkDocs Material avec déploiement GitHub Pages
  automatique. Site `docs/` réorganisé (Premiers pas, Guide
  utilisateur, Référence, Pour développeurs, Annexes). Premiers
  pas complet (Installation / Configuration / Premier import /
  Workflow type), section Contribuer + Changelog initial.
  Workflow `.github/workflows/docs.yml` build + déploie sur
  push main. — V0.9.0-gamma.5.1.
- ✅ Pages utilisateur complétées : `guide/concepts.md`
  (définition canonique Fonds/Collection/Item/multi-appartenance,
  diagramme Mermaid, vocabulaire), `guide/cli/index.md`
  (conventions transversales : périmètres, désambiguïsation,
  codes de sortie, format text/json), `guide/cli/collections.md`
  (3 sous-commandes documentées), `reference/exports.md`
  (mapping DC + colonnes Nakala + structure xlsx),
  `reference/controles.md` (référence détaillée des 14 contrôles
  avec « ce qui est vérifié / pourquoi / comment résoudre »).
  Mermaid configuré via `pymdownx.superfences.custom_fences`.
  `profils_creation.md` supprimé (contenu obsolète v1, déjà
  couvert par `premier-import.md` + `reference/profils.md`).
  `composants_ui.md` reste dans `exclude_docs` jusqu'à
  V0.9.0-gamma.5.3 (relocation vers `developpeurs/composants-ui.md`).
  — V0.9.0-gamma.5.2.
- ✅ Section Pour développeurs complète : `architecture.md`
  (couches, arborescence, patterns), `modele.md` (tables ORM,
  invariants base + code, champs notables), `services.md`
  (composabilité Python avec exemples copiables), `tests.md`
  (organisation, conventions, invariants), `composants-ui.md`
  (intégration des macros Jinja2 réelles, remplaçant
  `docs/composants_ui.md` supprimé). Refactos transverses :
  centralisation des conventions de périmètre dans
  `guide/cli/index.md` (renommer + deriver allégés), séparation
  `guide/cli/exporter.md` vs `reference/exports.md` (la guide ne
  duplique plus les structures). URLs GitHub factorisées via
  `mkdocs-macros-plugin` (variable `{{ repo_main }}`).
  `annexes/limites.md` complet. **V0.9.0 stable** (bump
  `0.9.0rc8` → `0.9.0`). — V0.9.0-gamma.5.3.
- Script de résolution Nakala (peuplement `Fichier.iiif_url_nakala`) — V0.7.
- Édition inline des métadonnées item (sans formulaire de page) — V0.9.1.
- Édition structurelle des champs personnalisés d'une collection
  (créer, renommer, déprécier) depuis l'UI — V0.7.
- Édition des vocabulaires contrôlés depuis l'UI — V0.7.
- Rattachement de fichiers à un item depuis l'UI (ajout depuis
  disque, copie ou déplacement selon la convention) — V0.7.

**Exports canoniques** (fait) :

- ✅ Export Excel / CSV d'une collection (granularité item ou fichier).
- ✅ Export Dublin Core XML (agrégé ou un fichier par item).
- ✅ Export CSV de dépôt Nakala.
- ✅ Rapport de préparation avant export (champs manquants, valeurs
  non mappées vers URI canoniques).
- Export JSON-LD avec contextes COAR et Nakala (reporté).

**Contrôles de cohérence de base** (fait) :

- ✅ Fichiers référencés sans fichier sur disque.
- ✅ Fichiers sur disque sans référence en base.
- ✅ Items sans fichier.
- ✅ Doublons potentiels (même hash).

### V0.9.1 — Renforcement mode local (préparation test d'usage) ✅ livrée

Durcissement avant test d'usage sur un mini-fonds réel. Tous les
items en place :

- ✅ SQLite en mode WAL explicite : `db.py::configurer_sqlite`
  applique `journal_mode=WAL`, `synchronous=NORMAL`,
  `foreign_keys=ON`, `temp_store=MEMORY`, `mmap_size=256MB` à
  chaque connexion via le hook SQLAlchemy `connect`.
- ✅ Verrou optimiste sur `Item`, `Collection`, `Fonds` :
  `TracabiliteMixin.version` mappé en `version_id_col` (SQLAlchemy
  ajoute `AND version=?` au `WHERE` de l'UPDATE). Service
  `api.services.conflits.verifier_et_incrementer_version`
  compare la version du formulaire à celle en base et lève
  `ConflitVersion` si divergence ; contexte manager
  `convertir_stale_data` traduit le `StaleDataError` cross-process
  en la même exception. Intégré dans `modifier_item` /
  `modifier_collection` / `modifier_fonds`.
- ✅ Mode lecture seule activable via `config_local.yaml`
  (`lecture_seule: true`) : middleware `middleware_lecture_seule`
  retourne 423 sur POST/PUT/PATCH/DELETE, bannière `Mode lecture
  seule` dans `base.html` via le filtre Jinja `est_lecture_seule`.
- ✅ Format JSON pour `archives-tool renommer {appliquer, annuler,
  historique}` (parité avec `controler` et `montrer` via l'enum
  partagée `_FormatRapport`).
- ✅ Documentation
  [`docs/premiers-pas/installation-locale-webdav.md`](docs/premiers-pas/installation-locale-webdav.md)
  pas-à-pas Windows / macOS / Linux + sections WAL / verrou
  optimiste / lecture seule / sauvegarde.

**Passe de revue 2026-05-23** (compléments) :

- ✅ `tests/test_db_pragmas.py` — garde-fou que les 5 pragmas SQLite
  sont effectivement appliqués à chaque connexion (si quelqu'un
  casse le hook `_set_pragmas`, le test saute).
- ✅ `ConflitVersion.version_actuelle` accepte `int | None` ; le
  sentinel `None` signale un conflit cross-process dont la version
  réelle n'est pas lisible sans relancer une transaction. Le message
  d'erreur s'adapte (« version actuelle non lisible — race
  cross-process » au lieu du trompeur « version 0 en base »).
  `convertir_stale_data` pose maintenant `None` ; les 3 routes
  consumers (`fonds_modifier` / `collection_modifier` / `item_modifier`)
  + le partial `inline_edit_conflit.html` gèrent le cas.
- ✅ Middleware lecture seule fait du **content-negotiation**
  (`Accept: text/html` → page HTML avec lien retour, sinon JSON).
  Avant, un utilisateur qui soumettait un form sur un poste en mode
  lecture seule voyait `{"detail": "..."}` brut dans le navigateur.

**Passe « trous documentés » 2026-05-23 (Phase A du T1)** :

Les boutons d'édition sont masqués sur les pages les plus visibles
en mode lecture seule, via wrap `{% if not est_lecture_seule() %}`
dans les templates :

- ✅ `pages/fonds_lecture.html` : « Modifier le fonds », « Créer une
  collection libre », formulaire de suppression et d'ajout de
  collaborateur — tous masqués en lecture seule.
- ✅ `pages/collection_lecture.html` : « Modifier » et « Ajouter
  des items » — masqués.
- ✅ `components/bandeau_item.html` : bouton « Modifier » du bandeau
  item — masqué.
- ✅ `pages/item_lecture.html` : `inline_edit.js` n'est plus chargé
  en lecture seule (les hooks `data-edit-field` restent dormants —
  l'utilisateur ne peut plus ouvrir un input par accident).
- ✅ `pages/import_accueil.html` : bouton « Nouvel import » remplacé
  par un message explicite (« imports désactivés »), bouton
  « Abandonner » sur les sessions en cours également masqué.

Tests `test_lecture_seule.py` enrichis : 4 nouveaux tests
intégration sur DB peuplée (fixture `client_demo_lecture_seule`
combinant `peupler_base` + config `lecture_seule: true`).

**Phase B 2026-05-23 (pages modifier)** :

- ✅ `pages/fonds_modifier.html`, `pages/collection_modifier.html`,
  `pages/item_modifier.html` : le bouton « Enregistrer » est
  remplacé par un message explicite « Enregistrement désactivé
  (mode lecture seule) » et « Annuler » devient « Retour ». Si
  l'utilisateur arrive par URL directe (ex. bookmark) ou en
  développant les flux de redirection, il voit le formulaire en
  consultation mais ne peut plus soumettre.

**Phase C 2026-05-23 (composants + étapes import)** :

- ✅ `components/panneau_colonnes_modale.html` : boutons
  « Appliquer » et « Réinitialiser » masqués en lecture seule
  (préférences UI restent visualisables, sauvegarde désactivée).
  Le bouton « Annuler » devient « Fermer ».
- ✅ `pages/items_picker.html` : bouton « Ajouter à la collection »
  remplacé par message ; « Annuler » devient « Retour ».
- ✅ Étapes internes import (6 fichiers : `tableur`, `fonds`,
  `mapping`, `mapping_simple`, `fichiers`, `apercu`) : le bouton
  d'avancement de chaque étape est remplacé par le message
  « Import désactivé (mode lecture seule) ». Sur `import_etape_tableur`,
  le bouton « Abandonner cet import » est aussi masqué (cohérent
  avec l'accueil).
- ✅ Tests : 2 nouveaux dans `test_lecture_seule.py`
  (`test_import_etape_tableur_desactive_en_lecture_seule` crée une
  `SessionImport` directement en base — le POST `/import/nouveau`
  étant bloqué — et vérifie le rendu).

**Dead code identifié pendant la passe** :

- `pages/collection_nouvelle.html` : template sans route active
  (création de collection libre passe par d'autres flux). Modifié
  pour cohérence en lecture seule, mais inaccessible via URL.
  **MAJ : plus vrai** — les routes GET/POST `/collections/nouvelle`
  existent (`routes/dashboard.py`) et sont liées depuis
  `menu_importer.html`. Le template est donc vivant.
- `components/section_collaborateurs.html` + `partials/_formulaire_collaborateur.html` :
  utilisaient l'ancienne route `collaborateurs.py` archivée en
  V0.8 (CLAUDE.md note explicite). Non touchés — dette V0.8.

**T1 désormais entièrement résolu.** Les seuls boutons de mutation
qui restent cliquables en lecture seule sont les bookmarks
hypothétiques vers l'ancienne route collaborateurs (dette V0.8,
non mountée).

**Polish C + D 2026-05-23 (trous T2/T3/T4/T5/T9 + dead code V0.8 + drag-drop lecture seule)** :

- ✅ **Dead code V0.8 supprimé** : `routes/collaborateurs.py`,
  `services/collaborateurs.py`, `templates/components/section_collaborateurs.html`,
  `templates/partials/_formulaire_collaborateur.html`,
  `templates/pages/collection_nouvelle.html`, `tests/test_collaborateurs.py`.
  Tous référençaient la route `collaborateurs.py` archivée V0.8 et
  jamais montée par `main.py`. Le modèle `CollaborateurCollection`
  + la relation `Collection.collaborateurs` restent (utilisés
  potentiellement par les exports). `conftest.py::collect_ignore`
  nettoyé en conséquence.
- ✅ **T3 — centralisation pattern cote** :
  `profils.generateur.PATTERN_COTE` exporté, importé dans
  `importers.lecteur_tableur` (`_identifier_colonne_cote`).
  Plus de duplication littérale du regex — un seul endroit pour
  faire évoluer le pattern.
- ✅ **T5 — a11y bandeau anomalies** : `role="region"` +
  `aria-label="Anomalies de mapping détectées"` sur
  `import_etape_mapping.html` (bandeau mode avancé). `role="alert"`
  + `aria-label` sur le bandeau « champs avancés perdus » dans
  `import_etape_mapping_simple.html`.
- ✅ **T9 — distinguer None vs ""** dans le macro
  `select_colonne` du mode simple : `valeur_active is none` pose
  la suggestion (première visite), `valeur_active == ""` respecte
  un choix « Aucune » explicite (re-render après erreur).
- ✅ **T4 — « Garder » persistant via localStorage** : le bouton
  « Garder le choix actuel » du bandeau anomalies stocke
  `{colonne, classif}` dans `localStorage.colleC-import-{sid}-
  anomalies-acceptees`. Au prochain rendu, `anomalies.js` filtre
  les `<li>` déjà acceptées. Scope par session — une autre import
  ne re-affiche pas les anomalies acceptées ailleurs. Le bandeau
  porte `data-session-id` ; les `<li>` portent `data-classif`.
- ✅ **Drag-drop Sortable désactivé en lecture seule** :
  `panneau_colonnes_modale.html` pose `data-lecture-seule="1"` ;
  `panneau_colonnes.js` skip `Sortable.create()` si l'attribut est
  présent. L'utilisateur ne peut plus déplacer visuellement les
  colonnes sans pouvoir sauver (UX trompeuse fermée).
- ✅ **T2 — double lecture du tableur** : `attacher_tableur` ne
  lit plus le tableur deux fois (`nrows=1` + `nrows=5000`). Une
  seule lecture via `analyser_colonnes_tableur`, les colonnes sont
  dérivées de `list(echantillons.keys())`. Économise ~1s d'upload
  sur PF.

**Skip décisions documentées** :
- **T7** : validation serveur cote/titre/date différentes — déjà
  couvert côté service via `construire_mapping_depuis_simple`.
  Test de garde-fou existant suffit, pas besoin de validation
  HTML supplémentaire.
- **T8** : récap « N autres colonnes » figé sur suggestions —
  nécessiterait du JS qui réagit aux changements de selects.
  Coût UI > valeur (informationnel pur, l'utilisateur quitte la
  page après submit).
- **Macro Jinja `action_mutation`** : refusée définitivement —
  le pattern inline `{% if est_lecture_seule() %}<span>...</span>
  {% else %}<button>...</button>{% endif %}` est plus lisible
  que la macro paramétrée (qui devrait recevoir style/classes/
  label/message à chaque appel — pas de DRY réel).

**Passe de revue Phase C 2026-05-23** :

Trouvaille principale : le `<form method="post">` reste ouvert sur les
pages en lecture seule (bouton submit masqué, mais form actif). Si
l'utilisateur appuie sur Entrée dans un `<input type="text">`, le
navigateur déclenche le submit DOM par défaut — le middleware bloque
en 423, mais l'écran devient moche. Filet de sécurité ajouté dans
`base.html` : un listener global `addEventListener("submit", ...)` qui
intercepte tous les submits POST en amont quand `est_lecture_seule()`
est vrai. Un seul fix, couvre les ~11 formulaires de mutation. Les
requêtes HTMX (`hx-post`) passent par leur propre canal et ne sont
pas concernées — leurs boutons sont déjà masqués en template.

Tests `test_filet_securite_javascript_present_en_lecture_seule`
+ `_absent_en_mode_normal` (pas de surcoût en mode normal).

**Trouvailles laissées non corrigées dans cette passe** :

- Drag-drop Sortable sur `panneau_colonnes_modale.html` reste actif
  en lecture seule (l'utilisateur peut réordonner visuellement, mais
  « Appliquer » masqué → rien n'est sauvé). UX dégradée mais sans
  effet de bord. Pour fixer proprement : conditionner le chargement
  de Sortable côté template ou ajouter un check côté JS.
- Pattern `{% if est_lecture_seule() %}<span>...</span>{% else %}<button>...</button>{% endif %}`
  dupliqué ~11 fois. Refactor possible en macro Jinja
  `action_mutation(label, style, ...)` — bénéfice maintenabilité,
  coût modéré, repoussé.

### V0.9.2 — Restauration ergonomique des pages détail

Cible : 3 sous-sessions courtes (alpha / beta / gamma). Lancée en
parallèle de V0.9.1, déclenchée par l'audit ergonomique
(`audit_ui_v0_9_0.md`) qui a constaté que les composants riches
du bundle Claude Design V0.6.0.1 n'étaient plus utilisés sur les
pages Fonds, Collection et Item.

- ✅ **V0.9.2-alpha** : page Fonds restaurée. `composer_page_fonds`
  enrichi (`repartition_etats`, `modifie_par`/`le` propagé depuis
  les items, `nb_fichiers` par fonds + par collection). Bandeau
  avec `avancement_detaille` + `cellule_modifie`. Liste collections
  via `tableau_collections`. Composant `phase_chantier` branché sur
  dashboard et page Fonds. Garde-fou SQL ≤ 9 requêtes par rendu.
  Helpers `_agreger_repartition` et `_plus_recent` factorés.
- ✅ **V0.9.2-beta** : page Collection restaurée. Bandeau enrichi
  (`avancement_detaille`, `phase_chantier`, `cellule_modifie`,
  compteurs items/fichiers/langues). Tableau d'items via
  `tableau_items` (pagination intégrée + boutons
  Filtrer/Colonnes/Exporter). Service
  `composer_page_collection` enrichi avec `repartition_etats`,
  traçabilité, `nb_fichiers`, `OptionsFiltresCollection`
  dynamiques. `ItemResume` étendu + propriétés alias attendues
  par `tableau_items`. Bug pré-existant `phase` enum brut dans
  `tableau_collections` corrigé. Garde-fou SQL ≤ 7 requêtes.
- ✅ **V0.9.2-beta.2** : filtres multi-valeurs branchés sur la
  page Collection. `parser_filtres_collection` (dataclass
  `FiltresCollection`, validation silencieuse contre les options
  dynamiques de la collection — états hors enum, langues
  inexistantes, types inconnus, années hors plage sont écartés
  sans erreur). `lister_items_collection` étendu (état IN,
  langue IN, type IN, plage d'années). Formulaire de filtres
  étendu (4 dimensions, multi-select), pastilles de filtres
  actifs avec retrait individuel, compteur dans le bouton
  « Filtrer ». Pagination préserve les filtres dans tous les
  liens (`cible_url` injecté avec query string complète).
  Test de régression `date_incertaine` ajouté pour le bug HIGH
  V0.9.2-beta. Drawer `panneau_filtres` riche et `panneau_colonnes`
  drag-drop reportés à V0.9.2-beta.3 (JS plumbing).
- ✅ **V0.9.2-beta.3** : drawer animé `panneau_filtres` (CSS pur
  via attribut `data-ouvert`, fermeture ESC + croix, slide-in
  200ms, backdrop semi-transparent) à la place du `<details>`
  collapsible. Drawer modale `panneau_colonnes` avec drag-drop
  Sortable.js (vendor 1.15.2) et boutons activer/désactiver/
  réinitialiser ; persistance via `PreferencesAffichage` (par
  utilisateur + collection + vue). HTMX 1.9.10 ajouté en vendor
  et inclus dans `base.html` — active aussi le tri d'en-têtes
  qui était dormant. Le service `preferences_colonnes` est
  migré au modèle V0.9.0 (junction `ItemCollection` au lieu de
  `Item.collection_id`) et `tests/test_preferences.py` est
  réactivé (était en `collect_ignore`). Le bouton « Colonnes »
  du tableau ouvre la modale via `hx-get`, le POST swap
  `#tableau-items` avec `HX-Trigger: panneau-colonnes-ferme`
  qui ferme la modale côté client. La cote `cote` reste
  obligatoire — réinjectée silencieusement si l'utilisateur
  tente de la décocher (défense en profondeur). +23 tests
  verts (514 au total).
- ✅ **V0.9.2-gamma** : page Item refondue en layout 3 zones
  (panneau fichiers gauche escamotable, cartouche métadonnées
  centre 460px, visionneuse droite flex-1). Trois composants
  recréés sous `components/` : `bandeau_item.html` (breadcrumb +
  cote + titre + badge état + meta + Précédent/Suivant),
  `cartouche_metadonnees.html` (4 sections repliables :
  Identification / Champs personnalisés / Identifiants externes /
  Description, hooks `data-edit-cle` / `data-edit-type` posés
  pour l'édition inline V0.7+), `panneau_fichiers.html` (CSS pur
  3 états collapsed/hover/pinned, vignettes, détection des sauts
  d'ordre). Visionneuse `OpenSeadragon` (vendor 4.x) instanciée
  par `visionneuse_osd.js` via `data-source` sérialisé ; fallback
  open-failed → secondary source puis message + télécharger.
  Service `composer_page_item` enrichi : `metadonnees_par_section`
  (4 sections, DOI rendus en lien cliquable, listes en CSV),
  `navigation_items` (préc/suiv triés par cote dans la miroir du
  fonds), `FichierResume.source_image` pré-résolu via
  `resoudre_source_image`. Router `derives` mounté sur `/derives`
  pour servir les aperçus locaux. Garde-fou SQL ≤ 8 requêtes.
  +14 tests verts (529 au total).

### V0.9.3 — Recherche full-text + livrables transversaux ✅ livrée

Voir `docs/annexes/changelog.md` V0.9.3 stable (2026-05-25) :
recherche FTS5, mode « tout afficher », filtres avancés, libellés
humains COAR/langue, layout responsive, raccourcis clavier, polish
des cartes dashboard, doc liseuse + import-assistant.

### V0.9.4 — Champs personnalisés + vocabulaires UI ✅ livrée

Workflow champs personnalisés bouclé bout-en-bout. Comble le gap
V0.7 backlog identifié pendant le test PF (l'import dumpait toutes
les colonnes hors socle DC en clés libres dans `Item.metadonnees`
sans aucune UI pour les formaliser).

- **Lot 1** : CRUD `ChampPersonnalise` depuis l'UI
  (`/collection/<cote>/champs?fonds=<f>`) — créer / renommer (avec
  propagation aux items) / déprécier (toggle `actif`) / réactiver
  / supprimer. Migration `n2r3s4t5u6v7` ajoute la colonne `actif`.
- **Lot 2** : bouton « Formaliser » sur les clés libres du cartouche
  → crée un `ChampPersonnalise` sur la miroir du fonds avec libellé
  synthétisé via `_libelle_depuis_cle`. Idempotent (re-clic
  retourne le champ existant), refus silencieux des clés à slug
  invalide (filtré côté composer). Race protection via try/except
  `IntegrityError` qui recharge l'existant.
- **Lot 3a** : CRUD vocabulaires personnalisés depuis l'UI
  (`/vocabulaires`) — service `vocabulaires_db.py`, `Vocabulaire` +
  `ValeurControlee` (créer / modifier / déprécier / supprimer).
  Distinct des vocabs hardcoded (`LANGUES_OPTIONS`,
  `TYPES_COAR_OPTIONS`, `ETATS_OPTIONS`) qui restent figés en code.
  Suppression d'un vocab référencé refusée (`VocabulaireReference`).
- **Lot 3b** : wire `ChampPersonnalise.valeurs_controlees_id` depuis
  les formulaires de création / modification d'un champ.
- **Lot 3c** : composer cartouche résout le libellé humain depuis
  le vocab DB (« Bande dessinée » pour le code « bd » stocké en
  `metadonnees`). Eager loading
  `selectinload(vocabulaire).selectinload(valeurs)` pour éviter N+1.
- **Lot V0.9.5** : `/item/<cote>/modifier` expose une section
  « Champs personnalisés ». Route POST passée en `async` pour
  relire `request.form()` après le parse Pydantic (les noms
  `meta_<cle>` sont dynamiques). Rendu selon `TypeChamp` :
  `liste_multiple` → checkboxes, `liste` → select, `texte_long` →
  textarea, `nombre` → `<input type="number">`, `texte` /
  `date_edtf` / `reference` → input texte. Valeur vide = clé
  supprimée (cohérent avec import + cartouche).
- **Polish transversal libellé humain** : `ItemResume.type_label`
  via `TYPES_COAR_OPTIONS`, pastilles + drawer filtres Collection,
  colonne Langue du `tableau_items`, formulaire item modifier.
  Macro `selecteur` étendue avec `libelle_vide` (option
  `value=""`) et fallback hors-liste (valeur courante absente du
  vocab → ajoutée en queue avec suffixe).
- **Polish UX** : lien « Gérer » discret sur le header de la
  section « Champs personnalisés » du cartouche →
  `/collection/<miroir>/champs` (résout la friction « 4 clics pour
  refiner après Formaliser »). `obligatoire=True` ajoute l'attribut
  HTML5 `required` sur input / textarea / select.

Bug fix latent : `m1q2r3s4t5u6_fts5_recherche.upgrade` rendu
idempotent face aux triggers FTS5 déjà créés par
`assurer_tables_fts` au startup. `ajouter_valeur` passe par la
relation (`vocab.valeurs.append`) au lieu de la FK seule —
SQLAlchemy back-populate auto, sinon `vocab.valeurs` restait stale
dans la session courante et le composer manquait les valeurs
nouvellement ajoutées dans la même requête.

### V0.9.6 — Synthèse + édition inline complète ✅ livrée

Chantier UX dirigé par les tests d'usage Por Favor. Deux angles
morts d'orientation comblés : (a) synthèse au-dessus des tableaux
d'items sur collection ET fonds ; (b) édition inline complète sur
les 3 entités (item / collection / fonds).

- **Synthèse collection** : composant `synthese_collection.html`
  rendant Identifiants (DOI Nakala + DOI parent inline), Période
  (mini-timeline avec barres + comptes + labels d'année), Agrégats
  qualitatifs (Langues, Types, top 6 méta items), Vignettes
  échantillonnées (12 max), Trous catalographiques (sans titre /
  sans année / sans fichier / à corriger), Activité récente (5
  derniers items modifiés). Cap top 5 par agrégat, rendu compact
  pour les agrégats à 1 valeur (« Langue : Espagnol (172) »).
- **Synthèse fonds** : composant `synthese_fonds.html` réutilisant
  les helpers de la synthèse collection (portés à tous les items
  via `Item.fonds_id`) + nouveau bloc **Cartographie cross-collection**
  : barre proportion + nb items + nb partagés par collection,
  toujours visible (même 1 miroir), DOI cliquable vers nakala.fr.
  Plus un **bloc Identifiants revue** (8 champs : Éditeur, Lieu,
  Périodicité, ISSN, Début, Fin, Responsable, Personnalité)
  inline-éditables, opacity:0.55 + « + ajouter » sur les vides.
- **Inline edit complet** : `CHAMPS_COLLECTION_EDITABLES_INLINE`
  (15 champs) + `CHAMPS_FONDS_EDITABLES_INLINE` (12 champs). Routes
  POST `/collection/<cote>/champ/<field>` et `/fonds/<cote>/champ/<field>`.
  Meta `<meta name="entity-context">` (rebaptisé depuis `item-context`,
  avec fallback compat). Partial `inline_edit_valeur.html` rendu
  générique. Hors whitelist (page Modifier) : cote, version,
  fonds_id, type_collection.
- **Heuristiques anti-bruit** sur la synthèse :
  - Blacklist `_META_ITEM_TECHNIQUES_SYNTHESE` (num_files, hash,
    sha256, data_url, iiif_url, categories…) — fingerprints Nakala.
  - Filtre identifiants : champ dont valeur la plus fréquente apparaît
    ≤ 1 fois ET ≥ 5 distinctes est écarté (`ancienne_cote` PF).
  - `_LANGUES_ISO1_VERS_ISO3` : fallback défensif `es` → `spa` →
    « Espagnol » (Nakala/DC exportent en ISO 639-1).
  - `_annee_depuis_date_edtf` : derive l'année depuis `Item.date`
    si `Item.annee` NULL (cas import Nakala).
- **Bascule URL fiche item V0.9.5 formellement livrée** : 6 tests
  `test_page_item_lecture_*` qui pointaient encore sur l'ancienne
  URL `/item/<cote>` (qui rend la fiche depuis V0.9.5) basculés
  vers `/item/<cote>/visionneuse`. Pleine suite passe désormais
  (1090/1090 verts — première fois depuis 8 mois).

Garde-fous SQL : synthese fonds ≤ 10 queries, synthese collection
≤ 7 queries. +85 tests au total (synthese collection 28, fonds 13,
inline edit étendu 14, fiche item maintien 30+).

### V0.9.7 — Création en série + annotations IIIF ✅ livrée

Deux chantiers groupés sous V0.9.7 (tag stable après les deux) :

**Création en série d'items ✅ livrée** —
[`plan-de-chantier.md`](docs/developpeurs/plan-de-chantier.md).
Combler le manquant : préparer N fiches d'items placeholders avant
numérisation, pour pouvoir y rattacher les scans au fil. La création
unitaire via l'UI est rebutante pour 60+ items, et le pipeline
d'import Excel est lourd quand on veut juste pré-créer une plage de
cotes.

- **Service** `creer_items_en_serie` (`services/items.py`) :
  pattern Python `str.format` avec variable `{n}` (ex
  `PF-{n:03d}`), plage `de_n..a_n` (inclus, cap dur 1000), titre
  template optionnel (`Numéro {n}`), valeurs par défaut
  `etat`/`type_coar`/`langue`. Résolution collection : miroir par
  défaut, libre rattachée ou transversale. Invariant 6 respecté
  (rattachement miroir auto si cible libre). Validation conflits
  en amont (SELECT) + détection doublons intra-série (pattern
  sans `{n}` → ItemInvalide explicite). `ignorer_existants` pour
  la rejouabilité. Transactionnel, rollback complet si erreur
  mid-bulk. `RapportSerieItems(crees, ignores)`.
- **CLI** `archives-tool items creer-serie --fonds PF --pattern
  "PF-{n:03d}" --de 1 --a 60 --titre "Por Favor n°{n}"` — sub-app
  `items` enregistrée sur l'app principal. Options exhaustives,
  codes de sortie 0/1/2 standard.
- **UI** `/collection/<cote>/items/serie?fonds=X` : formulaire
  avec pattern pré-rempli sur la cote (`{cote}-{n:03d}`),
  validation côté serveur, re-render avec erreurs si invalides.
  POST réussi redirige avec flash `serie_crees=N` lu par la page
  collection. Bouton **+ Créer une série** sur la page collection
  (miroir + libres rattachées). Masqué sur transversales et en
  lecture seule. Middleware bloque le POST direct (423 Locked).

27 tests (15 service, 6 CLI, 9 UI dont 4 garde-fou : transversale,
lecture seule pour le bouton + le POST).

**Annotations IIIF ✅ α + β + γ + δ livrés** —
[`annotations-image-future.md`](docs/developpeurs/annotations-image-future.md).
Module d'annotation d'image conforme W3C Web Annotation Data Model
+ IIIF Presentation API 3. Cible : chantier Por Favor (identifier
les dessinateurs, marquer caricatures avec lien Wikidata,
indexation à la granularité région).

- **Modèle** `AnnotationRegion` (`models/annotation.py`) : FK
  CASCADE sur Fichier, `selecteur` (text), `selecteur_type`
  (`fragment` | `svg`), `corps` (JSON liste de bodies W3C),
  `motivation` (text). TracabiliteMixin standard. Index
  `(fichier_id, cree_le)` pour listing chronologique. Relation
  `Fichier.annotations` avec cascade delete-orphan.
- **Migration Alembic** `o3s4t5u6v7w8` idempotente (skip si table
  déjà créée via Base.metadata.create_all).
- **Service** `services/annotations.py` : CRUD avec verrou
  optimiste. `FormulaireAnnotation` (Pydantic) avec validators
  stricts (`motivation` ∈ `MOTIVATIONS_W3C` 13 valeurs standard,
  `selecteur_type` ∈ `{fragment, svg}`). Sérialisation W3C
  JSON-LD à la volée — jamais stockée. Omet les champs
  optionnels (`creator`, `modified`) quand absents (W3C strict).
- **5 routes REST** sous `/api` : GET liste, POST création, GET
  unitaire, PUT modification (verrou optimiste, 409 si conflit),
  DELETE idempotent (204). POST/PUT acceptent forme simple OU
  forme W3C native (target/body) — un client Annotorious peut
  envoyer son JSON-LD natif sans conversion.

- **β — Annotorious sur OSD** (commit `ce468dd` + 4 polish) :
  plugin `@recogito/annotorious-openseadragon` 2.7 ajouté au
  `package.json`, copié via `scripts/vendor.mjs` vers
  `static/js/vendor/annotorious/`. Script `annotations_osd.js`
  écoute `visionneuse:pret` émis par `visionneuse_osd.js` et
  greffe Annotorious sur l'instance OSD ; charge les annotations
  existantes via `GET /api/fichiers/<id>/annotations` au load.
  Bouton « Annoter » flottant coin haut-droite (haut-gauche est
  occupé par les contrôles natifs OSD) du viewer item, masqué
  sur PDF et en lecture seule. Toggle bascule `anno.readOnly` +
  `setDrawingTool("rect")`. Events Annotorious `createAnnotation`
  / `updateAnnotation` / `deleteAnnotation` POSTent / PUTent /
  DELETEnt vers l'API REST α — l'API accepte la forme W3C native
  donc aucune conversion client. L'`id` retourné par le POST
  remplace l'id temporaire d'Annotorious pour que les updates
  ultérieurs ciblent la bonne ressource. β est livrée sur la
  page `/item/<cote>/visionneuse` (catalogage). La fiche
  `/item/<cote>` et la liseuse `/lire/...` ne chargent pas
  Annotorious.

- **γ — Panneau latéral + autocomplete vocabulaire + pivot URI**
  (commits `691203d` + `784b227`) :
  - γ.1 — Panneau flottant en haut-droite sous le bouton Annoter
    (`<aside data-panneau-annotations>`), liste numérotée du fichier
    courant, synchronisée via `rafraichirPanneau` à
    create/update/delete. Clic = `anno.selectAnnotation(id)` +
    `anno.fitBounds(annotation)` → zoom OSD sur la région et popup
    d'édition ouvert. Auto-masqué (`data-vide="1"`) quand 0
    annotations. Rendu HTML même en lecture seule (préparé pour
    futur lot consultation sans JS lourd Annotorious 380 Ko).
  - γ.2 — `ValeurControlee.uri` existait déjà sur le modèle, le
    formulaire service (`FormulaireValeurControlee.uri`) et la page
    UI `/vocabulaires/<id>` (champ « URI canonique »). Pas
    d'ajout — γ.2 ✓ par construction.
  - γ.3 — Endpoint `GET /api/vocabulaires/autocomplete` qui liste
    toutes les `ValeurControlee` actives (libellé, code, URI,
    vocabulaire racine) — 1 requête léger, alimentation client.
    `annotations_osd.js` précharge via `_vocabReady` Promise (race
    fix : l'init Annotorious await avant d'instancier le widget
    TAG). Widget TAG natif Annotorious configuré avec
    `vocabulary: _vocabLibelles` → suggestions à la frappe.
    `enrichirBodiesAvecUri` parcourt les `TextualBody` au
    create/update et, si le `value` matche une `ValeurControlee`
    connue avec URI (matching normalisé NFD-lowercase), ajoute un
    body `SpecificResource purpose=identifying source=<URI>`
    (idempotent contre la duplication). Pivot Wikidata/VIAF prêt
    pour l'export Nakala δ.

25 tests α annotations + 9 tests β + 3 tests γ (panneau présent
sur image, absent sur PDF, rendu en lecture seule) + 2 tests
γ.3 (POST avec body SpecificResource roundtrip, endpoint
autocomplete avec filtrage actif=true). 43 tests annotations au
total.

- **δ — Export Nakala JSON W3C** (commit en cours) :
  `serialiser_annotation_collection_w3c` enveloppe la liste
  `lister_annotations_collection` (ou `..._item`) dans un W3C
  AnnotationCollection avec un seul AnnotationPage. Format conforme
  à la spec W3C Web Annotation §6.3 + IIIF Presentation API 3 :
  `@context`, `id`, `type=AnnotationCollection`, `label`, `total`,
  `first.{id, type, partOf, items}`. Le pivot URI Wikidata présent
  dans `body.source.id` (créé par γ.3 via Annotorious natif) est
  préservé tel quel dans l'export — utilisable directement par
  Mirador / Recogito / portail futur.
  CLI : `archives-tool exporter annotations <cote_collection>
  [--fonds X] [--sortie path.json]`. URI canonique du
  AnnotationCollection : DOI Nakala de la collection si publié,
  sinon URI relative locale (à remplacer manuellement après dépôt
  Nakala).
- **Bonus γ-fiche** (commit `83eb98f`) : remplace le placeholder
  « Annotations IIIF (V2) » de la fiche notice `/item/<cote>` par
  la liste des tags agrégés depuis tous les fichiers de l'item
  (TagAnnotationAgrege libellé/uri/nb). Tri fréquence desc + alpha,
  libellé clickable vers l'URI si présente (Wikidata/VIAF).
  Dédup par (libellé, uri) pour distinguer un tag libre « Copi »
  d'un tag Wikidata « Copi ». Vue d'ensemble du catalogage sur la
  notice sans devoir ouvrir page par page.

48 tests annotations au total (α + β + γ + δ + γ-fiche).

**Suppression d'entités depuis l'UI** (suite du chantier V0.9.7) —
manque historique comblé : le projet avait des CRUD complets partout
sauf le D pour fonds / collection / item. Trois routes
`POST /<entité>/<cote>/supprimer` ajoutées dans
`api/routes/dashboard.py` pour fonds / collection libre+transversale /
item, plus une zone de suppression rouge en bas de chaque page
`/_/<cote>/modifier`. Double-confirmation par recopie de la cote
(`confirmer` form param = `cote`, sinon 400). Bouton submit
désactivé côté client tant que l'input ne matche pas
(`static/js/zone_suppression.js` lit `data-cote-confirmer` sur le
form). Lecture seule bloquée par le middleware en amont (423).
Miroir refusée par le service `supprimer_collection_libre`, et la
page modifier d'une miroir était déjà en 403 via `_refuser_si_miroir`
→ l'utilisateur ne peut pas atteindre la zone. Cascade ORM
existante (déjà bien faite côté modèles) : fonds → items + miroir +
collaborateurs (libres rattachées deviennent transversales via
FK ON DELETE SET NULL), collection libre → junctions item_collection
seules (items survivent dans leur fonds + miroir + autres
collections), item → fichiers + annotations + junctions.

Dette identifiée et documentée :
- Pas de verrou optimiste sur delete (cohérent avec les autres
  delete du projet : champ, collaborateur, vocabulaire).
- Pas de journal pour les delete d'entités (cohérent avec
  l'existant — la dette est globale au projet, principe directeur
  n°4 demande journal des opérations destructives mais
  `OperationFichier` ne couvre que les opérations sur fichiers).
- Pas de redirect avec flash en cas de 400 confirmation invalide
  (JSON brut affiché ; mitigé par la garde client-side qui
  empêche le submit en cas de typo).
- Pas de suppression de fichier individuel (ni route, ni UI).
- Pas de multi-sélection / lot.

16 tests dédiés dans `test_suppression_entites.py` : happy path
par entité + cascade items-survivent sur libre + confirmation
invalide + lecture seule (423) + miroir refusée + zone absente en
lecture seule + attribut `data-cote-confirmer` présent + 404 sur
cote inconnue + 403 sur la page modifier d'une miroir.

**Menu « Importer » dans le header** (V0.9.7) — autre manque
historique : `components/menu_importer.html` existait depuis V0.7+
(dropdown listant `/import` et `/collections/nouvelle`) mais
n'était inclus par aucune page. Inclus maintenant dans
`components/header.html` (donc visible sur toutes les pages via
`base.html`), masqué en lecture seule. `static/js/menu_importer.js`
chargé globalement (inerte sans bouton à toggler).

**CLI suppression** (suite V0.9.7) — symétrie côté CLI ajoutée
maintenant que les routes web existent : `archives-tool fonds
supprimer COTE [--yes]` (cascade complète : items + fichiers +
miroir + collaborateurs, libres rattachées deviennent
transversales) et `archives-tool items supprimer COTE --fonds COTE
[--yes]` (cascade fichiers + annotations + junctions). Confirmation
interactive par défaut avec récap des cascades attendues (« N
item(s) + N fichier(s) seront supprimés »), `--yes` pour scripts.
Réutilise les services backend partagés avec les routes web. 6
tests dans `test_cli_suppression.py`.

**Test suite** — fix collatéral de la fixture `test_lecture_seule.py`
qui ne settait jamais `ARCHIVES_DB` : la fixture retombait sur
`data/archives.db` (défaut) qui n'existe pas sur un checkout propre
→ `OperationalError: no such table: fonds` sur 8 tests qui rendent
des pages (dashboard, /import). Fix : helper `_amorcer_base_vide`
qui crée une SQLite avec le schéma seul (sans peupler — ~50× plus
rapide que `peupler_base`, suffit pour ces tests qui ne consultent
pas de données). **1180/1180 verts** sur ce poste pour la première
fois.

### V0.9.8 — Année dérivée de la date EDTF

Friction relevée au catalogage : `Item.annee` (colonne numérique
indexée, utilisée par les filtres de période, la timeline de
synthèse et `META-ANNEE-IMPLAUSIBLE`) était un champ saisi à la
main *en plus* de `Item.date` (EDTF). Double saisie source de
désynchronisation silencieuse (date `1969-09` mais année oubliée à
`1968`).

Décision : **`annee` devient entièrement dérivée de `date`** à
chaque enregistrement. Plus de saisie directe dans l'UI.

- **Helper** `annee_depuis_date_edtf` (`services/items.py`) :
  déplacé depuis `dashboard.py` (qui le ré-importe désormais sous
  l'alias `_annee_depuis_date_edtf` — les call sites timeline /
  synthèse inchangés). Extrait l'année d'une date EDTF tolérante
  (`1974`, `1974-03`, `1974-03-11`). Retourne `None` sur l'imprécis
  (`vers 1974`, `19XX`, `s.d.`) **et hors plage plausible**
  (`[ANNEE_MIN=0, ANNEE_MAX=3000]`) — BCE `-0044` ou aberrante
  `9999` : la date garde son texte, l'index reste vide, QA signale.
  **Borne partagée avec le validateur** `FormulaireItem._annee_borne`
  (constantes `ANNEE_MIN`/`ANNEE_MAX`) : `annee` étant dérivée
  *après* la validation Pydantic, une valeur hors plage écrite ici
  casserait le round-trip `formulaire_depuis_item` au prochain
  chargement (ValidationError → édition impossible). L'ancienne
  implémentation renvoyait par ailleurs `None` sur `-0044`
  (`split("-")[0]` → `""` → `ValueError`) — bug latent jamais
  déclenché car l'année n'était alors pas écrite.
- **`_appliquer_formulaire`** (3 branches, dans l'ordre) :
  1. date parse en année → `item.annee` synchronisée (la date fait
     autorité, écrase une `annee` de formulaire contradictoire) ;
  2. date imprécise/vide + `formulaire.annee` fourni (CLI, API,
     import) → on l'utilise ;
  3. date imprécise/vide + rien → on conserve `item.annee`
     existant (préserve les imports legacy où seule `annee` était
     peuplée — une modif sur date incertaine ne l'efface pas).
- **UI** `item_modifier.html` : l'input Année devient `disabled`
  (lecture seule, fond grisé, libellé « Année (indexée, auto) » +
  aide « Dérivée de la date à l'enregistrement »). `annee` retirée
  de `CHAMPS_ITEM_EDITABLES_INLINE` (plus d'édition inline du
  cartouche) ; libellé `_LIBELLES_IDENTIFICATION` passé à
  « Année (auto) ».
- **Rafraîchissement inline de l'année** : `date` reste éditable
  inline dans le cartouche ; comme `annee` en dépend, la route POST
  `/item/<cote>/champ/date` renvoie l'année recalculée dans
  `data-annee-derivee` (attribut caché du fragment) et `inline_edit.js`
  repeint la cellule lecture seule `[data-edit-field="annee"]` sans
  reload (même pattern que `rafraichirBadgeEtatItem` pour l'état). La
  valeur transportée est la vérité base après save (préservée si la
  date est imprécise), vide → rendu « non renseigné ». Le hint n'est
  émis que pour `field == "date"` côté item.

7 tests dans `test_items.py` (helper EDTF : imprécis + hors-plage
BCE/aberrante → None, dérivation à la création, 3 branches de
`_appliquer_formulaire`, régression round-trip hors-borne) + 4 dans
`test_inline_edit.py` (date → hint année dérivée + sync base, date
imprécise → année préservée + hint reflète la base, champ non-date →
pas de hint, contrat cartouche : cible `data-edit-field="annee"`
rendue + champ non-éditable).

### V0.9.9 — Journal des suppressions d'entités

Comble le principe directeur n°4 (« journaliser toutes les opérations
destructives ») pour les suppressions, jusque-là non tracées :
`OperationFichier` ne couvrait que les fichiers, `ModificationItem`
que les métadonnées d'item.

- **Modèle** `OperationEntite` (`models/journal.py`) : `type_entite`
  (fonds/collection/item), `entite_id` (ancien id, informatif — pas
  de FK car la cible n'existe plus), `cote`, `fonds_cote`, `titre`,
  `snapshot_json` (colonnes propres de l'entité), `cascade_resume`
  (JSON : compteurs + ids/cotes des enfants affectés), `execute_le`,
  `execute_par`. Migration `q5u6v7w8x9y0` idempotente.
- **Service** `services/operations_entite.py` : `journaliser_suppression_*`
  (item / collection / fonds) insère la ligne **avant** le delete, dans
  la même session — le service de suppression fait un commit unique →
  journal et cascade atomiques (les deux, ou rien). Snapshot des
  colonnes via introspection SQLAlchemy. `lister_suppressions`
  (filtre type, ordre récent, limite).
- **Câblage** : les 3 services `supprimer_*` prennent `execute_par`,
  journalisent puis suppriment ; routes web (ajout
  `Depends(get_utilisateur_courant)` aux 3 routes `/supprimer`) ;
  commandes CLI delete (`--utilisateur`).
- **Surfaçage** : `archives-tool montrer suppressions [--type ...]
  [--format text|json]` (lecture seule).
- **Undo : hors scope** (réversibilité asymétrique). Le snapshot +
  les listes d'ids bornées rendent un restore futur possible sans
  perte d'information, mais l'exécution (surtout la cascade fonds à
  l'échelle PF : 7000+ fichiers) reste un chantier dédié. Pas
  d'unification avec `ModificationItem` / `OperationFichier` (migration
  risquée, zéro gain immédiat — principe n°6).

8 tests (`test_operations_entite.py`) : journalisation + cascade par
entité, atomicité, snapshot, listing/filtre/ordre, route web
(`execute_par` capté), CLI (delete + `montrer suppressions`).

### V1.0 — Déploiement VPS + multi-utilisateurs

Cible : 2 sessions ~12h, après le test d'usage de V0.9.1. Si
frictions bloquantes identifiées au test d'usage, V0.9.2 avant
V1.0.

**Session 1 — auth et adaptation modèle**

> **Avancement (2026-06-26)** : les **prérequis de dé-risquage** et la
> **Phase 1 de la couche identité** sont livrés en amont, en mode local
> (sans déploiement) :
> - **Isolation per-owner** des états serveur en mémoire (creds ShareDocs
>   RAM + gardes mono-job) via la couture `deps.get_owner_key()`
>   (constante `"local"` aujourd'hui, id de session demain) — la fuite
>   cross-user structurelle est neutralisée. Cf. *Décisions notables* +
>   `test_isolation_owner.py`.
> - **Table `Utilisateur` + service + CLI** `archives-tool utilisateurs`
>   (ajouter/lister/modifier/désactiver) — modèle minimal V1.0
>   (`nom` unique, `actif`, `peut_editer`), migration `x2b3c4d5e6f7`.
>   Non consulté en mode local.
>
> **Reste (Phase 2)** : `ARCHIVES_MODE` + session/login + rendre les 3
> coutures (`get_utilisateur_courant`/`get_owner_key`/`est_lecture_seule`)
> mode-aware. Cookie de session = **HMAC stdlib** décidé (zéro dépendance).

- ✅ Table `Utilisateur` (id, nom, actif, peut_editer) + migration Alembic.
- ✅ CLI `archives-tool utilisateurs` (ajouter, lister, modifier,
  désactiver).
- Variable `ARCHIVES_MODE` (`local` | `serveur`) détectée au
  démarrage. *(Phase 2)*
- Page de login simple (sélection dans liste, cookie de session signé
  HMAC, pas de mot de passe). *(Phase 2)*
- Middleware FastAPI pour la session. *(Phase 2)*
- Adaptation des **3 coutures de `deps`** pour utiliser l'utilisateur de
  session en mode serveur, `config_local.yaml` en mode local (les
  services restent intacts — injection par dépendance). *(Phase 2)*

**Session 2 — déploiement**

- Dockerfile multi-stage + docker-compose (ColleC + Caddy/nginx).
- Mount WebDAV ShareDocs (`davfs2`).
- TLS Let's Encrypt.
- Sauvegarde quotidienne automatique (cron + `restic`).
- Documentation `docs/deploiement/{vps,maj,restore}.md`.

Décisions d'infrastructure préservées dans le document interne
[`docs/developpeurs/deploiement-future.md`](docs/developpeurs/deploiement-future.md)
(exclu du build MkDocs, accessible aux contributeurs et à
Claude Code).

### V2 — Confort du chantier vivant

- Refactoring de métadonnées en masse (scinder un champ en deux,
  normaliser des valeurs, remplacer en lot avec aperçu).
- Vue tableau éditable type tableur pour saisie rapide (composant
  à choisir : AG Grid, Handsontable, ou équivalent).
- Journal de bord auto-généré par collection, consultable, avec
  possibilité d'annoter les entrées.
- ✅ Création en série d'items (pattern + incrément) — **livrée
  en V0.9.7** (service `creer_items_en_serie` + CLI
  `archives-tool items creer-serie` + bouton UI sur page
  collection). Voir
  [`docs/developpeurs/plan-de-chantier.md`](docs/developpeurs/plan-de-chantier.md)
  et [`docs/guide/cli/items.md`](docs/guide/cli/items.md).
- Onglet « Avancement » consolidé sur la page Fonds (lecture par
  jalons : planifiés / numérisés / OCR / catalogués / validés) —
  voir [`docs/developpeurs/plan-de-chantier.md`](docs/developpeurs/plan-de-chantier.md).
- ✅ **Module d'annotation d'image** (W3C Web Annotations sur
  l'OpenSeadragon existant via Annotorious) — **α + β + γ + δ
  livrés en V0.9.7** (modèle + 5 routes REST + Annotorious sur
  OSD + panneau latéral + autocomplete vocabulaire avec pivot URI
  Wikidata/VIAF + export JSON W3C AnnotationCollection,
  48 tests). Voir
  [`docs/developpeurs/annotations-image-future.md`](docs/developpeurs/annotations-image-future.md).
- **Export site statique** (arbre Markdown + assets prêt pour
  Quarto en phase 1, Hugo en phase 3, autres SSG extensibles via
  templates Jinja). Format de sortie parallèle à DC/Nakala/xlsx,
  produit la donnée pas le thème. Voir
  [`docs/developpeurs/sites-statiques-future.md`](docs/developpeurs/sites-statiques-future.md).
- **Module OCR + indexation textuelle** (ALTO format pivot,
  ABBYY pour le natif, pdfalto pour PDFs externes type Por Favor
  Nakala). Indexation FTS5 du contenu OCR + surlignage régionalisé
  dans OSD + audit qualité via scores de confiance ALTO. Tirable
  en V1.x si pression Por Favor (l'OCR existant des PDFs Nakala
  est exploitable sans re-OCR). Voir
  [`docs/developpeurs/ocr-module-future.md`](docs/developpeurs/ocr-module-future.md).
- « Feuille de scan » : flux rapide avec raccourcis clavier.
- Consultation Nakala (API REST + IIIF) pour vérification croisée
  et import de notices.

### V3 — Finition et interop

- Versionnement des fichiers (remplacement avec historique).
- Opérations sur scans (rotation persistante, recadrage, scission
  d'un scan multi-pages, fusion).
- Dépôt vers Nakala depuis l'outil.
- OCR intégré.
- Empaquetage distribuable (PyInstaller ou équivalent).

### Hors scope prévisible

- Multi-utilisateurs simultanés avec résolution de conflits.
- Authentification, rôles, droits.
- Déploiement cloud.
- Import direct par glisser-déposer de fichiers externes dans le
  navigateur.
- **Édition d'image et OCR intégrés.** Restent en outils
  spécialisés en amont (ScanTailor, Tesseract, etc.). Voir
  [`docs/developpeurs/workflow-numerisation.md`](docs/developpeurs/workflow-numerisation.md).
- **Portail public.** Projet séparé, en lecture seule, alimenté
  par les exports / synchros ColleC — pas une extension du
  présent dépôt. Voir
  [`docs/developpeurs/portail-public-future.md`](docs/developpeurs/portail-public-future.md).
- **Gestion de projet** (dates prévues, assignations, priorités,
  Gantt). Reste en outil tiers (Trello, Notion, Excel partagé).
  ColleC garde la traçabilité historique, pas le prévisionnel.

---

## Décisions d'architecture notables

### Séparation ColleC interne / portail public

**Décision stratégique** (mai 2026, suite à plusieurs sessions de
discussion sur le positionnement) : ColleC reste un **espace de
travail interne** (équipe + invités à identité nommée), et le
**public général ne consulte pas ColleC** mais des artefacts
produits par lui (sites statiques figés via
[`sites-statiques-future.md`](docs/developpeurs/sites-statiques-future.md),
portail dynamique séparé via
[`portail-public-future.md`](docs/developpeurs/portail-public-future.md)).

Trois raisons décisives :

1. **L'auth V1.0 est explicitement « attribution, pas sécurité
   forte »** (cf. `deploiement-future.md`). Suffisant pour une
   équipe en confiance derrière une URL semi-privée, inadéquat
   pour exposer publiquement. Passer à de la vraie auth
   (passwords, sessions, rate limiting, audit, RGPD) = chantier
   majeur non planifié, pollue le focus catalographique.
2. **Les UX divergent fondamentalement.** Catalogueur =
   tableau dense, raccourcis, édition inline silencieuse,
   filtres complexes. Visiteur = grande image, texte aéré,
   navigation thématique, dossiers éditoriaux. Faire les deux
   dans la même UI finit toujours en compromis (Omeka S l'a
   fait et c'est sa principale faiblesse).
3. **Cohérence avec le principe directeur n°1**
   (« la base locale est la source de vérité pendant le
   travail »). Les exports / sites statiques / portail sont des
   sorties, pas la vérité courante.

**Trois catégories d'identité, pas deux** (raffinement issu des
scénarios « consultation externe » et « contribution
spécialiste ») :

- **Anonyme public** → portail / site statique (lecture seule,
  sans identité).
- **Externe à identité nommée** (invité contributeur, invité
  consultation, peer-reviewer) → ColleC avec compte temporaire
  + scope limité. Cf. matrice d'identités dans
  `deploiement-future.md`.
- **Équipe interne permanente** → ColleC avec compte permanent
  + scope global.

**Réversibilité asymétrique préservée.** Si un besoin précis
émerge un jour (« on veut que telle vue soit publique pour tel
projet »), on peut **ajouter** une route publique anonyme en
lecture seule sur ColleC, sur un sous-ensemble bien défini de
routes, sans pour autant fusionner les deux applications.
L'inverse (retirer la dimension publique d'un monolithe une fois
que le monde s'est habitué à cette URL) est nettement plus
coûteux. La décision actuelle n'est donc pas un cul-de-sac.

### Une instance = une DB = un contexte

ColleC ne supporte qu'une seule base SQLite par instance. Le
**multi-fonds vit dans le modèle** (autant de lignes `Fonds`
qu'on veut dans la même DB, avec navigation, recherche
transversale, collections transversales), **pas dans le
déploiement**.

Les besoins de cloisonnement fort se résolvent **par déploiements
séparés**, pas par multi-DB intra-instance :

- **Confidentialité forte / NDA** : deux instances ColleC
  distinctes, deux URLs, deux DBs, aucun chevauchement.
- **Multi-institutionnel** (Huma-Num hébergeant pour plusieurs
  institutions) : une instance par institution, chacune cliente
  de sa propre DB.
- **Dualité local / institutionnel** : un ColleC local
  (`localhost:8000`) + un ColleC institutionnel
  (`colle-c.institution.fr`) dans le navigateur, transfert
  d'un fonds entre les deux via les exporters / import existants.

**Pourquoi cette règle.** Le multi-tenancy intra-instance
introduirait : session-management cross-DB, switching UX,
auth globale qui doit savoir parler à N DBs, multi-appartenance
impossible entre items de DBs différentes, exports cross-DB
impossibles, migrations en parallèle, sauvegardes éclatées. Pour
zéro gain par rapport à des déploiements séparés. La règle
préserve la simplicité, protège la sécurité par cloisonnement
physique pour les cas qui le réclament, et évite l'illusion
qu'une auth globale résoudrait des permissions complexes
(elles sont presque toujours mieux servies par des instances
séparées avec leurs propres comptes).

**Indication visuelle d'instance** (à prévoir si un utilisateur
alterne entre deux instances dans la journée) : bandeau coloré
en haut de chaque ColleC, nom de l'instance, type
d'environnement (« production institutionnelle » / « local
Hugo »). Extension naturelle du pattern `est_lecture_seule`
existant. Pas un sujet V1.0, juste une attention UX à avoir si
le cas se présente.

### Formats d'interchange

ColleC est un système hybride par construction — chaque format
de données est choisi pour son domaine d'interchange spécifique,
pas par préférence idéologique. **Aucun format d'interchange
n'est promu en format de stockage natif.** Le cœur reste
relationnel SQL + JSON columns ; XML et JSON-LD interviennent
uniquement aux frontières.

| Niveau | Format | Pourquoi |
|---|---|---|
| Stockage interne | SQL + JSON columns | Performance, invariants, jointures, FTS5 |
| API live (HTMX, REST) | JSON | Frontend, intégration moderne |
| Échange IIIF (images, annotations, manifestes) | JSON-LD | Standard web actuel — consommable par OSD, UV, Mirador, Annotorious |
| Échange archivistique (Dublin Core, ALTO, TEI futur) | XML | Standard documentaire long terme — Nakala, interop institutionnelle |
| Sites statiques (frontmatter + corps) | Markdown + YAML | Standard SSG (Quarto, Hugo) |
| Profils d'import | YAML | Lisibilité humaine, édition à la main |

**Implication architecturale.** ColleC ingère du XML (ALTO en
entrée, profils import YAML), produit du XML (DC en sortie, ALTO
si re-OCR ABBYY local), produit du JSON-LD (annotations W3C,
manifestes IIIF si générés), consomme du JSON-LD (manifestes
IIIF Nakala), tout en gardant son cœur relationnel SQL. **Règle
qui évite l'usine à gaz** : on parse en entrée, on sérialise en
sortie, on stocke à plat en interne. Si demain un nouveau
standard émerge (Linked Art enrichi, remplacement de DC, autre),
il s'ajoute en exporter parallèle aux autres, sans toucher au
cœur.

**Le XML n'est pas un fardeau.** `lxml` en Python est mature,
les schémas (XSD pour ALTO, DC, TEI) sont stables et bien
documentés, les validations community DH sont réutilisables.
Quand un module produit ou consomme du XML, c'est parce que le
standard du domaine l'exige — et la complexité reste contenue
dans ce module, pas dispersée dans le reste du code.

### Stockage des chemins

Les fichiers sont stockés en base sous forme **(racine_logique,
chemin_relatif)**, jamais en absolu. Chaque utilisateur configure ses
racines dans un `config_local.yaml` hors base et hors dépôt Git.

Exemple :
```yaml
# config_local.yaml (local à chaque poste, non versionné)
utilisateur: "Marie Dupont"
racines:
  scans_revues: /Users/marie/Archives/Scans
  miniatures: /Volumes/NAS/archives/miniatures
```

Avantages : portabilité entre machines, collaboration possible avec des
chemins différents par utilisateur.

**Garde anti-traversal centrale OS-agnostique** (revue sécurité
2026-06-27, finding F1). `files/paths.valider_chemin_relatif` (utilisée
par `resoudre_chemin`, le renamer, la qa, l'import et l'ingestion
ShareDocs) rejette désormais explicitement les **antislashs** et les
**lettres de lecteur Windows** (`ntpath.splitdrive`) *avant* l'analyse
POSIX. Sans cela, `PurePosixPath` voyait `..\..\x` ou `C:\x` comme des
caractères ordinaires (ni `..`, ni absolu) et `Path.joinpath` les
réinterprétait en séparateurs/racine en production Windows → **écriture
de fichier hors racine** (arbitraire, prouvée end-to-end via l'ingestion
ShareDocs). Les chemins relatifs légitimes du projet sont toujours POSIX
(`/`), donc le durcissement ne rejette aucune valeur saine. Défense en
profondeur côté ShareDocs : extraction du *vrai* basename (normalisation
`\`→`/` avant `rsplit`) + ceinture `Path.resolve().is_relative_to(racine)`
post-résolution (couvre aussi l'échappement par symlink). Deux autres
findings traités dans la même passe : **IDOR jobs** (les routes
suivi/statut/annulation des tâches de fond filtrent maintenant par
`owner` — un job d'autrui est indiscernable d'un inconnu, prérequis
multi-user) et **F2** (validation anti-SSRF de `ShareDocsConfig` mise à
parité avec Nakala : allowlist d'hôte + userinfo + IP interne, plus
seulement `https://`). Dette identité Phase 2 actée en docstrings
(`peut_editer=True` par défaut à inverser vers le moindre privilège ;
unicité `nom` sensible à la casse à trancher avant le login).

### Métadonnées étendues en JSON

Les champs Dublin Core étendus et spécifiques à chaque collection sont
stockés dans un champ `metadonnees` de type JSON sur `Item`. Les champs
structurants récurrents (titre, date, cote, type COAR) sont des colonnes
dédiées pour l'indexation et la recherche performante.

### Profils d'import YAML

Chaque collection reprise a un profil YAML qui décrit :
- Le mapping colonnes du tableur → champs de l'item
- La convention de nommage des scans (regex ou template)
- La règle de dérivation de la cote
- Le template de nommage cible (pour renommage canonique)

Les profils sont versionnés dans le dépôt Git (dossier `profiles/`).

### Renommage transactionnel

Toute opération de renommage :
1. Calcule le nom cible selon le template.
2. Détecte les conflits (deux fichiers cible identiques, cycles).
3. Présente un aperçu (mode simulation).
4. Exécute en transaction : déplacement physique + mise à jour base.
5. Journalise dans `OperationFichier` avec un batch_id.

Toute opération est annulable via le batch_id.

### SQLite en mode WAL

Activer dès l'ouverture de connexion :
```python
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
```

Note : si la base est un jour mise sur partage réseau, repasser en mode
journal DELETE classique (plus fiable sur SMB/NFS).

### Configuration locale vs partagée

- **Config locale (par poste)** : fichier YAML hors base, contenant
  racines de fichiers, identité utilisateur, préférences UI.
- **Config partagée (en base ou dans le dépôt)** : profils de
  collections, vocabulaires contrôlés, templates de nommage.

### Double granularité item / fichier

Le modèle `Item 1..n Fichier` supporte nativement deux vues qui sont
des concepts de premier ordre dans l'outil :

- **Granularité item** : unité de catalogage (un numéro, un volume,
  une loi, un document archivistique). Vue principale pour la
  consultation bibliothéconomique.
- **Granularité fichier** : unité de numérisation (une page, un scan,
  un fac-similé). Vue principale pour les opérations techniques
  (renommage, dérivés, intégrité) et pour les exports
  Nakala-compatibles.

Les profils d'import déclarent une granularité source (`item` ou
`fichier`). L'interface et la CLI exposeront les deux vues.

### Hiérarchie archivistique

Les collections peuvent être imbriquées via `Collection.parent_id`.
Cas d'usage : fonds d'archives avec séries et sous-séries, éditeur
avec plusieurs revues, bibliothèque avec sous-ensembles thématiques.

Règles :

- Collection racine : `parent_id = NULL`.
- La cote reste unique globalement (pas de cote relative au parent).
- Un item peut être rattaché à une collection à n'importe quel niveau
  de l'arbre.
- Pas d'héritage automatique des métadonnées parent → enfant
  (cohérent avec le principe d'autonomie).
- Pas de limite de profondeur dans le schéma. 2–3 niveaux attendus
  en pratique.
- Validation anti-cycle au niveau applicatif (listener SQLAlchemy
  `before_flush` dans `models/collection.py` — SQLite ne supporte
  pas les CHECK récursifs).
- Cascade de suppression complet : parent → enfants → items des
  enfants.

En complément, certaines collections expriment aussi une hiérarchie
**interne** dans la cote elle-même (exemple : fonds avec cote type
`FA-AA-00-01` encodant fonds/sous-fonds/série/numéro). Cette
hiérarchie interne est parsée à l'import via regex du profil et
stockée dans `Item.metadonnees.hierarchie`. Les deux mécanismes
cohabitent sans se remplacer : `parent_id` exprime l'arborescence
de collections, `metadonnees.hierarchie` décompose la cote d'un
item individuel.

### Conventions de valeur nulle

Les tableurs sources utilisent des sentinelles variées pour
représenter l'absence de valeur : `"none"`, `"n/a"`, `"s.d."`, chaîne
vide, NaN pandas.

Les profils d'import déclareront une liste `valeurs_nulles`
configurable. Ces valeurs sont converties en `NULL` avant toute autre
transformation.

En revanche, les **dates archivistiques incertaines** (`"s.d."`,
`"vers 1964"`, `"1923 ?"`) sont conservées telles quelles dans un
champ texte (format EDTF tolérant), sans normalisation forcée qui
perdrait l'information.

### Nakala comme première classe

Les DOI Nakala sont stockés dans des colonnes dédiées sur `Item` et
`Collection`, pas dans `metadonnees` JSON. Cela permet :

- Une contrainte d'unicité pour détecter les doubles imports.
- Un index pour les requêtes rapides lors de la consultation.
- Une assise claire pour les liens externes riches (V2+ via
  `SourceExterne` / `RessourceExterne` / `LienExterneItem`).

Colonnes :

- `Collection.doi_nakala` : UNIQUE, le DOI de la collection publiée.
- `Item.doi_nakala` : UNIQUE, le DOI de l'item publié.
- `Item.doi_collection_nakala` : non-unique, rattachement à une
  collection Nakala partagée par plusieurs items.

### Identité simplifiée

L'outil ne gère pas d'utilisateurs structurés. Chaque poste est
configuré avec un nom libre dans la config locale
(`utilisateur: "Marie"`). Ce nom est copié comme chaîne de caractères
dans les champs d'audit (`cree_par`, `modifie_par`, `ajoute_par`,
`execute_par`). Aucune contrainte d'unicité, aucune FK.

Si une personne change de nom, ou si deux personnes ont le même nom,
ce n'est pas un problème technique — l'information reste uniquement
informative, pas une clé métier.

### Descriptions publiques vs internes

Les entités structurantes (`Collection`, `ChampPersonnalise`,
`Vocabulaire`, `ValeurControlee`) portent deux types de descriptions :

- `description` : public / catalographique, destinée aux exports
  et aux consultations externes.
- `description_interne` : équipe / chantier, destinée à documenter
  les choix et les conventions pour les catalogueurs qui reprennent
  le travail.

Les deux sont libres (TEXT), aucune structure imposée.

### Tâches de fond : runner mémoire + reprise idempotente

**Décision** (2026-06-13, introduite avec l'UI de dépôt collection
Nakala — backlog dépôt UI D1-D6) : la 1ʳᵉ tâche de fond du projet
est portée par un **`threading.Thread` daemon** + un **registre
mémoire** thread-safe, **pas par un broker** (Celery, RQ, dramatiq,
arq…).

Trois angles de justification :

1. **Une instance = un processus** (cf. `Une instance = une DB = un
   contexte` plus haut). Le mono-processus exclut nativement un
   bus de messages distribué — il n'y a aucun consommateur ailleurs
   à qui parler. Un broker imposerait un Redis/PostgreSQL dédié
   alors que le déploiement V1.0 vise précisément le contraire
   (SQLite + Caddy + davfs2, pas d'infrastructure annexe). Pour le
   local mono-utilisateur (mode actuel), un broker serait
   absurde.
2. **Une tâche concurrente à la fois.** Le registre porte
   `_id_actuel` (`api/services/nakala_depot_jobs.py`) avec un
   `threading.Lock` : `reserver_job()` lève `JobConcurrent` si un
   autre dépôt tourne. Pas de queue, pas de scheduling — l'UI
   refuse simplement un 2ᵉ dépôt simultané. Suffisant tant qu'il
   n'y a pas plusieurs types de tâches de fond concurrentes ; à
   revoir si le projet en accumule (export, OCR, IIIF
   manifests…).
3. **Sûreté par reprise idempotente, pas par retry de queue.** Le
   service `deposer_collection` persiste les `Collection.doi_nakala`
   et `Item.doi_nakala` au fil de l'eau — un crash mid-run laisse
   les items déjà créés intacts. Relancer le dépôt depuis l'UI
   re-déroule la séquence : les items avec DOI sont sautés (branche
   `sautes`), le restant reprend. La reprise n'est pas un
   composant séparé (replay/dead-letter/exponential backoff) — elle
   est la conséquence directe du modèle de données déjà imposé
   par le principe « Nakala comme première classe » (DOI = colonne
   dédiée, unique). Le bouton « Reprendre » de la page de suivi
   est donc juste un relancement du POST normal.

**Conséquences observables** :

- État volatile : un restart du processus FastAPI perd le registre
  en mémoire (`_JOBS`). Conséquence acceptée : la page de suivi
  d'un job en cours pointera vers un `job_id` inconnu (404). La
  **base reste cohérente** (DOI persistés transactionnellement)
  — relancer le dépôt reprend où on s'était arrêté.
- Pas de timeline historique des tâches de fond — uniquement
  l'état courant + le dernier job terminé tant que le processus
  vit. Si l'historique devient utile (audit, debug), introduire
  une table `OperationTacheDeFond` (analogue à `OperationFichier`
  / `OperationEntite`).
- L'UI affiche un avertissement « gros fonds → CLI » à partir de
  50 items et un avertissement fort à partir de 200, avec la
  commande CLI pré-remplie. La CLI (`archives-tool nakala
  deposer-collection ... --no-dry-run`) reste l'outil de
  référence pour les opérations massives : journalisation propre,
  reprise plus simple en cas d'incident, pas de risque de
  plantage onglet navigateur.

**Conditions de remise en cause** : passage à plusieurs types de
tâches de fond simultanées (auquel cas une vraie queue
intra-processus type `asyncio` ou `concurrent.futures` avec
priorisation ferait sens) ; ou bascule vers un déploiement
multi-processus (auquel cas le registre mémoire ne suffit plus et
un store partagé devient inévitable — probablement SQLite à
nouveau, par cohérence avec le reste du projet, avant un broker
externe).

Référence opérationnelle : `api/services/nakala_depot_jobs.py`
(registre + runner), `api/routes/nakala_web.py` (4 routes apercu /
lancer / suivi / statut), pages `nakala_deposer_collection_apercu.html`
+ `nakala_deposer_suivi.html` + partial `nakala_deposer_statut.html`.

---

## Vocabulaires et standards

- **Dublin Core qualifié** comme socle de métadonnées.
- **COAR Resource Types** pour la typologie documentaire (stocker
  URI + label, pas juste le label).
- **EDTF (Extended Date/Time Format)** pour les dates incertaines
  (`1923`, `192X`, `1923-04?`, `1923/1924`).
- **ISO 639-3** pour les langues.
- **IIIF Presentation API 3.x** pour les manifestes de visionneuse
  (V2+).

Les valeurs contrôlées (types COAR, langues) sont stockées en table
dédiée avec URI + label, pas en dur dans le code.

---

## Questions ouvertes / à décider

(Mettre à jour au fil du projet.)

- [x] **Ajouter `--format json` sur les commandes Nakala destructives**
      — **résolu passes 19+20 P3+c.2** : les 10 commandes destructives
      (`rapatrier`, `rafraichir`, `rapatrier-collection`,
      `rafraichir-collection`, `deposer`, `deposer-collection`,
      `pousser`, `publier`, `pousser-collection`, `publier-collection`)
      ont reçu `--format json` avec helper `_payload_push_json` partagé
      et 7 tests gardiens. **14/14 commandes Nakala ont JSON** (puis la
      commande `citer` ajoutée en S4 expose aussi JSON → 15/15).
- [x] **Re-caractérisation du binaire après `pousser_fichiers_item`**
      — **partiellement résolu passe 25 P3+c.2** : `hash_sha256` (SHA-256
      disque, distinct du sha1 Nakala) et `taille_octets` recalculés sur
      le binaire courant pour modifies/nouveaux. **Reliquat** : `format`,
      `largeur_px`, `hauteur_px` (PIL) restent obsolètes — V2+ avec
      calcul asynchrone si dimensions deviennent un blocage UX. À
      combiner avec module OCR ou thumbnails async.
- [x] **Logging structuré transversal sur `nakala_depot.py`** — **résolu
      passe 21 P3+c.2** : les 7 services écriture (`deposer_item`,
      `deposer_collection`, `pousser_item`, `publier_item`,
      `pousser_metadonnees_collection`, `pousser_collection`,
      `publier_collection`) ont reçu le pattern logger structuré
      (INFO/WARNING/DEBUG) avec events `START`, `OK`, `COMMIT`, `END`,
      `ECHEC`, `IRREVERSIBLE START` pour les publications. **8/8
      services ont logger**.
- [x] **Cohérence cross-service du garde-fou item publié** (Trou T
      passe 9 sur `pousser_fichiers_item` uniquement) — **résolu passe
      22 P3+c.2** : `DepotPublie` déplacée dans `nakala_depot.py`
      (couche plus basse), check ajouté à `pousser_item` (metas) avec
      `forcer_publie=False` par défaut + court-circuit si aucun
      changement. CLI `--force-published` sur `pousser` et
      `pousser-collection`. Propagation dans la boucle collection.
- [x] **Journaliser les push fichiers Nakala** (principe directeur n°4)
      — **résolu passe 24 P3+c.2** : table `operation_push_nakala`
      (analogue `OperationEntite` V0.9.9) avec `batch_id`, `cote_item`,
      `doi`, `snapshot_avant/apres` JSON, `sha1s_uploades/retires` JSON.
      Service `journaliser_push_fichiers` insère dans la même transaction
      que les mutations DB (atomique). CLI `archives-tool montrer
      push-nakala` pour consultation post-mortem.
- [x] **Documenter la CLI Nakala dans `docs/guide/cli/nakala.md`** —
      **résolu passe 23 P3+c.2** : page guide structurée en 7 flux
      (Lecture / Rapatriement / Export tableur / Dépôt / Push
      métadonnées / Synchronisation fichiers / Publication). 14
      commandes documentées avec exemples concrets, garde-fous, format
      JSON, codes de sortie, observabilité. Nav `mkdocs.yml` à jour,
      `mkdocs build --strict` OK.
- [x] **`Fichier.description_externe` : transcription par fichier (S7)** —
      **round-trip complet livré**. Cas d'usage : pour chaque scan
      (revue numérisée, correspondance, manuscrits, partitions, cartes…),
      stocker la **transcription textuelle** par fichier (distinct des
      annotations IIIF à granularité bulle/région — modèle W3C séparé).
      Validé apitest H11 : Nakala accepte `description` par fichier au
      `POST /datas` et `PUT /datas/{id}`, le préserve, le restitue.
      **Livré** : colonne ORM `Fichier.description_externe` (migration
      `u9y0z1a2b3c4`) + capture au pull + UI (édition sur le viewer de
      catalogage, lecture seule dans la liseuse) + **intégration push**
      (`deposer_item` au `POST /datas`, `_reordonner_files` au PUT,
      `comparer_fichiers_item` détecte un diff description-seule). Règle
      **anti-wipe probe-independent** : le PUT émet la transcription
      LOCALE si présente, sinon préserve la distante re-lue. **Reste** :
      (a) indexation FTS5 (à réconcilier avec le plan `ocr_text` du module
      OCR — cf. [`ocr-module-future.md`](docs/developpeurs/ocr-module-future.md)
      § *Articulation*), (b) consultation portail public (futur).
      **(c) smoke round-trip live : ✅ FAIT (2026-06-18, apitest revenu)** —
      `test_description_par_fichier_round_trip_live` (round-trip identique) +
      `test_anti_wipe_description_au_push_fichiers_live` (push préserve la
      description). **Sonde omit-vs-wipe → WIPE** : un `PUT files[]` omettant
      la clé `description` la met à `null` (Nakala) → anti-wipe confirmé
      nécessaire, effacement distant désormais faisable par omission (futur
      chemin explicite). Cf. `nakala-savoir-api.md` H12 + `backlog-nakala-api.md` S7.
- [ ] **Activer le verrou optimiste sur `Fichier`** (`__mapper_args__
      = {"version_id_col": TracabiliteMixin.version}`). La colonne
      `Fichier.version` existe mais n'est **pas câblée** comme verrou
      optimiste, contrairement à `Item`, `Collection`, `Fonds`. Pas
      de bug actif aujourd'hui : `deposer_item` (P3+a) écrit
      `sha1_nakala` toujours avec la même valeur idempotente, et les
      autres mutations passent par le `renamer` transactionnel
      (verrouillage applicatif). Mais dette structurelle : toute
      future mutation par session concurrente (ex. UI rename + dépôt
      simultané, ou annotations / état fichier en V2+) bénéficierait
      du verrou. **Risque** : activer `version_id_col` casse les tests
      qui n'incrémentent pas `version` à l'écriture — audit complet
      requis avant. Voir pattern dans `models/item.py:46-47`.
- [x] **Isolation per-user des états module-globaux (prérequis V1.0)** —
      **structure livrée (2026-06-25)**. Les trois états serveur en mémoire
      (`sharedocs_session` creds RAM, `nakala_depot_jobs` + `sharedocs_jobs`
      gardes mono-job) sont désormais **keyés par owner** : `sharedocs_session`
      passe d'un singleton à `dict[owner, creds]` (la vraie fuite de
      confidentialité cross-user), et la garde `_id_actuel` des deux runners
      devient `dict[owner, job_id]` (un user ne bloque plus les autres ;
      `_JOBS` reste keyé par UUID non devinable). La couture
      `deps.get_owner_key()` renvoie la constante `OWNER_DEFAUT = "local"`
      aujourd'hui (mode mono-utilisateur, comportement identique) ; les routes
      la passent en `Depends`. **Activation multi-user (Chantier 3) = une
      ligne** : faire renvoyer à `get_owner_key()` l'id de session courant,
      sans toucher aux services (pattern *resolver-ready*). Tests d'isolation :
      `tests/test_isolation_owner.py` (8). Doctrine secrets / coffre chiffré
      multi-comptes restent V1.0 (cf. `deploiement-future.md`).
- [x] **Tester `alembic downgrade` dans la CI** — **résolu passe 26
      P3+c.2** : 2 nouveaux tests dans `tests/test_migration.py` :
      `test_migration_downgrade_apres_refonte_v090_puis_upgrade_head_est_idempotent`
      valide le cycle complet upgrade head → downgrade jusqu'à la
      refonte V0.9.0-alpha → upgrade head sur toutes les migrations
      postérieures à la refonte (borne `_BORNE_DOWNGRADE = "g7l8m9n0o1p2"`
      — la refonte reste appliquée, décision documentée non-réversible).
      `test_migration_downgrade_traverse_refonte_v090_leve_explicitement`
      garde-fou si quelqu'un implémente un jour la downgrade() de la
      refonte (V2+ ?).
- [x] **Pattern obligatoire pour les futures migrations `add_column`**
      — **résolu passe 26 P3+c.2** : 3 règles documentées dans
      [`docs/developpeurs/contribuer.md`](docs/developpeurs/contribuer.md)
      section « Migrations Alembic » :
      1. Idempotence `create_table` (skip si table existe)
      2. `batch_alter_table` + guard pour `add_column` sur table déjà
         touchée (sinon parité metadata vs migrations casse)
      3. `downgrade()` fonctionnelle pour toute migration post-refonte
         (validée par le test ajouté ci-dessus).
      Exemples de référence : `q5u6v7w8x9y0_operation_entite`,
      `t8x9y0z1a2b3_operation_push_nakala`.
- [ ] Nom définitif du projet et du package Python.
- [ ] Choix précis de l'empaquetage final (PyInstaller, Briefcase,
      simple scripts run.bat/run.sh ?).
- [ ] Stratégie exacte de sauvegarde automatique (fréquence, rotation).
- [ ] Gestion des droits par collection (tous utilisateurs voient tout
      ou cloisonnement ?).
- [ ] Format canonique des noms de fichiers après renommage (tout
      minuscule ? tirets ou underscores ?).
- [ ] Faut-il un champ `Collection.ordre` pour ordonner les enfants
      d'un même parent dans la navigation, ou l'ordre alphabétique
      de la cote suffit-il ?
- [ ] Pour la création en série d'items (V2+), où stocker le pattern
      de génération (profil YAML, champ `Collection`, autre) ?
- [ ] Choix du composant de vue tableau éditable pour V2 (AG Grid
      community, Handsontable community, tabulator.js, autre). À
      évaluer en amont de V2.
- [ ] Stratégie d'implémentation des refactorings de métadonnées
      (scinder / fusionner / renommer un champ personnalisé) :
      opération directe avec journal, ou migration applicative avec
      état `a_migrer` temporaire ?
- [ ] Journal de bord : vue calculée pure à partir des tables
      existantes (`ModificationItem`, `OperationFichier`), ou table
      `NoteCollection` pour entrées libres additionnelles ?
- [ ] **Verrou optimiste sur suppression d'entités** (fonds /
      collection / item) — reporté à V1.0 (avec l'auth multi-
      utilisateurs). En mono-utilisateur local, le scénario « deux
      onglets concurrents, l'un édite l'autre supprime » est
      quasi-théorique. Quand l'auth arrivera, ajouter `version`
      en hidden input sur le form de suppression + comparaison
      service (analogue à `ConflitVersion` sur modify).
- [x] **Journal des suppressions d'entités** (fonds / collection /
      item) — **résolu Phase 1 en V0.9.9** : table `OperationEntite`
      qui journalise chaque suppression (snapshot des colonnes +
      compteurs de cascade + ids/cotes des enfants affectés) dans la
      même transaction que le delete. Câblé dans les 3 services
      `supprimer_*`, les routes web et les commandes CLI ; listing
      via `archives-tool montrer suppressions`. **Undo non implémenté**
      (réversibilité asymétrique : le snapshot rend un restore futur
      possible sans perte d'info, mais l'exécution — surtout la
      cascade fonds — reste un chantier dédié). `ModificationItem`
      et `OperationFichier` restent séparés (pas d'unification :
      hors scope, migration risquée pour zéro gain immédiat).
- [x] **Intégration FTS5 sur `item`** (titre, description, métadonnées) —
      **livré en V0.9.3** : `item_fts` (cote, titre, description,
      notes_internes, `metadonnees_text` flatten JSON), tokeniseur
      `unicode61 remove_diacritics 2`, mode standard (`snippet()`),
      triggers de synchro + `fonds_fts` / `collection_fts`. Le piège
      anticipé s'est confirmé et est traité : `alembic/helpers.py`
      expose `drop_fts_triggers()` / `create_fts_triggers()` (source SQL
      unique `db._SQL_TRIGGERS_FTS`) à encadrer toute migration
      `batch_alter_table` sur `item`/`fonds`/`collection`. **Reste
      futur** : étendre l'index au contenu OCR (`ocr_text`) et à
      `description_externe` — cf. `ocr-module-future.md` (révision
      text-first).

---

## Comment Claude Code doit travailler sur ce projet

- **Lire ce fichier en début de session** et relever toute contradiction
  avec les demandes.
- **Proposer les décisions structurantes avant de coder.** Si une
  question n'est pas tranchée ici ou dans `docs/`, la poser avant
  d'implémenter.
- **Écrire les tests avant ou en parallèle du code** pour les zones à
  risque (importers, renamer, rapprochement fichiers).
- **Ne pas introduire de nouvelle dépendance sans la justifier** dans le
  message et la documenter.
- **Mettre à jour `CLAUDE.md` et `docs/`** quand une décision
  structurante est prise.
- **Commit fréquents avec messages explicites** (convention Conventional
  Commits recommandée).
- **En cas de doute sur la portabilité Windows/Mac**, signaler et
  proposer un test.

---

## Commandes utiles

(À compléter au fur et à mesure.)

```bash
# Installation
uv sync

# Lancer les tests
uv run pytest

# Lancer l'application en dev (deux processus)
npm install                          # une fois pour Tailwind + vendors
npm run vendor                       # copie OpenSeadragon + Sortable + htmx dans static/js/vendor/
npm run watch:css                    # recompile le CSS à chaque édition
uv run uvicorn archives_tool.api.main:app --reload --port 8000

# Base de démonstration pour explorer l'UI
uv run archives-tool demo init
ARCHIVES_DB=data/demo.db uv run uvicorn archives_tool.api.main:app --reload

# CLI
uv run archives-tool --help

# Import d'un profil (dry-run par défaut)
uv run archives-tool importer profils/ma_collection.yaml

# Import réel avec journal
uv run archives-tool importer profils/ma_collection.yaml \
    --no-dry-run --utilisateur "Marie" --verbose

# Exports (par collection : miroir, libre rattachée, transversale)
uv run archives-tool exporter dublin-core HK --fonds HK --sortie hk_dc.xml
uv run archives-tool exporter nakala FA-OEUVRES --fonds FA --licence "CC-BY-4.0"
uv run archives-tool exporter xlsx TEMOIG  # transversale, --fonds inutile

# Aide à la création d'un profil d'import
uv run archives-tool profil analyser inventaire.xlsx --sortie mon_profil.yaml
uv run archives-tool profil init --cote HK --titre "Hara-Kiri" \
    --tableur inventaire.xlsx --sortie squelette.yaml

# Contrôles de cohérence (lecture seule)
uv run archives-tool controler                       # base entière, text
uv run archives-tool controler --fonds HK            # un seul fonds
uv run archives-tool controler --format json         # pour CI
uv run archives-tool controler --strict              # exit 1 dès un avertissement

# Génération de dérivés (vignettes + aperçus)
uv run archives-tool deriver appliquer --fonds HK
uv run archives-tool deriver appliquer --item HK-1960-01 --fonds HK --force
uv run archives-tool deriver nettoyer --collection HK-FAVORIS --fonds HK

# Renommage transactionnel (dry-run par défaut)
uv run archives-tool renommer appliquer \
    --template "{cote_fonds}/{cote}-{ordre:03d}.{ext}" --fonds HK
uv run archives-tool renommer appliquer \
    --template "{cote}-{ordre:03d}.{ext}" --item HK-001 --fonds HK \
    --no-dry-run --utilisateur "Marie"
uv run archives-tool renommer annuler --batch-id <UUID> --no-dry-run
uv run archives-tool renommer historique

# Visualisation (lecture seule, Rich ou JSON)
uv run archives-tool montrer fonds                       # liste
uv run archives-tool montrer fonds --cote HK             # détail
uv run archives-tool montrer collection --fonds FA       # liste filtrée
uv run archives-tool montrer collection --cote TEMOIG    # transversale
uv run archives-tool montrer item HK-001 --fonds HK
uv run archives-tool montrer fichier 142
uv run archives-tool montrer item HK-001 --fonds HK --format json
uv run archives-tool montrer statistiques

# Migration base
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# Lint / format
uv run ruff check .
uv run ruff format .
```
