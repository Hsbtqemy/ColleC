# Décisions d'architecture — annotations d'image

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur l'introduction
    d'un module d'annotation d'image dans ColleC, en vue notamment
    du chantier Por Favor (identification systématique des
    dessinateurs : Copi, Vázquez de Sola, Forges, etc.).

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Positionnement

L'annotation d'image dans ColleC n'est pas une fonction nouvelle
indépendante, c'est **l'indexation poussée à une granularité plus
fine**. Aujourd'hui ColleC indexe au niveau item (FTS5 sur
titre/description/métadonnées) et au niveau fichier (type de page,
ordre, hash) ; le module d'annotation indexera au niveau région
d'image (cette zone = dessin de Copi). Même logique catalographique,
juste une coordonnée spatiale en plus.

Cas d'usage typiques :

- Identifier les dessinateurs (Copi, Forges) au sein d'une page
  qui contient plusieurs auteurs.
- Marquer les caricatures représentant une personnalité (Franco,
  Carrillo) avec un lien vers une fiche d'autorité.
- Signaler des éléments iconographiques récurrents (symboles,
  scènes-types) pour analyse transversale.
- Préparer les corpus exploitables côté portail public (« tous
  les dessins de Copi dans Por Favor entre 1974 et 1978 »).

## Norme retenue : W3C Web Annotations + IIIF

L'annotation se conforme à la spécification W3C Web Annotation
Data Model, qui est aussi le format d'annotation natif d'IIIF
Presentation API 3. Une annotation est un document JSON-LD avec :

- **target** : la cible — un canvas IIIF (= une image) et un
  sélecteur de région (`xywh=x,y,w,h` pour un rectangle, SVG
  selector pour formes complexes).
- **body** : le corps — texte, tag, URI vers une fiche d'autorité.
- **motivation** : `tagging`, `identifying`, `describing`, etc.

Exemple minimal :

```json
{
  "@context": "http://www.w3.org/ns/anno.jsonld",
  "type": "Annotation",
  "target": {
    "source": "https://colle-c.example/canvas/fichier-1234",
    "selector": {
      "type": "FragmentSelector",
      "value": "xywh=234,456,800,600"
    }
  },
  "body": [
    { "type": "TextualBody", "purpose": "tagging", "value": "dessin" },
    { "type": "SpecificResource",
      "purpose": "identifying",
      "source": "https://www.wikidata.org/entity/Q733678" }
  ]
}
```

Ce format est lu nativement par Mirador, OpenSeadragon +
Annotorious, et tous les serveurs d'annotation standards. Le
choisir garantit une **réversibilité totale** : on peut exporter
vers Recogito ou tout autre outil à tout moment.

## Choix de la bibliothèque d'édition : Annotorious

Distinction importante entre **bibliothèque** et **plateforme** :

- **Annotorious** : *bibliothèque* JS de ~30 Ko, plugin officiel
  pour OpenSeadragon. Sait dessiner et éditer des régions, émet
  et consomme du W3C Web Annotation. Ne gère ni stockage, ni
  auth, ni UI du corps. C'est un crayon.
- **Mirador** : *viewer IIIF complet* (~1-2 Mo) qui intègre
  Annotorious + comparaison multi-fenêtres + plugins. Stockage
  et auth restent à charge.
- **Recogito 2 / TPEN** : *plateformes complètes* avec comptes,
  groupes, workflows, NER, liaisons aux autorités, exports. Une
  seconde application autonome.

**Choix retenu : Annotorious intégré à ColleC.**

L'annotation est de l'**enrichissement catalographique** — même
geste que de remplir le champ « auteur » d'une notice, avec une
coordonnée spatiale en plus. L'externaliser violerait le principe
directeur n°1 (la base locale est la source de vérité), créerait
un deuxième dépôt de vérité à synchroniser, et ferait perdre
l'intégration avec les vocabulaires contrôlés, la traçabilité,
le journal d'opérations et le verrou optimiste.

Recogito reste pertinent pour un futur scénario : chantier
collaboratif inter-institutions avec annotateurs externes refusant
d'apprendre ColleC, livrable scientifique propre, écosystème
Pelagios. Pas le scénario de la prochaine année. La réversibilité
W3C garantit qu'on pourra basculer si besoin.

## Module à construire (sketch technique)

### Modèle

Une table `AnnotationRegion` calquée sur les mixins existants :

```python
class AnnotationRegion(Base, TracabiliteMixin):
    __tablename__ = "annotation_region"

    id: Mapped[int] = mapped_column(primary_key=True)
    fichier_id: Mapped[int] = mapped_column(
        ForeignKey("fichier.id", ondelete="CASCADE"), index=True
    )
    # Sélecteur de région : "xywh=234,456,800,600" ou SVG path.
    selecteur: Mapped[str] = mapped_column(Text)
    selecteur_type: Mapped[str] = mapped_column(
        String, default="fragment"  # "fragment" | "svg"
    )
    # Corps libre : liste de bodies W3C. Permet plusieurs tags +
    # une liaison vers une ValeurControlee.
    corps: Mapped[dict] = mapped_column(JSON)
    motivation: Mapped[str] = mapped_column(
        String, default="tagging"
    )
    # Statut pour la pré-segmentation depuis ALTO :
    #   "auto_candidat" : zone détectée automatiquement, à valider
    #   "valide" : zone confirmée par un humain
    #   "rejete" : faux positif marqué pour ne plus être proposé
    statut: Mapped[str] = mapped_column(
        String, default="valide"  # défaut = création humaine directe
    )
    # TracabiliteMixin apporte cree_par, cree_le, modifie_par,
    # modifie_le, version (pour verrou optimiste).
```

Migration Alembic simple, aucune contrainte sur les autres
tables.

### Routes REST

Quatre endpoints suffisent pour le CRUD :

```
GET    /api/fichiers/{id}/annotations       → liste W3C
POST   /api/fichiers/{id}/annotations       → création
PUT    /api/annotations/{id}                → modification
DELETE /api/annotations/{id}                → suppression
```

Service métier `services/annotations.py` qui sérialise en W3C
au moment du GET et désérialise au POST/PUT. Les annotations
internes sont stockées en SQL (plat, jointures rapides) ; le
W3C JSON est calculé à la volée. Mêmes erreurs partagées que les
autres services (`EntiteIntrouvable`, `FormulaireInvalide`,
`ConflitVersion`).

### UI

Sur la page item (`/item/{cote}`), dans la zone visionneuse :

- Un bouton « Annoter » dans la barre de la visionneuse bascule
  entre mode lecture et mode édition.
- En mode édition, Annotorious s'active sur l'instance
  OpenSeadragon existante (`OpenSeadragon.Annotorious()` en une
  ligne).
- Drag pour dessiner un rectangle ou polygone.
- Popup de formulaire au save : auteur (avec autocomplete sur
  `ValeurControlee`), type (vocabulaire), sujet, note libre.
- Liste des annotations existantes affichée en panneau latéral
  ou dans la cartouche métadonnées.

### Intégration vocabulaires

Le `body` d'une annotation peut référencer une `ValeurControlee`
de la table `Vocabulaire` (entrée « Copi » avec URI Wikidata
Q733678). Toutes les annotations qui citent Copi deviennent
requêtables en une jointure SQL, **et** la fiche d'autorité Copi
peut être enrichie d'attributs (dates de vie, langues, etc.).

Ajout suggéré sur `ValeurControlee` : un champ `uri` optionnel
(VIAF, Wikidata, GeoNames) qui devient le pivot inter-systèmes.

### Export

Au moment de l'export Nakala / publication :

- Sérialiser toutes les `AnnotationRegion` d'un item en un
  unique `annotations.json` (W3C AnnotationCollection avec
  AnnotationPages par canvas).
- Déposer le JSON à côté des images sur Nakala (DOI dédié,
  citation propre type « annotations de Por Favor n°47 »).
- Référencer le DOI annotations dans le manifeste IIIF de l'item.

Granularité : un JSON par item (pas par image). Un numéro de
revue de 60 pages avec quelques centaines d'annotations tient
sous 500 Ko en un seul fichier. Éclatement par-canvas uniquement
si volume pathologique (manuscrit annoté ligne par ligne sur 800
folios — pas notre cas).

## Couplage avec le module OCR

Découvert tardivement dans les discussions (mai 2026) — le module
annotations et le module OCR ([`ocr-module-future.md`](ocr-module-future.md))
sont **structurellement complémentaires**. Ils partagent la même
philosophie (indexer le contenu, à des granularités différentes)
et se renforcent mutuellement.

### Pré-segmentation depuis ALTO `<Illustration>`

ALTO marque les zones d'illustration comme `<Illustration HPOS=
"..." VPOS="..." WIDTH="..." HEIGHT="..."/>` lors de la layout
analysis effectuée en amont par ABBYY (ou autre). Ces rectangles
géolocalisés sont exactement les **zones que l'annotateur voudra
peut-être annoter** (« ce dessin est de Copi »).

Workflow proposé :

1. À l'import OCR, parser chaque ALTO et identifier les
   `<Illustration>`.
2. Créer des `AnnotationRegion` candidates (table étendue avec
   un champ `statut: Mapped[str]` = `auto_candidat` / `valide` /
   `rejete`).
3. Dans l'UI d'annotation, ces candidats apparaissent comme des
   rectangles **pré-tracés en pointillé** à valider/compléter
   (auteur, type, sujet) ou rejeter (faux positif de l'analyse
   de layout).
4. Une fois validé, le statut passe à `valide` et l'annotation
   entre dans le flux normal (indexée, exportable Nakala, etc.).

Énorme économie sur les corpus iconographiques (7000+ scans
Por Favor) — on évite le geste fastidieux de dessiner chaque
rectangle à la souris. L'annotation se réduit alors à
**identification + qualification** (le geste sémantique humain),
plus le tracé géométrique (le geste mécanique).

**Qualité de la pré-segmentation = qualité de l'OCR amont.** Si
le layout analysis ABBYY est bonne, les illustrations sont nettes
et utilisables. Si le layout analysis est faible (OCR ancien),
on aura des faux positifs / faux négatifs — c'est l'un des
critères qui peut motiver une re-OCR ABBYY en Phase C du module
OCR.

### Cas BD : complémentarité indispensable

L'OCR seul est **structurellement incomplet** sur les BDs et
contenus à bulles (cas dominant dans Por Favor : caricatures
signées, planches BD intégrées dans le magazine). Quatre
éléments coexistent :

| Élément | Comportement OCR | Comblement via annotation |
|---|---|---|
| Cadre / panel | Identifié comme `<Illustration>` par layout analysis | Pré-segmentation OK |
| Texte de bulle | Souvent ignoré (zone illustration) ou mal reconnu (police manuscrite) | **Transcription manuelle** par annotateur |
| Onomatopées (BAM!, CRAC!) | Presque toujours perdues (texte stylisé intégré au dessin) | **Transcription manuelle** par annotateur |
| Légende / cartouche hors panel | Bien reconnu, traité comme `<TextBlock>` | OCR seul suffit |

Stratégie : OCR fait ce qu'il sait faire (texte typographique +
pré-segmentation des illustrations), le module annotations
comble le reste. Le geste de transcription manuelle est **ciblé
et opportuniste** — pas une obligation de transcrire toutes les
bulles de Por Favor (chantier titanesque), juste celles qui
comptent pour un projet précis (un chercheur travaillant sur la
satire anti-franquiste transcrit systématiquement les bulles
pertinentes pour son corpus, cumulatif dans le temps).

### Enrichissement de l'index FTS5

Quand le module annotations est en place et que le module OCR
livre l'indexation textuelle, `item_fts` peut gagner une colonne
supplémentaire `annotations_text` agrégeant les contenus textuels
des annotations validées. Une recherche unique sur la barre
globale couvre alors :

- Titre, description, métadonnées (déjà en place).
- Texte OCR (couche OCR).
- Transcriptions manuelles d'annotations (cette couche).

L'utilisateur ne se soucie pas de la provenance — il cherche, il
trouve. Le résultat pointe sur la coord précise (mot OCR ou
annotation transcrite, peu importe).

## Coexistence PDF.js / OSD dans la liseuse

Cas particulier souvent rencontré (Por Favor en tête) : un item
a à la fois des JPEGs (un par page) et un PDF (numéro entier
OCRisé). **Une seule surface d'annotation, l'IIIF/JPEG via OSD +
Annotorious.** Le PDF reste un outil de **lecture continue**
(PDF.js avec `Ctrl+F` natif). Les annotations sont **signalées**
dans la liseuse PDF.js sans pouvoir y être créées ou modifiées.

### Pourquoi une seule surface

- L'annotation est sémantiquement attachée à une région d'image,
  pas à une position dans un PDF.
- Le standard W3C Web Annotation + IIIF référence les canvases
  (= images), pas les pages PDF.
- Une seule source de vérité = pas de divergence possible.
- Séparation claire des intentions : PDF = lecture continue,
  OSD = examen précis et édition.

### Patterns UX pour la coexistence

Trois patterns s'empilent dans la liseuse PDF.js :

1. **Indicateurs visuels par-dessus le PDF.** Pour chaque page
   affichée, on superpose des petits marqueurs (pastilles
   colorées discrètes) aux positions des annotations existantes
   sur le JPEG correspondant. La conversion coord-JPEG →
   coord-PDF est immédiate (facteur d'échelle inverse de celui
   utilisé à l'import OCR). Lecture seule dans cette vue.
2. **Survol pour aperçu.** Hover d'un marqueur → popup léger
   avec le contenu textuel de l'annotation (« transcription bulle
   Copi : *Je ne suis pas mort* »).
3. **Click pour annoter.** Click sur une zone vide (ou bouton
   « annoter cette page ») → bascule vers OSD sur le JPEG
   correspondant, Annotorious en mode édition pré-activé sur la
   position cliquée. Pas de friction pour retrouver le scan.

### Storage unifié, double rendu

L'annotation est stockée **une fois** (table `AnnotationRegion`
avec `fichier_id` du JPEG + coords pixels). Elle est rendue par
défaut dans OSD/IIIF natif, et **projetée** dans PDF.js par
transformation à la volée. Aucun doublon, pas de risque de
divergence, et chaque outil reste dans son rôle.

## Roadmap

Placement naturel : **V2** (« confort du chantier vivant ») aux
côtés du refactoring de métadonnées en masse, ou plus tôt en
V1.x si la pression Por Favor le justifie. Auto-contenu, pas de
dépendance sur le reste de la roadmap.

Règle de bascule : si un chantier d'annotation visuelle systématique
démarre sur Por Favor (identification des dessinateurs sur
l'ensemble du fonds), tirer en V1.x ; sinon V2.

Découpage envisageable :

- **V1.x ou V2 — alpha** : modèle + migration + 4 routes REST,
  pas d'UI (alimentation via API ou import scripté).
- **V1.x ou V2 — beta** : intégration Annotorious dans la
  visionneuse OSD existante, mode lecture + édition, popup
  formulaire minimal.
- **V1.x ou V2 — gamma** : autocomplete vocabulaire + URI
  d'autorité + panneau latéral listant les annotations.
- **V1.x ou V2 — delta** : export Nakala (sérialisation W3C +
  dépôt JSON).

Chaque sous-version livrable en 1-2 sessions.

## Décisions à conserver

- **Annotations W3C Web Annotations + IIIF.** Norme, jamais de
  format propriétaire.
- **Annotorious + ColleC**, pas Recogito ni TPEN tant que
  l'usage reste catalographique interne.
- **Stockage SQL plat** dans ColleC (table `AnnotationRegion`),
  sérialisation W3C à la volée. Pas de stockage JSON-LD natif.
- **Une seule surface d'édition (OSD sur JPEG)**, projection des
  marqueurs dans PDF.js en lecture seule. Storage unifié.
- **Couplage explicite avec le module OCR** : pré-segmentation
  depuis `<Illustration>` ALTO (statut `auto_candidat`),
  complémentarité sur les BDs (transcriptions manuelles des
  bulles que l'OCR ne capte pas), enrichissement FTS5 via
  `annotations_text` agrégé.
- **Export par item**, pas par canvas, sauf volume pathologique.
- **Réversibilité préservée** : la norme W3C garantit qu'on peut
  exporter vers Recogito, Mirador, Universal Viewer ou n'importe
  quel viewer IIIF compliant, à tout moment. Le choix de la
  visionneuse côté consommateur (portail public, site statique)
  est totalement indépendant — voir analyse OSD/UV/Mirador dans
  [`portail-public-future.md`](portail-public-future.md).
- **Liaison aux autorités** via URI Wikidata/VIAF sur
  `ValeurControlee` — préserve l'interop avec le futur portail
  et avec les exports Nakala enrichis.

## Renvois

- Portail public consommateur des annotations :
  `portail-public-future.md`.
- Module OCR (couplage explicite via ALTO et FTS) :
  `ocr-module-future.md`.
- Workflow amont (les annotations interviennent après
  rattachement, donc en phase 7 de la chaîne) :
  `workflow-numerisation.md`.
