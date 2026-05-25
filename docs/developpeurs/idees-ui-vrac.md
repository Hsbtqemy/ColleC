# Idées UX en vrac — réserve à puiser

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). C'est une **réserve
    d'idées non formalisées** issue d'un brainstorm UX (mai 2026,
    inspiré de l'analyse Tropy + patterns modernes).

    Contrairement aux autres docs `-future.md` qui actent des
    décisions, celle-ci préserve juste les pistes. Pas
    d'engagement, pas de phasage. À puiser au gré des
    opportunités. Pas une référence utilisateur.

## Workflow et marquage des items

- **Étiquettes / tags colorés libres** distincts de
  `etat_catalogage`. Permet le marquage ad-hoc qui sert au
  quotidien (« à vérifier auprès du conservateur », « cas
  litigieux », « relu par Hugo »). Modèle : table
  `Etiquette(id, libelle, couleur)` + junction `item_etiquette`.
  Filtrable, multi-tag par item. Inspiration directe Tropy.
- **« Quick entry » — création rapide en chaîne.** Sous-mode
  pas-à-pas de la création en série V2 : chaque nouvel item
  hérite du précédent (template + valeurs par défaut +
  incrément), saisie au clavier sans aller-retour vers le
  formulaire complet. Utile pour saisir un inventaire papier.
- **Sélections temporaires** sur le tableau d'items via
  cases-à-cocher + actions groupées (exporter la sélection,
  étiqueter, modifier en masse). Vit en `localStorage`, pas en
  base. Couvre 80 % du besoin des « lists » Tropy sans
  introduire un nouveau concept persistant.

## Navigation et découvrabilité

- **Command palette (Ctrl+K étendu).** Aujourd'hui Ctrl+K =
  recherche globale. Pattern moderne (VSCode, Notion, Linear) :
  palette qui combine **recherche + actions** (« créer item »,
  « aller au fonds PF », « lancer un export », « ouvrir la
  liseuse de... »). Fuzzy search sur les commandes disponibles.
- **Aperçu rapide (preview pane).** Dans les tableaux d'items,
  panneau latéral droit escamotable qui affiche un résumé de
  l'item sélectionné sans naviguer. Permet de scanner 20 items
  pour repérer celui qu'on cherche, sans aller-retour. Bénéficie
  de `composer_page_item` existant. Pattern Finder macOS.
- **Quick actions au survol des lignes.** Icônes d'actions
  secondaires apparaissent au hover (dupliquer, modifier l'état,
  étiqueter, supprimer). Peu de code HTMX, gain UX
  disproportionné.

## Cohérences à pousser dans l'existant

- **Édition inline étendue.** L'édition inline avec verrou
  optimiste existe sur Item depuis V0.9.x. Cohérence : la
  généraliser à Collection et à Fonds pour tous les champs
  simples (titre, description, dates). Aujourd'hui, modifier le
  titre d'un fonds demande de naviguer vers
  `/fonds/X/modifier` — un clic sur le titre devrait suffire.
  Mécanique existe, il faut la propager.
- **Auto-complete des vocabulaires.** Quand un champ pointe
  vers un `Vocabulaire` (langue, type COAR, futur auteur de
  dessin), proposer les valeurs existantes au fil de la frappe.
  Endpoint unique `/api/vocabulaires/{slug}/suggestions?q=` +
  petit composant. Prépare aussi le terrain pour le module
  annotations (cf. `annotations-image-future.md`).
- **Historique navigable des modifications.** `ModificationItem`
  existe en base et journalise déjà tout. Aucune UI pour le
  consulter. Onglet « Historique » sur la page item, listant
  qui a changé quoi quand, avec diff des valeurs avant/après.
  Pas de retour en arrière (donc pas de complexité
  transactionnelle), juste de la transparence. Prépare la
  confiance multi-utilisateurs V1.0.

## Pour plus tard, à creuser quand l'usage se stabilisera

- **Mode « items similaires ».** Sur un item, bouton qui
  exécute une recherche par chevauchement (même auteur, même
  date, même type, même fonds). Aide pour déduplication ou
  enrichissement par référence croisée.
- **Mode comparaison.** Deux items côte à côte avec leurs
  métadonnées + leurs images. Tropy ne le fait pas mais Mirador
  oui ; utile pour les doublons ou variantes (deux exemplaires
  d'un même numéro de revue qui diffèrent légèrement).
- **Mode présentation / diaporama de collection.** Parcours
  visuel séquencé d'une collection, utile pour démonstration ou
  validation finale d'un chantier. Cousin de la liseuse mais
  centré items, pas fichiers.
- **Vue graphique exploratoire.** Visualisation des relations
  items ↔ collaborateurs ↔ collections sous forme de graphe
  interactif. Probablement V3 ou jamais — pas évident que ça
  apporte autant qu'un bon tableau filtrable.

## Principes transversaux à garder en tête

Au moment d'implémenter n'importe laquelle de ces pistes :

1. **Ne pas multiplier les concepts du modèle.** Les étiquettes
   colorées sont OK (un concept de plus, sémantiquement clair) ;
   un système de « projets » par exemple ne le serait pas
   (chevauchement avec collections).
2. **Préférer l'augmentation à la prolifération.** Pousser
   l'édition inline existante est mieux que créer un nouveau
   mode d'édition. Étendre Ctrl+K en command palette est mieux
   que créer une nouvelle UI de commande.
3. **Aucune fonction qui demande à l'utilisateur d'apprendre un
   nouveau modèle conceptuel sans payback clair.** Les « lists »
   éphémères de Tropy en sont un exemple — concept en plus,
   valeur faible chez nous, donc on s'en passe en faveur de la
   sélection multi-cases qui ne demande rien.

## Favoris si on devait piocher 3

Par ordre de rapport valeur/coût :

1. **Étiquettes colorées** — workflow fluide, table simple,
   filtre natif.
2. **Édition inline étendue à Collection et Fonds** — pure
   cohérence, peu de code, gain quotidien.
3. **Quick actions au survol** — petit, visible, sympa.

## Renvois

- Plan de chantier (création en série, vue Avancement) :
  `plan-de-chantier.md`.
- Annotations image (l'auto-complete de vocabulaires prépare
  son terrain) : `annotations-image-future.md`.
- Module annotations / templates par type d'item (idée Tropy
  écartée pour l'instant mais à reconsidérer si l'autocomplete
  vocabulaires en révèle le besoin).
