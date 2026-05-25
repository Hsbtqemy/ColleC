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

## V0.9.4 (en cours, 2026-05-25)

Itération courte après V0.9.3 stable, démarrée pendant la poursuite
du test d'usage Por Favor. Cible : combler le gap V0.7 backlog
identifié sur Por Favor — l'import dumpe les colonnes hors socle DC
en clés libres dans `Item.metadonnees` sans qu'on puisse les
formaliser depuis l'UI. Aboutit à une UI complète de gestion
structurelle des champs personnalisés d'une collection.

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
