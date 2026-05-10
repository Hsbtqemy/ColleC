# Limites connues

Limitations identifiées de ColleC V0.9.0. Beaucoup peuvent être
levées dans des versions ultérieures — voir
[changelog](changelog.md) et les
[issues GitHub](https://github.com/Hsbtqemy/ColleC/issues).

## Modèle et données

- **Pas de migration automatique depuis V0.5/V0.6.** Le modèle a
  été refondu en V0.9.0 (introduction de `Fonds`, suppression de
  `Collection.parent_id`, ajout de `item_collection`). Les bases
  anciennes nécessitent un ré-import via les profils v2.
- **`Item.metadonnees`** : champ JSON libre, pas de validation
  de schéma. La structure dépend du profil d'import.
- **Pas de versionnage des items** : les modifications sont
  journalisées dans `modification_item` mais l'historique
  granulaire (qui a changé quoi) n'est pas encore exposé dans
  l'UI.

## Formats et conversions

- **EDTF non converti vers ISO 8601** : les dates EDTF
  (`1969?`, `1969/1985`, `192X`) sont **préservées telles
  quelles** dans les exports. Les consommateurs DC/Nakala
  doivent supporter EDTF (Nakala l'accepte).
- **TIFF dans la visionneuse web** : les navigateurs ne supportent
  pas nativement TIFF. La visionneuse propose un fallback
  téléchargement. Les dérivés JPEG (générés par
  [`archives-tool deriver`](../guide/cli/deriver.md)) sont la
  solution recommandée.
- **PDF** : pour la dérivation, seule la première page est
  rasterisée (via PyMuPDF, à 200 dpi). Les PDF multipages
  perdent les pages 2+ dans la prévisualisation.
- **Type COAR non validé** contre la liste officielle. Le rapport
  d'export signale les valeurs hors
  `http://purl.org/coar/resource_type/`, mais l'export n'est
  pas bloqué.
- **Pas de JSON-LD** : prévu pour une session ultérieure
  (contextes COAR et Nakala).

## Système de fichiers

- **Sensibilité à la casse** : sur macOS et Windows, le système
  de fichiers est insensible à la casse par défaut. ColleC
  considère les noms comme sensibles à la casse (cohérent avec
  Linux / serveur de production). Conséquence : un même chemin
  écrit dans deux casses différentes peut entrer en collision
  silencieuse à l'export ou au déploiement.
- **Chemins Unicode (NFC/NFD)** : géré sur macOS via
  `chemin_existe_nfc_ou_nfd`. Des comportements inattendus
  peuvent subsister sur des chemins exotiques (caractères
  supplémentaires Unicode hors BMP).

## Excel et CSV

- **Cellules Excel** : limite de 32 767 caractères par cellule
  (limite Excel native). Les descriptions plus longues sont
  tronquées par Excel à l'ouverture (pas par ColleC).
- **Titres de feuille xlsx** : limite de 31 caractères. Tronqués
  silencieusement, les caractères interdits (`[]:*?/\`)
  retirés.
- **CSV Nakala** : encodage UTF-8 BOM (compatible Excel). Pas
  d'échappement spécial des `;` à l'intérieur des valeurs au-delà
  des règles RFC 4180.

## Performance

- **Bases > 50 000 items** : non testé en production. Les
  contrôles qa et le dashboard peuvent ralentir.
- **Renommage massif** : pour des renames > 5 000 fichiers, le
  rapport Rich peut devenir verbeux. Utiliser `--format json`
  pour parser facilement (à venir).
- **Hash SHA-256 à l'import** : calculés sur le binaire complet,
  ce qui peut être lent pour des fichiers très lourds (TIFF
  >100 MP). En dry-run, les hash ne sont pas calculés.

## Web UI

- **Pas d'authentification ni de gestion de droits.** Conçu pour
  usage local ou réseau interne de confiance.
- **Édition concurrente** : pas de verrou sur les items. Deux
  utilisateurs qui modifient simultanément le même item ont un
  comportement « last write wins ».
- **Édition inline** : les métadonnées s'éditent via formulaire
  de page (pattern PRG). L'édition cellule-par-cellule dans les
  tableaux est prévue mais reportée à V0.9.1+.
- **OpenSeadragon** : la visionneuse riche IIIF/DZI est prévue
  pour une version future. V0.9.0 utilise un `<img>` direct
  pour les formats raster supportés navigateur.

## Fonctionnalités hors scope V0.9.0

- **Dépôt automatique vers Nakala** via leur API : hors scope.
  L'upload du CSV bulk se fait manuellement via l'interface
  Nakala.
- **OCR intégré** : non prévu. Les outils OCR externes
  (Tesseract, Transkribus) doivent être utilisés en amont.
- **Refactoring de métadonnées en masse** (renommer un champ,
  scinder/fusionner) : prévu pour V2 avec aperçu et journal.
- **Vue tableau éditable type tableur** : prévu pour V2 avec
  raccourcis clavier (« feuille de scan »).

## Roadmap

Plusieurs de ces limites peuvent être levées dans les versions
suivantes :

- **V0.9.1** : édition inline, polish de l'UI.
- **V1.0** : stabilisation après usage en production. Pas de
  nouvelle fonctionnalité majeure prévue d'ici là — priorité au
  polish, à la doc et à la robustesse.
- **V2** : refactoring métadonnées en masse, vue tableau
  éditable, intégration Nakala API.
- **V3** : versionnement des fichiers, opérations sur scans
  (rotation, recadrage, scission), OCR, empaquetage distribuable.

Voir [changelog](changelog.md) pour les jalons réalisés.
