# Workflow type

Le parcours typique d'un fonds, du dépôt physique à la publication
Nakala. Les étapes 4 et 8 se font hors de l'outil ; les autres
sont automatisables via la CLI.

## 1. Réception

Numérisation des originaux par votre service de numérisation,
ou par un prestataire. Les scans arrivent typiquement comme un
dossier de fichiers TIFF haute résolution, parfois accompagnés
d'un tableur d'inventaire (Excel ou CSV).

À cette étape, **organiser les scans** sous une arborescence
prévisible — typiquement un sous-dossier par item — pour
faciliter la résolution automatique au moment de l'import.

## 2. Préparation

Écrire (ou faire générer) un [profil d'import YAML](../reference/profils.md)
qui décrit :

- les métadonnées du fonds (titre, éditeur, dates, descriptions…) ;
- la structure du tableur (mapping colonnes → champs internes) ;
- la convention de nommage des scans (motif chemin avec
  placeholders).

Voir [Premier import](premier-import.md) pour un exemple complet
qu'on peut adapter.

## 3. Import

Toujours commencer par un dry-run :

```bash
archives-tool importer profils/votre_fonds.yaml
```

Lire le rapport, corriger les `lignes_ignorees` et `warnings`,
puis lancer pour de vrai :

```bash
archives-tool importer profils/votre_fonds.yaml \
    --no-dry-run --utilisateur "Votre nom"
```

À ce stade, le fonds existe en base avec sa **miroir auto-créée**
(la collection « tous les items du fonds »).

## 4. Catalogage

Hors CLI : utiliser l'[interface web](../guide/interface-web.md)
pour enrichir les métadonnées item par item — descriptions,
auteurs, sujets, type COAR, langue…

L'interface gère :

- édition complète des items (formulaires PRG) ;
- ajout/retrait d'items dans des collections libres ;
- gestion des collaborateurs (numérisation, transcription,
  indexation, catalogage) ;
- visionneuse de fichiers avec navigation Précédent/Suivant.

À l'issue de cette étape, les items passent typiquement de l'état
`brouillon` à `verifie` ou `valide`.

## 5. Vérification

Avant de publier, vérifier la cohérence :

```bash
archives-tool controler --fonds VOTRE_FONDS
```

Le rapport classe les problèmes en **erreurs** (à corriger),
**avertissements** (à arbitrer) et **infos** (signalements
contextuels). Sur la base demo, des avertissements
`FILE-MISSING` sont attendus (chemins fictifs).

Si la base sert dans une CI, utiliser le format JSON :

```bash
archives-tool controler --format json --strict > rapport_qa.json
```

`--strict` fait sortir avec code 1 dès qu'un avertissement
remonte — utile pour bloquer un déploiement automatique.

Référence : [Contrôles qa](../reference/controles.md).

## 6. Génération de dérivés

Pour l'affichage web et les exports, générer vignettes et
aperçus :

```bash
archives-tool deriver appliquer --fonds VOTRE_FONDS
```

Idempotent par défaut (les fichiers déjà dérivés sont sautés). Le
flag `derive_genere` est invalidé automatiquement après chaque
[renommage](../guide/cli/renommer.md), pour forcer la régénération
en aval.

Référence : [deriver](../guide/cli/deriver.md).

## 7. Export Nakala

Préparer le fichier de dépôt bulk :

```bash
archives-tool exporter nakala VOTRE_COLLECTION --fonds VOTRE_FONDS \
    --licence "CC-BY-4.0" --statut publié
```

Trois choix de granularité — toujours **par collection** :

- la **miroir** d'un fonds (cote = cote du fonds) pour exporter
  tout le fonds ;
- une **libre rattachée** pour une sélection éditoriale ;
- une **transversale** (sans `--fonds`) pour mélanger des items
  de plusieurs fonds.

Le rapport signale les `items_incomplets` (champ obligatoire
manquant) et les `valeurs_non_mappees` (`type_coar` hors COAR,
langue hors ISO 639-3). Aucun item n'est bloqué — c'est à vous
d'arbitrer si vous corrigez avant publication ou si vous
déposez tel quel.

Référence : [exporter](../guide/cli/exporter.md).

## 8. Publication

Hors outil : déposer le CSV produit sur Nakala via leur
interface ou leur API. ColleC ne fait pas l'upload (V2+).

Après publication, ranger les DOI Nakala obtenus dans la base
via l'interface web ou par ré-import (le ré-import est tolérant
aux mises à jour).

## Étapes optionnelles

### Renommage canonique

Si les scans arrivent avec des noms peu cohérents, normaliser
avant le reste du flux :

```bash
archives-tool renommer appliquer \
    --template "{cote_fonds}/{cote}-{ordre:03d}.{ext}" \
    --fonds VOTRE_FONDS
```

Dry-run par défaut ; `--no-dry-run` pour appliquer ; annulable
via `archives-tool renommer annuler --batch-id <UUID>`.

Référence : [renommer](../guide/cli/renommer.md).

### Export Excel pour relecture

Pour faire relire un fonds par un collègue qui n'a pas l'outil :

```bash
archives-tool exporter xlsx VOTRE_COLLECTION --fonds VOTRE_FONDS
```

Une feuille avec un item par ligne, ouvrable dans Excel ou
LibreOffice.

## Et ensuite ?

Tout est en place. Les sections [Guide utilisateur](../guide/index.md)
et [Référence](../reference/index.md) donnent le détail de chaque
commande et chaque format.
