# Liseuse de consultation

Mode de lecture distinct du mode édition, conçu pour parcourir un
item page par page sans interface de catalogage. Utile pour
relire une collection, vérifier un fac-similé, ou montrer un item
à quelqu'un sans risque de modification accidentelle.

## Accéder à la liseuse

Trois entrées possibles :

- **Bouton « Mode consultation »** dans le header de chaque page
  qui supporte la liseuse (item, fonds, collection). Sur la page
  item, le bouton ouvre l'item courant. Sur les pages fonds ou
  collection, il ouvre le premier item (cote ASC).
- **URL directe** : `/lire/<fonds>/<cote>` (ex. `/lire/PF/PF-001`).
- Depuis la **page item** en édition, basculer via le bouton
  header (l'URL préserve le fichier courant via `?fichier=N`).

Sur la liseuse, un bouton **« Cataloguer »** dans le bandeau
ramène à `/item/<cote>?fonds=<f>` (mode édition).

## Layout

Trois colonnes fixes :

| Zone | Contenu | Largeur |
| --- | --- | --- |
| Gauche | Cartouche métadonnées (lecture seule) | 280px |
| Centre | Visionneuse (image / PDF / fallback) | flex |
| Droite | Panneau de vignettes (toujours visible) | 200px |

Le bandeau en haut affiche le chip **« Consultation »** (couleur
distinctive bleue), la cote, le titre, et deux jeux de boutons :

- **Page ←/→** : navigue entre les fichiers de l'item courant.
- **Item ←/→** : navigue entre les items adjacents du fonds
  (cote ASC).

Avoir les deux jeux séparés résout une friction historique : avant,
« Suivant » changeait d'item et perdait la page de lecture
courante. Maintenant les rôles sont explicites.

## Visionneuse

Le composant `visionneuse_consultation.html` dispatche selon
l'extension du fichier courant :

- **Image** (JPG, PNG, TIFF, WebP, JP2…) → viewer **OpenSeadragon**
  avec zoom natif, pan, niveaux de détail. Source IIIF Nakala
  préférée (streaming progressif sans téléchargement complet) ;
  fallback aperçu local si dérivé généré ; sinon `<img>` direct.
- **PDF** → viewer **PDF.js** embedded (build legacy + WASM
  OpenJPEG pour décoder les images JP2 typiques des fac-similés
  Nakala). Mode scroll continu : toutes les pages affichées d'un
  bloc, lazy render via IntersectionObserver. Couche texte OCR
  sélectionnable quand le PDF en contient.
- **Autres** (xlsx, audio, vidéo, archives…) → fallback HTML avec
  bouton **« Télécharger ... »** qui pointe :
  - vers la route locale `/item/<cote>/fichiers/<id>?fonds=<f>` si
    le fichier est sur disque,
  - vers `/data/<doi>/<sha>` sur Nakala si le fichier est
    Nakala-only (cas standard pour les exports Nakala).

## Navigation au fil du PDF

Le viewer PDF a sa **propre barre de contrôles** distincte des
boutons Page ←/→ du bandeau :

| Action | Bandeau (entre fichiers) | Barre PDF (entre pages du PDF) |
| --- | --- | --- |
| ← / → | change de **Fichier** | non |
| ‹ N/M › | non | scroll vers la **page** du PDF |
| ⤢ | non | recalcule le zoom largeur |
| − / + | non | zoom in/out |
| Télécharger | non | lien direct vers le PDF original |

Cette séparation surprend parfois (sur un PDF de 40 pages, `←/→`
clavier ne fait pas défiler les pages du PDF mais change le
fichier de l'item) — c'est volontaire : le scope « liseuse =
entre fichiers » reste cohérent quel que soit le format.

## Raccourcis clavier

| Touche | Effet |
| --- | --- |
| **`←`** | Fichier précédent (clic « Page précédente ») |
| **`→`** | Fichier suivant (clic « Page suivante ») |
| **`Esc`** | Retour catalogage (clic « Cataloguer ») |

Skip si le focus est dans un `<input>` / `<textarea>` /
`contenteditable` — vous pouvez sélectionner du texte dans la
couche OCR du PDF sans déclencher la navigation parasite.

## Panneau de vignettes

Toujours visible à droite (contrairement au panneau fichiers de
la page item qui est escamotable). Affiche jusqu'à 100 vignettes
36×48 par item, avec :

- **Numéro de page** sous chaque vignette.
- **Highlight bleu** sur la vignette du fichier courant.
- **Indicateur de saut d'ordre** (`⋯ manque entre 5 et 8`) si la
  séquence `Fichier.ordre` n'est pas continue.

Clic sur une vignette → swap HTMX simultané de trois fragments :
la visionneuse, le bandeau (boutons Page ←/→ rafraîchis), et le
panneau lui-même (highlight déplacé). Pas de reload, l'URL est
mise à jour côté client via `hx-push-url="true"` pour permettre
le bookmark d'une page précise.

## Limites V0.9.3

- **Pas de bascule auto vers l'item suivant** en fin de séquence
  de fichiers. Si vous arrivez à la dernière page d'un item,
  cliquer une fois de plus sur « Page suivante » ne fait rien —
  utilisez « Item → » pour passer à l'item suivant. Choix
  d'utilisation : boutons explicites séparés préférés à un
  enchaînement implicite (l'utilisateur saurait perdu sur quel
  item il est).
- **PDF.js text layer cancellation** : si vous swappez très
  rapidement entre fichiers PDF, la couche texte d'un ancien
  rendu peut brièvement persister au-dessus du nouveau canvas.
  Mineur (200-300 ms), corrigeable V2 si gênant.
- **Cache des assets vendor PDF.js** : si on upgrade pdfjs, faire
  un `npm run vendor` puis Ctrl+F5 pour purger le cache navigateur
  sur `pdf.min.mjs`.
