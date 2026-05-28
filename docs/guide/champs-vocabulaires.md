# Champs personnalisés et vocabulaires

ColleC stocke pour chaque item un socle Dublin Core (titre, cote, date,
langue, type COAR, description…) **plus** un dictionnaire JSON libre
`metadonnees` qui héberge tout le reste. À l'import, les colonnes du
tableur qui ne sont pas mappées vers le socle DC sont déversées dans
cette zone libre. C'est rapide, sans perte, mais ces clés restent
**informelles** : pas de libellé propre, pas de type, pas de
vocabulaire contrôlé, pas d'ordre d'affichage.

Cette page documente comment **formaliser** ces clés libres en
*champs personnalisés* attachés à une collection, et comment les
adosser à un *vocabulaire* (liste de valeurs contrôlées) gérable
depuis l'interface.

Workflow complet : import → bouton « Formaliser » sur clé libre →
gestion des champs par collection → édition de valeur depuis le
formulaire item → affichage du libellé humain dans le cartouche.

## Pourquoi formaliser ?

L'import dump tout en JSON libre, ce qui marche pour démarrer. Mais
plusieurs frictions apparaissent rapidement :

- **Libellé synthétisé approximatif** : `ancienne_cote` s'affiche
  « Ancienne cote » via une heuristique de capitalisation, mais
  `mots_cles` devient « Mots cles » (accent perdu).
- **Pas d'ordre d'affichage** : les clés libres sont triées
  alphabétiquement, sans contrôle.
- **Pas de validation** : l'utilisateur peut taper n'importe quoi,
  pas de liste fermée pour les vocabulaires métier (genres, tags,
  personnages, etc.).
- **Pas de wire avec les exports** : un champ formel est intégrable
  aux mappings Dublin Core ; une clé libre reste invisible aux
  exporters (sortie en CSV mais pas en `<dc:*>`).

La formalisation résout ces points sans perdre les données
existantes.

## Étape 1 — Formaliser une clé libre

Sur la **page item**, dans le cartouche, section « Champs
personnalisés », chaque clé libre dont le slug est valide
(`^[a-z][a-z0-9_]*$`) porte un mini bouton **« Formaliser »**
(petit, bleu pâle, à droite de la valeur). Il n'apparaît qu'en
mode édition — masqué en lecture seule.

Un clic crée un `ChampPersonnalise` sur la **miroir du fonds** de
l'item, avec :

- la même `cle` que la clé libre originale (la valeur stockée dans
  `Item.metadonnees` ne bouge pas)
- un `libelle` synthétisé via `_libelle_depuis_cle`
  (`ancienne_cote` → `Ancienne cote`)
- `type = "texte"` par défaut
- `ordre = 0`

L'opération est **idempotente** : un re-clic ne casse rien. Si un
champ déprécié existe déjà avec cette clé, il est retourné sans
réactivation (l'utilisateur conserve le contrôle).

Les clés à slug invalide (`Mots-Clés`, `Unnamed: 15`, etc.) **ne
peuvent pas être promues directement** — le bouton est masqué côté
cartouche pour ces cas. Il faut d'abord nettoyer la clé en amont
(édition métadonnées) avant de réessayer.

## Étape 2 — Gérer les champs personnalisés

Depuis la page Collection (lecture), bouton **« Champs
personnalisés »** dans le bandeau. Ou depuis la page item, lien
**« Gérer »** sur le header de la section « Champs personnalisés »
du cartouche.

URL : `/collection/<cote>/champs?fonds=<cote_fonds>`.

La page propose trois actions par champ :

- **Modifier** : libellé, type, ordre, aide, description interne,
  vocabulaire associé. La `cle` reste figée (le rename est une
  opération distincte avec propagation).
- **Déprécier** / **Réactiver** : toggle `actif`. Un champ
  déprécié n'apparaît plus dans la section formelle du cartouche,
  mais les valeurs dans `Item.metadonnees` sont préservées et
  retombent dans le fallback « clé libre » du composer
  (aucune perte affichable).
- **Renommer la clé** (depuis la page modifier) : change le `cle`
  ET propage la valeur dans `Item.metadonnees` de tous les items
  de la collection. Bump de `version` sur chaque item touché —
  les éditeurs inline concurrents recevront un conflit propre.

## Étape 3 — Vocabulaires personnalisés

Pour des champs à valeurs fermées (genres, typologies internes,
tags personnages…), créer un vocabulaire depuis **/vocabulaires**
(lien discret en haut à droite du dashboard).

Workflow :

1. Créer le vocabulaire (`code`, `libelle`, description publique
   optionnelle, description interne, URI base optionnelle pour
   exports DC).
2. Ajouter ses valeurs contrôlées (`code` + `libelle` + URI
   canonique optionnelle, ordre, description interne).
3. Sur la page de modification d'un `ChampPersonnalise`,
   sélectionner ce vocabulaire dans le dropdown « Vocabulaire
   associé ».

!!! note "Distinct des vocabs système"

    Les vocabulaires LANGUES (ISO 639-3), TYPES COAR et ÉTATS de
    catalogage sont **hardcoded** dans `services/vocabulaires.py`
    et ne sont pas affichés sur /vocabulaires. Ce sont des
    fondamentaux du domaine, partagés entre tous les fonds, jamais
    modifiables depuis l'UI.

Une fois le vocabulaire attaché :

- Le **formulaire item modifier** rend automatiquement un
  `<select>` (type `liste`) ou une grille de **checkboxes** (type
  `liste_multiple`) au lieu d'un input libre.
- Le **cartouche** affiche le libellé humain (« Bande dessinée »)
  au lieu du code brut (« bd »).
- Les valeurs hors vocab (legacy ou dépréciées) ne sont **pas
  perdues** — elles s'affichent en valeur brute dans le cartouche
  et apparaissent en queue du `<select>` du modifier avec suffixe
  « (hors-liste) ».

Suppression d'un vocabulaire : refusée tant qu'un
`ChampPersonnalise` y fait référence. Le message d'erreur liste
les champs en cause pour faciliter le détachage.

### Restreindre un vocabulaire à certains fonds (portée)

Par défaut, un vocabulaire est **global** : ses valeurs sont
proposées dans l'autocomplete d'annotations de tous les fonds.
Utile pour les vocabs transverses (langues, types iconographiques
courants). Mais sur un vocab spécifique à un corpus (ex.
« Dessinateurs Hara-Kiri »), proposer les noms sur un fonds
Por Favor pollue les suggestions.

La page détail d'un vocabulaire (`/vocabulaires/<id>`) propose
une section **« Fonds rattachés »** avec une carte par fonds de
la base. Clic sur une carte blanche « + » → le vocabulaire est
restreint à ce fonds (carte devient bleue « ✓ »). Re-clic → on
détache (retour blanc). Un vocab rattaché à plusieurs fonds est
visible dans tous ; un vocab sans aucun rattachement reste global.

La page liste (`/vocabulaires`) affiche un badge dans la colonne
**« Portée »** : « global » (gris, aucun rattachement) ou
« N fonds » (bleu, avec tooltip listant les cotes). Repère
visuel pour identifier les vocabs qui « polluent » partout.

**Effets immédiats** : l'autocomplete Annotorious du viewer
catalogage récupère le filtrage à chaque ouverture de fichier.
Les annotations déjà saisies en libre dans un fonds ne sont **pas**
réécrites quand on rattache le vocab après coup — pour les
enrichir (associer leur URI Wikidata par exemple), il faudra un
service d'enrichissement rétroactif (T4 non encore livré). Pour
l'instant, taper un libellé matchant une valeur du vocab **au
moment de l'annotation** crée le pivot URI directement.

## Étape 4 — Éditer les valeurs sur un item

Page `/item/<cote>/modifier?fonds=<f>` : section **« Champs
personnalisés »** entre « Catalogage » et « Identifiants externes ».

Rendu automatique selon le `TypeChamp` :

| Type | Rendu |
| --- | --- |
| `texte` | `<input type="text">` |
| `texte_long` | `<textarea>` 5 lignes |
| `nombre` | `<input type="number">` |
| `date_edtf` | `<input type="text">` (EDTF accepte « vers 1960 », pas de `type=date`) |
| `liste` + vocab | `<select>` avec libellés humains + fallback hors-liste |
| `liste_multiple` + vocab | grille de checkboxes |
| `reference` | `<input type="text">` (URI / DOI / lien) |

Sémantique de la saisie :

- **Valeur non vide** → stockée dans `Item.metadonnees[cle]`
- **Valeur vide / 0 checkbox cochée** → clé **supprimée** de
  `metadonnees` (cohérent avec le rendu « non renseigné » et la
  sémantique d'import)

Si le champ est marqué `obligatoire` (case « Obligatoire » à la
création), l'attribut HTML5 `required` est posé sur l'input / select.
Le navigateur bloque le submit si vide — défense en profondeur,
pas de validation côté service (un catalogue WIP peut avoir des
champs obligatoires non remplis pendant le travail).

## Cas particulier : item dans plusieurs collections

Un item peut appartenir à plusieurs collections (la miroir +
collections libres et/ou transversales). Le composer cartouche
**mutualise** tous les `ChampPersonnalise` des collections
d'appartenance, en déduplique par `cle` (les formels les plus
prioritaires gardés en tête, puis le fallback clé libre).

Conséquence : `ChampPersonnalise` (genre, vocab Genres) attaché à
la miroir HK, et l'item HK-001 figure aussi dans une transversale
« Témoignages » → le champ Genre est visible / éditable sur
HK-001 même via la lecture de la transversale.

Le bouton « Formaliser » crée toujours sur la **miroir** du fonds
de l'item (jamais sur une transversale). C'est le choix naturel :
la miroir est la source de vérité structurelle du fonds.

## Bonnes pratiques

- **Formaliser au fil de l'eau** : ne pas chercher à tout
  formaliser dès l'import. Promouvoir une clé quand le besoin
  apparaît (filtre de recherche, libellé moche, vocab fermé).
- **Description interne** : remplir systématiquement pour les
  champs perso et les vocabulaires créés à plusieurs. Documente
  *pourquoi* le champ existe et *comment* le remplir. Visible
  uniquement côté équipe.
- **Vocabulaires partagés** : un même vocabulaire peut être référé
  par plusieurs `ChampPersonnalise` de fonds différents (par
  exemple un vocab « Pays » réutilisé par tous les fonds). Pas
  besoin de dupliquer.
- **Déprécier vs supprimer** : préférer déprécier dans la
  majorité des cas. La suppression définitive est réservée aux
  faux départs (champ créé par erreur, sans valeur attachée nulle
  part).

## Référence des routes

| Route | Méthode | Effet |
| --- | --- | --- |
| `/collection/<c>/champs?fonds=<f>` | GET | Liste + form création |
| `/collection/<c>/champs/creer` | POST | Crée un champ |
| `/collection/<c>/champs/<id>/modifier` | GET | Form modif |
| `/collection/<c>/champs/<id>/modifier` | POST | Sauve modif |
| `/collection/<c>/champs/<id>/renommer` | POST | Renomme + propage |
| `/collection/<c>/champs/<id>/deprecier` | POST | Toggle déprécié |
| `/collection/<c>/champs/<id>/reactiver` | POST | Toggle actif |
| `/collection/<c>/champs/<id>/supprimer` | POST | Hard delete |
| `/item/<c>/promouvoir-cle?fonds=<f>` | POST | Bouton « Formaliser » |
| `/vocabulaires` | GET | Liste + form création |
| `/vocabulaires/<id>` | GET | Détail + valeurs |
| `/vocabulaires/<id>/modifier` | POST | Sauve métadonnées |
| `/vocabulaires/<id>/valeurs/ajouter` | POST | Ajoute valeur |
| `/vocabulaires/<id>/valeurs/<v>/...` | POST | modifier / déprécier / réactiver / supprimer |
| `/vocabulaires/<id>/supprimer` | POST | Hard delete (refuse si référencé) |
