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
- **Export par item**, pas par canvas, sauf volume pathologique.
- **Réversibilité préservée** : la norme W3C garantit qu'on peut
  exporter vers Recogito, Mirador, n'importe quel viewer
  standard, à tout moment.
- **Liaison aux autorités** via URI Wikidata/VIAF sur
  `ValeurControlee` — préserve l'interop avec le futur portail
  et avec les exports Nakala enrichis.

## Renvois

- Portail public consommateur des annotations :
  `portail-public-future.md`.
- Workflow amont (les annotations interviennent après
  rattachement, donc en phase 7 de la chaîne) :
  `workflow-numerisation.md`.
