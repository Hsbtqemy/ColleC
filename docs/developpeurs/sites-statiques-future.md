# Décisions d'architecture — export site statique

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur l'ajout d'un
    exporter générant un arbre Markdown propre à alimenter un
    générateur de site statique (Quarto, Hugo, Jekyll, …).

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Positionnement

ColleC gagne un nouvel exporter — `exporters/site_statique.py` —
qui produit, pour une collection donnée, **un arbre de Markdown
avec frontmatter YAML + assets**, prêt à être consommé par le
générateur de site statique choisi par l'utilisateur.

C'est un **format de sortie** au même titre que Dublin Core XML,
Nakala CSV ou xlsx. Strictement additif, pas une refonte. Le
module réutilise `composer_export(db, collection)` (zéro
duplication de la logique de chargement) et suit la même signature
canonique `(session, collection, sortie, options) → RapportExport`
que les exporters existants.

### Différence avec les autres formats de sortie

| Format | Cible | Granularité | Usage typique |
|---|---|---|---|
| Dublin Core XML | entrepôt / archivage | collection | dépôt académique, conservation |
| Nakala CSV | Nakala | collection | dépôt Nakala bulk |
| xlsx | tableur | collection | reprise / relecture humaine |
| **Site statique** | **SSG (Quarto/Hugo/…)** | **collection** | **valorisation web autonome** |

### Différence avec le portail public

- **Portail public** (voir `portail-public-future.md`) : site
  **dynamique central**, multi-fonds, recherche serveur,
  administration continue, projet séparé alimenté par
  exports/synchros ColleC.
- **Site statique** : **artefact figé** d'une collection ou d'un
  fonds particulier, citable, archivable, hébergeable n'importe
  où (GitLab Pages, GitHub Pages, simple serveur HTTP), low-tech
  par construction.

Les deux cohabitent : ColleC produit le matériel, le portail
l'agrège dynamiquement, les sites statiques le figent pour des
occasions précises de valorisation (exposition virtuelle,
publication d'un corpus thématique, version archivable d'un fonds
achevé).

## Inspirations externes

Deux projets Huma-Num référents ont été analysés en amont :

### OPUS / publication-efe

[Dépôt GitLab](https://gitlab.huma-num.fr/bmorandiere/publication-efe).
Chaîne éditoriale du réseau des Écoles françaises à l'étranger.

- **SSG** : Jekyll + GitLab Pages.
- **Pivot** : Markdown avec frontmatter YAML, **clés en français
  aplaties à la racine**, champs vides conservés.
- **Génération** : Jupyter Notebooks lisant Tropy + Zotero.
- **Limites observées** : couplage frontmatter ↔ SSG via
  `layout: fiche` (instruction Jekyll mêlée à la donnée), pas
  d'IIIF (chemins d'images locaux seulement), pas d'URI
  d'autorité, doublon `identifier` / `identifiant`.

**Ce qu'on emprunte** : clés FR aplaties, conservation des champs
vides, pages éditoriales coexistent dans le projet site mais ne
sont pas générées par ColleC.

**Ce qu'on évite** : tout couplage entre pivot et instructions
SSG. Les clés comme `layout:`, `permalink:`, `_quarto:` sont
ajoutées par le **template Jinja de la cible**, jamais par le
pivot.

### nakala-quarto-view

[Dépôt GitLab](https://gitlab.huma-num.fr/mshs-poitiers/plateforme/nakala-quarto-view).
Visualisation Quarto d'un corpus Nakala (MSHS Poitiers).

- **SSG** : Quarto + GitLab Pages.
- **Génération** : 5 modules Python interrogeant l'API Nakala REST.
- **Structure** : `dataPost/{collection_slug}/{doi_slug}.qmd` —
  un niveau de hiérarchie par collection.
- **Multi-appartenance** : résolue par **duplication** (un item
  dans 2 collections → 2 fichiers, un par sous-répertoire).
- **Images** : **IIIF natif** (`iiif/{doi}/{sha1}/full/!200,200/0/default.jpg`)
  avec vignette locale pour couverture.
- **Pages globales** (`index.qmd`, `about.qmd`, `alldata.qmd`,
  `authors.qmd`, `collections.qmd`, `statistiques.qmd`)
  **pré-écrites par l'auteur du site**, pas générées.
- **Séparation nette** code Python / environnement Quarto.

**Ce qu'on emprunte** : Quarto comme cible initiale, IIIF natif,
duplication pour multi-appartenance, hiérarchie 1-niveau, pages
éditoriales pré-écrites par l'utilisateur, séparation
code/environnement.

## Décisions actées

### Cible initiale et extensibilité

- **Phase 1 livrée avec Quarto seul**, validation de l'archi de
  templates Jinja extensibles.
- **Phase 3 ajoute Hugo** pour prouver l'extensibilité multi-SSG.
- Cibles ultérieures (Jekyll, 11ty, Pelican, MkDocs Material)
  ajoutables par contribution sans toucher au cœur du module.
- **CLI** : `archives-tool exporter site-statique COTE [--fonds COTE]
  --sortie ./site/ [--cible quarto|hugo] [--images copier|iiif|hybride]
  [--inclure-items-sans-fichier]`.

### Pivot frontmatter

- **Clés en français.** Aligné avec le reste de ColleC, et validé
  par publication-efe.
- **Aplaties à la racine** pour les champs catalographiques
  canoniques. Permet à l'SSG de les indexer/filtrer nativement.
- **Champs personnalisés regroupés sous `metadonnees:`** pour
  éviter les collisions avec les conventions SSG (`title`, `date`,
  `tags`, `layout`, etc. réservés).
- **Champs vides conservés** (`dessins: ""`). Facilite les
  templates qui itèrent sans tester l'existence.
- **Strictement neutre vis-à-vis du SSG.** Aucune clé d'instruction
  de rendu (`layout`, `permalink`, `categories`, etc.) dans le
  pivot. Les clés SSG sont ajoutées par le template Jinja de la
  cible.
- **Vocabulaires contrôlés en double sortie** : champs typés
  (`type_coar:`, `langue:`) **et** dupliqués dans `tags:` pour les
  listings natifs SSG.

#### Énumération du pivot (V1 — phase 1)

```yaml
# Identification
cote: "PF-001"
slug: "pf-001"                    # nom du fichier sans extension
titre: "Por Favor n°1"

# Rattachement
fonds_cote: "PF"
fonds_titre: "Por Favor"
collection_cote: "PF-MIROIR"      # collection courante dans ce répertoire
collection_titre: "Por Favor (miroir)"
collections_appartenance:         # toutes les collections où figure l'item
  - cote: "PF-MIROIR"
    titre: "Por Favor (miroir)"
    type: "miroir"
  - cote: "DESSINS-COPI"
    titre: "Dessins de Copi"
    type: "libre"

# Catalographie
date: "1974-05-25"                # EDTF brut, l'SSG normalise s'il veut
type_coar: "http://purl.org/coar/resource_type/c_3e5a"
type_coar_libelle: "Périodique"
langue: "spa"                     # ISO 639-3
description: |                    # Markdown autorisé
  Numéro inaugural de la revue satirique…

# Identifiants externes
doi_nakala: "10.34847/nkl.xxxxxxxx"
doi_collection_nakala: "10.34847/nkl.716dhx95"
iiif_manifest: ""                 # URL si générable, sinon ""

# Médias
couverture: "assets/vignettes/pf-001-couverture.jpg"
nb_fichiers: 40
fichiers:
  - ordre: 1
    type_page: "couverture"
    folio: ""
    iiif_image: "https://api.nakala.fr/iiif/.../info.json"
    vignette: "assets/vignettes/pf-001-001.jpg"
  - ordre: 2
    type_page: "page"
    folio: "2"
    iiif_image: "https://api.nakala.fr/iiif/.../info.json"
    vignette: "assets/vignettes/pf-001-002.jpg"
  # …

# Champs personnalisés (sous namespace pour éviter collisions SSG)
metadonnees:
  ancienne_cote: "PF/1/1974"
  numero: "1"
  collaborateur_dessins: "Copi, Forges"

# Tags consommables par l'SSG (vocabulaires aplatis)
tags:
  - "Périodique"
  - "spa"
  - "Por Favor"

# État (optionnel, exclu par défaut, inclus si --inclure-etat)
# etat_catalogage: "valide"
```

#### Exclus du pivot par défaut

- `notes_internes` (privé chantier).
- Traçabilité (`cree_par`, `modifie_par`, dates) — privée
  chantier, hors-scope publication.
- `etat_catalogage` par défaut — exposable via flag
  `--inclure-etat` si on veut publier un état des lieux interne.

### Structure de répertoires

Hiérarchie légère **1-niveau** par collection, inspirée de
nakala-quarto-view. La cible Quarto produit :

```
site_pf/
  _quarto.yml                          # config Quarto, généré par template
  index.qmd                            # page d'accueil collection (généré)
  items/
    pf-miroir/
      pf-001.qmd                       # un item = un .qmd, contenu complet
      pf-002.qmd
      pf-003.qmd
      …
    dessins-copi/                      # même item dupliqué ici
      pf-001.qmd                       # avec collection_cote différent
      pf-014.qmd
      …
  assets/
    vignettes/
      pf-001-couverture.jpg
      pf-001-001.jpg
      …
  references.bib                       # optionnel, si métadonnées biblio
```

- **Un sous-répertoire `items/{collection_slug}/` par collection
  exportée**. Cas mono-collection (export d'une seule miroir) → un
  seul sous-répertoire. Cas multi-collection → plusieurs.
- **Pages globales** (`about.qmd`, `bibliographie.qmd`,
  `exposition.qmd`, etc.) **non générées**. L'utilisateur les
  ajoute dans son projet de site après l'export.
- **`_quarto.yml` minimal généré** (titre, navbar de base, thème
  par défaut). L'utilisateur customise ensuite.
- **`references.bib`** généré uniquement si des métadonnées
  bibliographiques sont présentes.

### Multi-appartenance

**Décision : duplication**, conforme à nakala-quarto-view et au
principe d'autonomie des items.

- Un item dans la miroir PF + dans la libre « Dessins de Copi »
  → deux `.qmd` générés (un dans `items/pf-miroir/pf-001.qmd`,
  un dans `items/dessins-copi/pf-001.qmd`).
- Les deux contiennent **le même corps catalographique**, ne
  diffèrent que par `collection_cote` / `collection_titre` (la
  collection « courante » dans ce répertoire) et leur position.
- Le champ `collections_appartenance:` liste toutes les
  collections d'appartenance dans les deux exemplaires —
  l'utilisateur du site peut donc afficher les liens croisés.

Justifications :
- Chaque sous-répertoire est un sous-site autonome
  navigationnellement (aucun lien relatif transverse à résoudre).
- Cohérent avec le principe d'autonomie des items du
  `CLAUDE.md` (chaque exemplaire est complet, intelligible hors
  contexte).
- Coût en duplication dérisoire (`.qmd` font quelques Ko).
- Cohérent avec l'expérience nakala-quarto-view.

### Images

Trois modes via flag CLI `--images` :

- **`copier`** : tous les dérivés copiés dans `assets/`. Site
  totalement autonome. Lourd. Idéal pour archivage long terme,
  pour un site qui doit survivre à la disparition de Nakala.
- **`iiif`** : aucune image copiée, toutes les références
  pointent sur les URLs IIIF Nakala. Léger. Dépendance forte à
  Nakala (404 si la donnée est dépubliée).
- **`hybride`** *(défaut)* : vignettes et aperçus moyens copiés
  localement (pour le chargement rapide des listings et des pages
  item), URLs IIIF pour les images haute résolution dans la
  visionneuse. Bon compromis pour la majorité des cas.

Le champ `iiif_image` du frontmatter pointe sur l'URL IIIF
`info.json` quand disponible (image servie par Nakala ou serveur
IIIF tiers), `""` sinon. Le champ `vignette` pointe sur le chemin
local relatif si copié, `""` sinon.

### Nommage des fichiers

- **Par cote slugifiée**, sans ambiguïté : `PF-001` → `pf-001.qmd`.
- Slugification : minuscules, accents retirés (NFD + drop
  diacritiques), tout caractère non `[a-z0-9-]` remplacé par `-`,
  collapse des `-` répétés.
- En cas de collision (deux items, cotes identiques après
  slugification — improbable mais possible) : suffixe numérique
  `-2`, `-3`, etc. Signalé dans le rapport.

### Items sans fichier

- **Exclus par défaut**. Un site public n'a généralement pas
  vocation à montrer « pas encore scanné ».
- **Flag `--inclure-items-sans-fichier`** pour les cas légitimes
  (publication d'un état des lieux interne, plan de chantier
  exposé à l'équipe).

### Versioning et régénération

- **Écrasement** du répertoire de sortie. ColleC ne versionne pas
  les exports.
- L'utilisateur fait son `git diff` côté projet de site s'il
  veut tracer les changements entre deux exports.
- Aucune annotation côté ColleC sur « date du dernier export » —
  hors-scope.

### Pages éditoriales additionnelles

**Non générées par ColleC.** Pas de :
- Page « À propos du fonds » personnalisable.
- Dossiers thématiques (« Por Favor pendant la Transition »).
- Biographies de contributeurs.
- Liste bibliographique de références scientifiques.

L'utilisateur les ajoute dans son projet de site **après**
l'export, en coexistence avec les `.qmd` générés. C'est la règle
qui sépare ColleC d'un CMS.

### Génération d'index, tags, archives

**Non générée par ColleC.** Le SSG (Quarto, Hugo) génère
nativement les listings, les pages de tag, les archives par
date, depuis les frontmatter. ColleC sort la donnée brute, le
SSG fait son travail.

### Validation post-export

- Rapport `RapportExport` aligné sur les autres exporters :
  items incomplets, vignettes manquantes, durée, conformité du
  pivot.
- **Pas de validation HTTP des URLs IIIF.** Trop fragile, trop
  lent, hors scope. Si l'URL IIIF est en base, on la sort
  telle quelle.
- **Pas de build du site.** ColleC ne lance pas `quarto render`
  ni `hugo build`. La phase de build appartient au projet de
  site.

### Multi-langue

**Hors V1.** Frontmatter en français unique, corps en français
unique. Si un jour un fonds est trilingue, on introduira des
champs `titre_es:` / `titre_fr:` / etc. dans le modèle ColleC,
et l'exporter saura les sérialiser — décision repoussée tant
qu'il n'y a pas de besoin concret.

### Visionneuse embarquée dans le site généré

**Choix du projet de site, pas de ColleC.** ColleC produit les
manifestes IIIF et les liens vers les ressources (Nakala IIIF
Image API), le site généré choisit la visionneuse qui les
consomme.

Trois candidats pertinents, équivalents à ceux discutés pour
le portail dynamique (cf. `portail-public-future.md` section
*Choix de la visionneuse*) :

- **OpenSeadragon** seul si UI custom souhaitée et faible
  besoin d'une couche multi-format.
- **Universal Viewer** comme viewer clé-en-main avec UI
  « pro de bibliothèque ». Bon défaut pour un site
  d'exposition ou de catalogue grand public.
- **Mirador** si le site cible un public érudit qui veut
  comparer les ressources entre elles (cas Por Favor à terme).

**Conséquence pour le template Jinja** : prévoir une variable
de config dans `_quarto.yml.j2` (ou équivalent) qui détermine
quel viewer est embarqué. Trois templates partiels possibles
(`_viewer_osd.qmd.j2`, `_viewer_uv.qmd.j2`, `_viewer_mirador.qmd.j2`)
dans `exporters/templates/site_statique/{cible}/partials/`,
sélectionnés par le frontmatter du site. L'utilisateur choisit
au moment de la configuration de son projet de site, ColleC
fournit les trois recettes.

**Interop préservée.** Les trois viewers consomment le même
manifeste IIIF et les mêmes W3C Web Annotations produits par
ColleC — le choix est réversible côté site, aucune transformation
des données à prévoir.

## Phases de développement

### Phase 1 — alpha (1 session)

Module squelette avec une cible (Quarto) et une stratégie images
(hybride par défaut). Validé end-to-end sur la base demo.

Livrables :

- `exporters/site_statique.py` avec signature canonique.
- `exporters/templates/site_statique/quarto/` avec trois fichiers
  Jinja minimaux : `item.qmd.j2`, `index.qmd.j2`,
  `_quarto.yml.j2`.
- Service de slugification (réutilisable, peut vivre dans
  `exporters/_commun.py`).
- CLI `archives-tool exporter site-statique` (Typer).
- Tests unitaires : rendu d'un item type avec frontmatter
  attendu, slugification, gestion des champs vides.
- Tests d'intégration : export complet d'une collection demo,
  vérification de l'arborescence produite.

### Phase 2 — beta (1 session)

Robustesse, multi-appartenance, cas réels.

Livrables :

- Duplication par sous-répertoire (multi-appartenance).
- Sérialisation propre des champs personnalisés sous
  `metadonnees:`.
- Sérialisation des vocabulaires en double (typé + tags).
- Trois modes images (`copier`, `iiif`, `hybride`) opérationnels.
- Génération `references.bib` si métadonnées bibliographiques
  présentes.
- Flag `--inclure-items-sans-fichier`.
- Flag `--inclure-etat`.
- Test d'intégration lourd : export d'une grosse collection
  demo + `quarto render` réel dans un sous-process (test marqué
  `slow`, exclu du CI rapide mais exécuté en pré-release).
- Doc utilisateur dans `docs/guide/cli/exporter.md`.

### Phase 3 — gamma (1 session)

Extensibilité multi-cible.

Livrables :

- Cible Hugo : `exporters/templates/site_statique/hugo/` avec
  frontmatter adapté (`date: YYYY-MM-DDTHH:MM:SSZ`,
  `taxonomies:`, etc.).
- Mécanisme `--cible quarto|hugo` câblé.
- Doc développeur dans `docs/developpeurs/` expliquant comment
  ajouter une troisième cible (Jekyll, 11ty, Pelican).
- Dépôt exemple séparé `colle-c-example-site-quarto` (et
  éventuellement `colle-c-example-site-hugo`) montrant un
  projet complet alimenté par un export, avec un thème basique
  mais propre.

### Phase 4 — delta (sessions ultérieures, sur usage réel)

Enrichissements à la demande, **jamais en anticipation** :

- Sérialisation des annotations IIIF dans les pages item
  (cf. `annotations-image-future.md`) sous forme de blocs
  d'overlays — quand le module annotation V2 existera.
- Génération optionnelle `search-index.json` pour MiniSearch /
  Lunr.js si l'SSG cible n'a pas de recherche native
  satisfaisante.
- Filtres d'export plus fins (« seuls les items à l'état
  validé », « seuls les items annotés », etc.).
- Multi-langue si besoin concret.

## Pièges à éviter

- **Ne pas lancer le SSG depuis ColleC.** L'export s'arrête à la
  production des fichiers. Le build relève du projet de site.
  Même règle que pour ScanTailor / Tesseract en amont.
- **Ne pas embarquer un thème ColleC officiel.** Vous deviendriez
  responsable de sa maintenance. Laissez ça au projet de site
  (et au dépôt exemple, qui n'est pas un thème officiel mais une
  démo).
- **Ne pas coder en dur les conventions d'un SSG dans le service
  principal.** Tout passe par les templates Jinja, point. La
  preuve doit être faite en phase 3 en ajoutant Hugo sans
  toucher au cœur.
- **Ne pas dériver vers un CMS.** Pas de génération de pages
  éditoriales, pas de Markdown wysiwyg dans ColleC, pas de
  gestion de versions d'exports.
- **Ne pas mélanger pivot et instructions SSG.** Erreur observée
  dans publication-efe (`layout: fiche` dans le frontmatter de
  données). Le pivot ColleC reste neutre ; chaque template
  ajoute les clés que son SSG attend.
- **Ne pas valider les URLs IIIF.** Tentation forte, mais c'est
  un puits sans fond (network, timeouts, 404 transitoires).

## Décisions à conserver

- **Site statique = format de sortie**, parallèle à DC/Nakala/xlsx.
- **ColleC produit la donnée, pas le thème.**
- **Frontmatter en français, aplati, champs vides conservés,
  neutre vis-à-vis du SSG.**
- **Multi-appartenance par duplication** dans des sous-répertoires
  par collection.
- **Quarto en phase 1, Hugo en phase 3** pour valider
  l'extensibilité.
- **Trois modes images** (`copier`, `iiif`, `hybride` par défaut).
- **Items sans fichier exclus par défaut**, flag d'inclusion.
- **Pages éditoriales hors-scope ColleC.**
- **Pas de build du site, pas de validation HTTP, pas de
  versioning d'exports, pas de multi-langue en V1.**

## Candidat image-first : Canopy IIIF + keystone manifeste IIIF Presentation (évalué 2026-06-18)

[Canopy IIIF](https://github.com/canopy-iiif/app) (MIT, mature — v1.12.2
mai 2026, ~164 releases) est un **générateur de site statique piloté par
IIIF** : on lui donne une **Collection IIIF Presentation** (clé `collection:`
de `canopy.yml`, et/ou des `manifest:`), il génère un site statique
(GitHub Pages, `npm run build`, Node ≥24) avec **une page « work » par
Manifest**, un **facettage automatique** par métadonnées (clé `metadata:`,
ex. `Subject` / `Date` / `Language` / `Genre`), une **recherche** et des
pages éditoriales **MDX** (`content/*.mdx`). Viewer Clover IIIF, theming
Tailwind (`theme: {appearance, accentColor, grayColor}`). Le repo `app`
est le **moteur** — les vrais projets partent d'un **template** (≠ cloner
`app`).

### Pourquoi c'est complémentaire de Quarto, pas concurrent

Les deux sont des **sorties statiques**, mais de **centre de gravité
opposé**, sur le **même substrat IIIF** :

| | **Quarto / Hugo** (ce doc) | **Canopy** |
|---|---|---|
| Pivot d'entrée | **Markdown + frontmatter** | **Collection IIIF Presentation** |
| Unité | la **notice** (texte) | le **Manifest** (objet/image) |
| Centre de gravité | **éditorial** : prose, dossiers, biblio, contrôle fin | **image-first** : feuilletage, deep-zoom, facettes + recherche clé-en-main |
| Idéal pour | corpus éditorialisé, exposition narrative | périodique numérisé à feuilleter/facetter (Por Favor) |
| Éditorial | natif (Markdown) | surcouche MDX |

Choix **par occasion**, non exclusif : Quarto = réponse éditoriale,
Canopy = réponse image-first. Tous deux nourris par ColleC.

### Keystone : un exporter `iiif_presentation.py` (prérequis partagé)

**Contrainte vérifiée** (`nakala-savoir-api.md` §13, sondé live) : Nakala
expose l'**Image API** (`info.json`) mais **pas** l'API **Presentation**
(`/iiif/{doi}/manifest…` → 404). Donc **aucun raccourci** « pointer Canopy
sur Nakala » : ColleC doit **générer** les manifestes Presentation. Cet
exporter est donc la **seule porte** vers tout consommateur Presentation,
et il **paie plusieurs fois** :

1. **débloque Canopy** (`collection:` pointe sur la Collection générée) ;
2. **rend réel le champ `iiif_manifest:`** du pivot Quarto, et le viewer
   embarqué (OSD / UV / **Mirador**) consomme le **même** manifeste ;
3. les **annotations W3C** déjà produites par ColleC s'**attachent au
   manifeste** → ressortent dans Clover (Canopy) **et** Mirador (Quarto).

C'est bien borné : ColleC a la structure item→fichiers ordonnés, les URLs
**Image API Nakala** (`info.json`) comme `service` de chaque canvas, les
métadonnées et les annotations. Le **mapping facettes Canopy** tombe
juste : `Subject`←`sujets`, `Date`←`date`/`année`, `Language`←`langue`,
`Genre`←`type_coar` (l'exporter pose ces labels dans le `metadata` du
Manifest → facettage Canopy sans config). Les `id` des manifestes prennent
un `--base-url` (même pattern que l'export annotations δ : URI relative à
remplacer après dépôt).

### Réserves

- **Hébergement des manifestes** = affaire du **projet de site** (ColleC
  produit, n'héberge pas). Option élégante : déposer les JSON générés comme
  *data* Nakala → URLs HTTP stables ; sinon raw GitHub du repo de site.
- **Build JS (Node ≥24)** côté projet de site, pas dans ColleC (cohérent
  avec « ColleC ne build pas le site »). Dépôt exemple type
  `colle-c-example-site-canopy` à partir du **template** Canopy.
- **Theming opiniâtre** (Tailwind tokens) → moins de liberté éditoriale
  que Quarto. C'est l'arbitrage assumé.

### Statut

**Candidat évalué, non engagé.** Le **prérequis** = l'exporter
`iiif_presentation.py`, qui a de la valeur **indépendamment** de Canopy
(Mirador, UV, portail public en consomment aussi). À séquencer dans le
**Chantier 4 (diffusion)**, après le Chantier 2 (OCR/recherche). Décision
de cible (Quarto / Canopy / les deux) à prendre **par occasion de
valorisation**, pas une fois pour toutes.

## Renvois

- Roadmap V2 du `CLAUDE.md` racine (section *Plan de
  développement*) : ajouter une entrée explicite « Export site
  statique » lors de la validation finale.
- **Canopy IIIF** + keystone manifeste IIIF Presentation : cf. section
  ci-dessus ; contrainte Nakala (Image API seul, pas Presentation) dans
  `nakala-savoir-api.md` §13.
- Portail public (consommateur dynamique parallèle aux sites
  statiques) : `portail-public-future.md`.
- Annotations IIIF (intégrables en phase 4) :
  `annotations-image-future.md`.
- Workflow amont (le site statique est produit après les
  étapes 6-7 de la chaîne) : `workflow-numerisation.md`.
