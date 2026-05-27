# Décisions d'architecture — module OCR et indexation textuelle

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur l'ajout
    d'une indexation OCR à ColleC, à partir du format ALTO produit
    en amont (ABBYY FineReader pour le natif, pdfalto pour les
    corpus PDF externes).

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Positionnement

Aujourd'hui ColleC indexe au niveau item (FTS5 sur titre,
description, métadonnées flatten JSON) et au niveau fichier (type
de page, ordre, hash). **Pas le contenu OCR.** Pour les corpus
textuels (revues, périodiques, presse satirique — Por Favor en
tête), c'est une limite forte : un chercheur qui veut tracer
« Franco » à travers 173 numéros ne peut pas le faire aujourd'hui,
il doit naviguer item par item.

Le module OCR vient combler ce trou en exploitant les ALTO
produits en amont par le workflow de numérisation. C'est une
**couche supplémentaire d'indexation**, pas un changement
structurel du modèle. Le format ALTO devient le contrat d'entrée,
identique à celui des images et des PDFs : un fichier supplémentaire
sur disque, référencé par un nouveau champ `ocr_chemin_relatif`
sur `Fichier`.

## Norme retenue : ALTO comme format pivot

ALTO (Analyzed Layout and Text Object) est un format XML
standardisé par la Library of Congress, conçu pour capturer
**à la fois le texte et la structure géométrique** d'une page
OCRisée :

- Hiérarchie `<Page> → <PrintSpace> → <TextBlock> → <TextLine> →
  <String> → <Glyph>` avec coordonnées `HPOS`, `VPOS`, `WIDTH`,
  `HEIGHT` à chaque niveau.
- Éléments parallèles `<Illustration>` et `<GraphicalElement>`
  pour les zones non-texte.
- `<ReadingOrder>` (ALTO 3+) qui capture l'ordre logique de
  lecture, indépendamment de la disposition spatiale (essentiel
  pour les revues multi-colonnes).
- Attribut `WC` (Word Confidence) sur chaque `<String>`, entre
  0 et 1 — exploitable pour l'audit qualité.

ALTO est lisible nativement par Mirador, Gallica, Internet
Archive, et tous les outils de recherche textuelle dans
contexte IIIF. Le choisir garantit l'interop maximale.

**ColleC est agnostique vis-à-vis de l'outil qui produit l'ALTO.**
Le contrat est « un Fichier a un `ocr_chemin_relatif` qui pointe
vers un ALTO valide ». D'où vient l'ALTO (ABBYY, pdfalto,
Tesseract, Transkribus pour le manuscrit ancien si un jour) reste
strictement la responsabilité du workflow amont.

## Outils de production amont

Deux outils couvrent la quasi-totalité des cas dans notre
écosystème :

### ABBYY FineReader (outil principal)

OCR commercial reconnu mondialement pour la qualité de son
analyse de mise en page (layout analysis). Sortie ALTO conforme
native, depuis n'importe quelle source (TIFF, JPEG, PDF avec
text layer, PDF born-digital). Pour les chantiers de numérisation
native (scanner pro → TIFF master → JPEG dérivés → ABBYY → ALTO),
c'est l'outil canonique.

Forces : layout analysis excellente (détecte correctement
colonnes, illustrations, légendes, tableaux), qualité OCR
supérieure sur corpus européens à mise en page complexe,
détection d'ordre de lecture, scores de confiance fiables. Sortie
simultanée possible ALTO + PDF/A avec text layer.

Limites : commercial (licences à gérer), pas open-source.

### pdfalto (cas des PDFs externes déjà OCRisés)

Outil open-source maintenu par Patrice Lopez (auteur de GROBID),
bâti sur Xpdf. **Ne fait pas d'OCR** — extrait l'ALTO depuis un
PDF qui contient déjà un text layer. Cas typique : corpus reçu
sous forme de PDF depuis Nakala ou une autre institution, déjà
OCRisé par un prédécesseur. pdfalto récupère cette OCR existante
sans la refaire, économise du temps machine et préserve la
chaîne d'origine.

Forces : pas de re-OCR, intégré au pipeline, sortie ALTO + fichiers
auxiliaires (annotations, table des matières), licence GPL2,
maintenu activement.

Limites : qualité du résultat = qualité de l'OCR d'origine
(si patchy, on hérite des erreurs). Ne sait rien faire d'un PDF
scanné sans text layer (il faut alors extraire les images via
`pdftoppm` puis passer ABBYY).

### Tableau récapitulatif des chemins

| Source | Outil | Sortie | Notes |
|---|---|---|---|
| JPEG / TIFF (chantier natif) | ABBYY | ALTO direct, coords en pixels | Chemin canonique pour les chantiers neufs |
| PDF avec text layer existant | pdfalto + split par page + conversion coords | ALTO par page, coords converties en pixels JPEG | Cas Por Favor, corpus Nakala existants |
| PDF born-digital | pdfalto | ALTO direct (texte natif, pas de bruit OCR) | Cas marginal |
| PDF scanné sans text layer | pdftoppm + ABBYY | ALTO direct | Cas rare |

## Stratégie progressive en trois phases

Tirée de la discussion sur les corpus à qualité OCR incertaine
(typiquement les fonds hérités d'un prédécesseur ou d'un partenaire
dont la chaîne n'est pas connue).

### Phase A — Baseline pdfalto

Sur un corpus PDF existant (cas Por Favor), on lance pdfalto en
batch, on génère les ALTO, on indexe. Coût quasi nul, valeur
immédiate : la recherche devient possible sur le corpus, même si
la qualité OCR d'origine est inégale. **Pré-requis pour mesurer
la qualité ensuite.**

### Phase B — Audit via scores de confiance ALTO

L'attribut `WC` de chaque `<String>` donne la confiance OCR par
mot. Un petit script Python agrège par page et par item :
moyenne, médiane, pourcentage de mots à basse confiance
(< 0.7 typiquement). Sortie : tableau classant les items du plus
sûr au moins sûr, flag automatique des items prioritaires pour
re-OCR.

```python
# Squelette du script d'audit (~50 lignes)
for item in fonds.items:
    confiances = [w.wc for page in item.pages_ocr for w in page.words]
    moyenne = mean(confiances)
    bas_taux = sum(1 for c in confiances if c < 0.7) / len(confiances)
    print(f"{item.cote}: moy={moyenne:.2f}, %_basse={bas_taux:.1%}")
```

L'audit data-driven évite à la fois la confiance aveugle et le
re-OCR systématique. Priorisation par chiffres.

### Phase C — Re-OCR ABBYY ciblée

Pour les items à confiance basse identifiés en phase B, on
repasse les JPEGs sous ABBYY local. Sortie : ALTO frais avec
coords natives en pixels (encore plus précises qu'après
conversion pdfalto). Le `ocr_chemin_relatif` est remplacé,
l'index FTS5 régénéré. Aucune migration de schéma, aucun
re-import d'images. Les anciens ALTO peuvent être archivés dans
un sous-dossier `_archive` au cas où.

**L'architecture ColleC reste identique** à travers les trois
phases. Un item peut être en phase A et son voisin en phase C,
ColleC s'en moque — la recherche fonctionne uniformément.

## Architecture ColleC

### Modèle de données

```python
class OcrPage(Base):
    id: Mapped[int]
    fichier_id: Mapped[int] = ForeignKey("fichier.id", ondelete="CASCADE")
    numero_page: Mapped[int]              # 1, 2, 3... pour les PDFs multi-pages
    texte_brut: Mapped[str]               # concaténation pour FTS, ordre de lecture respecté
    alto_chemin_relatif: Mapped[str]      # source ALTO sur disque
    largeur_image: Mapped[int]            # pour reconstruire les coords si besoin
    hauteur_image: Mapped[int]
    confiance_moyenne: Mapped[float]      # pour affichage UX et audit
    nb_mots_basse_confiance: Mapped[int]  # pour audit

class OcrMot(Base):                       # optionnel — alternative : parse ALTO à la volée
    id: Mapped[int]
    ocr_page_id: Mapped[int]
    forme: Mapped[str]
    x: Mapped[int]                        # en pixels JPEG, après conversion pdfalto si besoin
    y: Mapped[int]
    w: Mapped[int]
    h: Mapped[int]
    confiance: Mapped[float]
    # index composé sur (forme, ocr_page_id) pour les hits de recherche rapides
```

### Indexation FTS5

Extension de `item_fts` avec une nouvelle colonne `ocr_text`
agrégée par `GROUP_CONCAT` depuis `OcrPage.texte_brut` (pattern
identique à celui déjà en place pour `metadonnees_text`). Triggers
de synchronisation étendus à insert/update/delete sur `ocr_page`.
**L'ordre de lecture ALTO est respecté lors de la concaténation**,
pas l'ordre document XML — crucial pour que les requêtes de phrase
exacte (`"transition démocratique"`) marchent sur les revues
multi-colonnes.

### Surlignage régionalisé (couche 2)

Une route `/api/items/{cote}/hits?q=<terme>` retourne pour chaque
hit la liste `[{page, x, y, w, h, contexte}]`. Le frontend OSD
reçoit ces coords, dessine un rectangle d'overlay, zoome dessus
au click. Mécanique identique à celle utilisée pour les annotations
(table `AnnotationRegion`), réutilisable.

Pour les coords : soit on a peuplé `OcrMot` à l'import (lecture
indexée rapide, coût stockage de quelques Mo par 1000 pages),
soit on parse l'ALTO à la volée à chaque requête (lecture lente,
zéro stockage). **Recommandation : peupler `OcrMot`** — l'usage
de recherche est trop fréquent pour reparser le XML à chaque
requête, et la table reste très accessible sur SQLite (~1.4M
lignes pour Por Favor, indexée sur `forme + ocr_page_id`).

### Affichage des scores de confiance

Bonus UX : afficher dans les résultats de recherche un indicateur
de confiance OCR du hit (« trouvé avec confiance 95 % » vs
« 62 %, possibles erreurs »). Évite à l'utilisateur d'être
surpris quand une page mal OCRisée ne ressort pas comme prévu,
matérialise visuellement les items qui mériteraient une re-OCR.
Petit, transparent, honnête.

## Couplage avec le module annotations

Le module OCR et le module annotations
([`annotations-image-future.md`](annotations-image-future.md))
se complètent naturellement — point découvert tardivement dans
la discussion, à acter explicitement.

### Pré-segmentation pour annotations depuis ALTO

ALTO marque les `<Illustration>` comme régions de dessin/photo,
avec coordonnées géolocalisées. Pour Por Favor (et tout corpus
iconographique), ça donne **gratuitement la liste des zones à
annoter** : voici les 7 rectangles qui contiennent des illustrations
sur cette page, un humain n'a plus qu'à dire « celui-là est de
Copi, celui-là est une caricature de Franco ».

Workflow :

1. À l'import OCR, on identifie les `<Illustration>` de chaque
   ALTO.
2. On les stocke comme **annotations candidates** (table
   `AnnotationRegion` étendue avec un champ `statut`
   = `auto_candidat` / `valide` / `rejete`).
3. Dans l'UI d'annotation, ces candidats apparaissent comme des
   rectangles pré-tracés à valider/compléter (auteur, type,
   sujet) ou à rejeter (faux positif de l'OCR).
4. Une fois validé, le statut passe à `valide` et l'annotation
   entre dans le flux normal.

Économie énorme sur les corpus iconographiques (7000+ scans
de Por Favor) — on ne perd plus de temps à dessiner les
rectangles à la souris.

### Cas BD : complémentarité indispensable

L'OCR seul est **structurellement incomplet** sur les BDs et
contenus à bulles. Quatre éléments coexistent dans une page de
BD type :

| Élément | Comportement OCR | Solution |
|---|---|---|
| Cadre / panel | Identifié comme `<Illustration>` | Pré-segmentation OK |
| Texte de bulle | Souvent ignoré (zone illustration) ou mal reconnu (police manuscrite) | **Transcription manuelle via annotation** |
| Onomatopées (BAM!, CRAC!) | Presque toujours perdues (texte stylisé intégré au dessin) | **Transcription manuelle via annotation** |
| Légende / cartouche hors panel | Bien reconnu, traité comme `<TextBlock>` | OCR seul suffit |

Stratégie : OCR fait ce qu'il sait faire (texte typographique +
pré-segmentation des illustrations), le module annotations comble
le reste (transcriptions manuelles des bulles, ciblées et
opportunistes — pas obligation de transcrire toutes les bulles
de Por Favor, juste celles qui comptent pour un projet précis).

### Enrichissement de l'index FTS5

Quand le module annotations sera en place, `item_fts` gagne une
colonne supplémentaire `annotations_text` agrégeant les contenus
textuels des annotations validées. Une recherche unique sur la
barre globale couvre alors :

- Le titre, la description, les métadonnées (déjà en place).
- Le texte OCR (cette couche).
- Les transcriptions manuelles d'annotations (couche annotations).

L'utilisateur ne se soucie pas de la provenance — il cherche, il
trouve.

## Coexistence PDF.js / OSD dans la liseuse

Cas particulier souvent rencontré (Por Favor en tête) : un item
a à la fois des JPEGs (un par page) et un PDF (numéro entier
OCRisé). Question UX : où annote-t-on, où lit-on ?

**Décision actée** : une seule surface d'annotation, l'IIIF/JPEG
via OSD + Annotorious. Le PDF reste un outil de **lecture
continue** (PDF.js avec `Ctrl+F` natif). Les annotations sont
**signalées** dans la liseuse PDF.js sans pouvoir y être créées
ou modifiées.

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
   PDF affichée, on superpose des petits marqueurs (pastilles
   colorées) aux positions des annotations existantes sur le
   JPEG correspondant. La conversion coord-JPEG → coord-PDF est
   immédiate (facteur d'échelle inverse de celui utilisé à
   l'import OCR). Lecture seule.
2. **Survol pour aperçu.** Hover d'un marqueur → popup léger
   avec le contenu textuel de l'annotation.
3. **Click pour annoter.** Click sur une zone vide (ou bouton
   « annoter cette page ») → bascule vers OSD sur le JPEG
   correspondant, Annotorious en mode édition pré-activé sur
   la position cliquée. Pas de friction pour retrouver le scan.

### Storage unifié, double rendu

L'annotation est stockée **une fois** (table `AnnotationRegion`
avec `fichier_id` du JPEG + coords pixels). Elle est rendue par
défaut dans OSD/IIIF natif, et **projetée** dans PDF.js par
transformation à la volée. Aucun doublon, pas de risque de
divergence.

## Pipeline d'import

### Conventions de nommage

À côté de chaque image, son ALTO avec extension `.alto.xml` :

```
derives_travail/
  por-favor/
    pf-001/
      page-001.jpg
      page-001.alto.xml      ← ALTO companion
      page-002.jpg
      page-002.alto.xml
      ...
      numero.pdf             ← optionnel, garde sa fonction liseuse
```

Le profil d'import YAML déclare le mapping vers ces fichiers
ALTO, comme il fait déjà pour `iiif_url_nakala`. Convention par
défaut : `{stem}.alto.xml` à côté de l'image.

### Script de batch pour Por Favor

`scripts/preparer_ocr_pf.py` — orchestre pdfalto sur les 173
PDFs, split par page, conversion de coords PDF → pixels JPEG,
écriture des ALTO companions à côté des JPEGs. Quelques minutes
de calcul pour tout le fonds. **Outil de commodité, pas module
ColleC** — cohérent avec la règle « ColleC n'orchestre pas la
chaîne amont ».

### Ré-indexation

Une commande `archives-tool importer --mode upsert-ocr` (à
designer) scrute les `ocr_chemin_relatif` mis à jour et
ré-indexe sans toucher au reste. Utile pour la Phase C
(remplacement d'ALTO après re-OCR ABBYY).

## Roadmap

Placement naturel : **V1.x ou V2** selon la pression du chantier
Por Favor. Initialement positionné en V3 dans le `CLAUDE.md`,
ramené plus tôt en V1.x/V2 grâce à l'accélération offerte par
pdfalto (pas de re-OCR massif à organiser, l'OCR existant est
exploitable directement).

### Découpage en sous-versions

- **V1.x/V2 — alpha** : modèle `OcrPage` + migration + indexation
  FTS5 + ingestion ALTO via profil d'import. Phase A pour Por
  Favor. Pas encore d'UI riche.
- **V1.x/V2 — beta** : surlignage régionalisé via OSD (couche 2),
  table `OcrMot`, API hits. UI search enrichie avec snippets.
- **V1.x/V2 — gamma** : audit confiance OCR + script d'audit +
  affichage des scores en UI. Phase B complète.
- **V2 — delta** : couplage module annotations — pré-segmentation
  depuis `<Illustration>`, projection markers PDF.js, FTS
  enrichi d'`annotations_text`.

Phases A et B sont autoporteuses (déjà énorme gain d'usage).
Delta arrive avec le module annotations.

### Volumétrie attendue (Por Favor)

- 173 items × ~43 pages × ~200 mots = ~1.4M mots
- Table `OcrPage` : ~7500 lignes
- Table `OcrMot` : ~1.4M lignes (acceptable SQLite, index
  composé `(forme, ocr_page_id)`)
- FTS5 ocr_text : index agrégé par item, ~25 Mo max
- Total ajout base : sous les 100 Mo, négligeable

Calcul de production : pdfalto + split + conversion = quelques
heures pour tout Por Favor, en une fois.

## Pièges à éviter

- **Ne pas re-OCRiser un corpus dont l'OCR existant est
  acceptable.** Audit phase B d'abord, re-OCR phase C ciblée
  seulement sur les items réellement problématiques.
- **Ne pas mêler le pivot OCR au format SSG.** L'export site
  statique (`sites-statiques-future.md`) consomme les ALTO via
  les coordonnées, mais le frontmatter du site reste neutre vis-à-vis
  de cette donnée — chaque template (Quarto, Hugo) décide comment
  l'afficher.
- **Ne pas valider HTTP les URLs IIIF** à l'import OCR. Trop
  fragile, trop lent.
- **Ne pas oublier le `ReadingOrder` ALTO** dans la concaténation
  pour FTS5. Sans, les requêtes de phrase exacte cassent sur les
  layouts multi-colonnes.
- **Ne pas embarquer ABBYY ni pdfalto dans ColleC.** Restent
  amont, lancés par l'utilisateur ou par un script de commodité.
- **Ne pas dupliquer les annotations entre PDF et JPEG.** Une
  seule surface (OSD), projection dans PDF.js, storage unifié.

## Décisions à conserver

- **ALTO format pivot** entrant. ColleC agnostique vis-à-vis de
  l'outil OCR producteur.
- **Trois chemins de production** : ABBYY direct (JPEG/TIFF
  natif), pdfalto (PDF avec text layer), pdftoppm + ABBYY (PDF
  scanné sans text layer).
- **Stratégie progressive A/B/C** : baseline pdfalto → audit
  confiance → re-OCR ABBYY ciblée. Évite le re-OCR massif
  systématique.
- **Couches 1 et 2 en priorité** (indexation FTS + surlignage
  régionalisé). Couches savantes (NER, textométrie, structure
  éditoriale) sur demande après usage réel.
- **Couplage explicite avec le module annotations** : ALTO
  `<Illustration>` comme seed, transcriptions manuelles
  complémentaires pour BDs, FTS5 enrichi des deux sources.
- **Une seule surface d'annotation (OSD)**, signalement dans
  PDF.js via projection, storage unifié.
- **Pipeline d'import via profil YAML + script de commodité**,
  pas de module orchestrateur ColleC.

## Renvois

- Module annotations (couplage explicite) :
  `annotations-image-future.md`.
- Workflow amont (ABBYY + pdfalto) :
  `workflow-numerisation.md`.
- Sites statiques (consomment les ALTO pour annotations
  publiables) : `sites-statiques-future.md`.
- Roadmap V2 du `CLAUDE.md` racine.
