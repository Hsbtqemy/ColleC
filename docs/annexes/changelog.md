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
