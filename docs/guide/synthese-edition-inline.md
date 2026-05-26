# Synthèse et édition inline

Depuis V0.9.6, les pages collection et fonds exposent une **synthèse**
au-dessus du tableau d'items, et l'**édition inline** est disponible
sur les trois entités (item, collection, fonds) pour les champs
courants. Plus aucun détour par la page Modifier n'est nécessaire
pour les modifications du quotidien.

## Synthèse

Section dense et sobre, placée juste sous le bandeau d'identification
et au-dessus du tableau d'items. Auto-masquée si l'entité n'a rien
à synthétiser (fonds frais sans items, par exemple). Le toggle
`<details>` permet de la replier si vous préférez accéder directement
au tableau.

### Sur une page collection

Cinq blocs, tous auto-masqués si vides :

- **Identifiants** : DOI Nakala + DOI parent. Inline-éditables au
  double-clic (cf. ci-dessous). Le DOI cliqué dans la
  synthèse-fonds ouvre la fiche Nakala.
- **Période** : mini-timeline avec une barre par année (plage ≤ 30
  ans) ou par décennie (au-delà). Le compte est affiché au-dessus de
  chaque barre qui dépasse 25 % de la hauteur, l'année est sous
  chaque barre. Si l'année d'un item n'est pas remplie mais que la
  date EDTF l'est (`1974-03-11`), l'année est dérivée automatiquement
  pour la timeline.
- **Agrégats qualitatifs** : Langues, Types COAR (libellés humains
  résolus via les vocabulaires hardcoded — `fra` → « Français »),
  puis les 6 clés `Item.metadonnees` les plus fréquentes (auteur,
  sujet, dessinateur, etc. selon votre import). Top 5 par agrégat.
  Quand un agrégat n'a qu'une seule valeur distincte
  (`Langue : Espagnol (172)` sur Por Favor), rendu compact sur une
  ligne.
- **Vignettes** : 12 vignettes échantillonnées uniformément dans la
  collection (premier fichier de chaque item sélectionné).
  Placeholder par extension pour les fichiers non-image.
- **À finir** : trous catalographiques — `N sans titre`, `N sans
  année`, `N sans fichier`, `N à corriger`. Seul « à corriger » a un
  lien actif vers le tableau filtré ; les autres signalent sans
  prétendre filtrer (pas de filtre dédié sur ces critères pour le
  moment).
- **Activité récente** : 5 derniers items modifiés du périmètre.

### Sur une page fonds

Mêmes blocs portés sur **tous les items du fonds** (toutes
collections confondues), plus un bloc spécifique :

- **Identifiants revue** : Éditeur, Lieu, Périodicité, ISSN, Début,
  Fin, Responsable, Personnalité. Tous inline-éditables. Les champs
  vides sont à demi-transparents avec un placeholder « + ajouter »
  pour suggérer le geste d'édition.
- **Collections** (cartographie cross-collection) : un mini-tableau
  par collection avec barre proportion + nb items + nb partagés
  avec une autre libre + DOI Nakala cliquable. Toujours affiché
  (même quand seule la miroir existe), header adapté :
    - 1 collection : « Collections · uniquement la miroir »
    - multi-libres : « N items uniquement dans la miroir · M dans
      plusieurs libres » (chevauchements thématiques)

Les **collections transversales** (sans rattachement à un fonds)
qui contiennent des items du fonds courant ne sont **pas** listées
dans la cartographie — elles empruntent des items mais
n'appartiennent à aucun fonds.

### Filtrage anti-bruit des agrégats

Trois heuristiques évitent de saturer la synthèse avec des données
techniques :

- Clés Nakala calculées (`num_files`, `hash`, `sha256`, `data_url`,
  `iiif_url`, `categories`…) ne sont **jamais** agrégées
  (fingerprints sans valeur documentaire).
- Champs « identifiant » détectés : si la valeur la plus fréquente
  d'un champ apparaît au plus 1 fois ET qu'il y a ≥ 5 valeurs
  distinctes, le champ est écarté (cas typique : `ancienne_cote`
  avec une valeur unique par item).
- Codes langue ISO 639-1 (`fr`, `es`, `en`…) sont automatiquement
  convertis en libellés humains via un pivot ISO 639-3 (sans
  imposer de migration des données d'import).

Ces filtres s'appliquent uniquement à la synthèse — le cartouche
métadonnées item et la page Modifier continuent d'exposer tous les
champs (l'utilisateur peut éditer une valeur même filtrée).

## Édition inline

Au double-clic sur n'importe quelle valeur portant l'icône « modifier »
(cartouche item, bandeau collection/fonds, bloc Identifiants des
synthèses), un input remplace le texte. La saisie est envoyée par
POST sur un endpoint dédié (`/item/<cote>/champ/<field>`,
`/collection/<cote>/champ/<field>`, `/fonds/<cote>/champ/<field>`).
Le serveur valide, met à jour, retourne le fragment HTML qui remplace
la valeur précédente. La version (verrou optimiste) est incrémentée
automatiquement.

### Champs éditables inline

| Entité | Bandeau | Synthèse / Cartouche | Page Modifier seulement |
|---|---|---|---|
| **Item** | — | titre, type COAR, date, année, langue, numéro, description, notes internes, DOI Nakala, DOI collection Nakala, état, champs personnalisés non-multivaleurs | cote, fonds_id, champs personnalisés `liste_multiple` |
| **Collection** | titre, description, phase | DOI Nakala, DOI parent | cote, type_collection, fonds_id, version |
| **Fonds** | titre, description | Éditeur, Lieu, Périodicité, ISSN, Début, Fin, Responsable, Personnalité, description_publique, description_interne | cote, version |

### Champs à vocabulaire contrôlé

Pour les champs `langue`, `type_coar`, `etat_catalogage`, `phase` —
l'input devient un `<select>` strict avec les options du vocabulaire.
Si la valeur courante n'est pas dans la liste (legacy ou import
hétérogène), elle est ajoutée en queue pour ne pas être perdue
silencieusement.

### Champs personnalisés sur les items

Les champs personnalisés d'une collection (créés depuis
`/collection/<cote>/champs?fonds=<f>`) sont aussi éditables inline
depuis le cartouche item — sauf ceux de type `liste_multiple` qui
passent par la page Modifier (besoin de checkboxes multi-sélection).

Si un champ a un vocabulaire personnalisé attaché, le sélecteur
affiche les valeurs contrôlées de ce vocabulaire.

### Conflit de version

Si vous éditez un champ alors qu'un autre utilisateur (ou vous-même
dans un autre onglet) a déjà modifié l'entité depuis le chargement
de la page, le serveur répond `409 Conflict` avec un fragment
indiquant la situation. Rechargez la page pour reprendre la dernière
version.

### Mode lecture seule

En `lecture_seule: true` dans le `config_local.yaml`, le `meta` de
contexte n'est pas rendu, les hooks `data-edit-field` restent dormants
(le JS détecte l'absence du meta et ne fait rien au double-clic).
Les champs vides du bloc Identifiants synthèse fonds sont aussi
masqués pour ne pas montrer des placeholders inertes.
