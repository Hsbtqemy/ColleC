# Génération de dérivés

Le module `archives_tool.derivatives` produit deux dérivés JPEG par
fichier source :

- **vignette** — côté long 300 px ;
- **aperçu** — côté long 1 200 px.

Lecture via Pillow (formats raster) ou PyMuPDF (PDF, première page
rasterisée à 200 dpi). Les TIFF multi-pages sont rendus sur leur
première frame (comportement par défaut de Pillow).

## Convention de stockage

Les dérivés vivent sous une racine logique dédiée (typiquement
`miniatures` dans `config_local.yaml`), dans un sous-dossier par
taille :

| Source                            | Vignette                          | Aperçu                          |
| --------------------------------- | --------------------------------- | ------------------------------- |
| `scans_revues:HK/01.png`          | `miniatures:vignette/HK/01.jpg`   | `miniatures:apercu/HK/01.jpg`   |
| `scans_archives:FA/A/02.tif`      | `miniatures:vignette/FA/A/02.jpg` | `miniatures:apercu/FA/A/02.jpg` |

Avantages : nettoyage sélectif d'une taille sans toucher aux autres,
mapping facile pour un service web (un préfixe d'URL par taille).

## CLI

Le périmètre est passé via exactement un de quatre sélecteurs
(alignés sur `archives-tool renommer`) : `--fonds` (seul), `--collection`,
`--item`, ou `--fichier-id` (répétable). `--fonds` peut accompagner
`--collection` ou `--item` pour désambiguïser une cote partagée
entre fonds.

```bash
# Tous les fichiers d'un fonds.
archives-tool deriver appliquer --fonds HK

# Une collection (la miroir auto, ou une libre).
archives-tool deriver appliquer --collection HK-FAVORIS --fonds HK

# Pour un seul item.
archives-tool deriver appliquer --item HK-1960-01 --fonds HK

# Pour des fichiers explicites.
archives-tool deriver appliquer --fichier-id 12 --fichier-id 13

# Forcer la régénération (par défaut, derive_genere=True est ignoré).
archives-tool deriver appliquer --fonds HK --force

# Aperçu sans écrire.
archives-tool deriver appliquer --fonds HK --dry-run

# Nettoyer (supprime les dérivés et remet derive_genere=False).
archives-tool deriver nettoyer --fonds HK
```

**Codes de sortie** :

- `0` : tous les dérivés générés (ou existants) sans erreur.
- `1` : au moins une erreur de génération (source absente, format
  non supporté, fonds/collection introuvable, …).
- `2` : erreur d'invocation (périmètre absent ou invalide, base
  introuvable, …).

## Effets en base

Pour chaque fichier traité :

- `Fichier.derive_genere` passe à `True` après une génération réussie.
- `Fichier.largeur_px` et `Fichier.hauteur_px` sont remplis avec les
  dimensions originales s'ils étaient nuls (utiles pour l'UI : ratio
  d'affichage, layout responsive).

`nettoyer` remet `derive_genere=False` et supprime les fichiers JPEG
sous la racine cible.

**Invalidation automatique au renommage** : lorsqu'un batch
`archives-tool renommer appliquer` (ou `renommer annuler`) déplace
un fichier, son `derive_genere` est remis à `False` et ses
`apercu_chemin` / `vignette_chemin` à `NULL`. Les dérivés JPEG
existants ne sont **pas** déplacés (ils gardent l'ancien chemin
sous `miniatures/`) — il faut les régénérer (`deriver appliquer`)
ou les nettoyer (`deriver nettoyer`) avec l'ancien chemin avant
le rename, selon le besoin. Conservateur par défaut : on n'efface
rien automatiquement.

## Modes et formats supportés

| Format source | Comportement                                            |
| ------------- | ------------------------------------------------------- |
| PNG, JPEG     | Pillow direct.                                          |
| TIFF          | Pillow, première frame.                                 |
| PDF           | PyMuPDF rend la première page à 200 dpi.                |
| RGBA          | Composé sur fond blanc avant la conversion JPEG.        |
| L, P, CMYK    | `convert("RGB")` standard de Pillow.                    |

Les formats inconnus de Pillow remontent en erreur dans le rapport.

## Limites V1

- Une seule page par PDF (la première). Les PDF multi-pages perdent
  leurs pages 2+ dans la prévisualisation.
- TIFF multi-pages : seule la première frame est dérivée. Cas usuel
  pour les scans de documents en pages séparées : OK ; cas TIFF
  pyramidaux : à investiguer.
- **Mémoire sur très grosses sources** : Pillow charge l'image
  entière en RAM avant de redimensionner. Un TIFF 60 MP en RGB
  consomme ~200 MB ; avec une copie pour le redimensionnement, prévoir
  jusqu'à ~500 MB de pic par fichier traité. La génération est
  séquentielle, donc on ne multiplie pas ce pic. Au-delà
  (TIFF >100 MP, scans archivistiques très haute résolution),
  envisager pyvips qui travaille en streaming et est listé comme
  alternative dans CLAUDE.md.
- Pas d'optimisation pyvips pour les TIFF lourds. À ajouter si la
  performance devient un goulot.
- Le DPI de rasterisation des PDF est figé à 200 ; ajustable par
  édition de la constante `DPI_PDF` dans `generateur.py`.
