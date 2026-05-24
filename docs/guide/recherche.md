# Recherche

ColleC indexe en permanence le titre, la description, les notes
internes, les cotes et les métadonnées libres de toutes les
entités (items, fonds, collections) via SQLite FTS5. La recherche
est disponible depuis n'importe quelle page via la **barre de
recherche globale** dans le bandeau du haut.

## Lancer une recherche

Trois entrées possibles :

- **Cliquer dans la barre** du bandeau supérieur.
- **Raccourci clavier `/`** : pose le focus dans la barre et
  sélectionne le contenu courant (équivalent du `Ctrl-F` de
  beaucoup d'applications).
- **Raccourci clavier `Cmd+K`** (macOS) ou `Ctrl+K` (Windows/Linux) :
  même effet.

La validation par `Entrée` ouvre la page de résultats `/recherche`
sur une URL bookmarkable :
`/recherche?q=mon-terme&fonds_id=12&etat=brouillon`.

## Syntaxe de la requête

La recherche utilise SQLite FTS5 avec quelques aménagements
ergonomiques pour les usages d'archives :

- **Insensible aux accents** : `numero` matche `Numéro`, `caratere`
  matche `caractère`. Indispensable sur des corpus multilingues.
- **Préfixe automatique** : chaque mot reçoit un `*` final pour
  matcher les préfixes — taper `PF-0` retourne `PF-001`, `PF-002`,
  `PF-014`, etc. Particulièrement utile pour les cotes partielles.
- **AND implicite** : plusieurs mots séparés par des espaces sont
  combinés en AND. `Por Favor Eduardo` retourne les entités qui
  contiennent les trois mots (dans n'importe quel ordre).
- **Caractères réservés ignorés** : `":-()*+` sont silencieusement
  retirés. Une recherche `"hara-kiri"` est tokenisée en
  `hara` AND `kiri` — pas de plantage.

Pas de syntaxe avancée (NOT, OR, parenthèses) côté utilisateur :
les opérateurs FTS5 sont neutralisés pour éviter les surprises et
les erreurs de syntaxe.

## Périmètre

Par défaut, la recherche balaie **tout l'outil** : tous les fonds,
toutes les collections, tous les items. Deux périmètres restreints
sont possibles :

- **Dans un fonds** — depuis la page d'un fonds, le contexte
  `?fonds_id=...` est passé automatiquement. Les fonds non
  correspondants et leurs items sont écartés.
- **Dans une collection** — depuis la page d'une collection (libre
  ou transversale), `?collection_id=...` est passé. Les items qui
  ne sont pas membres de la collection sont écartés ; le fonds
  parent n'est pas remonté.

Un bandeau au-dessus du formulaire signale le périmètre actif :
`Limité au fonds HK (lever)`. Cliquer sur `(lever)` élargit la
recherche à tout l'outil **en conservant les filtres avancés en
cours** — utile pour passer d'une recherche locale à une recherche
globale sans avoir à re-saisir l'état ou la langue cherchés.

## Type d'entité

Trois cases à cocher exposent le filtre par type :

- **Items** (✓ par défaut)
- **Fonds** (✓ par défaut)
- **Collections** (✓ par défaut)

Décocher restreint l'affichage. Par exemple, `?types=item` ne
retourne que les items, même si la query matcherait des fonds ou
des collections par titre.

## Filtres avancés

Section repliable `<details>` sous le formulaire. **Ouverte
d'office** si au moins un filtre est actif (pour ne pas oublier ce
qui est posé). Le compteur `· 3 actifs` apparaît dans le titre du
panneau.

### Raffinement de la requête (`q2`)

Champ libre `Rechercher dans les résultats`. Concaténé à la requête
principale via un AND FTS5 implicite — équivalent à taper les deux
termes dans la barre principale, mais préservé visuellement et
techniquement séparé. S'applique aux **3 types d'entités** (items,
fonds, collections).

Usage typique : `q=Por Favor` (173 items) puis `q2=Eduardo` pour
ne garder que ceux qui mentionnent aussi Eduardo.

### État de catalogage

Multi-sélection sur les états réellement présents dans le
périmètre (brouillon, à vérifier, vérifié, validé, à corriger).
Un état absent du périmètre n'apparaît pas dans la liste — pas de
case à cocher fantôme. **Items uniquement** : ce filtre ne
restreint pas les fonds ou collections, qui passent à travers.

### Langue

Multi-sélection sur les langues (ISO 639-3) présentes dans le
périmètre. **Items uniquement**.

### Type COAR

Multi-sélection sur les types documentaires (URIs COAR) présents
dans le périmètre. Le label est tronqué visuellement sur le
suffixe (`c_3e5a` pour Périodique) ; l'URI complète apparaît au
survol via l'attribut `title`. **Items uniquement**.

### Période

Deux champs `min` / `max` (années entières). Les bornes
proposées en placeholder reflètent la plage réelle des items du
périmètre. Si vous saisissez une plage inversée (`min` > `max`),
elle est silencieusement swappée pour donner un résultat
exploitable plutôt qu'une page vide. **Items uniquement**.

### Périmètre des filtres

Tous les filtres item-specific (état, langue, type, période)
n'affectent que **les items**. Les fonds et les collections
continuent d'apparaître en haut des résultats normalement —
c'est un choix d'UX : on suppose que filtrer « valider » ne doit
pas masquer le fonds dont vous cherchez le titre.

Une note discrète au bas du panneau le rappelle dès qu'un filtre
item-specific est actif :
*« État, langue, type et période ne filtrent que les items
(fonds et collections continuent d'apparaître). »*

## Lire les résultats

Chaque résultat affiche :

- **Un badge type** coloré (Item bleu, Fonds rouge, Collection
  vert) pour le repérage rapide.
- **La cote** en monospace, cliquable, qui mène à la page de
  l'entité.
- **Le titre** à côté.
- **Pour les items**, la cote du fonds parent à droite (`dans HK`).
- **Un snippet** : court extrait textuel avec les termes
  recherchés surlignés en `<mark>` (jaune). Le snippet protège du
  XSS : un item dont la description contient `<script>` est
  affiché tel quel, pas exécuté.

Les résultats sont triés par **pertinence BM25** (score natif
FTS5). Plus le terme est rare ou dans un champ court (titre), plus
le score est bon.

## Pastilles de filtres actifs

Dès qu'un filtre est posé, une **pastille `×`** apparaît au-dessus
de la liste des résultats. Cliquer dessus retire ce filtre précis
en préservant tous les autres. Exemple :

> `dans : Eduardo ×`   `État : Brouillon ×`   `Période : 1965–1980 ×`

À partir de **2 filtres actifs**, un lien **« Tout réinitialiser »**
apparaît à droite des pastilles. Il préserve la requête `q`, le
scope et les types, mais retire tous les filtres avancés en un
clic.

## Compteur et pagination

Le compteur principal au-dessus de la liste indique le **total
exact** de matches FTS5 (compte séparé sans LIMIT) :

> **173** résultats trouvés pour **« Por Favor »** dans le fonds
> `PF` *(51–100 sur cette page)*.

Les résultats sont **paginés par 50** par défaut (`?par_page=N`,
borne 10..200). Une **pagination cliquable** apparaît en bas de
la page dès qu'il y a plus d'une page :

> 51–100 sur 173   ‹ 1 2 [3] 4 ›

Les liens de pagination **préservent** la query, le scope, les
types et tous les filtres avancés en cours. À l'inverse, **modifier
un filtre** (cliquer une pastille `×`, taper une nouvelle query,
ouvrir une nouvelle valeur de filtre) **retourne automatiquement
à la page 1** — sinon vous risqueriez d'arriver sur une page 3
vide après avoir réduit drastiquement le nombre de résultats.

**Cap dur** : 5000 résultats par type sont effectivement triables.
Au-delà, un message discret invite à affiner avec les filtres
avancés. Ce cap n'est pratiquement jamais atteint en usage
courant — il existe juste pour éviter de matérialiser plusieurs
dizaines de milliers d'objets en mémoire.

## Ce qui est indexé

| Entité       | Champs indexés                                                  |
| ------------ | --------------------------------------------------------------- |
| Item         | cote, titre, description, notes internes, métadonnées (JSON)    |
| Fonds        | cote, titre, description, description publique, interne         |
| Collection   | cote, titre, description, description publique                  |

Les **métadonnées libres** d'un item (clé/valeur arbitraires
issues d'un import tableur) sont **applaties à plat** dans l'index
— une valeur libre `auteur=Topor` est trouvable par `topor`.

L'index est maintenu en temps réel par des triggers SQL
(insert/update/delete sur les tables source). Pas besoin de
réindexer manuellement.

## Ce qui n'est PAS indexé (limites)

- **OCR des documents** : pas encore. Roadmap V3 — ajoutera soit
  une table `fichier_fts` dédiée, soit une colonne `ocr_text` sur
  l'index item.
- **Live-search dropdown** : la barre globale soumet en GET vers
  `/recherche` (page complète), il n'y a pas de dropdown
  interactif au fil de la frappe. Acceptable pour un usage
  archivistique où la requête se réfléchit avant d'être lancée.
- **Surlignage dans la page de l'entité cliquée** : si vous
  cliquez sur un résultat, vous arrivez sur la page de l'item sans
  les termes recherchés mis en évidence. À itérer V2 via `?q=`
  propagé.

## Réindexer manuellement

Cas rare : si une migration ColleC ajoute de nouveaux champs
indexés, ou si la base est restaurée depuis une sauvegarde sans
les tables FTS, il faut réindexer. Depuis Python :

```python
from archives_tool.db import creer_engine, reindexer_fts
from pathlib import Path

engine = creer_engine(Path("data/archives.db"))
counts = reindexer_fts(engine)
print(counts)
# {'item': 173, 'fonds': 1, 'collection': 1}
engine.dispose()
```

L'opération est **idempotente** : vous pouvez l'appeler plusieurs
fois sans dupliquer les entrées. Coût ≈ 1 seconde pour ~10 000
items.
