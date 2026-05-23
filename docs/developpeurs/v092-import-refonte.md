# V0.9.2-import — refonte de l'assistant de mapping

Document interne (exclu du build MkDocs). État : **Phases 1 + 2 + 3
+ 4 livrées 2026-05-23**, refonte complète. Ouvert 2026-05-22 après
le test d'usage F sur fonds PF (Por Favor, export Nakala, 7467
lignes / 173 cotes / 28 colonnes).

## Constat — pourquoi une refonte

V0.9.1 a livré l'assistant d'import et 4 frictions correctives
(F1-F4 dans [`TEST_USAGE_V0.9.1.md`](../../TEST_USAGE_V0.9.1.md)).
Test sur PF montre que **ces correctifs ne suffisent pas pour un
catalogueur non-expert**. Les frictions résiduelles :

1. **Le mapping reste à la charge de l'utilisateur colonne par
   colonne.** 28 selects à 25 options. Pour un export Nakala
   typique, ~20 décisions sont des choix « Métadonnée personnalisée
   (item) » répétés, et 6-7 sont des choix subtils item-vs-fichier.

2. **La distinction `Item.metadonnees` vs `Fichier.metadonnees` est
   structurelle mais invisible dans la donnée.** L'utilisateur n'a
   aucun moyen de deviner que `chiffre` est par-page et `Description`
   par-item sans inspecter son tableur manuellement. Choisir le mauvais
   niveau produit 44 000 warnings de divergence (cf. session #1 sur PF).

3. **Les noms de cible sont techniques.** `type_coar`, `iiif_url_nakala`,
   `__meta__`. L'utilisateur catalogueur n'a pas le vocabulaire interne.

4. **Aucun retour sur le contenu réel des colonnes.** Le nom seul
   ne suffit pas — pour comprendre que `chiffre` contient `1, 2, 3`
   et donc est un numéro de page, il faut rouvrir le tableur.

5. **L'erreur est silencieusement coûteuse.** Une seule case mal
   cochée et tu te retrouves avec un import à reprendre en entier.

Conclusion : l'assistant **demande à l'utilisateur** des décisions
qu'il devrait **analyser tout seul** à partir de la donnée. C'est
inversé.

## 5 propositions, par ordre d'implémentation

### Phase 1 — Foundations (≈ 2h) ✅ livrée 2026-05-23

#### #2 — Échantillons de valeurs inline ✅

À l'upload du tableur, capter pour chaque colonne :

- 3 premières valeurs non-nulles
- valeur la plus fréquente
- nombre de valeurs uniques
- taux de remplissage (% non-null)

Stocker dans une nouvelle colonne JSON
`session_import.colonnes_echantillon` (alembic migration légère,
idempotente comme F3).

L'étape mapping affiche ces échantillons sous le nom de colonne :

```
chiffre                    → [Sélecteur]
  ex. « 1 », « 2 », « 3 » · 7466/7466 remplis · 200 valeurs uniques
```

**Impact** : élimine le besoin de retourner au tableur pour se rappeler
ce qu'une colonne contient. Ressenti immédiat sur tous les imports.

#### #5 — Heuristique nominative enrichie ✅

Étendre `proposer_mapping` dans
[`profils/generateur.py`](../../src/archives_tool/profils/generateur.py)
pour reconnaître plus de patterns de noms de colonnes :

- `filename`, `nom_fichier`, `name` → `fichier.nom_fichier`
- `hash`, `sha`, `checksum`, `empreinte` → `fichier.hash_sha256`
- `iiif`, `info.json` → `fichier.iiif_url_nakala`
- `data_url`, `embed_url`, `preview_url`, `thumb*` → `fichier.metadonnees.<slug>`
- `auteur`, `author`, `creator` → `metadonnees.auteur`
- `editeur`, `publisher`, `éditeur` → `metadonnees.editeur`
- `contributeur`, `contributor` → `metadonnees.contributeur`
- `doi` → `doi_nakala`
- `langue`, `language`, `lang` → `langue`
- `date`, `année`, `year` → `date` / `annee`

Tests fixtures pour chaque pattern.

**Impact** : sur un export Nakala typique, ~70% des colonnes
pré-remplies correctement sans intervention.

### Phase 2 — Intelligence (≈ 3h) ✅ livrée 2026-05-23

#### #1 — Auto-détection par-item vs par-fichier ⭐ killer feature ✅

À l'upload, après détection des colonnes et choix probable de la
colonne cote (heuristique nom ou première colonne ne contenant que
des valeurs uniques au global) :

Pour chaque autre colonne :
1. Grouper les lignes par cote
2. Compter les valeurs distinctes non-null par groupe
3. Statistique sur l'ensemble des groupes :
   - **>90% des groupes ont 1 valeur** → classer **par-item**
   - **>50% des groupes ont >1 valeur** → classer **par-fichier**
   - **mélangé** → laisser à l'heuristique nom

Stocker la classification dans
`session_import.colonnes_echantillon` (mutualisé avec #2).

`cibles_proposees` consomme la classif et propose
`fichier.metadonnees.<slug>` par défaut pour les colonnes par-fichier
(quand granularité=fichier).

UI : afficher l'indice à côté du sélecteur :

```
chiffre                    → [Métadonnée personnalisée (fichier) ▾]
  ex. « 1 », « 2 », « 3 »
  ⓘ détectée par-fichier (varie au sein de chaque cote)
```

**Impact** : 90% des décisions par-item/fichier prises automatiquement
et justifiées. Sur PF : `chiffre`, `hash`, `thumb`, `data_url`,
`embed_url`, `preview_url`, `filename`, `ext`, `num_files` auto-classés
par-fichier. Plus de configuration manuelle pour distinguer.

**Risques** :
- Faux positifs sur colonnes vides ou peu peuplées → seuils ajustables
- Erreur silencieuse si l'utilisateur ne lit pas le hint « détectée
  par-fichier » → afficher l'indice de manière visible

### Phase 3 — Diagnostic intelligent (≈ 1h30) ✅ livrée 2026-05-23

#### #4 — Warnings agrégés et actionnables ✅ (+ T6 dry-run 2026-05-23)

Aujourd'hui : 44 373 lignes « Cote X : divergence sur metadonnees.Y
(garde a, ignore b) ».

Demain : agréger par colonne et par-cote-mal-classée :

```
⚠️ Anomalies détectées (2)

La colonne `chiffre` a 173 valeurs uniques par item (valeurs : 1, 2, 3…).
Elle est probablement propre à chaque fichier, pas à l'item.
[Déplacer en niveau fichier] [Garder en item — toutes les valeurs sauf une seront ignorées]

La colonne `num_files` a 1 seule valeur par item (valeur la plus fréquente : 4).
Cohérent avec un import par-item. OK.
```

Une décision par colonne suspecte au lieu de N par ligne. Réalisable
une fois #1 en place (la classif fournit l'info diagnostique).

### Phase 4 — Refonte UI complète (≈ 4h, optionnelle) ✅ livrée 2026-05-23

#### #3 — Inverser le défaut : tout en métadonnée, opt-in pour les champs structurants ✅

L'étape mapping actuelle = 28 selects à 25 options.

L'étape refondée = 4 questions explicites :

1. **Cote** : « Quelle colonne identifie chaque item ? » (obligatoire, sélection unique)
2. **Granularité** : « Une ligne = un item, ou une ligne = un fichier ? »
3. **Titre** (optionnel) : « Quelle colonne contient le titre des items ? »
4. **Date** (optionnel) : « Quelle colonne contient la date ? »

Tout le reste va en `metadonnees.<slug>` (item ou fichier selon #1).
Un lien « Affiner le mapping » ouvre un mode avancé qui réexpose
l'écran actuel pour les utilisateurs experts.

**Impact** : 4 décisions au lieu de 28. Démystifie complètement
l'assistant pour le non-expert.

**Risques** :
- Perte de granularité pour les utilisateurs avancés → préservée
  par le mode caché
- Migration des sessions existantes → garder l'étape actuelle comme
  "mode avancé" sans changement de session model

## Plan de session V0.9.2-import

| Session | Phase | Effort | Livrable | Statut |
|---|---|---|---|---|
| 1 | Phase 1 (#2 + #5) | ~2h | Échantillons en base + UI, heuristique nominative enrichie | ✅ 2026-05-23 |
| 2 | Phase 2 (#1) | ~3h | Auto-détection par-item/fichier, UI d'indice | ✅ 2026-05-23 |
| 3 | Phase 3 (#4) | ~1h30 | Warnings agrégés + actions [Déplacer / Garder] | ✅ 2026-05-23 |
| 4 | Phase 4 (#3) | ~4h, optionnelle | Refonte UI étape mapping avec mode avancé | ✅ 2026-05-23 |

### Notes Phase 1 (livrée)

- Colonne `session_import.colonnes_echantillon` (JSON nullable) +
  migration idempotente `k1p2q3r4s5t6`. Format :
  `{nom_colonne: {exemples, valeur_frequente, uniques, remplies, total}}`.
- `importers.lecteur_tableur.analyser_colonnes_tableur` capture les
  stats (lecture bornée à 5000 lignes, sentinelles `none/n/a/s.d./
  NaN/""` neutralisées, NFC). Branchée dans `attacher_tableur` ;
  échec d'analyse non bloquant (l'upload garde `colonnes_detectees`
  et `colonnes_echantillon=None`).
- Heuristique élargie dans `profils.generateur._HEURISTIQUES`
  (filename/hash/iiif/doi/auteur/editeur/contributeur/sujet/droits/
  source + variantes FR/EN), plus un nouveau bucket
  `_HEURISTIQUES_FICHIER_META` (thumb, data_url, embed_url,
  preview_url) qui force `fichier.metadonnees.<slug>` pour éviter
  les warnings de divergence à la fusion par cote. Le cas spécial
  composé `doi` + `nakala` distingue maintenant `doi_collection_nakala`
  des autres DOI.
- UI : aperçu inline sous chaque nom de colonne dans le template
  mapping — `ex. « 1 », « 2 », « 3 » · 7466/7466 remplis · 200
  valeurs uniques`. Compatible avec les anciennes sessions
  (`colonnes_echantillon = None` → bloc masqué).
- Inefficacité connue : `attacher_tableur` lit le tableur deux fois
  (entêtes via `nrows=1` puis échantillons via `nrows=5000`).
  Acceptable pour la Phase 1 (~1s d'upload en plus sur PF), à
  factoriser plus tard si la Phase 2 ajoute encore une passe.

### Notes Phase 2 (livrée)

- `analyser_colonnes_tableur` ajoute la clé `classif` par colonne :
  `cote` | `par-item` | `par-fichier` | `melange` | `indetermine`.
  Calculée sur le df normalisé (sentinelles → null) avant le groupby
  pour éviter qu'une `none` / `n/a` compte comme valeur distincte.
- Identification de la cote : pattern strict (`^cote$|^cote_item$|...`)
  puis fallback « première colonne 100% unique au global ». Si rien
  ne convient, toutes les autres colonnes sont `indetermine`.
- Seuils : `>=90%` des cotes à 1 valeur → `par-item` ;
  `>50%` à plusieurs valeurs → `par-fichier` ; entre les deux →
  `melange`. Codés dans `_SEUIL_PAR_ITEM` / `_SEUIL_PAR_FICHIER`.
- `cibles_proposees` consomme la classif : à la première visite du
  mapping, une colonne qui tomberait sur `CIBLE_META` (slug libre)
  et qui est classée `par-fichier` est **promue** en
  `CIBLE_META_FICHIER`. Les champs dédiés (cote, fichier.nom_fichier,
  metadonnees.auteur…) gagnent toujours sur la classif. Quand un
  mapping est déjà enregistré (l'utilisateur revient sur l'étape),
  aucune ré-promotion : on respecte le choix utilisateur.
- UI : un second paragraphe sous l'aperçu affiche l'indice par
  colonne (`ⓘ identifie chaque item`, `ⓘ stable par cote — métadonnée
  d'item`, `ⓘ varie au sein de chaque cote — métadonnée de fichier`,
  `⚠ valeurs mêlées par cote`). Style coloré discret (bleu cote,
  brun fichier, ambré mélange).
- Refactor latéral : `_normaliser_pour_analyse` extrait au module-level,
  partagée avec le groupby. Bug subtil corrigé pendant la session —
  après `df.map()`, pandas convertit les `None` retournés en `NaN`
  dans une série object ; `v is not None` laissait passer les NaN.
  Filtre changé en `isinstance(v, str)` (le post-normalize ne contient
  que str ou null).
- Passe de revue (même session) :
  - `par-item` masqué dans l'UI — c'est le défaut attendu, le
    signaler sur ~80 % des colonnes serait du bruit (la classif
    reste calculée + stockée pour les phases ultérieures).
  - Fallback `100 % unique` durci : `_PATTERNS_COTE_EXCLUS_DU_FALLBACK`
    saute `filename`/`hash`/`iiif`/`doi` (typiquement 100 % uniques)
    pour qu'une cote non-canonique placée après ne soit pas masquée
    par une fausse détection. Test dédié `test_classif_fallback_
    cote_ignore_filename`.
  - Test du seuil exact à 9/10 pour confirmer le `>=90%` strict.
- Couplage à surveiller : `_PATTERN_COTE_CANDIDATE` (lecteur_tableur)
  est volontairement aligné sur le premier triplet de
  `_HEURISTIQUES` (profils.generateur). Si l'un évolue (ajout d'une
  nouvelle variante de cote), penser à propager. Pas de centralisation
  pour l'instant — la duplication est documentée et le coût d'un
  drift est faible (juste un fallback en plus).

### Notes Phase 3 (livrée)

- Dataclass `AnomalieMapping` (gelée) dans `api.services.import_web` :
  `colonne`, `classif`, `cible_actuelle`, `cible_suggeree`, `message`.
  `cible_suggeree=""` pour les cas `melange` (pas de bouton « Corriger »
  affiché, juste l'alerte).
- Service `detecter_anomalies_mapping(session, cibles)` produit la
  liste à partir de la classif Phase 2 + des cibles choisies. Trois
  motifs :
  - `par-fichier` + cible item (CIBLE_META ou `metadonnees.<dc>`)
    → suggère `CIBLE_META_FICHIER` ;
  - `par-item` + cible fichier (CIBLE_META_FICHIER ou `fichier.*`)
    → suggère `CIBLE_META` ;
  - `melange` → alerte simple, sans suggestion.
  - Skip si cible = `CIBLE_IGNORE` (l'utilisateur a décidé) ou
    classif `cote` / `indetermine`.
- Helper `_cible_est_fichier(cible)` partage la logique entre la
  détection et `cibles_proposees` — distingue les cibles fichier
  (CIBLE_META_FICHIER + `fichier.*`) des cibles item (tout le reste
  sauf CIBLE_IGNORE).
- Route `GET /import/{sid}/mapping` appelle systématiquement le
  détecteur et passe `anomalies` au contexte. À la première visite
  (après auto-promotion Phase 2), les cibles sont cohérentes → aucune
  anomalie. Les anomalies n'apparaissent qu'après un override
  utilisateur (POST mapping puis retour sur l'étape).
- Template : bandeau `data-anomalies` en haut du form (jaune amber),
  une `<li>` par anomalie avec son message + boutons « Déplacer en
  niveau fichier » / « Déplacer en niveau item » / « Garder le choix
  actuel ». Les selects ont maintenant un attribut `data-colonne`
  pour le repérage côté JS.
- JS `anomalies.js` : click delegation sur
  `[data-action-corriger] / [data-action-garder]`. « Corriger »
  trouve le select via `[data-cible-select][data-colonne="..."]`
  (CSS.escape pour gérer apostrophes / quotes / URIs Dublin Core),
  bascule sa value et déclenche un événement `change` (pour que
  `hints_cibles.js` réactualise le hint). Puis retire la `<li>`.
  Si la liste est vide, masque le bandeau entier.
- Le JS n'envoie aucun POST intermédiaire — l'utilisateur soumet le
  form complet quand il est prêt. Trade-off : si l'utilisateur ferme
  l'onglet après avoir cliqué « Corriger », sa correction est perdue
  (rien n'est persisté côté serveur tant que le form n'est pas soumis).
  Acceptable pour un wizard linéaire ; à revoir si on bascule en mode
  édition non-linéaire (Phase 4).
- Tests : 7 unitaires (un par cas du service) + 2 intégration (anomalie
  visible après override / pas d'anomalie en first-visit cohérent).
- Passe de revue Phase 3 :
  - Renforcement du test message (vérifie les chiffres
    `X valeurs uniques sur Y cellules`) — la simple présence de
    "varie au sein de chaque cote" n'aurait pas détecté un casse
    d'interpolation.
  - Test intégration cas `melange` (rendu HTML) : confirme que le
    bouton « Corriger » est absent (`cible_suggeree=""`), seul
    « Garder » reste.
  - Garde-fou `ValueError` si `len(colonnes) != len(cibles)` (le
    `zip` natif tronquerait silencieusement et masquerait des
    anomalies).
- Trous laissés volontairement :
  - Le bouton « Garder le choix actuel » ne persiste rien — si
    l'utilisateur revient sur l'étape, l'anomalie réapparaît.
    Acceptable (l'utilisateur a soumis le form en l'état, c'est
    son choix). Persistance possible via une clé `anomalies_
    masquees` dans la session, mais c'est de l'état accessoire.
  - Aucune attribute a11y (`role="region"`, `aria-label`) sur le
    bandeau anomalies — cohérent avec le reste du wizard d'import
    qui n'a pas de couche a11y dédiée. Chantier transverse, hors
    périmètre.
  - **T6 livré 2026-05-23 (option B « finir V0.9.x avant test
    d'usage »)** : l'agrégation des warnings de divergence au dry-run
    d'aperçu est désormais en place.
    - Dataclass `DivergenceAgreg` ajoutée à
      `importers.ecrivain` (champ, niveau, nb_cotes_affectees,
      nb_divergences, exemple_cote, exemples_valeurs).
    - `RapportImport.divergences_aggregees: list[DivergenceAgreg]`
      champ optionnel — vide si pas de divergence. Backward-compat :
      `warnings: list[str]` reste rempli en parallèle (tests
      existants qui font `assert any("ne matche pas" in w for w in
      rapport.warnings)` continuent à passer).
    - `_grouper_par_cote` collecte l'agrégat dans un dict
      `(niveau, champ) → {cotes, nb, exemple_cote, exemples}` puis
      le convertit en liste triée par `nb_divergences` décroissant
      (les colonnes vraiment problématiques en tête). Helper
      `_enregistrer_divergence_agreg` dédié.
    - Template `import_etape_apercu.html` : nouveau bloc
      « N colonne(s) à reclasser » qui résume chaque champ
      problématique (`metadonnees.X varie au sein de N cotes,
      M valeurs ignorées, ex. « 1 », « 2 », « 3 »`). Fallback
      sur la liste flat des warnings résiduels (orphelins,
      ordre_depuis_nom, etc.).
    - CLI `_afficher_rapport` : même bloc résumé toujours visible
      (pas conditionné à `--verbose`, c'est un signal utile).
      Les warnings flat de divergence (« divergence sur ») sont
      filtrés du listage verbose pour éviter le doublon.
    - Tests : 3 unitaires (`test_divergences_aggregees_par_champ`,
      `test_divergences_aggregees_vide_si_pas_de_conflit`) et 1
      intégration (`test_apercu_affiche_divergences_aggregees`
      qui dérou le wizard complet en TestClient et vérifie le
      rendu HTML).

### Notes Phase 4 (livrée)

- Deux modes coexistent : **simple** (par défaut, 4 questions
  explicites) et **avancé** (l'ancienne grille de 28 selects).
  Toggle via query string `?avance=1` sur la route GET — pas de
  state DB, bookmarkable, idempotent. Le dernier mode utilisé n'est
  pas mémorisé : on revient toujours au simple par défaut, l'user
  peut basculer en avancé via le lien en bas du form.
- Service `suggerer_reponses_simple(session) → SuggestionsModeSimple`
  pré-remplit les 4 questions :
  - `colonne_cote` : la colonne dont la classif vaut `"cote"` (déjà
    calculée à l'upload par `_identifier_colonne_cote` de
    `lecteur_tableur`).
  - `colonne_titre` / `colonne_date` : premier match du pattern
    correspondant dans `proposer_mapping`.
  - `granularite` : `"fichier"` si plus de la moitié des colonnes
    hors cote sont par-fichier, sinon `"item"`. Le template affiche
    un indice « ⓘ La majorité des colonnes varient au sein de chaque
    cote » sous le radio quand la suggestion est `fichier` (pour
    justifier le choix par défaut).
- Service `construire_mapping_depuis_simple(session, colonne_cote,
  colonne_titre, colonne_date) → dict` produit le mapping complet :
  les 3 colonnes explicites sur leurs champs dédiés
  (`cote`/`titre`/`date`), le reste en `metadonnees.<slug>` —
  préfixé `fichier.metadonnees.<slug>` si la classif le marque
  par-fichier. Lève `MappingInvalide` si une colonne pointée
  n'existe pas, ou si la même colonne est choisie pour plusieurs
  rôles. Tests dédiés pour chaque branche d'erreur.
- Route `POST /import/{sid}/mapping/simple` : 4 champs de form
  (`colonne_cote`, `granularite`, `colonne_titre`, `colonne_date`).
  Re-render avec erreur si validation échoue, sinon avance vers
  l'étape fichiers via `enregistrer_mapping`. Mutualise le même
  service de persistance que la route avancée — pas de duplication
  d'invariant.
- Template `import_etape_mapping_simple.html` : 4 fieldsets, helper
  Jinja `select_colonne(name, valeur, suggestion, ...)` pour les
  selects (option vide + colonnes du tableur, premier exemple
  affiché à côté du nom). Récap des colonnes restantes en bas avant
  les boutons. Footer : « ← Fonds » à gauche, « Fichiers → » au
  milieu, lien discret « Affiner colonne par colonne (mode avancé)
  → » à droite.
- Template avancé : ajout du lien « ← Revenir au mode simple » à
  droite du footer.
- Tests intégration : 6 nouveaux. Vérifient le rendu par défaut
  (mode simple sans `data-cible-select`), le toggle `?avance=1`
  (28 selects + lien retour), la soumission minimale (cote seule),
  la soumission avec titre/date explicites, le rejet sans cote
  (400 + message), et le rejet d'une cote inexistante (400).
- **Migration des tests Phase 1–3** : tous les tests qui faisaient
  des assertions sur le DOM avancé (`data-cible-echantillon`,
  `data-classif`, section anomalies, hints) ont été basculés sur
  `GET .../mapping?avance=1`. La fonctionnalité reste accessible,
  juste plus le défaut.
- Trous laissés volontairement :
  - Pas de validation côté serveur que cote/titre/date soient des
    colonnes différentes au niveau form HTML (juste côté service via
    `construire_mapping_depuis_simple`). Acceptable, le service
    couvre.
  - La sélection « ColonneAbsente » n'est possible que via un POST
    direct (manipulation hors UI) — les `<select>` ne contiennent
    que les colonnes existantes. Garde-fou serveur quand même.
  - L'affichage du premier exemple à côté du nom dans le select
    `« colonne — ex. « valeur » »` peut être tronqué si la valeur
    est longue. Filtre `truncate(25, true, '…')` posé.
- Passe de revue Phase 4 :
  - `suggerer_reponses_simple` restaure les choix utilisateur si
    `session.mappings` existe (édition d'un mapping déjà soumis,
    quel que soit le mode utilisé pour le soumettre). Sans ça,
    revenir sur l'étape mapping repré-remplissait les selects avec
    les suggestions auto et perdait l'override. Test unitaire dédié
    `test_suggerer_reponses_simple_restaure_mapping_existant`.
  - Test intégration `test_mapping_simple_pre_selectionne_suggestions`
    vérifie via regex que `<option value="Cote" selected>` est rendu
    (pas seulement calculé).
  - Test intégration `test_mapping_simple_indice_granularite_fichier`
    vérifie le rendu du hint « ⓘ La majorité des colonnes varient au
    sein de chaque cote » quand la classif suggère fichier.
  - Trous documentés non corrigés :
    - Récap des « N autres colonnes » basé sur les suggestions et
      pas sur les choix utilisateur courants. Mineur (informationnel
      pur, l'utilisateur quitte la page après submit). Le re-render
      après erreur réutilise les `valeurs` pour les selects mais le
      récap reste figé.
    - `valeur_active or suggestion` dans le macro : si l'utilisateur
      a explicitement choisi « Aucune » (chaîne vide) et qu'une
      erreur survient, le re-render lui propose à nouveau la
      suggestion plutôt que de respecter le choix vide. Sub-optimal
      mais rare en pratique (l'utilisateur re-choisit « Aucune » en
      re-soumettant).

### Passe de revue transversale (5e passe)

Trouvaille : le mode simple est **lossy** par rapport au mode avancé.
Scénario qui cassait silencieusement :

1. L'utilisateur mappe `Année` → champ dédié `annee` en mode avancé.
2. Soumet, navigue, revient sur `/mapping` → arrive en mode simple.
3. `Année` n'est pas dans cote/titre/date.
4. Resubmit le simple → `construire_mapping_depuis_simple` re-slugifie
   `Année` en `metadonnees.annee`. Le mapping `annee` (champ dédié) est
   **perdu sans signal**.

Le brief lui-même dit « tout le reste va en metadonnees » — c'est
intentionnel, le mode simple est volontairement réducteur. Mais sans
avertir l'utilisateur, on piège les usages avancés.

Mitigation (livrée 2026-05-23) :

- Nouveau helper `colonnes_champs_avances(session) → list[str]`
  recense les colonnes du mapping qui seraient ramenées en metadonnees
  au prochain submit simple. Couvre :
  - Champs dédiés Item hors cote/titre/date (`annee`, `type_coar`,
    `langue`, `doi_nakala`, `numero`, `description`, …).
  - Champs dédiés Fichier (`fichier.nom_fichier`, etc.).
  - DC canoniques (`metadonnees.auteur` / `editeur` / etc.) — leur
    sémantique « cible canonique » se perd même si le slug textuel
    coïncide.
  - Ignore les slugs libres (`metadonnees.<X>`, `fichier.metadonnees.<X>`)
    qui sont re-générés fidèlement par la slugification.
- Bandeau amber non-bloquant dans `import_etape_mapping_simple.html` :
  « ⚠ Votre mapping actuel utilise N colonnes sur des champs avancés
  (X, Y, Z). Soumettre ce formulaire les ramènera en métadonnées
  personnalisées. [Passer en mode avancé] pour les préserver. »
- Tests : 4 nouveaux. Unitaire détection (matrice de cibles +
  session vide) + test documentaire de la perte effective (le
  comportement reste lossy par design, juste maintenant signalé)
  + intégration rendu de la bannière + intégration absence quand
  rien à signaler.

Conséquence opérationnelle : un utilisateur qui retourne sur l'étape
mapping après usage du mode avancé voit immédiatement quels champs
sont menacés et choisit en connaissance de cause. Pas de perte
silencieuse — le brief tient (mode simple lossy) mais l'UX est
explicite.

Tests à chaque phase. La friction est réelle sur PF — ce sera la
condition d'acceptance.

## Hors scope V0.9.2-import

- Édition inline du mapping après import (cas de la migration des
  données depuis ColleC vers ColleC). Reporté à V1.
- Suggestion de structure (decomposition_cote) à partir d'un
  échantillon. Trop ambitieux pour V0.9.2.
- Multi-tableurs (import en plusieurs vagues coordonnées). Reporté
  à V1+.
