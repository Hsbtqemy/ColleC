# V0.9.2-import — refonte de l'assistant de mapping

Document interne (exclu du build MkDocs). État : *à attaquer*, ouvert
2026-05-22 après le test d'usage F sur fonds PF (Por Favor, export
Nakala, 7467 lignes / 173 cotes / 28 colonnes).

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

### Phase 1 — Foundations (≈ 2h)

#### #2 — Échantillons de valeurs inline

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

#### #5 — Heuristique nominative enrichie

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

### Phase 2 — Intelligence (≈ 3h)

#### #1 — Auto-détection par-item vs par-fichier ⭐ killer feature

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

### Phase 3 — Diagnostic intelligent (≈ 1h30)

#### #4 — Warnings agrégés et actionnables

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

### Phase 4 — Refonte UI complète (≈ 4h, optionnelle)

#### #3 — Inverser le défaut : tout en métadonnée, opt-in pour les champs structurants

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

| Session | Phase | Effort | Livrable |
|---|---|---|---|
| 1 | Phase 1 (#2 + #5) | ~2h | Échantillons en base + UI, heuristique nominative enrichie |
| 2 | Phase 2 (#1) | ~3h | Auto-détection par-item/fichier, UI d'indice |
| 3 | Phase 3 (#4) | ~1h30 | Warnings agrégés + actions [Déplacer / Garder] |
| 4 | Phase 4 (#3) | ~4h, optionnelle | Refonte UI étape mapping avec mode avancé |

Tests à chaque phase. La friction est réelle sur PF — ce sera la
condition d'acceptance.

## Hors scope V0.9.2-import

- Édition inline du mapping après import (cas de la migration des
  données depuis ColleC vers ColleC). Reporté à V1.
- Suggestion de structure (decomposition_cote) à partir d'un
  échantillon. Trop ambitieux pour V0.9.2.
- Multi-tableurs (import en plusieurs vagues coordonnées). Reporté
  à V1+.
