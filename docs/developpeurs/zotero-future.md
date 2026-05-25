# Décisions d'architecture — intégration Zotero

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur l'intégration
    de Zotero comme source d'import et cible d'export, en
    complément des formats canoniques existants (Dublin Core,
    Nakala CSV, xlsx, site statique).

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Constat

Zotero est l'outil bibliographique **de facto** dans la recherche
académique. Très large adoption (universitaires, doctorants,
chercheurs indépendants), gratuit, ouvert, multi-plateforme,
synchronisable via un compte zotero.org. Stocke des références
structurées (livre, article, chapitre, manuscrit, image, etc.)
avec métadonnées complètes et PDF/images attachés.

Beaucoup de chercheurs constituent leur corpus dans Zotero **avant
ou en parallèle** d'arriver sur un outil de catalogage spécialisé.
L'analyse de publication-efe a confirmé ce pattern : leur chaîne
utilise un fichier `.bib` Zotero rendu via `jekyll-scholar` pour
la bibliographie scientifique des publications.

Deux points d'intégration possibles avec ColleC :

- **Export Zotero/BibTeX** : produire un `.bib` ou un `.ris`
  importable depuis Zotero, à côté des autres exporters.
- **Import Zotero** : lire une collection Zotero pour pré-remplir
  des items ColleC (équivalent de l'onramp Excel pour les
  chercheurs qui utilisent Zotero plutôt que des tableurs).

## Positionnement

Pourquoi le faire :

- **Export** : permet aux chercheurs et bibliothécaires de
  rapatrier facilement leurs données ColleC dans leur Zotero
  personnel pour citation, sans intervention manuelle.
- **Export** (bis) : alimente directement la bibliographie d'un
  site statique généré (via `jekyll-scholar` pour Jekyll,
  `quarto-bib` pour Quarto, etc.).
- **Import** : onramp pour les chercheurs qui maintiennent déjà
  un corpus Zotero — équivalent moral de l'import tableur, format
  différent.

Pourquoi ce n'est pas prioritaire :

- ColleC produit déjà du Dublin Core, du Nakala CSV et du xlsx.
  Zotero **peut importer** depuis ces formats (notamment xlsx
  via des extensions, et CSV natif). L'export Zotero n'est donc
  pas le seul chemin pour rapatrier dans Zotero, juste le plus
  direct.
- Pour l'import : ciblage prioritaire est aux corpus
  iconographiques (Por Favor, Hara-Kiri) où Zotero est moins
  adapté que Tropy. Zotero brille sur les corpus **textuels**
  (articles, livres, chapitres).

Verdict : **utile mais secondaire**. Roadmap V2 ou V3 sauf
demande utilisateur explicite.

## Décisions actées

### Périmètre V1 — export uniquement

Export Zotero comme un exporter de plus, parallèle aux autres :

- Signature canonique `(session, collection, sortie) → RapportExport`.
- Granularité : la collection, comme les autres exporters.
- Réutilisation de `composer_export(db, collection)`.

**Pas d'import en V1.** L'import a plus de pièges (mapping des
types Zotero vers `type_coar`, attachements, doublons à
dédupliquer) et moins de valeur immédiate. À considérer en V2
sur demande.

### Formats de sortie supportés

Deux formats coexistent dans l'export :

- **BibTeX (`.bib`)** : format historique, supporté par tous
  les outils LaTeX et Markdown académique
  (`jekyll-scholar`, `quarto-bib`, `pandoc-citeproc`). Output
  unique : un seul `.bib` par collection exportée.
- **RIS (`.ris`)** : format Reference Manager, importable
  directement dans Zotero, Mendeley, EndNote. Plus universel
  pour le rapatriement dans Zotero.

**Choix utilisateur via CLI** : `--format bib|ris` (défaut `bib`,
plus universel en monde académique francophone).

### Mapping ColleC → Zotero/BibTeX

#### Type de l'entrée

`Item.type_coar` → type BibTeX/RIS :

| `type_coar` (label) | BibTeX | RIS |
|---|---|---|
| `journal` | `@article` | `JOUR` |
| `book` | `@book` | `BOOK` |
| `chapter` | `@incollection` | `CHAP` |
| `photograph` | `@misc` | `ART` |
| `map` | `@misc` | `MAP` |
| `manuscript` | `@unpublished` | `MANSCPT` |
| autre/inconnu | `@misc` | `GEN` |

Table d'alias centralisée dans `exporters/mapping_zotero.py`,
source de vérité unique.

#### Champs standards

Mapping direct des champs catalographiques :

| ColleC | BibTeX | RIS |
|---|---|---|
| `cote` | `note = {cote: ...}` | `M1` (Misc field 1) |
| `titre` | `title` | `TI` |
| `date` (EDTF) | `year` (extrait) + `note` (date complète) | `PY` + `Y1` |
| `description` | `abstract` | `AB` |
| `langue` (ISO 639-3) | `language` | `LA` |
| `doi_nakala` | `doi` + `url` | `DO` + `UR` |
| `fonds_titre` | `series` ou `booktitle` selon type | `T2` |
| `collection_titre` | `series` | `T3` |
| `metadonnees.auteur` ou `collaborateurs` | `author` | `AU` |
| `metadonnees.editeur` | `publisher` | `PB` |
| `metadonnees.lieu` | `address` | `CY` |
| `metadonnees.issn` | `issn` | `SN` |
| `metadonnees.numero` | `number` | `IS` |
| `metadonnees.volume` | `volume` | `VL` |
| `metadonnees.pages` | `pages` | `SP` + `EP` |

Tout champ `metadonnees.X` non-mappé est ignoré (BibTeX/RIS sont
des standards fermés, on ne pollue pas avec des champs custom).

#### Identifiant BibTeX

La clé de citation BibTeX (`@article{KEY, …}`) doit être unique
et stable. Convention proposée : `{fonds_slug}_{cote_slug}`, ex
`pf_pf-001`. Garde-fou contre les collisions inter-collections.

#### Auteurs multiples

BibTeX attend `author = {Nom1, Prénom1 and Nom2, Prénom2}`. Si
les auteurs sont stockés en `metadonnees.auteur` sous forme de
liste (depuis V0.9.2-import) ou de chaîne CSV, parser et
sérialiser correctement. Garde-fou : ne jamais produire
`author = {}` (vide) — soit on a la donnée, soit on omet le
champ.

### CLI

```bash
archives-tool exporter zotero COTE [--fonds COTE] \
    --sortie ./collection.bib \
    [--format bib|ris] \
    [--inclure-incomplets]
```

`--inclure-incomplets` permet d'inclure les items sans
métadonnées bibliographiques de base (titre uniquement) — par
défaut exclus parce que sans valeur citationnelle.

### Rapport d'export

Aligné sur les autres exporters via `RapportExport` :

- Items inclus / exclus (raison : type non mappable, métadonnées
  insuffisantes).
- Champs manquants par item (titre vide, date absente, auteur
  absent — les trois piliers d'une référence bibliographique
  utile).
- Avertissements sur les approximations de type (`@misc` quand
  on n'a pas mieux).

## Périmètre V2 ou V3 — import

**À discuter avec demande utilisateur.** Cadre prévu si ouverture :

### Source de l'import

Deux modes :

- **Fichier local** : `.bib` ou `.ris` exporté depuis Zotero.
  Pipeline aligné sur l'import tableur (lire → transformer →
  écrire via services).
- **API Zotero** : requête sur une bibliothèque Zotero (user ou
  group) via `pyzotero`. Plus puissant (synchro automatique
  possible si on l'ouvre un jour) mais introduit une
  dépendance externe + clé API à gérer.

V2 : commencer par le fichier local. V3 ou plus tard si demande
forte : ouvrir l'API.

### Mapping inverse

Inverse du mapping export :

- Type Zotero → `type_coar` (table d'alias inverse).
- Champs Zotero → champs ColleC, avec `metadonnees.X` comme
  poubelle pour ce qui ne mappe pas exactement.
- Attachements PDF/images : copiés dans `derives_travail` et
  rattachés comme `Fichier` à l'Item créé.

### Dédoublonnage

Items déjà présents dans ColleC (par DOI, ou par cote si
définie) : signalés en dry-run, créés en nouveau (avec note de
rapprochement) ou mis à jour (avec verrou optimiste) selon flag
utilisateur.

### Profil d'import Zotero

Sur le modèle des profils tableur v2, un profil YAML pour
configurer le mapping des champs custom et les valeurs par
défaut. Mais beaucoup moins critique que pour Excel parce que
Zotero a déjà une structure typée.

## Pièges à éviter

- **Ne pas tenter de représenter dans BibTeX ce qui n'a pas de
  sens.** Une photographie ou un manuscrit en `@misc` est plus
  honnête qu'un faux `@article` qui troublera les processeurs.
- **Ne pas générer de champ `author` vide ou « anonyme ».**
  Omettre est mieux qu'inventer.
- **Ne pas polluer le `.bib` avec des champs custom.** BibTeX
  est un standard fermé. Les champs non-standards (`x-cote`,
  `x-fonds`) cassent certains processeurs. Tout passe par
  `note` ou est omis.
- **Pour l'import (V2+) : ne pas écraser silencieusement.**
  Toujours dry-run par défaut, comme l'import tableur.
- **Pour l'import API (V3+) : ne pas stocker la clé API Zotero
  dans la base ColleC.** Variable d'environnement ou
  `config_local.yaml` (hors versionning), jamais en base
  partagée.
- **Ne pas faire de sync bidirectionnel.** Zotero et ColleC ont
  des modèles distincts, la synchronisation ouvrirait un puits
  de cas-limites. Imports/exports ponctuels uniquement.

## Décisions à conserver

- **Export en V2/V3** comme exporter parallèle aux autres
  (DC/Nakala/xlsx/site statique).
- **Deux formats** : BibTeX (défaut) et RIS, choix CLI.
- **Mapping centralisé** dans `exporters/mapping_zotero.py`.
- **Import différé** à V2/V3 sur demande utilisateur réelle.
- **Pas de sync bidirectionnel jamais.**
- **Champ `cote` stocké dans `note` BibTeX**, pas en champ
  custom (compat avec processeurs stricts).

## Renvois

- Sites statiques (consomment souvent un `.bib` Zotero via
  jekyll-scholar / quarto-bib pour la bibliographie scientifique
  du site) : `sites-statiques-future.md`.
- Notebooks (cas d'usage typique : croiser une biblio Zotero
  avec ColleC en pandas) : `notebooks-sdk-future.md`.
- Tropy (complémentaire pour les corpus iconographiques, où
  Zotero est moins pertinent) : `import-tropy-future.md`
  (à créer si décidé).
