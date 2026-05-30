# Annotations IIIF

Depuis V0.9.7, ColleC supporte l'**annotation de régions d'image**
conformément au W3C Web Annotation Data Model et à IIIF Presentation
API 3. Cas d'usage typique : identifier les dessinateurs d'une page de
revue qui contient plusieurs auteurs, marquer les caricatures
représentant une personnalité avec un lien Wikidata, signaler des
éléments iconographiques récurrents.

Les annotations sont un **enrichissement catalographique** — pas une
fonction séparée. Même logique que de remplir le champ « auteur » d'une
notice, avec une coordonnée spatiale en plus.

## Workflow

### 1. Définir un vocabulaire avec URIs d'autorité

Avant d'annoter, créer un vocabulaire qui liste les valeurs prévues.
Aller sur `/vocabulaires`, créer un vocabulaire (ex « Dessinateurs »),
puis ajouter ses valeurs.

Pour chaque valeur, renseigner :

- **Libellé** : nom affiché (« Copi »)
- **URI canonique** (optionnel mais recommandé) : URI Wikidata, VIAF
  ou autre référentiel — ex `https://www.wikidata.org/entity/Q733678`

Sans URI, le tag fonctionne mais reste local à ColleC. Avec URI, c'est
un pivot d'autorité utilisable par toute application externe
(portail public, Mirador, Recogito…) et exporté tel quel vers Nakala.

### 2. Annoter sur la visionneuse

Aller sur `/item/<cote>/visionneuse?fonds=<f>` (page catalographique).
Choisir un fichier image dans le panneau gauche (les PDFs et non-images
n'ont pas d'annotation).

Cliquer le bouton **Annoter** en haut-droite du viewer (sous les
contrôles OSD natifs) — il bascule entre mode lecture et mode édition.

En mode édition, deux outils sont disponibles dans la barre en
haut-droite du viewer :

- **▭ Rectangle** (par défaut) : drag sur l'image pour dessiner un
  rectangle aligné.
- **⬠ Polygone** : clic à chaque sommet, double-clic pour fermer la
  forme. Utile pour les caricatures aux contours irréguliers, les
  vignettes BD au cadre non rectangulaire, ou toute zone qu'un
  rectangle englobant entoure trop largement.

Cliquer sur un outil active automatiquement le mode édition (pas
besoin de cliquer « Annoter » d'abord). L'outil sélectionné reste
actif d'un tracé au suivant — pratique pour annoter plusieurs
zones d'un coup.

Après tracé, le popup d'édition s'ouvre :

- **Champ TAG** : taper les premières lettres → suggestions du
  vocabulaire (préchargé). Sélectionner ou taper librement.
- **Champ COMMENT** (en dessous) : note libre optionnelle.
- **OK** : sauvegarde l'annotation.

### 3. Voir les annotations

**Pendant la consultation** :

- Sur la visionneuse, les régions annotées apparaissent en surbrillance.
  Hover affiche le tag.
- Un **panneau latéral** flottant à droite (sous le bouton Annoter)
  liste les annotations du fichier courant. Clic sur une ligne →
  zoom OSD sur la région + ouverture du popup d'édition.

**Sur la fiche notice** (`/item/<cote>`) :

- Section **Annotations IIIF** dans la colonne fichiers du milieu
  liste tous les tags agrégés depuis tous les fichiers de l'item, avec
  leur compte d'occurrences. Libellé cliquable vers l'URI Wikidata si
  renseignée. Permet de voir d'un coup d'œil « qui dessine » dans un
  numéro entier sans ouvrir page par page.

### 4. Enrichir rétroactivement (vocab rattaché après coup)

Cas typique : un fonds a été annoté en tags libres (Annotorious ne
proposait pas encore le vocab parce qu'il n'était pas rattaché). Puis
on rattache le vocab au fonds. Les nouvelles annotations bénéficient
de l'autocomplete + URI Wikidata, mais les annotations existantes
restent en `TextualBody value="Copi"` sans URI.

L'**enrichissement rétroactif** propage les URIs canoniques du vocab
vers les tags libres existants qui matchent (insensible aux accents
et à la casse).

Depuis l'UI :

1. Aller sur `/vocabulaires/<id>` du vocab concerné.
2. Dans la section « Fonds rattachés », cliquer **⤴ Enrichir** sur la
   ligne du fonds.
3. La page de preview liste les matches (annotation #N — tag libre →
   libellé canonique → URI Wikidata cliquable). **Aucune modification
   en base à ce stade.**
4. Relire la liste, puis cliquer **Confirmer l'enrichissement**. Les
   `TextualBody` matchés sont remplacés par des
   `SpecificResource source={id, label}` portant l'URI.

Depuis la CLI :

```bash
# Dry-run par défaut — affiche le rapport, ne touche pas la base.
uv run archives-tool annotations enrichir \
    --vocabulaire dessinateurs --fonds PF

# Appliquer
uv run archives-tool annotations enrichir \
    --vocabulaire dessinateurs --fonds PF \
    --appliquer --utilisateur marie
```

Idempotent : rejouer = no-op (les bodies déjà enrichis sont skippés).
Pourquoi pas une opération automatique au moment du rattachement ? Un
même tag libre peut désigner la mauvaise personne (homonyme, alias)
selon le fonds. Le diff explicite laisse l'utilisateur arbitrer.

### 5. Exporter

```bash
uv run archives-tool exporter annotations <cote_collection> \
    [--fonds <cote_fonds>] [--sortie path.json]
```

Produit un fichier JSON-LD W3C `AnnotationCollection` conforme à la
spec W3C Web Annotation §6.3 + IIIF Presentation API 3. Format
réversible : importable dans Mirador, Recogito, ou tout viewer
respectant la norme.

Pour le dépôt Nakala : déposer ce JSON à côté des images de la
collection, et référencer son DOI dans le manifeste IIIF de l'item.

## Format des annotations

Chaque annotation stockée en base produit un JSON-LD W3C minimal :

```json
{
  "@context": "http://www.w3.org/ns/anno.jsonld",
  "id": "https://colle-c.example/api/annotations/42",
  "type": "Annotation",
  "motivation": "tagging",
  "created": "2026-05-27T14:30:00",
  "creator": "marie",
  "target": {
    "source": "https://colle-c.example/api/fichiers/100",
    "selector": {
      "type": "FragmentSelector",
      "conformsTo": "http://www.w3.org/TR/media-frags/",
      "value": "xywh=234,456,800,600"
    }
  },
  "body": [
    { "type": "SpecificResource", "purpose": "tagging",
      "source": { "id": "https://www.wikidata.org/entity/Q733678",
                  "label": "Copi" } },
    { "type": "TextualBody", "purpose": "commenting",
      "value": "Caricature de Franco" }
  ]
}
```

Le `body` est une liste, on peut combiner tags + commentaires + URIs
d'identification dans une même annotation.

Pour les polygones, le `selector` devient un `SvgSelector` avec un
SVG inline :

```json
"selector": {
  "type": "SvgSelector",
  "value": "<svg><polygon points='120,80 350,90 410,260 200,310 90,180'/></svg>"
}
```

Les deux formes (`FragmentSelector` rectangle + `SvgSelector`
polygone) cohabitent dans une même AnnotationCollection sans
configuration supplémentaire — Mirador, Recogito et Annotorious les
gèrent nativement.

## Bibliothèque côté navigateur

Annotorious 2.7 (plugin OpenSeadragon, ~380 Ko) est greffé sur
l'instance OSD existante via l'événement `visionneuse:pret` émis par
`visionneuse_osd.js`. Pas de chargement supplémentaire sur la fiche
notice ou la liseuse consultation (l'édition d'annotation reste sur
`/item/<cote>/visionneuse`).

En mode lecture seule (`config_local.yaml: lecture_seule: true`),
Annotorious n'est pas chargé du tout (380 Ko économisés) et le bouton
Annoter n'apparaît pas — un futur lot pourra ajouter un mode
consultation pure des annotations existantes.

## Hors scope

- **Annotation de PDFs** : Annotorious cible les images uniquement.
  Annoter un PDF nécessiterait un autre stack (PDF.js + annotations
  natives PDF). Le bouton Annoter est masqué sur les PDFs.
- **Multi-utilisateurs concurrents sur une même région** : le verrou
  optimiste (version) protège contre les écrasements silencieux, mais
  pas de mécanisme de notification en temps réel.
- **OCR + ML pour pré-tagging automatique** : à voir en V2+ si la
  pression du chantier le justifie. La norme W3C ouvre la possibilité.

## Voir aussi

- [Vocabulaires personnalisés](champs-vocabulaires.md) — comment créer
  les valeurs avec URIs d'autorité.
- [CLI exporter](cli/exporter.md) — pour le sous-commande
  `annotations`.
- Spec interne :
  [docs/developpeurs/annotations-image-future.md](https://github.com/Hsbtqemy/ColleC/blob/main/docs/developpeurs/annotations-image-future.md)
  (réservée aux contributeurs, exclue du build).
