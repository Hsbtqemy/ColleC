# Changelog

Les jalons notables. Le détail commit-par-commit est dans
[l'historique GitHub](https://github.com/Hsbtqemy/ColleC/commits/main).

## Roadmap

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
