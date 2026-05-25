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
- **Visionneuse** : OpenSeadragon (déjà choisi côté ColleC) ou
  Mirador pour la lecture érudite avec comparaison multi-fenêtres.
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
avec leurs propres briques. Pour notre échelle, BaseX peut être
préféré à eXist (plus rapide, plus léger), mais le principe est
identique.

## Décisions à conserver

- **Portail = consommateur**, pas extension de ColleC.
- **Stack légère par défaut** : FastAPI/Django + Meilisearch +
  OpenSeadragon/Mirador + IIIF.
- **Pas d'eXist-db ni TEI tant qu'il n'y a pas de chantier de
  transcription structurée.** Décision réversible dans ce sens
  (on peut introduire eXist plus tard si le besoin se matérialise)
  mais pas dans l'autre (sortir de eXist coûte cher).
- **Si TEI un jour, pattern hybride** : ColleC garde catalogue +
  images, eXist/BaseX héberge les transcriptions, Meilisearch
  indexe l'ensemble pour la façade publique.
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
