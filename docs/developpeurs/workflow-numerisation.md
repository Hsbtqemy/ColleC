# Workflow amont — numérisation, post-traitement, OCR

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur l'articulation
    entre les outils amont (scanners, ScanTailor, ABBYY FineReader,
    pdfalto) et ColleC.

    Tenue à jour au fil des sessions. Pas une référence utilisateur
    directe (un guide utilisateur pourra être dérivé en V2 quand
    la chaîne sera stabilisée par l'usage réel).

## Principe directeur

**ColleC n'est pas un éditeur d'images ni un moteur d'OCR**, et
n'a aucune ambition de le devenir. Ces fonctions existent en
outils matures, spécialisés, gratuits ou bien rodés. Compétir y
serait absurde et hors scope.

Mais ColleC peut intervenir **bien plus tôt que la fin de la
chaîne**, parce qu'il sait gérer des items sans fichier (vu dans
le seeder de démo) et parce que le positionnement « espace de
travail, pas catalogue figé » l'autorise. Le point d'entrée
optimal dépend du scénario de départ — voir plus bas.

## Chaîne canonique en sept étapes

1. **Constitution intellectuelle.** Inventaire papier ou tableur
   du fonds, identification des unités catalographiques. Peut se
   faire avant toute numérisation, à partir de l'objet physique ou
   d'un inventaire reçu d'une autre institution.

2. **Préparation matérielle.** Tri, dépoussiérage, éventuel
   démontage de reliure. Hors numérique.

3. **Numérisation (capture).** TIFF 16-bit haute résolution
   (400-600 DPI pour scanner plat, plus pour caméra de table),
   conservation des **masters bruts** sur une racine séparée
   jamais touchée ensuite. Outils selon le matériel :
   - **Scanner plat** : VueScan, logiciel constructeur.
   - **Scanner spécialisé livre** : BookEye, Atiz, ScanRobot.
   - **Caméra de table** : DSLR + logiciel constructeur, ou
     Capture One pour les workflows pro.

4. **Post-traitement images.** Recadrage, redressement (deskew),
   conversion vers dérivés JPEG ou JPEG2000.
   - **Outil de référence open-source** : **ScanTailor Advanced**
     (deskew automatique, détection de marges, traitement en lot
     d'un numéro entier en quelques minutes).
   - **Cas spéciaux** : GIMP, Photoshop, Affinity Photo pour
     retouches manuelles, restauration, cas pathologiques.
   - **Pour les pros** : Capture One, DxO PhotoLab.

5. **OCR.** Sur les images post-traitées (la qualité d'OCR
   dépend directement de la qualité du post-traitement, jamais
   l'inverse).
   - **ABBYY FineReader** est l'outil principal pour les
     chantiers natifs. Layout analysis de qualité industrielle
     (détecte correctement colonnes, illustrations, légendes,
     tableaux — crucial pour les revues à mise en page complexe
     type Por Favor), sortie ALTO conforme native, qualité OCR
     supérieure aux alternatives sur corpus européens. Commercial.
   - **pdfalto** ([dépôt GitHub](https://github.com/kermitt2/pdfalto),
     GPL2, maintenu par Patrice Lopez) pour les **corpus PDF
     externes déjà OCRisés** — typiquement reçus depuis Nakala
     ou d'une autre institution. **Ne fait pas d'OCR** : extrait
     l'ALTO depuis un PDF qui contient déjà un text layer. Évite
     le re-OCR coûteux quand l'OCR d'origine est exploitable.
   - **Sortie canonique : ALTO XML** (avec coordonnées des mots,
     ordre de lecture, scores de confiance par mot). PDF/A avec
     text layer en sortie secondaire pour la liseuse PDF Lot 2
     côté ColleC. Hors ABBYY/pdfalto, tout outil OCR produisant
     un ALTO conforme (Tesseract, Transkribus pour manuscrit
     ancien) est acceptable — ColleC est agnostique sur l'outil,
     contrat ALTO uniquement.
   - **Pour les cas difficiles** (manuscrits, polices anciennes,
     mises en page complexes) : ABBYY FineReader (payant) ou
     Transkribus (paléographie, payant en lot mais qualité
     incomparable).
   - **Post-correction** : manuelle, éventuellement assistée
     (recherche-remplacement sur erreurs récurrentes).

6. **Rattachement à ColleC.** Point d'entrée principal de
   l'outil : `archives-tool importer` (avec profil YAML v2) ou
   rattachement manuel via l'UI. ColleC indexe en base, génère
   vignettes/aperçus via `archives-tool deriver`, indexe en FTS5.

7. **Enrichissement catalographique dans ColleC.** Saisie des
   métadonnées complémentaires, annotations spatiales (voir
   `annotations-image-future.md`), vérifications de cohérence
   (`archives-tool controler`), puis export (Dublin Core, Nakala,
   xlsx).

## Trois racines distinctes

Discipline à suivre dès maintenant pour éviter le casse-tête de
versionnement des fichiers (que la V3 prévoit d'aborder mais qui
est aujourd'hui un trou).

```yaml
# config_local.yaml
utilisateur: "Hugo"
racines:
  masters: D:/Archives/masters       # TIFF bruts, jamais modifiés
  derives_travail: D:/Archives/scans # Sortie de ScanTailor, vu par ColleC
  vignettes: D:/Archives/miniatures  # Généré par archives-tool deriver
```

- **`masters`** : sortie directe du scanner. Sauvegarde lourde
  obligatoire. Jamais référencé par ColleC. Sert de filet de
  sécurité — toute retouche se régénère depuis là.
- **`derives_travail`** : sortie de ScanTailor (recadré, redressé,
  format de travail). **C'est ce que ColleC voit comme « les
  fichiers » de l'item.** Tous les `Fichier` en base pointent ici.
- **`vignettes`** : dérivés générés par ColleC lui-même via
  `archives-tool deriver appliquer` (vignettes 300 px + aperçus
  1200 px). Reconstructibles sans perte. Peut vivre sur un
  stockage moins fiable (NAS lent, cache).

**Règle absolue : toute retouche d'image se fait avant le
rattachement à ColleC.** Sinon on crée une ambiguïté
(« le fichier en base correspond-il au master, au pré-retouche
ou au post-retouche ? ») que rien ne tranche aujourd'hui.

Si re-édition nécessaire après rattachement :

1. Régénérer le post-traitement depuis le master.
2. Écraser dans `derives_travail`.
3. Lancer `archives-tool deriver appliquer --force` sur l'item
   concerné.

ColleC invalide déjà automatiquement les dérivés au renommage
(`derive_genere = False` après chaque rename FS dans
`renamer/execution.py` et `renamer/annulation.py`), le pattern
est cohérent.

## Deux scénarios d'entrée dans ColleC

Quand ColleC intervient dépend du point de départ.

### Scénario A : numérisation native

Vous scannez vous-mêmes un fonds physique encore non numérisé.

- ColleC entre **dès l'étape 1** : héberge l'inventaire (items
  sans fichiers), sert de plan de chantier (« tout le numéro 47
  reste à scanner »).
- Étapes 3-4-5 conduites en outils dédiés, **hors ColleC**.
- Étape 6 : `archives-tool importer profil.yaml` rattache les
  fichiers post-traités aux items pré-créés.
- Étape 7 : enrichissement.

Workflow idéal — ColleC suit l'avancement, on voit les trous,
le travail reste séquencé proprement.

### Scénario B : reprise de fonds existant

Vous héritez d'un disque dur de TIFF en vrac + un tableur Excel
pas tout à fait à jour. Cas fréquent dans les transferts entre
institutions.

- ColleC entre **plus tôt** : import des TIFF bruts + du tableur
  pour faire l'état des lieux.
- `archives-tool controler` détecte doublons par hash, items sans
  fichier, fichiers orphelins.
- Une fois la photographie posée : ScanTailor ciblé sur ce qui en
  a besoin, relance `archives-tool deriver`, suite normale.
- Étape 7 : enrichissement.

Workflow récupération — ColleC sert d'abord à diagnostiquer, puis
à piloter la complétion.

## Cas concret : Por Favor

1. **Inventaire** : liste papier ou tableur des numéros parus
   (date, n°, pagination) → import direct dans ColleC en items
   peu remplis → tableau de bord du chantier.
2. **Numérisation par numéro complet** (~40-80 pages chacun) en
   TIFF 600 DPI dans `masters`.
3. **Post-traitement** : un numéro entier passé en lot dans
   ScanTailor (~15 min pour un opérateur exercé), sortie JPEG
   2000 ou JPEG haute qualité dans `derives_travail`.
4. **OCR** : pour Por Favor, deux situations selon le matériau :
   - **JPEGs natifs** (chantier de re-numérisation, ou versions
     locales) → ABBYY FineReader en batch sur les JPEGs, sortie
     ALTO direct avec coords pixels.
   - **PDFs Nakala existants déjà OCRisés** → pdfalto sur chaque
     PDF, puis script de split par page et conversion des coords
     PDF → pixels JPEG. Pas de re-OCR.

   Voir [`ocr-module-future.md`](ocr-module-future.md) pour la
   stratégie progressive Phase A (baseline) / Phase B (audit via
   scores de confiance) / Phase C (re-OCR ABBYY ciblée).
5. **Rattachement** : `archives-tool importer profil_pf.yaml`
   par numéro.
6. **Enrichissement** : annotations des dessins (Copi, Forges,
   Vázquez de Sola) via le futur module annotation V2.
7. **Export Nakala** : `archives-tool exporter nakala PF
   --fonds PF`.

Traçabilité d'un numéro de bout en bout dans ColleC à partir de
l'étape 6, étapes amont gardent leurs outils naturels.

## Décisions à conserver

- **ColleC ne fait ni édition d'image, ni OCR.** Outils
  spécialisés en amont, point.
- **OCR canonique = ABBYY FineReader** pour le natif (qualité
  supérieure, layout analysis industrielle), **pdfalto** pour
  les PDFs externes déjà OCRisés (évite le re-OCR). ColleC reste
  agnostique : le contrat est « un Fichier a un
  `ocr_chemin_relatif` qui pointe vers un ALTO valide », d'où il
  vient est libre.
- **Trois racines distinctes** : `masters`, `derives_travail`,
  `vignettes`. Discipline opérationnelle dès maintenant.
- **Retouches toujours avant rattachement.** Pas de re-édition
  post-rattachement sans passer par le pipeline complet
  (master → ScanTailor → `deriver --force`).
- **Deux scénarios d'entrée** distincts mais convergents :
  numérisation native (ColleC dès l'inventaire) ou reprise
  (ColleC pour l'état des lieux). Le modèle supporte les deux
  sans modification.
- **Pas d'automatisation amont depuis ColleC.** Ne pas chercher
  à lancer ScanTailor, ABBYY ou pdfalto depuis l'UI — c'est
  tentant mais c'est le début d'une dérive vers un orchestrateur
  de chaîne, hors scope. Des scripts de commodité dans
  `scripts/` (par exemple `preparer_ocr_pf.py` pour orchestrer
  pdfalto + split + conversion sur les 173 PDFs Por Favor) sont
  acceptables — pas des modules.

## Renvois

- Plan de chantier (planification dans ColleC en amont de la
  numérisation) : `plan-de-chantier.md`.
- Module OCR (consommateur des ALTO produits ici, stratégie A/B/C,
  couplage avec annotations) : `ocr-module-future.md`.
- Annotations (étape 7) : `annotations-image-future.md`.
- Portail public (consommateur en aval de l'étape 7) :
  `portail-public-future.md`.
