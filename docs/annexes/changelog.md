# Changelog

Les jalons notables. Le détail commit-par-commit est dans
[l'historique GitHub](https://github.com/Hsbtqemy/ColleC/commits/main).

## Roadmap

### V0.9.2 — Restauration ergonomique (3 sous-sessions)

- **V0.9.2-alpha** : page Fonds restaurée avec
  `tableau_collections` + `avancement_detaille` + `cellule_modifie`.
  Composant `phase_chantier` branché sur dashboard et page Fonds.
  Service `composer_page_fonds` enrichi (répartition d'états par
  fonds + par collection, `modifie_par`/`le` propagé depuis les
  items, `nb_fichiers` par fonds + par collection). Garde-fou SQL
  ≤ 9 requêtes.
- **V0.9.2-beta** : page Collection restaurée avec
  bandeau enrichi (`avancement_detaille`, `phase_chantier`,
  `cellule_modifie`, compteurs items/fichiers/langues) et
  `tableau_items` avec pagination intégrée. Service
  `composer_page_collection` enrichi (répartition d'états,
  `modifie_par`/`le` propagé depuis les items,
  `OptionsFiltresCollection` dynamiques). `ItemResume` étendu
  avec `nb_fichiers`, `modifie_par`, `description`, `langue`,
  `doi_*`, `metadonnees` + propriétés alias attendues par la
  macro `tableau_items`. Bug pré-existant `phase` enum brut
  dans `tableau_collections` corrigé. Garde-fou SQL ≤ 7
  requêtes pour la page.
- **V0.9.2-beta.2** : filtres multi-valeurs branchés sur la
  page Collection. Nouveau parseur `parser_filtres_collection`
  qui valide silencieusement contre `OptionsFiltresCollection`
  (état, langue, type COAR, période). `lister_items_collection`
  étendu pour supporter les filtres multi (état IN, langue IN,
  type IN, plage d'années). Le formulaire de filtres expose les
  4 dimensions ; pastilles de filtres actifs sous le bandeau,
  retrait individuel par lien ; compteur de filtres dans le
  résumé du tableau. La pagination préserve tous les filtres
  actifs dans ses liens. Test de régression `date_incertaine`
  ajouté pour le bug HIGH corrigé en passe V0.9.2-beta.
- **V0.9.2-beta.3** : drawer animé `panneau_filtres` (CSS pur
  via `data-ouvert`, fermeture ESC + croix, slide-in 200ms
  depuis la droite, backdrop semi-transparent) à la place du
  `<details>` collapsible. Drawer modale `panneau_colonnes`
  avec drag-drop Sortable.js (vendor 1.15.2) et boutons
  activer/désactiver/réinitialiser ; persistance via la table
  existante `PreferencesAffichage` (par utilisateur + collection
  + vue). Nouveau hook `url_panneau_colonnes` câblé dans la
  macro `tableau_items` ouvre la modale via `hx-get`. POST de
  sauvegarde swappe `#tableau-items` via HTMX (vendor 1.9.10
  inclus dans `base.html`) avec `HX-Trigger:
  panneau-colonnes-ferme` qui ferme la modale côté client.
  Service `preferences_colonnes` migré au modèle V0.9.0
  (junction `ItemCollection` au lieu de `Item.collection_id`)
  et tests réactivés (auparavant en `collect_ignore`). Cote
  obligatoire `cote` réinjectée silencieusement si l'utilisateur
  tente de la décocher. +23 tests verts (514 au total).
- **V0.9.2-gamma** : page Item refondue en layout 3 zones
  (panneau fichiers escamotable à gauche, cartouche métadonnées
  centre 460px, visionneuse OpenSeadragon flex-1 à droite).
  Trois composants recréés sous `components/` :
  - `bandeau_item.html` : breadcrumb + cote + titre + badge état
    + meta (nb fichiers, modifié, fonds parent) + boutons
    Précédent/Suivant qui pointent vers les items adjacents
    (cote ASC) dans la miroir du fonds.
  - `cartouche_metadonnees.html` : 4 sections `<details>`
    repliables (Identification / Champs personnalisés /
    Identifiants externes / Description). Hooks `data-edit-cle`,
    `data-edit-type`, `data-editable` posés sur chaque `<dd>` pour
    l'édition inline V0.7+ (aucun JS d'édition actif en gamma).
  - `panneau_fichiers.html` : 3 états visuels (collapsed 36px /
    hover 240px avec délai 200ms / pinned via checkbox CSS pure).
    Vignettes 36×48 (depuis `Fichier.vignette_chemin` via le
    service `sources_image`), détection des sauts d'ordre
    (« ⋯ manque entre 5 et 8 »), bouton « Ajouter des fichiers »
    désactivé (V0.7+).

  Service `composer_page_item` enrichi : `metadonnees_par_section`
  (4 sections, DOI Nakala rendus en lien cliquable, listes
  multi-valeurs en CSV, `ChampPersonnalise` dédupliqués par `cle`),
  `navigation_items` (préc/suiv triés par cote ASC, bornes incluses,
  contexte « fonds X »), `FichierResume.source_image` pré-résolu
  via `resoudre_source_image` (priorité IIIF Nakala → DZI local
  réservé V2 → aperçu local).

  Visionneuse `visionneuse_osd.html` + `visionneuse_osd.js` :
  OpenSeadragon (vendor 4.x déjà présent) instancié sur l'élément
  `.visionneuse-osd[data-source]`. Le JSON sérialisé contient
  `primary` / `fallback` / `telecharger` / `nom`. L'événement
  `open-failed` essaie la source secondaire puis affiche un
  message + lien télécharger. Sur la base demo (chemins fictifs,
  aperçus non générés), le fallback structurel est rendu en
  Jinja avant même l'instanciation OSD.

  Router `derives` mounté sur `/derives` dans `api/main.py`
  (jamais inclus jusque-là, dette technique levée). Garde-fou
  SQL ≤ 8 requêtes pour `composer_page_item`. +14 tests verts
  (529 au total).
- ✅ **V0.9.2-finale** *(2026-05-10)* : passe de nettoyage avant
  stable. Onze fichiers legacy V0.6 supprimés (~1 600 lignes) :
  `routes/{collection,collections}.py`,
  `services/{collection,collections_creation}.py`,
  trois fichiers de tests (`test_collection_routes`,
  `test_collection_services`, `test_collections_creation`),
  quatre templates (`pages/collection.html`,
  `partials/collection_fichiers.html`,
  `partials/collection_sous_collections.html`,
  `components/collection_row.html`). Router `import_assistant`
  mounté (placeholder `/import` accessible). Décision
  d'archivage actée pour `CollaborateurCollection` (Option B :
  collaborateurs gérés exclusivement au niveau Fonds via
  `routes/dashboard.py`) — `routes/collaborateurs.py` et
  `services/collaborateurs.py` conservés en quarantaine, jamais
  mountés ni consommés. Helper `charger_collection_ou_404`
  inliné dans `routes/collaborateurs.py` pour découpler de
  `routes/collections.py` supprimé. `collect_ignore` allégé
  (3 entrées retirées). `main.py` actualisé (commentaires +
  bump `0.9.2-gamma` → `0.9.2`). Audit `ItemResume` : tous les
  champs sont consommés (directement ou conditionnellement via
  les colonnes configurables `description`/`langue`/`doi_*`).
  Cohérence visuelle vérifiée — incohérences mineures signalées
  (style du bouton « Modifier » sur Item, présence variable du
  pied de page « Retour ») mais hors scope simplify.

## V0.9.10 (2026-06-08)

### Vocabulaires Nakala vendorisés + résolution de langue (Tier A)

Premier pas du chantier **dépôt/round-trip Nakala** (voir
`docs/developpeurs/nakala-depot-future.md`). Reprend les *données* d'un
dépôt annexe de plugins Nakala (`plugins-madbot`, MSHS Poitiers) sans
coupler ColleC à madbot.

- Vendoring sous `archives_tool/reference/vocabulaires_nakala/` : types
  COAR acceptés par Nakala (29), langues (~8043), licences SPDX (~620),
  avec `PROVENANCE.md` (source + révision amont + mises en garde).
- `reference/loaders.py` : chargeurs cachés (`langues_iso639`,
  `types_coar_nakala`, `licences_spdx`).
- `libelle_langue` : résolution du libellé sur la table complète (un
  code 639-3 de longue traîne s'affiche correctement, plus seulement
  les ~17 langues curées). Impédance documentée : ColleC stocke en
  639-3, le snapshot Nakala est 639-1 pour les majeurs → pont reporté.

**Décision actée** (voir doc) : ColleC possèdera son propre chemin de
dépôt Nakala (lecture + écriture, round-trip via `PUT /datas/{id}` +
versioning), **sans couplage madbot**.

**Trouvaille** : 9 des 15 types COAR de ColleC sont hors du set accepté
par Nakala (dont `c_12cd` mal étiqueté « Vidéo » = en fait « carte »).
Correction en attente d'une décision produit (Périodique/Numéro de
périodique n'ont pas d'équivalent Nakala).

6 tests (`test_vocabulaires_nakala.py`).

## V0.9.9 (stable, 2026-06-08)

### Journal des suppressions d'entités

Comble le principe directeur n°4 (« journaliser toutes les opérations
destructives ») pour les suppressions de fonds / collection / item,
jusque-là non tracées (`OperationFichier` ne couvrait que les fichiers,
`ModificationItem` que les métadonnées d'item).

Nouvelle table `OperationEntite` : à chaque suppression, une ligne est
écrite **dans la même transaction** que le delete (atomicité : les deux,
ou rien) avec le type d'entité, la cote, le fonds de contexte, un
snapshot JSON des colonnes propres, et un résumé de cascade (compteurs
items / fichiers / annotations / collaborateurs / collections détachées
+ listes d'ids/cotes des enfants affectés).

- Service `services/operations_entite.py` (`journaliser_suppression_*`
  + `lister_suppressions`), câblé dans les 3 services `supprimer_*`.
- Routes web `/…/supprimer` : journalisent avec l'utilisateur courant.
- Commandes CLI delete : option `--utilisateur` pour l'attribution.
- Listing : `archives-tool montrer suppressions [--type fonds|
  collection|item] [--format text|json]` (lecture seule).
- **Undo hors scope** : le snapshot + les listes d'ids (bornées, même
  pour un fonds à 7000+ fichiers) rendent un restore futur possible
  sans perte d'information, mais son exécution reste un chantier dédié.
  Pas d'unification avec les journaux existants (migration risquée,
  gain nul à court terme).

Migration Alembic `q5u6v7w8x9y0` idempotente. 8 tests.

## V0.9.8 (stable, 2026-06-08)

### Année dérivée de la date EDTF

Friction relevée au catalogage Por Favor : `Item.annee` (colonne
numérique indexée, utilisée par les filtres de période, la timeline
de synthèse et le contrôle qa `META-ANNEE-IMPLAUSIBLE`) était un champ
saisi à la main *en plus* de `Item.date` (EDTF). Double saisie, donc
désynchronisation silencieuse (date `1969-09` mais année oubliée à
`1968`).

`annee` est désormais **entièrement dérivée de `date`** à chaque
enregistrement, via tous les chemins d'écriture (création, modification,
édition inline, import — tous passent par `_appliquer_formulaire`). Plus
de saisie directe.

- Helper `annee_depuis_date_edtf` centralisé dans `services/items.py`
  (le module `dashboard` le ré-importe pour la timeline / synthèse).
  Extrait l'année d'une date EDTF tolérante (`1974`, `1974-03`,
  `1974-03-11`) ; retourne `None` sur l'imprécis (`vers 1974`, `19XX`,
  `s.d.`) **et hors plage plausible** `[0, 3000]`.
- La borne de dérivation est partagée avec le validateur Pydantic
  (`ANNEE_MIN` / `ANNEE_MAX`) : `annee` étant dérivée *après* la
  validation, une valeur hors plage (BCE, année aberrante) écrite en
  base casserait le round-trip du formulaire au chargement suivant.
- `_appliquer_formulaire` : date parse → autorité ; sinon `annee`
  fournie (CLI / API / import) ; sinon conserve l'existant (préserve
  les imports legacy où seule `annee` était peuplée).
- UI : champ Année passe en lecture seule (page Modifier + cartouche
  inline). En édition inline, modifier `date` repeint la cellule
  Année sans reload (valeur recalculée renvoyée par la route, peinte
  par `inline_edit.js`).

11 tests (7 service, 4 route inline dont un test de contrat
template ↔ JS).

## V0.9.7 (stable, 2026-05-27)

Deux chantiers livrés sous V0.9.7.

### Création en série d'items

Manquant identifié dans `plan-de-chantier.md` : préparer N fiches
d'items placeholders avant numérisation, pour pouvoir rattacher les
scans au fil. Service `creer_items_en_serie` + CLI `archives-tool
items creer-serie` + bouton « + Créer une série » sur la page
collection. Pattern Python `str.format` avec variable `{n}` (ex
`PF-{n:03d}`), plage `de_n..a_n` (cap 1000), titre template
optionnel, valeurs par défaut etat/type_coar/langue, transactionnel,
`ignorer_existants` pour rejouabilité. Détection des doublons
intra-série (pattern sans `{n}` produit la même cote) en amont
plutôt qu'IntegrityError opaque. 27 tests.

### Annotations IIIF W3C complet (α + β + γ + δ)

Module d'annotation d'image conforme **W3C Web Annotation Data
Model + IIIF Presentation API 3**. Indexation à la granularité
région d'image (cas Por Favor : identifier les dessinateurs Copi /
Forges / Reiser, marquer caricatures avec lien Wikidata).
Réversible vers Mirador, Recogito, tout viewer standard.

#### α — Modèle + 5 routes REST + migration

- `AnnotationRegion` (FK CASCADE sur Fichier, `selecteur` text,
  `selecteur_type` ∈ `{fragment, svg}`, `corps` JSON liste de
  bodies W3C, `motivation` text). TracabiliteMixin standard (verrou
  optimiste).
- Migration Alembic `o3s4t5u6v7w8` idempotente.
- Service `FormulaireAnnotation` (Pydantic) avec validators stricts
  (`motivation` ∈ `MOTIVATIONS_W3C` 13 valeurs spec), CRUD avec
  verrou optimiste, sérialisation W3C JSON-LD à la volée (jamais
  stockée — toujours calculée depuis SQL plat). Omet les champs
  optionnels (`creator`, `modified`) quand absents (W3C strict).
- 5 routes REST sous `/api` : GET liste fichier (AnnotationPage),
  POST création, GET unitaire, PUT modification (409 si conflit),
  DELETE idempotent (204). POST/PUT acceptent forme simple OU forme
  W3C native (target/body) — un client Annotorious peut envoyer son
  JSON-LD natif sans conversion.
- 25 tests service + routes.

#### β — Annotorious sur OSD

- Vendor `@recogito/annotorious-openseadragon@^2.7` copié via
  `scripts/vendor.mjs` vers `static/js/vendor/annotorious/`.
- `visionneuse_osd.js` émet `visionneuse:pret` (couplage faible
  avec scripts tiers) après que OSD ait fini d'`open`.
- `annotations_osd.js` écoute cet event, greffe Annotorious sur
  l'instance OSD via `OpenSeadragon.Annotorious(osd, opts)`,
  charge les annotations existantes au load via GET, sync les
  create/update/delete via POST/PUT/DELETE.
- Bouton « Annoter » flottant haut-droite du viewer (haut-gauche
  occupé par les contrôles natifs OSD). Masqué sur PDF et en
  lecture seule.
- 9 tests intégration.

#### γ — Panneau latéral + autocomplete vocabulaire + pivot URI

- **Panneau latéral** `<aside data-panneau-annotations>` flottant
  sous le bouton Annoter, liste numérotée des annotations du
  fichier courant, sync via `rafraichirPanneau` à
  create/update/delete. Clic = `anno.selectAnnotation(id)` +
  `anno.fitBounds` → zoom OSD sur la région + popup d'édition.
  Auto-masqué quand 0 annotations.
- **Endpoint** `GET /api/vocabulaires/autocomplete` qui liste
  toutes les `ValeurControlee` actives (libellé, code, URI,
  vocabulaire racine) — 1 requête léger.
- **Widget TAG Annotorious natif** configuré avec
  `vocabulary: [{label, uri}, …]`. Quand l'utilisateur sélectionne
  une entrée avec URI, Annotorious crée DIRECTEMENT un body
  `SpecificResource source={id, label}` (pivot Wikidata/VIAF
  gratuit — pas besoin d'enrichissement client). Race fix : la
  précharge `_vocabReady` Promise est awaited avant init
  Annotorious dans l'event handler `visionneuse:pret`.
- **Tags agrégés sur fiche notice** (`pages/item_fiche.html`) :
  remplace le placeholder « Annotations IIIF (V2) » par la liste
  des tags agrégés depuis tous les fichiers de l'item, dédup par
  (libellé, uri), tri fréquence desc + alpha, libellé cliquable
  vers URI si présente. Vue d'ensemble du catalogage sur la
  notice sans devoir ouvrir page par page.
- 5 tests γ + 1 test γ-fiche.

#### δ — Export Nakala JSON W3C

- Service `serialiser_annotation_collection_w3c` empaquette les
  annotations d'une collection dans un W3C `AnnotationCollection`
  avec un seul `AnnotationPage`. Format conforme spec W3C Web
  Annotation §6.3 + IIIF Presentation API 3 (`@context`, `id`,
  `type=AnnotationCollection`, `label`, `total`, `first.{id, type,
  partOf, items}`).
- Le pivot URI Wikidata créé par γ.3 (`body.source.id` via
  Annotorious natif) est préservé tel quel dans l'export —
  utilisable directement par Mirador / Recogito / portail futur.
- CLI `archives-tool exporter annotations <cote_collection>
  [--fonds X] [--sortie path.json]`. URI canonique du
  AnnotationCollection = DOI Nakala de la collection si publié,
  sinon URI relative locale (à remplacer manuellement après dépôt
  Nakala).
- 4 tests δ.

### Bilan

63 tests annotations (α + β + γ + δ + γ-fiche) + 27 tests création
série. Reste éventuellement, en bonus futur : pagination par canvas
si volume > 5000 annotations, intégration du JSON exporté dans le
manifeste IIIF principal au moment du dépôt Nakala (action manuelle
pour l'instant). Le module d'annotation est utilisable bout en bout
sur PF (créer vocabulaire avec URI Wikidata → annoter via widget
TAG natif → voir sur fiche notice → exporter JSON pour Nakala).


## V0.9.6 (stable, 2026-05-26)

Chantier UX dirigé par les tests d'usage sur le fonds Por Favor.
Objectif : combler les deux angles morts d'orientation —
(a) sur la page collection on saute du compteur d'items au tableau
sans aucune synthèse intermédiaire ;
(b) la moindre édition de métadonnée passe par une page Modifier
séparée.

Aboutit à : (1) une **synthèse** dense au-dessus du tableau d'items
sur les pages collection ET fonds, qui répond à « quoi / quand /
quelle gueule / quoi finir / où j'en suis » ; (2) l'**édition inline
complète** des bandeaux et identifiants sur les 3 entités (item,
collection, fonds) — plus aucun détour par /modifier pour les
champs courants ; (3) le redirect URL `/item/<cote>` vers la fiche
notice (la visionneuse vit sur `/visionneuse`) qui était en chantier
V0.9.5 mais non formellement livré.

**1090/1090 tests verts** au total — première fois que la suite
complète passe depuis le bascule fiche V0.9.5 (6 tests visionneuse
pointaient sur l'ancienne URL, dette de 8 mois résorbée).

### Synthèse de collection (Lot 1)

Composant `synthese_collection.html` au-dessus du tableau d'items
sur `/collection/<cote>`. Service `composer_synthese_collection`
en ~4 requêtes SQL bornées indépendamment du volume.

Sections (toutes auto-masquées si vide) :
- **Identifiants** : DOI Nakala + DOI parent inline-éditables
  (déplacé du bandeau après retour utilisateur — tout dans la même
  boîte)
- **Période** : mini-timeline avec barres + comptes + labels d'année.
  Pas annuel si plage ≤ 30 ans, sinon décennal aligné sur multiples
  de 10. Année dérivée de `Item.date` EDTF si `Item.annee` est NULL
  (cas import Nakala). Cap de labels (1 sur 2) au-delà de 12 barres.
- **Agrégats qualitatifs** : Langues + Types COAR (libellés humains
  via vocab, fallback ISO 639-1 → 639-3 pour `es` → `Espagnol`),
  puis top 6 clés `Item.metadonnees` les plus fréquentes. Rendu
  compact « Langue : Espagnol (172) » sur 1 ligne quand
  `nb_distinct == 1` (sinon header multi-ligne avec top N).
- **Vignettes** : 12 vignettes échantillonnées uniformément (stride
  flottant), placeholder par extension pour les non-images.
- **À finir** : trous catalographiques (sans titre / sans année /
  sans fichier / à corriger), seul « à corriger » a un deep-link
  vers la liste filtrée.
- **Activité récente** : 5 derniers items modifiés du périmètre.

Heuristiques anti-bruit côté agrégats :
- Blacklist `_META_ITEM_TECHNIQUES_SYNTHESE` (num_files, hash,
  sha256, data_url, iiif_url, categories, …) — fingerprints Nakala
  sans valeur documentaire.
- Filtre identifiants : un champ dont la valeur la plus fréquente
  apparaît ≤ 1 fois ET ≥ 5 valeurs distinctes est écarté (cas PF :
  `ancienne_cote` = 173 valeurs uniques, identifiant pur).

### Synthèse de fonds + cartographie cross-collection (Lot 2)

Composant `synthese_fonds.html` au-dessus de la liste des
collections sur `/fonds/<cote>`. Service `composer_synthese_fonds`
en ~5-7 requêtes SQL bornées (test garde-fou à 10).

Réutilise les helpers de la synthèse collection portés à tous les
items du fonds (via `Item.fonds_id`). Ajoute :

- **Bloc Identifiants revue** : Éditeur, Lieu, Périodicité, ISSN,
  Début, Fin, Responsable, Personnalité. Tous inline-éditables.
  En lecture seule, seuls les champs renseignés apparaissent ;
  en édition, les vides sont à `opacity:0.55` avec placeholder
  « + ajouter » (s'effacent visuellement sans dominer l'œil).
- **Collections** : cartographie cross-collection toujours visible
  (mêmes si une seule miroir). Par collection : barre proportion +
  nb items + nb partagés avec une autre libre + DOI Nakala
  cliquable vers nakala.fr. Header adapté :
  - « Collections · uniquement la miroir » (cas usuel 1 collection)
  - « N items uniquement dans la miroir · M dans plusieurs libres »
    (cas multi-libres, cas demo FA avec 4 libres)
  Exclut les transversales (elles empruntent des items mais
  n'appartiennent pas au fonds — décision sémantique testée).

### Édition inline complète sur les 3 entités (Lot 3)

Le pattern V0.9.1 d'édition inline (item) est étendu à collection
et fonds. Plus aucun champ courant ne nécessite la page Modifier.

- **Items** (déjà V0.9.1) : `CHAMPS_ITEM_EDITABLES_INLINE`
  (etat_catalogage, titre, type_coar, date, annee, langue, numero,
  description, notes_internes, doi_nakala, doi_collection_nakala).
- **Collection** (V0.9.6 Lot 3) :
  `CHAMPS_COLLECTION_EDITABLES_INLINE` (15 champs). Bandeau :
  titre + description + phase (avec select PHASES_OPTIONS).
  Synthèse Identifiants : DOI Nakala + DOI parent.
  Route POST `/collection/<cote>/champ/<field>?fonds=X`.
- **Fonds** (V0.9.6 Lot 3) :
  `CHAMPS_FONDS_EDITABLES_INLINE` (12 champs). Bandeau : titre +
  description. Synthèse Identifiants : 8 champs revue.
  Route POST `/fonds/<cote>/champ/<field>`.

Le `<meta name="entity-context">` (renommé depuis `item-context`,
avec fallback compat pour pages item) est lu par `inline_edit.js`
qui ouvre l'input au double-clic, POST la valeur, swap la réponse
dans `[data-value]`, met à jour la version. Partial
`inline_edit_valeur.html` rendu générique (entity / item fallback).

Restent hors whitelist (page Modifier) sur les 3 entités : `cote`
(URLs + exports + renommage chantier), `version` (technique),
`fonds_id` / `type_collection` (invariants).

### Pages détaillées item — bascule URL formellement livrée

V0.9.5 avait mis en place la fiche item (notice 3 colonnes sans
visionneuse) comme vue par défaut sur `/item/<cote>`, avec la
visionneuse déplacée sur `/item/<cote>/visionneuse`. Le bascule
n'avait pas été formellement livré : 6 tests `test_page_item_lecture_*`
pointaient encore sur l'ancienne URL et échouaient silencieusement.

V0.9.6 : tests mis à jour vers `/visionneuse`, docstrings actualisées.
Pleine suite passe (1090/1090).

Composants livrés en V0.9.5 (formellement intégrés en V0.9.6) :
- `pages/item_fiche.html` : layout 3 colonnes (cartouche métadonnées,
  fichiers compact, vignettes scrollables).
- `composer_fiche_item` : agrégats meta fichier (sans techniques),
  position 1-indexed (distincte de Fichier.ordre qui peut avoir
  des sauts sur fac-similés incomplets).
- `_META_FICHIER_TECHNIQUES` : blacklist URL Nakala / hash / chiffre
  pour les agrégats fichier.

### Détails techniques notables

- `_LANGUES_ISO1_VERS_ISO3` : mapping défensif pour résoudre les
  codes ISO 639-1 (`fr`, `es`…) que Nakala/DC exportent
  fréquemment, alors que `LANGUES_OPTIONS` est en ISO 639-3.
- `_annee_depuis_date_edtf` : extraction de l'année (4 chiffres) depuis
  une chaîne EDTF tolérante. Sert de fallback à `Item.annee`.
- `PHASES_OPTIONS` exporté depuis `vocabulaires` + enregistré dans
  `OPTIONS_PAR_CHAMP` pour résolution du libellé humain dans
  l'inline edit.
- Service `composer_page_collection` reste inchangé (bandeau + filtres) ;
  la synthèse vit en parallèle dans `composer_synthese_collection`
  pour séparation des responsabilités.

### Tests

+85 nouveaux tests (synthese collection 28, synthese fonds 13,
inline edit étendu 14, fiche item maintien 30+). Garde-fous SQL :
synthese fonds ≤ 10 queries, synthese collection ≤ 7 queries.

### Migration

Pas de migration de données. Pas de migration de config. Hot-reload
sans risque.


## V0.9.4 (stable, 2026-05-25)

Itération après V0.9.3 stable, démarrée pendant la poursuite du test
d'usage Por Favor. Cible : combler le gap V0.7 backlog — l'import
dumpe les colonnes hors socle DC en clés libres dans
`Item.metadonnees` sans qu'on puisse les formaliser depuis l'UI.

Aboutit à un workflow champs personnalisés bouclé bout-en-bout :
import → bouton « Formaliser » sur clé libre → page de gestion par
collection → édition de valeur depuis le formulaire item → affichage
du libellé humain dans le cartouche. Plus une UI complète de
vocabulaires custom (CRUD `Vocabulaire` + `ValeurControlee`)
attachables à un `ChampPersonnalise` de type `liste` / `liste_multiple`.

1015+ tests verts au total, ruff src clean.

### Champs personnalisés (Lot 1)

- Nouvelle colonne `ChampPersonnalise.actif` (migration
  `n2r3s4t5u6v7`) : permet de déprécier un champ sans détruire les
  valeurs des items, qui retombent en clé libre dans le composer
  cartouche.
- Service `champs_personnalises.py` : `creer_champ` (validation slug
  minuscule + underscore, libellé obligatoire), `modifier_champ`
  (libellé / type / ordre / aide / description interne — la `cle`
  reste figée), `renommer_champ` (change la `cle` ET propage la
  valeur dans `Item.metadonnees` de tous les items de la collection,
  avec bump de `version` pour invalider les éditeurs inline
  concurrents), `deprecier_champ` / `reactiver_champ` (idempotent
  via toggle `actif`), `supprimer_champ` (hard delete réservé aux
  cas qui ne récidiveront pas).
- Page de gestion `/collection/<cote>/champs?fonds=<f>` : liste
  triée par (ordre, clé) avec actif/déprécié en colonne, formulaire
  de création en bas de page (7 champs : clé, libellé, type, ordre,
  aide, description interne). Boutons Modifier / Déprécier /
  Réactiver par ligne.
- Page de modification d'un champ : 3 blocs distincts —
  attributs (libellé / type / ordre / aide / desc interne, sans la
  clé), renommage de la clé (avec mention explicite de la propagation
  transactionnelle), cycle de vie (déprécier / réactiver). Garde
  anti-confused-deputy : un POST sur `/collection/HK/champs/<id>` où
  l'`<id>` appartient en réalité à une autre collection retourne 404.
- Lien « Champs personnalisés » dans le bandeau de la page Collection
  lecture (à côté de « Modifier » / « Voir le fonds »).
- `composer_metadonnees_par_section` filtre `actif=True` : les champs
  dépréciés n'apparaissent plus dans la section formelle du cartouche
  item, mais leurs valeurs restent affichables via le fallback Bug C
  V0.9.2-import (clé libre, libellé synthétisé).
- Tests : 19 nouveaux (service + routes), suite stable.

### Champs personnalisés (Lot 2 — promotion clé libre)

- `ChampMetadonnee.est_libre_promouvable` : nouveau flag posé par
  `composer_metadonnees_par_section` sur les lignes de la section
  « Champs personnalisés » issues du fallback Bug C (clés libres
  sans `ChampPersonnalise` formel). True uniquement pour les clés
  dont le slug est valide (PATTERN_CLE) — l'utilisateur doit
  nettoyer en amont les clés malformées (Mots-Clés, Unnamed: 15,
  etc.) avant promotion.
- Service `promouvoir_cle_libre_en_champ(db, item, cle)` : trouve
  la miroir du fonds de l'item, crée un `ChampPersonnalise` avec
  libellé synthétisé via `_libelle_depuis_cle`. Idempotent (si un
  champ avec cette clé existe déjà, retourne le champ existant sans
  réactiver un éventuel déprécié — l'utilisateur conserve le contrôle).
- Route `POST /item/<cote>/promouvoir-cle?fonds=<f>` : redirige vers
  la page item (le champ apparaît immédiatement en section formelle).
- Cartouche : mini bouton « Formaliser » à droite de chaque ligne
  libre promouvable, masqué en lecture seule. Discret (bleu pâle,
  border 1px) ; tooltip explicatif.
- 8 nouveaux tests (service + composer + routes).

### Vocabulaires personnalisés (Lot 3 — CRUD + wire ChampPersonnalise + composer)

- Service `vocabulaires_db.py` : CRUD complet `Vocabulaire` +
  `ValeurControlee` (créer / modifier / supprimer / déprécier /
  réactiver). Distinct des vocabs hardcoded (`LANGUES_OPTIONS`,
  `TYPES_COAR_OPTIONS`, `ETATS_OPTIONS`) qui restent figés en code
  comme fondamentaux du domaine.
- Suppression d'un vocabulaire refusée s'il est encore référencé par
  un `ChampPersonnalise` (`VocabulaireReference` avec liste des
  champs en cause).
- Routes `/vocabulaires`, `/vocabulaires/<id>`, ajout/modif/déprécier
  des valeurs. Garde anti-confused-deputy sur l'appartenance
  valeur→vocab.
- Templates : `pages/vocabulaires.html` (liste + création),
  `pages/vocabulaire_detail.html` (4 blocs : métadonnées, valeurs
  contrôlées, ajout, suppression).
- Lien discret « Vocabulaires » en haut à droite du dashboard.
- Wire avec `ChampPersonnalise.valeurs_controlees_id` : dropdown
  dans les formulaires de création et de modification d'un champ
  personnalisé. Détacher = `<option value="">— aucun —</option>`
  (Pydantic validator convertit "" en None).
- Composer cartouche : pour un champ avec vocab DB, charge les
  options et résout le libellé humain (« Bande dessinée » pour le
  code « bd » stocké en `metadonnees`). Valeur hors vocab (legacy
  ou déprécié) → fallback sur la valeur brute (pas de perte).
- Eager loading `selectinload(ChampPersonnalise.vocabulaire).selectinload(Vocabulaire.valeurs)`
  pour éviter N+1 dans le composer.
- Bug fix : `ajouter_valeur` passait par la FK seule
  (`vocabulaire_id=X`), ce qui laissait `vocab.valeurs` stale dans
  la session courante. Refactor pour passer par la relation
  (`vocab.valeurs.append(valeur)`) — back-populate auto.
- 22 nouveaux tests vocab + 5 nouveaux tests champs (54 au total
  sur les deux modules).

### Item modifier expose les champs personnalisés (Lot V0.9.5)

Avant ce lot, formaliser une clé libre via le cartouche créait bien
le `ChampPersonnalise` mais l'utilisateur n'avait aucune UI pour
**éditer la valeur** d'un item. Il fallait éditer le JSON
`metadonnees` à la main. La page de modification ignorait totalement
les `ChampPersonnalise`.

- Helper `lister_champs_actifs_pour_item(db, item_id)` factorisé
  depuis `composer_page_item` (eager-load vocab + valeurs, filtre
  `actif=True`, trié par (ordre, cle)). Composer et page modifier
  utilisent maintenant la même requête.
- Route `POST /item/<cote>/modifier` convertie en `async` pour
  pouvoir relire `request.form()` après le parse Pydantic. Itère
  sur les champs perso actifs, extrait les `meta_<cle>` du form,
  fusionne dans `formulaire.metadonnees`. Valeur vide = clé
  supprimée (sémantique cohérente avec import + cartouche).
- Template `item_modifier.html` : section « Champs personnalisés »
  entre Catalogage et Identifiants externes. Rendu conditionnel
  selon le type :
  - `liste_multiple` + vocab → grille de checkboxes (cases_a_cocher)
  - `liste` + vocab → `<select>` libellé humain + hors-liste fallback
  - `texte_long` → textarea 5 lignes
  - `nombre` → `<input type="number">`
  - autres → input texte
- `obligatoire=True` ajoute l'attribut HTML5 `required` sur
  input / textarea / select (defense en profondeur, bloque le submit
  navigateur si vide). Pas de validation côté service — un catalogue
  WIP peut avoir des champs perso non remplis.

### Affichage libellé humain (polish transversal)

Plusieurs endroits affichaient encore les valeurs brutes des
vocabulaires système au lieu des libellés humains :

- `ItemResume.type_label` résout via `TYPES_COAR_OPTIONS` (le
  commentaire « pas de table de libellés en V0.9.0 » était obsolète
  depuis V0.9.3).
- Pastilles de filtres actifs Collection : `t | libelle_coar` et
  `lang | libelle_langue` (avant : « Type: c_3e5a », « Langue: fra »).
- Drawer panneau filtres Collection : `libelles` dict pour Langue
  et Type — le composant supportait déjà le slot.
- Colonne « Langue » du `tableau_items` : `item.langue | libelle_langue`.
- Item modifier : `<select>` pour `langue` et `type_coar` (avant :
  inputs libres). Macro `selecteur` étendue avec `libelle_vide`
  (option `value=""` en tête) et fallback hors-liste (valeur
  courante absente du vocab → ajoutée en queue avec suffixe).

### Lien « Gérer » sur le cartouche

Friction UX du Lot 2 fermée : après « Formaliser » une clé libre,
4 clics étaient nécessaires pour atteindre la page de gestion (Item
→ Collections → Collection → bouton « Champs perso »). Ajout d'un
lien discret « Gérer » dans le header de la section « Champs
personnalisés » du cartouche → `/collection/<miroir>/champs`. 1 clic.

Macro `section()` étendue avec `action_url` + `action_label` ; le
clic appelle `event.stopPropagation()` pour ne pas toggler le
`<details>`. Lien rendu uniquement si `gestion_champs_url` est
fournie (page consultation `lire_item.html` ne le passe pas →
read-only).

### Race protection (polish Lot 2)

- `promouvoir_cle_libre_en_champ` : try/except `IntegrityError` qui
  recharge le champ existant si une autre transaction a inséré le
  même `(collection_id, cle)` entre notre SELECT et notre INSERT.
  Cohérent avec l'idempotence documentée.
- `aria-label` explicite sur le bouton « Formaliser » pour les
  lecteurs d'écran.

### Fix latent (migration FTS5)

- `m1q2r3s4t5u6_fts5_recherche.upgrade` n'était pas idempotent face
  à des triggers déjà créés par `assurer_tables_fts` au startup de
  l'app (cas d'une base où l'app avait démarré avant d'appliquer la
  migration). DROP TRIGGER IF EXISTS ajouté avant la recréation.

## V0.9.3 (stable, 2026-05-25)

Trois gros chantiers livrés au fil de l'eau après V0.9.2 stable,
pilotés par un premier test d'usage sur un export Nakala réel
(corpus Por Favor : 173 items, 7454 scans). 944 tests verts.

### Recherche full-text (FTS5)

- Backend SQLite FTS5 sur les champs textuels des items, fonds et
  collections (cote, titre, description, notes internes,
  métadonnées libres flattenées). Tokeniseur `unicode61` insensible
  aux accents (`numero` matche `Numéro`). Triggers SQL maintiennent
  l'index en temps réel.
- Page `/recherche` : barre + scope (fonds/collection) + filtre par
  type d'entité, snippets surlignés `<mark>` (HTML-safe anti-XSS).
- Barre de recherche globale dans le bandeau, disponible sur toutes
  les pages. Raccourcis `/` ou `Cmd+K` pour focus.
- Filtres avancés : état de catalogage, langue, type COAR, période
  d'années, raffinement « rechercher dans les résultats ». Options
  scope-aware (un fonds en français n'affiche pas « polonais »).
  Pastilles cliquables × pour retirer un filtre, bouton « Tout
  réinitialiser » dès 2 filtres actifs.
- Pagination réelle (50/page par défaut, cap 200), cap dur 5000
  résultats par type avec note discrète si dépassé.
- Libellés humains pour Type COAR (« Périodique » au lieu de
  `c_3e5a`) et Langue (« Français » au lieu de `fra`) — réutilise
  les tables `TYPES_COAR_OPTIONS` / `LANGUES_OPTIONS` partagées avec
  l'édition inline.
- Surlignage propagé : `?q=` transmis aux pages détail item pour
  retrouver les matches sur la fiche cliquée (filtre Jinja
  `surligner_q`).
- Raccourcis clavier sur la page résultats : ← / → pour paginer,
  Esc pour défocus la barre.
- Documentation [guide/recherche.md](../guide/recherche.md) dédiée.

### Liseuse consultation

- Mode lecture distinct du mode édition : route
  `/lire/<fonds>/<cote>` avec layout 3 colonnes (cartouche meta
  gauche, visionneuse centre, panneau vignettes droite). Bandeau
  spécifique avec navigation séparée Page ← → / Item ← →.
- HTMX swap multi-fragments (visionneuse + bandeau + vignettes) à
  chaque clic vignette ou bouton Page — pas de reload.
- **Lot 2** : viewer PDF embedded via PDF.js 5 (build legacy + WASM
  OpenJPEG pour JP2 Nakala), couche texte OCR sélectionnable.
- **Lot 3** : raccourcis clavier ← / → (navigation pages dans la
  liseuse), Esc retour catalogage. Indicateur loading pendant
  HTMX swap.
- **Lot 4** : viewer PDF en scroll continu (toutes les pages
  affichées, IntersectionObserver pour lazy render des canvas,
  économie mémoire sur PDF longs comme les fac-similés Nakala
  à 40+ pages).

### Assistant d'import (V0.9.2-import)

- Refonte en 2 modes : simple (4 questions cote/granularité/titre/
  date, auto-classification des autres colonnes) et avancé (grille
  de 28 sélecteurs avec aperçu inline + heuristiques nominatives +
  détection d'anomalies).
- Classif par-item / par-fichier automatique (≥ 90 % stables =
  item, > 50 % variables = fichier), promotion auto des colonnes
  par-fichier vers `fichier.metadonnees.<slug>`.
- Section « Anomalies détectées » avec correction client-side sans
  POST intermédiaire.
- 4 frictions résolues sur le test PF (F1-F4) + 3 bugs critiques
  (promotion URL Nakala silencieuse, mode simple qui écrasait les
  champs DC dédiés, champs personnalisés invisibles sur la page
  item) + trou #9 (singulier/pluriel auteur/sujet à l'export DC).
- Normalisation IIIF Nakala (URL data → info.json) + téléchargement
  direct dans le fallback visionneuse + type COAR auto (alias
  textuel → URI canonique) + propagation DOI collection Nakala sur
  la miroir + miniatures Nakala via thumb IIIF.

### Autres polish

- Édition inline : textarea Description agrandi à 10 lignes (était
  3), padding aéré pour confort de rédaction.
- Pages modifier (item/collection/fonds) : Description publique
  passe à 10 lignes, Description interne / Notes à 5-6 lignes.
- Layout responsive : nouveau block Jinja `container_class` dans
  `base.html`, défaut `max-w-7xl` (1280px). La page recherche
  l'override en `max-w-full` pour profiter de la pleine largeur
  sur grand écran (snippets et filtres avancés respirent mieux).
  Les autres pages gardent le cap (cartouche item, formulaires
  fixed-width n'aiment pas s'étirer sur 4K).
- A11y des pastilles de filtres : `aria-label` explicite sur les
  liens × pour les lecteurs d'écran (« Retirer le filtre État :
  Brouillon » au lieu de « lien : État deux points Brouillon
  multiplication »).
- CLI `archives-tool reindexer` : commande utilitaire pour
  reconstruire les tables FTS5 d'une base ancienne (pré-V0.9.3)
  ou restaurée depuis une sauvegarde sans index. Idempotent.
- Check FTS au démarrage de l'app : hook lifespan FastAPI qui
  appelle `assurer_tables_fts` sur la base courante. Sécurise
  l'upgrade : pas besoin d'appeler `reindexer` à la main quand
  on ouvre une base pré-V0.9.3 dans l'interface web.
- Documentation : nouvelles pages [guide/liseuse.md](../guide/liseuse.md)
  et [guide/import-assistant.md](../guide/import-assistant.md)
  qui comblent un trou (les deux chantiers étaient livrés sans
  page MkDocs dédiée).

## V0.9.2 (stable, 2026-05-10)

Cible atteinte : interface web complète sur les 4 pages
(Dashboard, Fonds, Collection, Item), drawers + drag-drop +
visionneuse OpenSeadragon, code legacy V0.6 entièrement purgé,
529 tests verts, ruff clean, mkdocs strict clean.

Voir le détail dans la roadmap V0.9.2 ci-dessus
(`alpha → beta.2 → beta.3 → gamma → finale`).

### V0.9.1 — Renforcement mode local

- Activation explicite de SQLite en mode WAL.
- Verrou optimiste sur l'édition (champ `version` exploité au
  save, message de conflit en cas de modification concurrente).
- Mode lecture seule activable via `config_local.yaml` (pour
  exposer ColleC à un consultant occasionnel sans risque de
  modification).
- Format JSON pour `archives-tool renommer` (parité avec
  `controler` et `montrer`).
- Documentation : « Installation locale + ShareDocs en WebDAV »
  pas-à-pas (Windows, macOS, Linux).

Cible : 1 session ~6h. Préparation du test d'usage sur un mini-
fonds réel avant de basculer en mode serveur partagé.

### V1.0 — Déploiement VPS + multi-utilisateurs

- Variable `ARCHIVES_MODE` (`local` | `serveur`) détectée au
  démarrage.
- Table `Utilisateur` avec auth simple (sélection dans liste +
  cookie de session, pas de mot de passe — réseau interne).
- CLI `archives-tool utilisateurs` (ajouter, lister, désactiver).
- Empaquetage Docker, reverse proxy Caddy/nginx avec HTTPS
  Let's Encrypt, mount WebDAV ShareDocs sur le VPS.
- Sauvegarde quotidienne automatique de la base SQLite.
- Documentation déploiement : `docs/deploiement/{vps,maj,restore}.md`.

Cible : 2 sessions ~12h, après le test d'usage de V0.9.1. Si
frictions bloquantes identifiées, V0.9.2 avant V1.0.

## V0.9.0 (stable)

Cycle de refonte majeur. Modèle pivoté autour du triptyque
**Fonds / Collection / Item** avec multi-appartenance et
distinction miroir / libre / transversale. C'est la version qui
sépare clairement les concepts de fonds (matériel) et de
collection (regroupement publiable).

### Nouveau modèle

- Introduction de l'entité `Fonds` (corpus brut, notion ColleC).
- Trois types de Collection : miroir (auto-créée à la création
  du fonds), libre rattachée, libre transversale (multi-fonds).
- Multi-appartenance des items via la table N-N
  `item_collection`.
- 10 invariants documentés, dont 4 vérifiés par les contrôles
  qa.

### CLI complète refondue

- `archives-tool importer` — profils YAML v2 (sections `fonds:`
  + `collection_miroir:`).
- `archives-tool collections` — gestion des libres
  (`creer-libre`, `lister`, `supprimer`).
- `archives-tool exporter` — Dublin Core XML, Nakala CSV, xlsx,
  tous par collection.
- `archives-tool controler` — 14 contrôles, 4 familles, formats
  text/JSON.
- `archives-tool montrer` — consultation rapide (4 sous-commandes
  pour fonds/collection/item/fichier).
- `archives-tool renommer` — transactionnel atomique, dry-run par
  défaut, annulation par batch.
- `archives-tool deriver` — génération vignettes/aperçus,
  invalidation automatique au renommage.
- Périmètre unifié `--fonds` / `--collection` / `--item` /
  `--fichier-id` partagé entre commandes.

### Interface web

- Dashboard avec arborescence dépliable fonds → collections.
- Pages détaillées Fonds, Collection (3 variantes), Item.
- Visionneuse de fichiers avec navigation
  Précédent/Suivant.
- Édition de métadonnées (formulaires Pydantic, pattern PRG).
- Gestion des collaborateurs par fonds (vocabulaire fermé,
  multi-rôles).

### Documentation

- Site [MkDocs Material](https://hsbtqemy.github.io/ColleC/)
  déployé sur GitHub Pages, mise à jour automatique sur push
  `main`.
- Guide « Premiers pas » complet : installation, configuration,
  premier import, workflow type.
- Pages Concepts (avec diagramme Mermaid), CLI (7 commandes
  documentées), Référence (profils, formats d'export, schéma de
  données, 14 contrôles qa).
- Section Pour développeurs : architecture, modèle, services,
  tests, composants UI, contribuer.

### Performance

- Pas de N+1 sur les routes principales (eager loading via
  `selectinload`).
- Index DB sur les champs critiques (`Fonds.cote`,
  `Item.fonds_id`, `ItemCollection`).
- Renamer en deux phases pour absorber les cycles de
  renommage.

## V0.9.0 (release candidate)

Cycles `gamma.4.x` (CLI) puis `gamma.5.x` (documentation).
Toutes les modifications sont consolidées dans la V0.9.0 stable
ci-dessus.

## V0.8.0

- Section Collaborateurs sur la page de modification d'une
  collection. Vocabulaire fermé (`numerisation`, `transcription`,
  `indexation`, `catalogage`), multi-rôles par personne,
  formulaire HTMX.

## V0.7.x

- Création de collection vide depuis l'UI.
- Menu Importer + page placeholder `/import` (assistant à venir).
- Empty state proactif sur collection vide.
- Boutons « Modifier » et « Importer dans cette collection » sur
  le bandeau collection.

## V0.6.x

- Interface web complète en lecture : dashboard, vue collection
  (3 onglets), vue item trois zones, visionneuse OpenSeadragon
  (multi-sources : IIIF Nakala > DZI > aperçu local).
- Tri des colonnes via HTMX, filtre/recherche dans tableaux,
  pagination, sélection persistée des colonnes via le panneau
  Colonnes (drag-drop Sortable.js, `PreferencesAffichage`).

## V0.5

- Premier dashboard simple (inventaire, alertes).

## V1.0 (à venir)

Stabilisation après usage en production sur plusieurs vrais
fonds. Pas de nouvelle fonctionnalité majeure prévue d'ici là —
priorité au polish, à la doc et à la robustesse.
