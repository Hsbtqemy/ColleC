# Décisions d'architecture — contribution via fichiers structurés

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur le **troisième
    mode de contribution externe** à ColleC : édition directe de
    fichiers XML/TEI structurés exportés depuis ColleC, hors UI
    web et hors API Python.

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Positionnement

ColleC a vocation à accepter des contributions externes selon
**trois ergonomies** distinctes, chacune adaptée à un public et un
type de geste différents :

| Mode | Outil | Public typique | Compétence requise | Type de geste |
|---|---|---|---|---|
| **UI web (HTMX)** | Navigateur | Catalogueur d'équipe, invité consultation/contributeur | Aucune compétence tech | Geste unitaire, saisie guidée |
| **API Python / notebook** | Services `archives_tool.api.services.*` | Chercheur Python-savvy, analyste | Python intermédiaire | Analyse, transformation en lot, export custom |
| **Fichiers XML/TEI structurés** | Oxygen XML Editor, VSCode + extensions, git | Archiviste DH-formé, philologue, éditeur scientifique | XML/TEI familier, git basique | Édition structurée approfondie, transcription savante |

Ce doc formalise le **troisième mode**. Les deux premiers sont
couverts respectivement par les invitations dans
[`deploiement-future.md`](deploiement-future.md) (matrice
d'identités) et par [`notebooks-sdk-future.md`](notebooks-sdk-future.md).

### Pourquoi ce mode mérite d'exister

- **Bulk editing** : corriger 50 fiches catalographiques d'un coup
  via une transformation XSLT est mille fois plus rapide qu'à
  l'UI.
- **Édition structurée approfondie** : la transcription TEI d'un
  article (encodage des `<persName>`, `<placeName>`, `<date>`,
  apparat critique) demande un éditeur dédié et une vision globale
  du document — pas une succession de petits formulaires.
- **Workflow distribué** : git permet à plusieurs contributeurs
  externes de travailler en parallèle sur des branches, de
  proposer des changements en PR, sans impacter l'instance
  ColleC vivante.
- **Public DH naturel** : archivistes et philologues formés en
  master DH connaissent déjà ces workflows. Leur demander
  d'apprendre une UI custom à la place crée de la friction.

### Le seuil d'accessibilité

XML/TEI **n'est pas accessible au novice absolu** — équilibrer
les balises, comprendre les namespaces, valider contre un schéma
demande de l'habitude. Mais c'est **accessible à beaucoup plus de
monde que SQL ou Python**, et c'est un format de travail courant
dans la communauté DH depuis 25 ans.

Outils qui rendent ça praticable :

- **Oxygen XML Editor** : commercial avec licences académiques
  courantes, c'est l'outil de référence DH. Éditeur visuel guidé
  par schéma, validation à la frappe, autocomplete des balises
  TEI, transformations XSLT intégrées, support natif des
  schémas ALTO / DC / TEI / EAD.
- **VSCode + extensions XML/TEI** : gratuit, équivalent
  fonctionnel pour qui accepte une UX un peu moins léchée.
  Schémas chargeables, validation, autocomplete.
- **OxGarage** : convertisseur web TEI ↔ Word ↔ PDF, utile pour
  les contributeurs qui démarrent depuis Word.
- **Git** : versionnement, partage, fusion. GitLab Huma-Num
  fournit déjà l'infrastructure.

## Pattern de round-trip

L'idée centrale : **tout ce que ColleC exporte, il doit pouvoir
le ré-ingérer**. Les exporters existants (Dublin Core XML, ALTO,
xlsx, futur TEI) deviennent simultanément des **formats
d'entrée** pour les contributions externes.

```
ColleC ──export──> XML file ──édition externe──> XML file modifié ──import──> ColleC
            (DC, ALTO, TEI)   (Oxygen, VSCode)                       (delta)
```

### Pré-requis techniques

Quatre conditions à remplir pour que ce round-trip soit fiable :

1. **Identifiants persistants.** Chaque entité exportée doit
   porter une clé stable que le ré-import utilise pour retrouver
   l'enregistrement existant. Candidats :
   - **`cote`** (déjà unique par fonds) : lisible, suffisant si
     pas de risque de re-cotage.
   - **`id_persistant`** (à introduire, type UUID ou ULID) :
     parfaitement stable même en cas de re-cotage. Plus robuste
     à long terme.
   Recommandation : ajouter `id_persistant` sur les entités
   (`Fonds`, `Collection`, `Item`, `Fichier`) en V1.x quand on
   ouvrira ce mode. Génération automatique à la création, jamais
   modifié ensuite. Sérialisé dans tous les exports XML comme
   attribut `xml:id` ou élément `<identifier>`.

2. **Round-trip integrity (lossless).** Ce que sort l'exporter
   doit être strictement équivalent à ce qui rentre via
   l'importer : mêmes champs, même ordre, même conventions de
   sérialisation. Pas de perte silencieuse de métadonnées custom
   pendant l'aller-retour. Test de régression dédié dans la
   suite de tests : `export → import → re-export → diff = vide`.

3. **Détection de delta.** À l'import, ColleC compare l'XML reçu
   à l'état en base, calcule les changements (champs modifiés,
   ajoutés, supprimés), applique seulement le delta via les
   services métier existants (`modifier_item`, etc.). Le verrou
   optimiste protège contre les conflits (« cet item a été modifié
   par X depuis votre export du DDMMYYYY, voulez-vous écraser ou
   rebaser ? »). Le journal trace l'origine (`origine_modification:
   import_xml`).

4. **Mode dry-run par défaut.** Cohérent avec les autres
   importers ColleC : `archives-tool importer-xml fichier.xml`
   simule par défaut, affiche le delta calculé, demande
   `--no-dry-run` pour appliquer. Évite les écrasements
   accidentels.

### Granularité de la contribution

L'unité d'export/import suit la convention déjà en place :

- **Une collection** = un fichier DC XML (existant).
- **Un item** = une notice + ses fichiers + leurs ALTO (futur).
- **Un fonds** = une arborescence de fichiers, potentiellement
  gérée comme un dépôt git autonome.

Le contributeur édite à la granularité qui convient à sa tâche :
quelques fiches au coup par coup, ou un fonds entier en
campagne d'édition critique.

## Workflow git (avancé)

Pour les chantiers d'édition distribuée à plusieurs
contributeurs (typique d'une édition critique collaborative), on
peut exposer un dépôt git d'une collection ou d'un fonds.
Pattern :

1. ColleC exporte régulièrement le fonds en arborescence XML
   (DC, ALTO, TEI) dans un dépôt git (GitLab Huma-Num par
   exemple).
2. Contributeurs externes clonent, créent une branche, éditent
   dans Oxygen ou VSCode, commitent, poussent.
3. Pull request / merge request acceptée par un mainteneur du
   fonds.
4. Webhook GitLab → endpoint `/api/git/synchroniser` de ColleC
   ré-importe les changements du merge dans ColleC, avec
   `modifie_par = "git:<user>"` dans le journal.

Coût : un webhook + un endpoint d'import git + tests. Mais
**aucune nouvelle dépendance majeure** — ça réutilise les
importers de fichiers structurés. À ouvrir uniquement si un
projet concret en a besoin (édition critique collaborative
d'envergure).

## Cas TEI spécifique

C'est le cas qui justifie le plus naturellement ce mode. Quand
un chantier de transcription savante démarre sur un fonds :

1. ColleC produit un **TEI initial** depuis les ALTO + métadonnées
   item, par un nouvel exporter `exporters/tei.py` (à concevoir
   le jour venu). Squelette TEI propre, sans encodage savant
   automatique (`<persName>`, etc. — l'humain les pose).
2. Le philologue récupère le TEI, l'enrichit dans Oxygen
   (encodage entités, apparat critique, normalisations,
   commentaires éditoriaux).
3. ColleC ré-importe le TEI enrichi. Le delta est appliqué : les
   champs métadonnées item qu'on retrouve dans `<teiHeader>` sont
   synchronisés, le contenu transcrit lui-même est stocké dans
   un nouveau champ `Item.tei_chemin_relatif` ou dans une table
   dédiée.

C'est aussi le scénario qui justifierait à terme un **moteur XML
dédié pour TEI** en parallèle de SQLite.

## Stockage et rendu TEI : a-t-on vraiment besoin d'un moteur XML séparé ?

**Question préalable à toute décision technique.** Le pattern
hybride canonique en DH (ColleC SQL + moteur XML séparé pour TEI
+ portail) suppose que **XQuery apporte une valeur incontournable**
sur le corpus considéré. C'est vrai pour les très gros corpus
textuels avec des requêtes analytiques complexes (concordances
cross-corpus, statistiques structurelles, jointures sémantiques
profondes). C'est **beaucoup moins évident** pour un usage TEI
modeste où les besoins se résument à :

- Stocker et versionner les transcriptions TEI.
- Les afficher dans une interface de lecture.
- Permettre une recherche plein texte dans leur contenu.
- Les exporter vers d'autres formats (HTML, PDF, ePub).

Pour ce périmètre, **l'option stay-in-stack est considérablement
plus simple** et respecte le principe du `CLAUDE.md` (« aucun
format d'interchange n'est promu en stockage natif »).

### Option par défaut : TEI dans ColleC, sans moteur séparé

Stocker les fichiers TEI sur disque comme on stocke les ALTO,
référencés par un champ `Item.tei_chemin_relatif` (similaire à
`ocr_chemin_relatif`). Indexer le texte pertinent dans FTS5 (en
extrayant via `lxml` le contenu textuel des balises principales).
Parser via `lxml` côté Python pour les transformations et
l'affichage. **Aucune nouvelle dépendance**, ColleC reste source
de vérité unique.

Le rendu côté consommateur (portail, site statique, liseuse
ColleC) se fait alors par deux voies non-exclusives :

- **CETEIcean** : bibliothèque JavaScript ~30 Ko qui transforme
  un TEI en HTML dans le navigateur via custom web components.
  Aucun backend XML, le fichier TEI est servi statiquement, le
  rendu se fait à l'affichage. Léger, autonome, fonctionne pour
  la consultation. Limite : pas de recherche cross-fichiers, pas
  de query XQuery, juste de l'affichage.
- **Static site generation depuis TEI** : un script (XSLT ou
  Python+lxml) transforme les TEI en HTML/Markdown au build, le
  site produit est purement statique. Aucun moteur XML en
  production, juste au build. Cohérent avec le pattern
  `sites-statiques-future.md` qu'on a déjà acté. Quarto a un
  support TEI émergent qu'on peut suivre.

Sacrifice de cette voie : **pas de XQuery**. Les requêtes
hiérarchiques complexes (« tous les `<persName>` dans des
`<div type="article">` entre 1974 et 1976 ») deviennent du Python
plutôt que de l'XQuery. Faisable mais plus verbeux. Acceptable
tant que ces requêtes sont rares ou faisables une à une plutôt
qu'en flux.

### Option « moteur XML séparé » : si l'usage le justifie vraiment

À ouvrir uniquement quand un chantier TEI **d'envergure
réelle** émerge — édition critique multi-institutions, corpus
volumineux, équipe DH avec compétences XQuery, requêtes
analytiques en flux. Critère pratique : si vous vous surprenez à
écrire le même Python d'extraction TEI pour la cinquième fois,
c'est peut-être le signe.

Le pattern hybride canonique devient alors :

```
ColleC (SQLite)         Moteur XML (eXist / BaseX)        Interface
  catalogue                transcriptions TEI                 publique
  + images IIIF            + apparat critique                 (TEI Publisher,
       │                          │                            MaX, EVT,
       └──────────────────────────┴──────────────────────────  custom)
                                  │
                          Portail public consommateur
```

**Trois familles d'outils à considérer**, à des niveaux
d'abstraction différents :

#### Moteurs bas-niveau

- **eXist-db** : plus ancien (~2000), plus mature, communauté
  plus large, plus de modules tiers. Plus lourd (Java, beaucoup
  de features embarquées), un peu plus lent sur les très gros
  corpus.
- **BaseX** : plus récent (~2005), plus léger, plus rapide,
  XQuery 3.1 plus avancé, écosystème en croissance. Communauté
  plus académique-européenne. Moins de modules tiers.

#### Frameworks de publication TEI (haut niveau)

- **TEI Publisher** (sur eXist-db) : la référence mondiale pour
  publier des éditions critiques TEI. ~10 ans, beaucoup d'éditions
  produites avec, stack documentée, génération ePub/PDF, viewer
  IIIF intégré, communauté TEI Consortium derrière. **L'option
  safe et éprouvée pour un projet TEI sérieux.**
- **MaX** ([dépôt GitLab Huma-Num](https://gitlab.huma-num.fr/estrades/max/max),
  forké du projet MRSH Caen) : interface de lecture TEI/EAD sur
  BaseX 10.4+. Projet jeune (création janvier 2024, ~1000 commits),
  actif, intégré au paysage français Huma-Num. À surveiller
  sur 12-24 mois pour validation par l'usage. Si MaX se confirme,
  c'est le pendant français de TEI Publisher.
- **EVT (Edition Visualization Technology)** : projet italien
  (Pise), tourne **entièrement côté client** sans backend.
  Spécialisé éditions critiques avec variantes textuelles,
  apparat critique, traductions parallèles. UI typée recherche
  philologique pointue. Autonome.

#### Approches sans base, juste pour la publication

- **CETEIcean** (déjà cité dans l'option par défaut) : marche
  aussi dans le cas « j'ai beaucoup de TEI mais je veux juste
  les publier ». Sans XQuery, sans backend.
- **TEI Stylesheets** + XSLT statique : la transformation
  classique de la communauté TEI, tournant en CLI. Sortie HTML
  ou autre. Convient pour un build statique.

### Recommandation finale, hiérarchisée

1. **Par défaut, rester stay-in-stack** : TEI dans ColleC
   (fichiers sur disque + FTS5 + lxml côté Python), rendu via
   CETEIcean côté client ou via static generation au build.
   C'est probablement le bon choix pour les 5 prochaines années
   à votre échelle.
2. **Si l'usage TEI s'intensifie sans devenir massif** : faire
   un audit honnête des requêtes qui font mal en Python. Si
   c'est < 10 requêtes par mois, garder stay-in-stack. Si c'est
   plus, envisager une bascule.
3. **Si l'usage TEI devient massif et XQuery indispensable** :
   - Premier choix : **TEI Publisher sur eXist** — mature,
     documenté, communauté mondiale, le standard de fait.
   - Second choix : **BaseX + MaX** si MaX s'est confirmé
     entre-temps, par alignement avec l'écosystème français
     Huma-Num. Penchant léger pour cette voie côté Hugo si MaX
     mûrit comme attendu.
   - Cas marginal : **EVT** si le projet est spécifiquement une
     édition critique avec variantes complexes.

**Surveillance prioritaire à exercer dans les 12-24 mois** :
maturité réelle de MaX (en discuter avec l'équipe Estrades, la
MRSH, ou les premiers utilisateurs), évolution du support TEI
dans Quarto (qui pourrait dispenser carrément du moteur XML
séparé pour la partie publication), retours d'usage de
TEI Publisher dans la communauté francophone.

**Décision actuelle non prise.** Les décisions techniques de
ColleC restent agnostiques : on produit du XML conforme aux
standards, n'importe quel moteur ou approche peut le consommer.
La bonne décision se prendra le jour où un chantier TEI concret
émergera, avec une volumétrie et des besoins de requêtes
mesurables.

## Roadmap

### V1.x — Pré-requis techniques

- **Introduction d'`id_persistant`** sur les entités
  catalographiques (`Fonds`, `Collection`, `Item`, `Fichier`).
  Migration Alembic, génération UUID/ULID à la création,
  sérialisation dans les exports XML.
- **Round-trip Dublin Core** : étendre l'exporter DC existant
  pour qu'il inclue les `id_persistant`, écrire l'importer
  symétrique (`archives-tool importer-xml fichier.xml`) avec
  dry-run par défaut + détection de delta + application via
  services métier.
- **Tests de régression** lossless : exporter une collection,
  ré-importer, ré-exporter, vérifier que le second export est
  identique au premier.

### V2 — Extension à d'autres formats

- **Round-trip ALTO** : un contributeur peut modifier un ALTO
  (correction manuelle de mots à basse confiance par exemple)
  et le ré-importer pour ré-indexer.
- **Round-trip xlsx** (l'exporter xlsx existant gagne son
  importer symétrique, complémentaire de l'importer de profils
  YAML qui sert au démarrage).

### V2-V3 (conditionnel) — Workflow git

- Endpoint d'import depuis git + webhook.
- Convention de structure du dépôt git d'un fonds.
- Documentation utilisateur.

### V2-V3 (conditionnel TEI) — TEI stay-in-stack

Le scénario par défaut, à activer au premier chantier TEI réel :

- Champ `Item.tei_chemin_relatif` (similaire à
  `ocr_chemin_relatif`).
- Exporter TEI initial (depuis ALTO + métadonnées) via
  `exporters/tei.py`.
- Indexation FTS5 du contenu TEI (extraction lxml des balises
  pertinentes).
- Rendu CETEIcean dans la liseuse ColleC ou dans le site
  statique généré.
- Round-trip via les patterns déjà acquis (delta, verrou
  optimiste, journal).

### V3+ (conditionnel et seulement si l'usage TEI explose) — Moteur XML séparé

À ouvrir uniquement si l'usage TEI dépasse ce que le
stay-in-stack peut servir confortablement (volumétrie massive,
XQuery indispensable en flux) :

- Choix entre TEI Publisher sur eXist (référence mondiale,
  mature), BaseX + MaX (si MaX s'est confirmé), ou EVT (cas
  édition critique avec variantes).
- Pipeline TEI ColleC → moteur XML (export périodique ou
  synchronisé).
- Synchronisation bidirectionnelle (ré-import des TEI enrichis
  dans ColleC).
- Articulation avec le portail public (qui peut soit consommer
  via le moteur XML, soit garder les TEI statiques selon
  l'architecture retenue).

## Pièges à éviter

- **Ne pas ouvrir le round-trip avant d'avoir les
  `id_persistant`.** Sans clés stables, ré-import = duplication
  ou conflit silencieux. Pré-requis bloquant.
- **Ne pas faire de bidirectionnel automatique en V1.x.** Le
  contributeur exporte, édite, re-soumet manuellement. Pas de
  sync continue, pas de webhook. Trop tôt.
- **Ne pas accepter d'import qui n'est pas passé par un export
  ColleC.** Le format est strictement défini par les exporters ;
  un fichier XML construit à la main hors workflow ne passe pas
  l'import (validation contre schéma + présence des
  `id_persistant`). Sinon on ouvre la porte à des entrées
  malformées difficiles à diagnostiquer.
- **Ne pas introduire de moteur XML séparé (eXist, BaseX, autre)
  avant que l'usage TEI ne le justifie réellement.** Le pattern
  stay-in-stack (TEI dans ColleC + CETEIcean ou static
  generation) couvre largement les usages modestes. Audit
  honnête des requêtes avant de basculer.
- **Ne pas confondre « accessibilité de l'outil XML » avec
  « accessibilité au novice absolu ».** Public cible = DH-formé,
  pas n'importe quel utilisateur. Documenter ça honnêtement dans
  les guides.

## Décisions à conserver

- **Trois modes de contribution externe** coexistent : UI web,
  API Python, fichiers structurés. Chacun pour un public et un
  geste.
- **Round-trip des exporters comme principe fondateur.** Ce que
  ColleC exporte, il doit pouvoir le ré-ingérer.
- **`id_persistant` comme pré-requis** technique au mode
  fichiers structurés.
- **Dry-run par défaut** sur tous les imports, comme les
  exporters et importers existants.
- **Workflow git en option, conditionnel à un projet concret.**
- **Stay-in-stack par défaut pour TEI** : fichiers TEI sur
  disque + FTS5 + lxml + rendu CETEIcean ou static generation.
  Aucun moteur XML séparé à déployer tant que l'usage ne le
  justifie pas réellement.
- **Moteur XML séparé seulement si chantier TEI massif** : par
  ordre de préférence, TEI Publisher sur eXist (mature, safe),
  ou BaseX + MaX si MaX se confirme dans les 12-24 mois (aligné
  écosystème Huma-Num). Décision actuelle non prise, agnosticité
  préservée.

## Renvois

- [`notebooks-sdk-future.md`](notebooks-sdk-future.md) — mode
  Python pour contributeurs techniques.
- [`deploiement-future.md`](deploiement-future.md) — matrice
  d'identités, gestion des invités contributeurs.
- [`portail-public-future.md`](portail-public-future.md) —
  section *Quand introduire TEI + eXist* (ce doc l'enrichit
  avec MaX et le pattern de moteur XML).
- [`ocr-module-future.md`](ocr-module-future.md) — l'export
  ALTO devient un canal de contribution pour les corrections
  OCR.
