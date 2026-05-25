# Décisions d'architecture — usage de ColleC depuis un notebook

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur la
    documentation de l'usage de ColleC comme bibliothèque Python
    depuis un Jupyter Notebook ou un script ad-hoc.

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Constat

ColleC est **déjà** une bibliothèque Python utilisable depuis
n'importe quel script ou notebook. Les services métier
(`api/services/`), le moteur ORM (`models/`), les exporters, le
runner d'import, le module qa, sont tous importables :

```python
from sqlalchemy.orm import Session
from archives_tool.db import obtenir_session
from archives_tool.api.services.dashboard import composer_dashboard
from archives_tool.api.services.fonds import lister_fonds
from archives_tool.exporters._commun import composer_export

with obtenir_session() as db:
    dashboard = composer_dashboard(db)
    for f in lister_fonds(db):
        print(f.cote, f.titre)
```

Pourtant, aucune documentation n'expose cet usage. Il existe
implicitement, mais aucun chercheur n'irait deviner que c'est
faisable. L'analyse de publication-efe et nakala-quarto-view —
qui tous deux scriptent leurs transformations en Jupyter — révèle
que **cet usage est demandé** dans le monde des humanités
numériques. Il bénéficie d'être documenté.

C'est **un usage à formaliser, pas un module à construire**.

## Positionnement

Pourquoi ouvrir cet usage :

- **Chercheurs avec compétences Python** : explorer la base de
  manière exploratoire (DataFrames, requêtes ad-hoc, statistiques).
- **Croisement avec données externes** : combiner ColleC avec un
  export Tropy, une bibliothèque Zotero, une base CSV externe,
  une API d'autorité (VIAF, Wikidata) pour enrichir
  ponctuellement.
- **Exports personnalisés** : produire un format de sortie
  non-canonique (un JSON ciblé, un GeoJSON pour cartographie,
  un graphe de citations) sans demander un nouveau module au cœur
  ColleC.
- **Analyse et visualisation** : tracer la chronologie d'un
  fonds, mesurer la complétude par jalon, visualiser les
  collaborateurs récurrents.

Pourquoi ne pas en faire un module :

- L'API Python existe. Pas besoin de duplication.
- Construire un SDK séparé alourdirait inutilement la maintenance
  (deux surfaces publiques à garder synchrones).
- La CLI Typer est déjà une surface stable bien documentée pour
  les usages courants — le notebook prend le relais pour les
  usages spécifiques.

## Décisions actées

### Surface publique

L'**API publique** documentée pour usage notebook se limite aux :

- **Services métier** sous `archives_tool.api.services.` :
  - `fonds`, `collections`, `items`, `collaborateurs_fonds`
  - `dashboard` (composer_dashboard, composer_page_fonds, etc.)
  - `recherche` (rechercher, Scope)
  - `tri` (Listage, OptionsFiltres*)
- **Exporters** sous `archives_tool.exporters.` :
  - `dublin_core.exporter`, `nakala.exporter`, `excel.exporter`
  - `_commun.composer_export`
- **Modèles ORM** sous `archives_tool.models.` :
  - Lecture seule recommandée (`Fonds`, `Collection`, `Item`,
    `Fichier`, etc.).
  - Écriture **possible** mais déconseillée : préférer les
    services qui garantissent les invariants.
- **Session DB** : `archives_tool.db.obtenir_session()`
  (context manager) ou `creer_engine()` pour intégration
  pandas.

**Hors API publique** (instable, peut changer sans préavis) :

- `archives_tool.api.routes.*` (FastAPI routes — usage HTTP, pas
  Python).
- `archives_tool.api.deps.*` (helpers FastAPI internes).
- `archives_tool.web.*` (templates Jinja).
- Toute fonction préfixée `_` dans n'importe quel module.

### Stabilité du contrat

Les services métier exposés ont déjà la maturité requise (testés,
documentés en code, utilisés par la CLI et les routes web).
Aucune réécriture nécessaire pour les promouvoir comme API
publique.

**Engagement** : pas de breaking change sur les signatures des
services listés ci-dessus entre versions mineures. Ajout possible,
suppression ou renommage uniquement entre versions majeures avec
note explicite dans le changelog.

### Pas de wrapper « SDK »

Pas de package `archives_tool_sdk` séparé, pas de classe
`ColleCClient` qui encapsulerait les services. L'utilisateur
notebook utilise **directement** les services. Justifications :

- Moins de code à maintenir, moins de divergence possible.
- L'utilisateur apprend l'archi réelle de ColleC en l'utilisant
  (utile s'il veut contribuer plus tard).
- Pas de couche d'indirection à comprendre.

## Livrables

### Phase 1 — page guide « Notebook » (1 session, surtout doc)

Nouvelle page `docs/guide/notebook.md` (publiée sur le site
MkDocs) avec :

- Présentation du cas d'usage.
- Setup minimal (Jupyter dans l'env uv, connexion DB locale ou
  WebDAV).
- **5-6 recettes concrètes** :
  1. Lister tous les items d'un fonds avec leurs métadonnées en
     DataFrame pandas.
  2. Exporter une vue custom (CSV personnalisé, JSON spécifique)
     non couverte par les exporters canoniques.
  3. Croiser avec une bibliothèque Zotero locale ou un export
     Tropy (renvois vers `zotero-future.md` et
     `import-tropy-future.md` si créé).
  4. Calculer des statistiques de chantier (timeline, complétion
     par jalon, collaborateurs récurrents).
  5. Enrichir ponctuellement avec une API d'autorité (résoudre
     un nom d'auteur en URI VIAF, géocoder un lieu).
  6. Construire un graphe de citations / co-occurrences (utile
     pour les corpus de revues comme Por Favor).
- Liste de l'API publique avec liens vers les docstrings (générés
  par mkdocstrings si on l'ajoute, ou liens manuels en V1).
- Avertissements explicites sur les pièges (édition concurrente
  avec l'UI, conflits de verrou optimiste, sessions de longue
  durée à éviter).

### Phase 2 — promotion de l'API (à la demande)

Si l'usage notebook décolle réellement et qu'on observe des
patterns d'utilisation stables :

- Introduction de mkdocstrings dans `mkdocs.yml` pour autogénérer
  la doc de l'API publique depuis les docstrings.
- Module `archives_tool.api_publique` ré-exportant explicitement
  les fonctions stables (alias d'imports, pas réimplémentation).
  Rend le contrat visible et limite les imports « profonds »
  dans les notebooks.
- Tests dédiés vérifiant que les signatures de l'API publique ne
  changent pas (régression de stabilité).

### Phase 3 — exemples versionnés (à la demande)

Dépôt séparé `colle-c-notebooks-exemples/` avec des notebooks
.ipynb exécutables sur la base demo, démontrant des analyses
type. À ouvrir si des chercheurs adoptent vraiment l'usage et
demandent des points de départ.

## Pièges à éviter

- **Ne pas créer de classe wrapper.** Pas de `ColleCClient`,
  `ColleCSDK`, etc. Les services existants **sont** l'API.
- **Ne pas promouvoir l'écriture directe en ORM** dans les
  notebooks. Toujours passer par les services pour garantir les
  invariants, le journal, le verrou optimiste. Lecture libre,
  écriture via services.
- **Ne pas laisser une session SQLAlchemy ouverte longtemps**
  dans un notebook (les notebooks vivent des heures, une session
  longue génère des verrous résiduels). Utiliser
  `with obtenir_session() as db:` à chaque opération.
- **Ne pas concurrencer l'UI en édition.** Si un utilisateur
  édite via le navigateur pendant qu'un notebook écrit, le
  verrou optimiste lève une exception — c'est correct mais à
  documenter clairement.
- **Ne pas dupliquer la logique des services dans le notebook.**
  Si on se surprend à réécrire `lister_items_collection` à la
  main, c'est que la fonction de service mérite peut-être un
  paramètre additionnel — créer une issue, pas un workaround.

## Décisions à conserver

- **L'API publique = services métier + exporters + modèles ORM
  en lecture**, telle qu'elle existe déjà.
- **Pas de SDK séparé**, pas de wrapper.
- **Page guide « Notebook »** à écrire en V0.9.x ou V1 (peu de
  code, surtout de la doc).
- **Engagement de stabilité** sur l'API publique entre versions
  mineures.
- **Lecture libre, écriture via services.**
- **Cas d'usage cibles** : exploration, croisement avec données
  externes (Tropy, Zotero), exports personnalisés, analyse.

## Renvois

- Sites statiques (export canonique alternatif à un notebook
  ad-hoc) : `sites-statiques-future.md`.
- Zotero (cas d'usage typique notebook : croisement avec une
  bibliothèque Zotero) : `zotero-future.md`.
- Tropy (idem, à formaliser après discussion) :
  `import-tropy-future.md` (à créer si décidé).
