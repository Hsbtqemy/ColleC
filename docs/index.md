# ColleC

Outil de gestion de collections numérisées pour archives
universitaires. Développé à l'Université de Poitiers.

## Vue d'ensemble

ColleC est un espace de travail vivant pour archiver, cataloguer
et publier des collections numérisées. Il gère le travail interne
(métadonnées riches, états de catalogage, multi-appartenance)
sans contraindre la sémantique Nakala pour la publication.

**Caractéristiques principales** :

- Modèle Fonds / Collection / Item compatible Nakala
- Multi-appartenance d'items à plusieurs collections
- Interface web pour le travail quotidien
- CLI pour l'automatisation et l'intégration
- Imports/exports configurables (Dublin Core, Nakala, xlsx)
- Contrôles de cohérence intégrés
- Renommage transactionnel et génération de dérivés

## Pour démarrer

[Installation et configuration →](premiers-pas/index.md)

## En cas de besoin

- [Schéma de données](reference/schema.md) — modèle relationnel,
  Fonds / Collection / Item et leurs relations
- [Workflow type](premiers-pas/workflow-type.md) — du dépôt
  physique à la publication Nakala
- [Contrôles qa (CLI)](guide/cli/controler.md) — les 14 contrôles
  de cohérence et leur interprétation

## État du projet

Version actuelle : V0.9.0 (release candidate). Modèle stable,
fonctionnalités complètes. La V1.0 marquera la stabilisation
après usage en production sur plusieurs vrais fonds.

## Contexte

Développé pour les archives de l'Université de Poitiers, ColleC
est ouvert et le code est public. Voir [Contribuer](developpeurs/contribuer.md)
si vous souhaitez participer.
