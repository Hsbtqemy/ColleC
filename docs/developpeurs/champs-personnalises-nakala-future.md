# Champs personnalisés ↔ propriétés Nakala (note de design — v1)

> **Statut : en discussion, itératif.** Cette note trace une décision
> structurante en cours de cadrage (cf. CLAUDE.md « proposer les décisions
> structurantes avant de coder »). Le modèle est validé dans ses grandes
> lignes mais **la formule exacte se précisera sur plusieurs passes** — ne
> pas la considérer comme figée. Ordre de chantier **non encore décidé**.

## Besoin

Pouvoir enrichir un item avec des **champs personnalisés** qui ne sont pas
de simples notes ColleC-internes, mais qui peuvent **se projeter vers des
propriétés Nakala / Dublin Core** :

1. **Remap ColleC → Nakala** : créer des champs métier (`dessinateur`,
   `directeur de collection`, `rubrique`…) et les **adosser à une propriété
   Nakala** (ex. `dcterms:contributor`) pour qu'ils partent au dépôt / push.
2. **Enrichir après coup** : ajouter une propriété Nakala **absente au moment
   du dépôt** (l'info n'existait pas alors) puis repousser.

## État actuel (vérifié dans le code + sondes live)

- Le push n'émet que les slugs de `SLUG_TO_NAKALA` (~57 connus,
  `external/nakala/depot_mapper.py`). **Tout slug inconnu est sauté**
  (`depot_mapper.py` : `if slug not in SLUG_TO_NAKALA: continue`). Un champ
  personnalisé inventé reste donc **ColleC-only**.
- `ChampPersonnalise` (`models/profil.py`) n'a **aucun `propertyUri`** —
  seules les *valeurs* contrôlées (`ValeurControlee.uri`) ont une URI (pivot
  Wikidata/VIAF des annotations), pas le *champ*.
- Par fichier : `Fichier.description_externe` est le **seul** champ par-fichier
  qui round-trip déjà vers Nakala (la `description` de fichier, S7).
- Un champ défini sur la **miroir** apparaît déjà sur **tous** les items, même
  **sans valeur** (« non renseigné » sur la notice + input vide au formulaire) :
  le « scaffold de collecte » existe (cf. § Granularité).

## Modèle cible

Étendre `ChampPersonnalise` avec un **pont Nakala optionnel** :

```text
ChampPersonnalise =
  (cle, libellé, type, vocabulaire, obligatoire)          # existant
  + (propertyUri Nakala ?, mode_emission ?, gabarit ?)    # à ajouter
```

- **Sans `propertyUri`** → champ **ColleC-only** : saisie, filtres, colonnes,
  exports internes — **ne push pas** Nakala.
- **Avec `propertyUri`** → champ **candidat au push / round-trip**.

### Émission : multi-valeur d'abord, concaténation rare

Recadrage (discussion 2026-06-24) : le besoin est **majoritairement du
multi-valeur**, pas de la concaténation. Le modèle Nakala est nativement une
**liste de metas** `{propertyUri, value, lang, typeUri}` :

- **Valeurs multiples (défaut)** : plusieurs champs / plusieurs valeurs
  adossés au même `propertyUri` → **N entrées** Nakala. Fidèle pour
  `dcterms:creator` / `contributor` / `subject` (chaque personne = une entrée).
- **Concaténation (optionnelle, à confirmer)** : composer plusieurs champs en
  **une seule** valeur (gabarit + séparateur). Pertinent surtout pour un
  texte libre (`dcterms:description`). **Peut-être hors v1** — à trancher.

**Préfixe de rôle (validé live, 2026-06-24).** Quand plusieurs champs métier
distincts (`dessinateur`, `directeur de collection`) sont adossés à une même
propriété générique (`dcterms:contributor`), on peut **préfixer chaque valeur
par le libellé du champ** : « Dessinateur : Topor », « Directeur de collection :
Reiser ». Sonde C2 : Nakala accepte les 2 valeurs et **restitue les préfixes
verbatim**. Décision de conception : le préfixe est un **transform appliqué au
push** (mode de mapping « préfixer par le libellé »), **pas stocké préfixé** —
ColleC garde la valeur structurée en interne (`dessinateur=Topor`, filtrable),
et compose la chaîne préfixée seulement à l'émission. Réversibilité au re-pull
(re-parser le préfixe vers le champ) = **question ouverte**.

### Cardinalité Nakala — sondée (2026-06-24)

Sonde dédiée `scripts/explorer_cardinalite_nakala.py` (apitest, dépôts
`pending` supprimés en fin) + `metadatas` granulaire (2026-06-19, cf.
[`nakala-savoir-api.md`](nakala-savoir-api.md)) :

- **C1 — set fermé** : `GET /vocabularies/properties` renvoie **60 URIs**, et
  **aucune métadonnée de cardinalité** (juste la liste). Nakala ne *déclare*
  donc pas répétable/scalaire ; toute autre propriété est rejetée au push.
- **C2 — multi-valeur + préfixe** : 2 valeurs `dcterms:contributor` acceptées
  (201) et **relues identiques, préfixes de rôle préservés verbatim**. Le
  multi-valeur fonctionne ; les valeurs sont des chaînes libres.
- **C3 — scalaire** : POSTer une 2ᵉ valeur sur `nkl:title` → **doublon créé**
  (201, pas de refus). **L'API n'impose PAS la cardinalité scalaire.**

**Conséquences** : le multi-mapping est sûr et fidèle sur les propriétés
répétables (`dcterms:*`) ; sur les scalaires cœur (`nkl:title`/`type` ; présumés
`created`/`license`) il créerait un doublon silencieux → **garde-fou UI
obligatoire** (interdire/avertir le multi-mapping de ces propriétés). Comme
Nakala ne donne pas la cardinalité, ColleC porte sa **propre petite table**
(scalaires connus) + défaut « répétable » pour le reste.

## Granularité

| Portée | Outil | État |
| --- | --- | --- |
| **Item (valeur qui varie)** | `ChampPersonnalise` valué par item (autonomie #8) | existe |
| **Scaffold fonds-wide** (champ vide proposé partout) | champ défini sur la **miroir** | existe (UX à polir) |
| **Même valeur pour tout l'ensemble** | **propagation** (écrire sur chaque item, garde l'auto-suffisance des notices) *ou* valeur portée par l'entité (hors autonomie) | partiel (`valeurs_par_defaut` à l'import ; pas de bulk-fill UI) |
| **Par fichier** | `Fichier.description_externe` (→ Nakala) ; sinon clés libres | partiel |

« Fonds » distinct de « miroir » : **non nécessaire** (la miroir *est* le
niveau fonds-wide ; décision de l'utilisateur, 2026-06-24).

## Deux régimes d'usage (cadrant le push)

- **Dépôts dont on est propriétaire** → enrichir une propriété absente →
  **repush**. Le `propertyUri` sert. Utile : surfacer « quelles propriétés
  Nakala sont vides » sur l'item.
- **Items ouverts qui ne sont pas à nous** (collections curées depuis des
  données Nakala publiques variées) → enrichir **dans ColleC pour son propre
  travail**, **sans push** (pas les droits). Le champ reste ColleC-only par
  nécessité.

→ Le `propertyUri` est un **indice d'export optionnel** qui ne se déclenche
qu'au push d'un dépôt possédé. Il **ne bloque jamais** l'enrichissement local.

## Le manque réel : l'UX (pas le modèle)

Le point 2 (scaffold) est surtout un manque d'**ergonomie** :

- **Créer un champ inline depuis l'item** (notice ou visionneuse) sans détour
  par `/collection/<cote>/champs`, en posant par défaut au niveau miroir.
- **Vue « complétude »** : montrer les slots attendus encore vides (la
  checklist de collecte du fonds).
- Au moment de créer/mapper : choisir le `propertyUri` dans le set fermé
  Nakala + le mode d'émission, avec garde-fou cardinalité.
- **Affichage des metas Nakala au retour (groupé)** : quand une propriété a
  plusieurs valeurs, **grouper sous un seul libellé**, une valeur par ligne —
  ne PAS répéter `dcterms:contributor` à chaque ligne. Ex :

  ```text
  Contributeur
    · Dessinateur : Topor
    · Directeur de collection : Reiser
  ```

  (vs la forme brute qui répète la propriété). Concerne l'aperçu
  rapatriement/comparaison Nakala.

## Décisions actées (discussion 2026-06-24)

- **Socle = registre partagé contrôlé** (Option B) : table associant un slug
  à une `propertyUri` + un mode (+ gabarit), éditable en base mais
  **vocabulaire contrôlé** (pas de champ libre), `propertyUri` ∈ les 60,
  garde-fou cardinalité, **droits
  d'édition restreints** (qui mappe ≠ qui catalogue, V1.0). Philosophie : ColleC
  plus strict que Nakala pour la qualité du push. Override par-champ (Option C)
  reporté, ajoutable si un cas réel l'exige.
- **Préfixe de rôle = oui, appliqué au push** (transform de mapping), pas stocké
  préfixé ; valeurs multiples plutôt que concaténation.
- **Projection à sens unique** : champs structurés ColleC = source de vérité ;
  le re-pull d'un dépôt possédé **ne réécrit pas** les champs structurés. Le
  diff de rafraîchissement **re-projette** ColleC → metas attendues et compare
  (pattern de canonicalisation de `diff_push`) → pas de faux conflit. Préfixe =
  pour l'œil humain, jamais re-parsé.
- **Autorités (valeur → URI) = ColleC-side** (réutilise `ValeurControlee.uri`),
  orthogonales au push (modèle Nakala plat ; exception `nkl:creator`/orcid).
- **Complétude « à enrichir sur Nakala »** = vue scaffold **filtrée** (champs
  mappés vides) **+ dépôts possédés** (appartenance via le scope de la clé).
- **Deux gates d'imposition** : (i) à l'enregistrement (`obligatoire`, existant) ;
  (ii) **au push** (preflight, porté par le registre) = le levier qualité.
- **Granularité de valeur** : per-item (autonomie) + **propagation** pour
  « même valeur partout » ; vraie valeur unique de l'ensemble = metas de la
  **collection** Nakala (chantier distinct, plus tard).
- **Affichage retour Nakala groupé** par propriété (cf. § UX).

## Questions ouvertes (à itérer)

- [ ] **Bulk-fill / propagation** d'une valeur sur N items → traité comme
      membre d'un socle d'opérations par lot :
      [`operations-par-lot-future.md`](operations-par-lot-future.md).
      (Rappel : la propagation de l'*entrée* = le scaffold, déjà en place ;
      seule la propagation de *valeur* reste à faire.)
- [ ] **Qui a le droit de mapper** (registre) — lié à l'auth V1.0.
- [ ] Metas au niveau **collection Nakala** (valeur unique de l'ensemble).
- [ ] **Ordre de chantier** — à décider (le registre `slug→propertyUri` + le
      gate push semblent le cœur ; scaffold/inline = polish UX).
- [x] ~~Cardinalité des propriétés Nakala~~ — **sondée** (2026-06-24).
- [x] ~~Réversibilité du préfixe~~ — **tranchée** : projection one-way, pas de
      re-parsing (cf. Décisions).
- [x] ~~`propertyUri` champ vs valeur~~ — **tranchée** : propertyUri au champ
      (registre) ; autorités au niveau valeur, ColleC-side.

## Références code

- `src/archives_tool/models/profil.py` — `ChampPersonnalise`.
- `src/archives_tool/external/nakala/depot_mapper.py` — `SLUG_TO_NAKALA`.
- `src/archives_tool/api/services/champs_personnalises.py` —
  `lister_champs_actifs_pour_item` (inclut les champs vides).
- `src/archives_tool/web/templates/components/cartouche_metadonnees.html` —
  rendu + « Formaliser » + « Gérer ».
- `scripts/explorer_cardinalite_nakala.py` — sonde cardinalité/multi-valeur
  (apitest, auto-nettoyante).
- [`nakala-savoir-api.md`](nakala-savoir-api.md) — comportement metas live.
