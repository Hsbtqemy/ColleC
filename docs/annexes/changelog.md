# Changelog

Les jalons notables. Le détail commit-par-commit est dans
[l'historique GitHub](https://github.com/Hsbtqemy/ColleC/commits/main).

## V0.9.0 (release candidate)

Cycle de refonte majeur. Modèle pivoté autour du triptyque
**Fonds / Collection / Item** avec multi-appartenance et
distinction miroir / libre / transversale. Stable, en attente de
mise en production.

- **Modèle** : refonte complète. Fonds (corpus brut), Collection
  (classement publiable, miroir auto ou libre), Item
  (multi-appartenance via `ItemCollection`).
- **Importers v2** : profils YAML avec sections `fonds:` +
  `collection_miroir:`. Rejet explicite des profils v1 obsolètes.
- **Exporters refondus** : Dublin Core, Nakala, xlsx, tous par
  collection. Helper partagé `composer_export`. Notice de tête
  collection en sortie.
- **CLI complète** : `archives-tool {importer, exporter, collections,
  controler, montrer, renommer, deriver, profil, demo}`. Périmètre
  unifié `--fonds` / `--collection` / `--item` / `--fichier-id`.
- **Module qa refondu** : 14 contrôles répartis en 4 familles
  (invariants, fichiers, métadonnées, cross), lecture seule,
  formats text Rich + JSON stable pour CI.
- **Interface web** : dashboard arborescent fonds → collections,
  pages détail Fonds / Collection / Item, édition complète,
  visionneuse navigable, gestion collaborateurs.
- **Renommage transactionnel** : `Perimetre` partagé renamer/
  deriver, invalidation automatique de `derive_genere` après
  rename ou annulation.
- **Documentation** : mise en place MkDocs Material, déploiement
  GitHub Pages automatique.

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
