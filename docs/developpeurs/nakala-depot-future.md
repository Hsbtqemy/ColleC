# Dépôt & round-trip Nakala (chantier futur)

> Document interne, exclu du build MkDocs. Décision structurante prise
> en session 2026-06-08, à implémenter en V2/V3. Préserve la décision
> et l'architecture avant de coder (cf. règle projet « proposer les
> décisions structurantes avant de coder »).

## Décision

**ColleC possède son propre chemin Nakala — lecture *et* écriture — sans
couplage à madbot.**

Le contexte : l'utilisateur a écrit en annexe un monorepo de plugins
**madbot** (`plugins-madbot`, MSHS Poitiers / FoReLLIS) couvrant Nakala
(`data` / `metadata` / `submission`) et WebDAV. Évalué comme **source
d'architecture et de données**, pas comme dépendance : ces plugins sont
liés au framework madbot (`plugins-api`, interfaces `DataPlugin` /
`SubmissionPlugin`) et ne sont pas branchables dans ColleC. Mais leur
**savoir Nakala** (mapping 57 champs, vocabulaires, logique HTTP de
dépôt) est largement découplable et sert de base de portage.

Pointeur amont (provenance, révision `46b45a6`) :
`https://gitlab.huma-num.fr/mshs-poitiers/forellis/plugins-madbot.git`
— voir la mémoire `plugins-madbot-nakala-assets`.

### Pourquoi pas madbot

- L'auth/scoping madbot et son modèle de broker recoupent partiellement
  ColleC ; déléguer le dépôt à madbot imposerait de maintenir le mapping
  en double et un point d'intégration externe.
- ColleC traite déjà l'export comme un livrable de premier ordre
  (principe n°2) et les DOI Nakala comme première classe (colonnes
  dédiées). Le dépôt est l'aboutissement naturel de ce chemin, pas une
  capacité à externaliser.

## Ce que le code anticipe déjà

- `Item.doi_nakala` / `Collection.doi_nakala` (UNIQUE) /
  `Item.doi_collection_nakala` — colonnes de première classe (décision
  « Nakala comme première classe »). Base de la réconciliation
  item ↔ dépôt.
- Entités `SourceExterne` / `RessourceExterne` / `LienExterneItem`
  (V2+) — dessinées pour référencer/cacher des ressources d'entrepôts
  externes.
- Roadmap : « Consultation Nakala (API REST + IIIF) » en V2, « Dépôt
  vers Nakala » en V3.
- `files/nakala.py` — helpers IIIF (`vers_iiif_info_json`, `vers_data`,
  `vers_thumb`) déjà utilisés pour l'affichage.
- `exporters/nakala.py` — export CSV bulk (point de départ, mapping
  partiel à remplacer par le mapping 57 champs).

## Faisabilité du round-trip

Confirmée contre l'API Nakala (release notes + re3data, 2026-06) :
`PUT /datas/{identifier}` modifie les métadonnées d'un dépôt existant,
et Nakala supporte le **versioning de fichiers**. Le « create-only » du
plugin `madbot_nakala_submission` était un choix de design madbot, pas
une limite Nakala. Le round-trip *récupérer → modifier → re-pousser* est
donc techniquement ouvert.

## Architecture cible (round-trip)

```
Nakala ──(pull, lecture)──► Items ColleC (lien DOI, fetched_at)
                               │
                               ▼  travail local = source de vérité (principe n°1)
                               │
ColleC ──(create POST /datas, pending)──► nouveau dépôt → DOI
ColleC ──(update PUT /datas/{id} + versioning fichiers)──► dépôt existant
```

Invariant directeur : **Nakala est source + puits, jamais la vérité
courante** (principe n°1). Le pull importe/rafraîchit, le push publie ;
entre les deux, la base locale fait foi.

## Les 4 difficultés (et parades)

1. **Conflit / fraîcheur.** Nakala n'expose pas de verrou optimiste.
   Pull → modif locale → si le dépôt a changé entre-temps, le `PUT`
   écrase. *Parade* : stocker `fetched_at` (+ etag/`modifiedDate` Nakala
   si dispo) sur le lien, et **diff + confirmation avant overwrite** ;
   à défaut, last-writer-wins explicite et tracé.
2. **Publié vs pending.** Sur dépôt publié (DOI minté DataCite), les
   métadonnées restent éditables et les fichiers passent par versioning,
   mais pas de dé-publication. *Parade* : modéliser le statut et adapter
   la sémantique du push (refus de delete sur publié, versioning sinon).
3. **Fidélité du round-trip.** pull → modèle ColleC → push doit être
   sans perte. ColleC a déjà saigné là-dessus (« Trou #9 » singulier/
   pluriel à l'export). *Parade* : **une carte de vérité unique
   lecture+écriture** — porter `SLUG_TO_NAKALA` (mapping 57 champs +
   `typeUri`) du plugin, et la valider par round-trip de test
   (`apitest.nakala.fr`).
4. **Identité fichiers.** item ↔ DOI est couvert ; fichier ColleC ↔
   fichier Nakala doit l'être pour le versioning. *Parade* : réconcilier
   par **SHA-1** (Nakala expose le sha1 par fichier ; `Fichier.hash_sha256`
   existe côté ColleC — attention, SHA-1 vs SHA-256, prévoir un champ
   `sha1_nakala` sur le lien ou recalcul).

## Inventaire COAR — bug de données à corriger (prérequis)

Validation des 15 `TYPES_COAR_OPTIONS` de ColleC contre le set de
**types de dépôt acceptés par Nakala** (snapshot `coar_resource_types.json`,
29 entrées) : **9 sur 15 ne sont pas dans le set Nakala** → rejet ou
coercition au dépôt, et URIs non résolvables à l'export DC.

| Label ColleC | URI actuelle | Statut |
|---|---|---|
| Texte | `c_18cf` | ✅ accepté Nakala |
| Article de revue | `c_6501` | ✅ |
| Livre | `c_2f33` | ✅ |
| Image | `c_c513` | ✅ |
| Partition musicale | `c_18cw` | ✅ |
| Enregistrement sonore | `c_18cc` | ✅ |
| **Vidéo** | `c_12cd` | ⛔ **mal étiqueté** : `c_12cd` = « carte géographique ». Vidéo = `c_12ce` |
| Carte | `c_ecc8` | ⛔ hors set Nakala (la carte Nakala = `c_12cd`) |
| Manuscrit | `c_8a7e` | ⛔ hors set (manuscrit Nakala = `c_0040`) |
| Document d'archives | `c_18co` | ⛔ hors set (fonds d'archives Nakala = `YC9F-HGCF`) |
| Périodique | `c_3e5a` | ⛔ hors set (proche : `c_2fe3` « journal ») |
| Numéro de périodique | `c_0640` | ⛔ hors set (**aucun équivalent Nakala**) |
| Chapitre de livre | `c_3248` | ⛔ hors set |
| Document de travail | `c_8042` | ⛔ hors set |
| Photographie | `c_18cd` | ⛔ hors set (proche : `c_c513` image) |

### Décision (2026-06-08) : vocabulaire généraliste + projection

**ColleC est un outil de collections numérisées tous types** (textes,
périodiques, manuscrits, correspondance, images, son, vidéo, cartes,
œuvres, données…) — pas un outil de périodiques. L'emphase « périodique »
des versions précédentes venait du cas de test Por Favor, pas du design.
Le vocabulaire de types doit donc être large.

Option retenue : **deux vocabulaires** (design (b)) avec un vocabulaire
interne **= le set Nakala complet (29 types) + 3 extras**. Implémenté en
V0.9.10 :

- `TYPES_COAR_OPTIONS` = **32 types** : les 29 types acceptés par Nakala
  (libellés FR), plus 3 genres COAR valides que Nakala n'accepte pas mais
  utiles au catalogage : **Chapitre de livre** (`c_3248`), **Document de
  travail** (`c_8042`), **Photographie** (`c_ecc8`). URIs vérifiées
  contre le vocabulaire COAR autoritatif (corrige les 9 URIs fausses/mal
  étiquetées d'avant — dont `c_12cd` « Vidéo » = en fait « carte »).
  « Numéro de périodique » non repris (un numéro = Item dans un Fonds
  périodique, pas un type COAR ; COAR n'a pas de « journal issue »).
- `COAR_INTERNE_VERS_NAKALA` + `type_coar_pour_nakala()` : projection
  des **3 extras** vers une cible Nakala (Chapitre→texte, Doc travail→
  prépublication, Photo→image) ; les 29 autres = identité. Appliquée à
  l'export Nakala sur `nkl:type` ; `dc:type` garde l'URI COAR interne
  (valide). Invariant testé : **chaque type interne projette vers le set
  Nakala**.
- `normaliser_type_coar` (alias d'import) couvre tous les genres
  (lettre/correspondance, rapport, thèse, œuvre, jeu de données,
  logiciel, site web…).
- Migration `r6v7w8x9y0z1` : remap des `item.type_coar` existants
  (anciennes URIs → corrigées : Périodique `c_3e5a`→`c_2fe3`, Vidéo
  `c_12cd`→`c_12ce`, Carte `c_ecc8`→`c_12cd`, etc.). Séquence d'UPDATE
  ordonnée pour la chaîne de réaffectations qui se recouvrent. Non
  bijective, pas de downgrade.

## Vocabulaires : impédances de schéma relevées

- **Langues** : ColleC stocke en **ISO 639-3** (`fra`/`eng`/`spa`) ;
  le snapshot Nakala est **ISO 639-1 pour les majeurs** (`fr`/`en`/`es`)
  + 639-3 pour la longue traîne. Le pull/push devra **ponter 639-1↔639-3**
  sur les ~185 majeurs (la longue traîne 639-3 coïncide). La résolution
  de libellé actuelle (`libelle_langue`) résout déjà la longue traîne ;
  le pont des majeurs est à ajouter en P1.
- **Licences** : `licenses.json` vendorisé ressemble à la liste **SPDX
  complète** (620), pas forcément au sous-ensemble accepté par Nakala.
  À confirmer avant d'en faire un vocabulaire d'export contraint.

## Phasage

| Phase | Contenu | Roadmap | Risque |
|---|---|---|---|
| **Tier A (fait 2026-06-08)** | Vendoring des 3 vocab snapshots + loaders + résolution libellé langue (longue traîne) | livré | faible |
| **Tier A bis** | Correction COAR (après décision (a)/(b)) + alias mis à jour | prochain | moyen (données) |
| **P1a — Client + mapper (livré)** | `external/nakala/client.py` (`ClientLectureNakala` httpx, lecture seule, exceptions ColleC) + `mapper.py` (dépôt Nakala JSON → `DepotNakala` neutre : titre/créateurs/date/type/langue 639-3/sujets/licence/fichiers/metadonnées) + config `nakala:` (base_url + clé API). **Aucune écriture DB.** 16 tests (httpx mocké + fixture). | livré | faible |
| **P1b — Cache + réconciliation (livré)** | `api/services/nakala.py` : `source_nakala` (get-or-create), `upsert_ressource` (par DOI, `recupere_le` bumpé / `metadonnees_brutes` JSON brut), `reconcilier_item` (lie `Item.doi_nakala` via `LienExterneItem`, ne crée pas d'item), `mettre_en_cache_depot` (orchestration, commit unique). 6 tests. | livré | moyen |
| **P1c — Rapatrier / rafraîchir (livré)** | `rapatrier` (crée un Item depuis un dépôt : cote dérivée du DOI ou explicite, mapping documentaire + métadonnées, cache + lien ; garde « déjà-existant » ; dry-run) + `rafraichir` (re-pull → **diff documentaire + dry-run par défaut** avant overwrite via `modifier_item`, champs ColleC-only préservés : cote/état/notes/fonds). 10 tests. | livré | moyen |
| **P1d — CLI (livré)** | `archives-tool nakala montrer <doi>` (lecture/inspection, text/json) + `rapatrier <doi> --fonds X [--cote] [--no-dry-run]` + `rafraichir <doi> [--no-dry-run]`. Client construit depuis la config `nakala:`. 7 tests (client mocké). **P1 scellé en V0.9.11.** UI web : reportée (respectera `lecture_seule`). | livré | faible |
| **P1.5a — Export tableur collection (livré)** | `archives-tool nakala exporter-tableur <doi_collection> --granularite donnee\|fichier --format csv\|xlsx [--sep] [--sortie]`. Lecture seule, ne touche pas la base. Itérateur `external/nakala/collection.py` (pagine le listing, qui renvoie déjà les `files` complets → pas de N+1), aplatisseur pur `external/nakala/tableur.py` (toutes les propriétés en colonnes, valeurs multiples jointes ` \| `), écrivains `tableur_io.py` (CSV `utf-8-sig` sép. `;` ; xlsx openpyxl `write_only`). Niveau fichier = métadonnées donnée recopiées + colonnes techniques (nom, sha1, mime, taille, embargo…). Validé réel sur José Mora (65 données → 155 fichiers). Backlog : [`backlog-nakala-collection.md`](backlog-nakala-collection.md). | livré | faible |
| **P1.5b — Pull collection en base (livré)** | `archives-tool nakala rapatrier-collection <doi> [--fonds COTE] [--no-dry-run]` : crée Fonds + miroir (DOI collection posé) + N Items en bouclant le `rapatrier` unitaire (`doi_collection_nakala` posé par item) ; dry-run par défaut ; erreurs par donnée collectées sans arrêter le lot. **Fichiers matérialisés** en `Fichier` (T2.5, `iiif_url_nakala` info.json/data via `rapatrier(base_url=...)`) → items navigables ; `sha1` en `metadonnees`. 9 + 4 tests (service + CLI). | livré | moyen |
| **P1.5c — Rafraîchir collection (livré)** | `archives-tool nakala rafraichir-collection <doi> [--no-dry-run]` : re-pull, diff par item lié (boucle `rafraichir`), dry-run par défaut ; données sans item ColleC signalées (`non_lies`) ; champs documentaires seulement (pas de re-sync fichiers). 4 + 2 tests. | livré | faible |
| **P1.5d — UI web (livré)** | Page autonome `/nakala` (`api/routes/nakala_web.py`) : export tableur (téléchargement CSV/xlsx), aperçu+rapatriement, aperçu+rafraîchissement ; bouton « Rafraîchir depuis Nakala » sur les fonds dont la miroir a un DOI. Pull/rafraîchir synchrones (aperçu dry-run GET + confirmation POST bloquée en lecture seule). DOI ou URL accepté. 11 tests, validé live. | livré | moyen |
| **P2 — Create (livré)** | Écriture : `write_client.py` (NakalaEcritureClient : upload/creer_depot/creer_collection/cleanup), `depot_mapper.py` (port `SLUG_TO_NAKALA` 57 champs), `preflight.py` (cascade), `api/services/nakala_depot.py` (`deposer_item`/`deposer_collection` : fichiers locaux, dry-run, statut pending/private, garde déjà-déposé). CLI `nakala deposer` + `deposer-collection`. `POST /collections` body `{status, metas, datas}`. Couplage madbot retiré. 45 tests + 2 d'intégration opt-in (apitest). **Limite** : Items à fichiers locaux seulement ; published/round-trip = P3. | livré | moyen |
| **P3 — Round-trip métadonnées (livré)** | `write_client.modifier_depot` (`PUT /datas/{id}`, remplace les metas) + `nakala_depot` : `diff_push` (par propertyUri, ordre-insensible), `pousser_item`/`pousser_collection` (re-pull → diff + dérive, dry-run, PUT + refresh cache), `publier_item` (`status=published`). CLI `nakala pousser`/`publier`/`pousser-collection`. **Validé live** (round-trip idempotent sur apitest). **Fidélité #3** : `diff_push` canonicalise les créateurs (Nakala ajoute `authorId`/`fullName`/`orcid:null` au stockage → sinon faux diff à chaque push). **Sans** versioning fichiers (#4) ni update métadonnées de collection. | livré | élevé |
| **P3.5 — Métadonnées de collection (livré)** | `write_client.modifier_collection` (`PUT /collections/{id}` → 204) + `nakala_depot.pousser_metadonnees_collection` (réutilise `diff_push` ; pas de dérive — collections sans `modDate`). **Fusion** (pas remplacement) : ColleC ne gère que titre+description → préserve les metas Nakala non modélisées, ne remplace que les champs gérés. `pousser-collection` pousse l'entité **puis** ses items. Sondage apitest : `typeUri` remis à null (ignoré par `diff_push`). Round-trip validé live. | livré | faible |
| **UI web de push (livré)** | Surfaçage du push/publication dans l'UI (`nakala_web.py`), parité avec le pull du Lot 3. `_client_ecriture_ou_none` + 8 routes : `GET/POST /nakala/{pousser,publier,pousser-collection,publier-collection}` (aperçu dry-run GET → confirmation POST bloquée 423 en lecture seule ; aperçus de publication rouges/irréversibles). `nakala_depot.publier_collection` (boucle `publier_item`). Boutons sur `item_fiche.html` (si `doi_nakala`) + `fonds_lecture.html` (si `doi_nakala_miroir`, via `miroir_resume.cote`) ; flash en query string. CLI `nakala publier-collection`. 18 tests web (clients mockés). | livré | moyen |
| **P3+ — Versioning fichiers** | `PUT /datas/{id}` versioning de fichiers (#4, réconciliation SHA-1) | futur | élevé |

## Assets de portage (plugin → ColleC)

| Plugin (fichier) | Réutilisable comme |
|---|---|
| `madbot_nakala_metadata/static/json/vocabularies/*` | **vendorisé** sous `reference/vocabulaires_nakala/` |
| `madbot_nakala_metadata/static/json/schema/v1/*` (57 schémas) | règles de validation pré-export (`exporters/rapport.py`) |
| `madbot_nakala_submission/mapper.py::SLUG_TO_NAKALA` | carte de vérité mapping 57 champs (P2/P3) |
| `madbot_nakala_submission/client.py::NakalaWriteClient` | client httpx de dépôt (P2/P3) — découpler des exceptions `plugins_api` |
| `madbot_nakala_submission/preflight.py` | cascade `dcterms→nkl`, sentinels |
| `madbot_nakala_data/client.py` | client de lecture (P1) |

Couplage madbot à retirer au portage : types d'exception `plugins_api`
et le DTO `MetadataObject` (remplacer par les métadonnées item ColleC).

## Hors scope

- WebDAV : les plugins `madbot_webdav*` restent hors périmètre. La V1.0
  prévoit un montage **davfs2 OS-level** (ShareDocs), pas un client
  WebDAV in-app.
- Auto-publication Nakala (`status/published`) : laissée à l'UI Nakala
  (relecture humaine avant mint DataCite).
- Création de collections Nakala : la collection cible doit préexister.
