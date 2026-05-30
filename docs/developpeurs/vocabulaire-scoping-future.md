# Décisions d'architecture — scoping vocabulaires ↔ fonds

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur la mise à
    l'échelle des vocabulaires utilisés par les annotations IIIF
    et les champs personnalisés.

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Constat

Depuis V0.9.7 γ, l'autocomplete du widget TAG d'Annotorious est
alimenté par `/api/vocabulaires/autocomplete` qui retourne **toutes
les `ValeurControlee` actives, tous vocabulaires confondus**. Tant
que l'outil reste sur 1-2 fonds avec 1-2 vocabs de qq dizaines
d'entrées, c'est tenable. Dès qu'on monte en charge (vocab
« Dessinateurs PF » + « Photographes HK » + « Personnalités
politiques années 70 » + « Onomatopées BD »…), la pertinence se
dégrade : annoter une page PF avec des suggestions Hara-Kiri = bruit.

## Décision retenue

**Rattachement explicite vocabulaire ↔ fonds**, many-to-many,
**défaut global**. Un vocab sans rattachement est visible partout
(cas légitimes : langues, types COAR, motifs iconographiques
transverses). Un vocab rattaché à 1 fonds n'apparaît que dans
l'autocomplete de ce fonds.

Pour le scénario « vocab rattaché à A, puis élargi à B déjà
annoté en libre » : les annotations existantes dans B restent en
`TextualBody value="Copi"` sans URI — la base ne fait pas de
jointure live. **On fige** via un service d'enrichissement
rétroactif idempotent (et non pas via résolution à la volée à la
lecture — plus simple à exporter, données stables, audit clair).

## État

- **T1 + T2 + T3 livrés** (mai 2026) : table de liaison, services
  attacher/détacher, autocomplete filtré par `?fichier_id=<id>`,
  wiring JS, UI rattachement (cases à cocher sur la page détail +
  badges « global » / « N fonds » sur la liste). Le filtrage est
  en place de bout en bout et utilisable directement depuis
  l'interface web.
- **T4 livré** (mai 2026) : enrichissement rétroactif des
  annotations existantes (TextualBody libre → SpecificResource avec
  URI canonique). Service backend idempotent, CLI
  `archives-tool annotations enrichir`, page web preview/confirmer
  accessible depuis chaque fonds rattaché de la page vocab. Le
  scoping vocabulaires ↔ fonds est désormais complet bout-en-bout.

## Tickets

### Ticket 1 — Modèle + migration  ✅ livré

**Cible** : table `vocabulaire_fonds(vocabulaire_id, fonds_id)`,
PK composite, FK CASCADE des deux côtés.

- Migration Alembic dédiée, ~20 lignes.
- Relation many-to-many sur `Vocabulaire.fonds_rattaches`
  (et symétrique `Fonds.vocabulaires_rattaches`).
- Tests : création / suppression d'un lien, cascade quand le
  vocab ou le fonds disparaît, idempotence (re-link sans
  doublon → contrainte UNIQUE sur la PK composite).

Petit, autonome. Pré-requis aux tickets suivants.

### Ticket 2 — Autocomplete filtré  ✅ livré

**Cible** : `/api/vocabulaires/autocomplete?fichier_id=<id>`
résout `fichier → item → fonds` et filtre les `ValeurControlee`
selon la convention « LEFT JOIN vocabulaire_fonds + WHERE
vf.fonds_id IS NULL OR vf.fonds_id = :fonds_courant ».

- Côté JS (`annotations_osd.js`) : passer `fichier_id` dans le
  fetch initial. Le `_vocabReady` Promise reste, juste l'URL
  enrichie.
- Sans `fichier_id` (cas d'usage hors annotation, ex. édition
  d'un champ personnalisé sur la fiche item) : retomber sur le
  comportement actuel (tout retourner) ou prendre un autre
  paramètre `?fonds_id=<id>` selon le contexte d'appel.
- Tests : POST annotation sur fonds A avec vocab rattaché → tag
  proposé ; POST sur fonds B sans rattachement → tag absent ;
  vocab global (sans rattachement) → visible partout.

C'est la pièce qui livre le **gain UX principal** — à coupler
avec T1 dans un même lot.

### Ticket 3 — UI rattachement  ✅ livré

**Cible** : `/vocabulaires/<id>` gagne une section « Fonds » avec
cases à cocher pour chaque fonds existant. Page liste des vocabs
(`/vocabulaires`) gagne un badge par ligne : « global » (zéro
rattachement), « 3 fonds » (rattaché à 3), etc. Signale
visuellement les vocabs qui polluent partout.

- Service `attacher_vocabulaire_au_fonds(db, vocab_id, fonds_id)`
  + symétrique `detacher_vocabulaire_du_fonds`. Idempotents.
- Routes POST `/vocabulaires/<id>/fonds/<cote>/attacher` et
  `/detacher` (HTMX, partial swap de la section).
- Page modifier vocab : checkboxes triées par cote de fonds.
- Tests : attacher → présent en base, détacher → absent ; UI
  reflète l'état ; lecture seule bloque les POST (423).

Suit naturellement T1+T2. Sans T3, l'admin se fait via CLI ou
SQL — viable pour les premiers tests mais inconfortable.

### Ticket 4 — Enrichissement rétroactif  ✅ livré

**Cible** : opération idempotente qui, pour un `(vocabulaire, fonds)`
donné, parcourt les annotations du fonds, matche les
`TextualBody.value` (normalisation NFD + lowercase) contre les
`ValeurControlee.libelle` du vocab, et **remplace** chaque match
par un `SpecificResource source={id, label}` avec URI Wikidata.

- Service
  `enrichir_annotations_par_vocab(db, vocab_id, fonds_id, *, dry_run=True, modifie_par=None)`
  dans `api/services/annotations.py`. Retourne `RapportEnrichissement`
  (`matches: tuple[MatchEnrichissement, ...]`, `deja_enrichies: int`,
  `annotations_modifiees: int`, `dry_run: bool`). Chaque `Match`
  contient `annotation_id`, `fichier_id`, `body_index`,
  `libelle_libre`, `valeur_id`, `valeur_libelle`, `valeur_uri`.
- Idempotence : si le `body` est déjà `SpecificResource` avec une
  URI connue du vocab (`source: str` direct ou `source.id`), il est
  compté dans `deja_enrichies` et n'est pas re-touché.
- **Remplacer** (pas ajouter) le `TextualBody` → `SpecificResource
  source={id, label}`. Cohérent avec ce qu'Annotorious crée
  nativement (un body par tag, jamais deux). La `purpose` du body
  initial est préservée (ne force pas `tagging` si le body était
  marqué `describing` par ex).
- Audit : `TracabiliteMixin` est bumpé à la main (le modèle
  `AnnotationRegion` n'a pas de `version_id_col` — verrou cross-
  process réservé à Fonds/Collection/Item). `modifie_par`,
  `modifie_le`, `version += 1` quand `dry_run=False`.
- CLI : `archives-tool annotations enrichir --vocabulaire X
  --fonds Y [--appliquer] [--utilisateur U]`. Dry-run par défaut.
  Le code vocab et la cote fonds sont des identifiants humains
  (résolus côté CLI vers les ids du service).
- UI : lien « ⤴ Enrichir » sur chaque fonds **rattaché** de la
  section « Fonds rattachés » de la page vocab détail. Ouvre une
  page `/vocabulaires/<id>/fonds/<cote>/enrichir` qui rend le
  rapport dry-run (tableau des matches avec libellé libre →
  libellé canonique → URI cliquable). Bouton « Confirmer
  l'enrichissement » → POST sur la même URL → applique + redirige
  vers la page vocab avec query string `?enrichi=N&fonds=COTE`.
- Tests :
  - 9 tests service (`test_annotations.py::test_enrichir_*`) :
    dry-run, appliquer, replay no-op, normalisation accents/casse,
    skip valeur sans URI / dépréciée, vocab/fonds introuvables,
    scope fonds isolé.
  - 5 tests CLI (`test_cli_annotations.py`) : dry-run par défaut,
    `--appliquer`, vocab/fonds introuvables, no-match.
  - 5 tests route + page (`test_vocabulaire_scoping.py`) :
    preview avec matches, POST applique + redirige, bouton présent
    uniquement sur fonds rattachés, lecture seule bloque (423),
    aucun match → message « Aucune annotation ».

**Pourquoi pas auto-enrichissement au moment du rattachement** :
un tag libre « Copi » dans le fonds B peut désigner la mauvaise
personne (homonyme, alias). Le diff explicite laisse l'utilisateur
arbitrer.

**Limites connues, reportées si un cas se présente** :
- Pas de pagination du rapport (un fonds avec 1000+ matches
  rendrait la page lourde ; en pratique on tape sur qq dizaines).
- Pas de filtre « enrichir uniquement les annotations de N à M » ;
  l'utilisateur arbitre via le rejet ciblé (non implémenté — il
  faudrait alors une UI de coches sur la preview).
- Pas de rollback automatique d'un enrichissement passé (la
  conversion `SpecificResource → TextualBody` est manuelle via la
  fiche annotation, et le bump de version ne supporte pas l'undo
  groupé). Reporté à un chantier dédié si besoin.

## Ordre de livraison recommandé

1. **T1 + T2** ensemble (un lot, un commit) — petit modèle,
   gain UX immédiat, pas de friction admin (défaut global).
2. **T3** quand l'admin via SQL/CLI devient gênante.
3. **T4** quand un fonds annoté élargit son périmètre vocab
   pour la première fois — pas avant.

## Alternatives écartées

- **Filtre client-side** (dropdown « Vocab : Dessinateurs PF ▾ »
  au-dessus du champ TAG) : zéro changement modèle, mais
  friction par annotation et pas d'effet positif sur la qualité
  des suggestions (l'utilisateur doit re-choisir le scope à
  chaque tracé).
- **Cap dur top N par fréquence + recherche serveur asynchrone
  via `?q=`** : pas d'admin nécessaire, mais infra plus lourde
  et pertinence aléatoire les premiers temps (rien à classer
  par fréquence sans usage).
- **Défaut inverse (vocab non rattaché = invisible)** : plus
  rigoureux mais bloquant au démarrage et probable source de
  confusion (« mon tag est dans le vocab, pourquoi pas de
  suggestion ? »).
- **Résolution à la lecture** (résoudre TextualBody → vocab
  côté serveur sur chaque GET) : zéro friction utilisateur,
  mais complique l'export Nakala JSON-LD (qui doit passer par
  la même couche pour ne pas exporter du « pauvre ») et coûts
  en perf.

## Renvois

- [Annotations IIIF (utilisateur)](../guide/annotations.md) — le
  workflow vocab+tag+URI tel qu'il fonctionne aujourd'hui.
- [`annotations-image-future.md`](annotations-image-future.md) —
  module annotations dans son ensemble, dont le couplage URI/
  vocab est dérivé.
