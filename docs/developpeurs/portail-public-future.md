# Décisions d'architecture — portail public consommateur

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur le futur
    portail public alimenté par ColleC.

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Positionnement

À moyen terme, certains fonds catalogués dans ColleC (Por Favor en
tête) ont vocation à alimenter un **portail de revues** public,
utilisable par n'importe qui : navigation par numéros, lecture en
visionneuse, recherche avancée, dossiers éditoriaux thématiques.
Les images et les notices viennent de ColleC ; le portail ajoute
une couche de présentation et de contenu éditorial.

Le portail est un **consommateur** de ColleC, pas une extension.
ColleC reste l'espace de travail catalographique ; le portail
reste un site public en lecture seule alimenté par exports ou
synchronisation. La frontière est nette et préservée par le
principe directeur n°1 du `CLAUDE.md` (« la base locale est la
source de vérité pendant le travail »).

## Évaluation d'eXist-db

eXist-db est une base de données XML native avec XQuery. Évaluée
comme runtime principal du portail.

**Verdict : non, sauf si chantier de transcription TEI.**

eXist gagne quand le **format de travail** est du XML structuré
(TEI pour les textes, EAD pour les inventaires) avec XQuery comme
langage de manipulation principal — c'est l'écosystème naturel
en humanités numériques, et Dublin Core XML devient quasi-natif au
lieu d'être un format de sortie. C'est pertinent **si** un
chantier de transcription/encodage des articles est lancé :
marquer les `<persName>`, `<placeName>`, rubriques, signatures,
variantes de date. Là on débloque « tous les billets de Manuel
Vázquez Montalbán entre 1974 et 1976 mentionnant Franco » avec
une requête XQuery propre — ce qu'un index full-text plat ne
permet pas, parce qu'il ignore la structure sémantique.

Mais pour le cas réel décrit (partager images + métadonnées
catalographiques + contenu éditorial + recherche avancée + site
public utilisable), eXist est un poids mort : déploiement lourd
(JVM), intégration Python pénalisante, écosystème éloigné de la
stack actuelle. La valeur ajoutée XML+XQuery n'est pas mobilisée
si le contenu reste de l'OCR brut + métadonnées DC, parce que
ColleC est relationnel par nature (Fonds 1-N Collection N-N Item
1-N Fichier) et que le XML/DC est un **format de sortie**, pas la
vérité courante.

EAD pour un portail de revues serait par ailleurs surdimensionné :
c'est un standard pour les instruments de recherche
archivistiques, pas pour exposer du contenu. ColleC remplit déjà
80 % du rôle EAD en interne via sa hiérarchie Fonds/Collection/Item.

## Stack recommandée pour le portail v1

Sans encodage TEI, le portail public peut se construire avec une
stack légère et homogène avec ColleC :

- **Backend** : FastAPI ou Django, en lecture seule, alimenté
  par des exports périodiques de ColleC (Dublin Core, CSV) ou
  par une synchronisation directe (DB répliquée en lecture).
- **Recherche** : Meilisearch ou Typesense — moteurs légers,
  excellents en facettage français, déployables en conteneur.
  Bien meilleurs que Elasticsearch pour ce volume / cette équipe.
- **Visionneuse** : choix à arbitrer au moment de la construction
  du portail (cf. section *Choix de la visionneuse* ci-dessous).
- **Images** : servies via IIIF Image API. Soit Nakala (déjà
  intégré côté ColleC), soit un serveur IIIF auto-hébergé
  (Cantaloupe, IIPImageServer) pointant sur ShareDocs.
- **Contenu éditorial** : dossiers thématiques rédigés en
  Markdown directement dans le dépôt du portail, ou via un CMS
  minimal type Wagtail si l'équipe éditoriale a besoin
  d'autonomie.
- **Annotations** : exportées depuis ColleC en W3C Web
  Annotations (voir `annotations-image-future.md`), affichées
  natitement par Mirador ou par OSD + Annotorious.

Cette stack reste dans l'écosystème Python, mobilise des outils
matures et bien documentés, et préserve la cohérence opérationnelle.

## Choix de la visionneuse

Trois candidats sérieux, à des niveaux d'abstraction différents.
Ce n'est pas une décision ColleC mais une décision du projet de
portail — préservée ici pour qu'elle ne soit pas reposée à zéro
le jour venu.

### OpenSeadragon (OSD)

Bibliothèque JavaScript de ~200 Ko, mature, maintenue depuis
plus de 10 ans. Vous instanciez sur un canvas, vous pilotez
tout : navigation, overlays, plugins, UI. Fondation utilisée par
à peu près tous les viewers IIIF sérieux (UV et Mirador
l'embarquent en interne).

Forces : contrôle total, intégration sur-mesure, footprint
minime, écosystème de plugins (Annotorious, GeoJSON, filtres).
**Faiblesse pour le portail** : il faut écrire toute la UI
autour (panneau métadonnées, navigation entre items, partage,
embed). Coût de développement non négligeable si on veut un
résultat poli.

Pertinent quand : on veut une UI portail très spécifique qui
ne ressemble à aucun viewer standard, et qu'on est prêt à
investir dans le dev frontend.

### Universal Viewer (UV)

Application clé-en-main développée par Digirati (~1500 stars,
soutenue historiquement par British Library et Wellcome,
refondue en v4 en TypeScript). Vous lui passez un manifeste
IIIF, il rend toute l'interface : navigation par vignettes,
panneau métadonnées avec champs DC affichés automatiquement,
boutons partager/télécharger/embed, internationalisation.

Forces : aspect « pro de bibliothèque/musée » sans effort de
dev, support multi-format natif (images, PDF, audio, vidéo, 3D
via IIIF), bundle bien intégré.

Faiblesses : bundle nettement plus lourd (plusieurs Mo),
customisation contraignante (config JSON + thèmes prédéfinis,
refonte profonde demande de plonger dans le code TS),
maintenance moins active qu'à son pic.

Pertinent quand : on veut le look « catalogue de bibliothèque
publique » classique, sans investissement dev important. Cible
plutôt grand public que chercheur.

### Mirador

Application complète orientée **espace de travail savant**
(Mellon, Stanford, Harvard, Yale, Princeton, British Library —
financement DH massif sur 15 ans). Mirador 3 est en React,
~3 Mo minifié, actif. Sa singularité : ce n'est pas un viewer
mais un workspace. Vous ouvrez une toile vide, vous y ajoutez
des ressources IIIF qui apparaissent dans des fenêtres
déplaçables/dockables, vous les zoomez et comparez en parallèle,
vous annotez sur chacune, vous exportez votre layout comme un
JSON partageable (cahier de laboratoire numérique).

Forces : multi-fenêtres natif (comparer deux numéros, deux
dessins, deux pages côte à côte), annotations IIIF natives,
recherche IIIF Content Search, plugins riches, communauté DH
active.

Faiblesses : courbe d'apprentissage pour l'utilisateur final
(concept workspace à apprivoiser), bundle lourd, peut paraître
surdimensionné pour un visiteur grand public qui veut juste
feuilleter.

Pertinent quand : cible chercheurs et public cultivé qui
veulent comparer, analyser, citer. Cas de figure d'un portail
Por Favor où les usages typiques incluent « comparer la
couverture de PF n°47 et HK n°200 », « suivre l'évolution de
la signature de Copi sur trois années », « voir un dessin et
sa transcription en regard ».

### Recommandation par cas d'usage

| Cas de figure portail | Recommandation |
|---|---|
| Catalogue grand public, contemplation simple | **Universal Viewer** ou OSD + UI light |
| Lecture savante, comparaison, citation précise | **Mirador** |
| UI portail très atypique avec workflows custom | **OSD + composition maison** |
| Mixte (le plus probable) | **OSD comme défaut** + **Mirador en mode « consultation savante »** activable via bouton |

**Pour Por Favor spécifiquement**, le pattern mixte est mon
penchant : un viewer simple par défaut sur la home (un visiteur
qui découvre la revue ne doit pas être noyé), un bouton
« ouvrir dans Mirador » pour basculer en mode comparatif quand
l'utilisateur sait ce qu'il cherche. Mirador 3 vieillit mieux
qu'UV en 2026 et sa philosophie de comparaison sert
particulièrement bien la matière (numéros à analyser, dessins
à mettre en regard, articles à comparer).

### Interop garantie par le standard

**Tous les viewers cités consomment IIIF + W3C Web Annotations
nativement.** Les annotations produites par ColleC (via
Annotorious dans OSD côté éditeur) sont consommables
indifféremment par OSD du portail, par UV ou par Mirador, sans
transformation. C'est l'avantage d'avoir tranché en faveur de
ces normes dans `annotations-image-future.md` — la décision
de viewer côté portail est totalement réversible et indépendante
de ce qui est produit côté ColleC.

## Quand introduire TEI + eXist

Le scénario qui justifie la bascule : **lancement d'un chantier
de transcription structurée** des articles d'un ou plusieurs
fonds (typiquement après OCR + correction humaine). Indices :

- On veut interroger le **contenu** des articles avec une
  granularité sémantique (qui, où, quand, à propos de quoi).
- On souhaite produire des éditions critiques ou des corpus
  exploitables par d'autres chercheurs.
- L'équipe a (ou recrute) une compétence TEI.

Dans ce cas, le **pattern hybride** est canonique en humanités
numériques :

```
ColleC (SQLite)        eXist/BaseX (XML/TEI)        Meilisearch
  catalogue              transcriptions               recherche
  + images IIIF          + annotations sémantiques     unifiée
       │                       │                          │
       └───────────────────────┴──────────────────────────┘
                               │
                       Portail public (consommateur)
```

C'est ce que font Gallica, Persée, OpenEdition à leur échelle,
avec leurs propres briques.

**Pour notre échelle, ce pattern n'est cependant pas
automatiquement nécessaire.** Une option **stay-in-stack** où le
TEI reste dans ColleC (fichiers sur disque + FTS5 + lxml + rendu
CETEIcean ou static generation) couvre largement les usages
modestes sans introduire de nouveau service. Le moteur XML
séparé (eXist + TEI Publisher, ou BaseX + MaX) se justifie
uniquement si la volumétrie ou les besoins en XQuery l'imposent.
Analyse détaillée et recommandation dans
[`contribution-fichiers-structures-future.md`](contribution-fichiers-structures-future.md)
section *Stockage et rendu TEI*.

## Décisions à conserver

- **Portail = consommateur**, pas extension de ColleC.
- **Stack légère par défaut** : FastAPI/Django + Meilisearch +
  OpenSeadragon/Mirador + IIIF.
- **Pas d'eXist-db ni TEI tant qu'il n'y a pas de chantier de
  transcription structurée.** Décision réversible dans ce sens
  (on peut introduire eXist plus tard si le besoin se matérialise)
  mais pas dans l'autre (sortir de eXist coûte cher).
- **Si TEI un jour, défaut = stay-in-stack** (TEI dans ColleC,
  rendu CETEIcean ou static), pattern hybride avec moteur XML
  séparé seulement si l'usage TEI le justifie réellement
  (volumétrie, XQuery en flux). Cf.
  `contribution-fichiers-structures-future.md`.
- **Pas de portail dans le repo ColleC** : projet séparé,
  développé indépendamment, alimenté par les exports / synchros
  ColleC. Évite le couplage et préserve la séparation des
  responsabilités.

## Renvois

- Annotations d'image (consommées par le portail) :
  `annotations-image-future.md`.
- Workflow amont (préparation des fonds avant publication) :
  `workflow-numerisation.md`.
- Plan de chantier (planification dans ColleC) :
  `plan-de-chantier.md`.
