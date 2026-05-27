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

En mode édition :

- **Drag** sur l'image pour dessiner un rectangle. Le popup d'édition
  s'ouvre.
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

### 4. Exporter

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
