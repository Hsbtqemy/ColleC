# Opérations par lot — socle partagé (note de design — v1)

> **Statut : en discussion, itératif.** Trace une décision structurante en
> cours de cadrage (cf. CLAUDE.md). Issue de la discussion 2026-06-24 sur le
> bulk-fill des champs personnalisés, élargie à un **socle d'opérations par
> lot**. Modèle non figé.

## Idée

Plusieurs besoins ColleC sont la même chose vue sous des angles différents :
**appliquer une modification à un ensemble d'entités, avec aperçu et
réversibilité**. Plutôt que des fonctionnalités one-off, viser un **socle
partagé** dont chaque opération est un membre.

Cycle commun à tous les membres :

```text
sélection (périmètre)  →  APERÇU (diff, principe #3)  →  batch journalisé
(#4)  →  UNDO par batch_id
```

## Le renamer = preuve d'existence du pattern

Le module `renamer/` fait **déjà** ça pour le renommage de fichiers :
`plan.py` (construction + détection conflits/cycles), `execution.py`
(transactionnel, rollback), `annulation.py` (undo idempotent par `batch_id`),
`historique.py`, journal `OperationFichier`. Et son `Perimetre` (sélection)
est **déjà mutualisé** — le module `deriver` le réutilise. Donc une partie du
socle existe et est éprouvée.

## Membres de la famille

- **Renommage de fichiers** — *existe* (renamer).
- **Bulk-fill de champ** (1ᵉʳ nouveau cas, cf. ci-dessous).
- Remplacer / normaliser une valeur en lot (roadmap V2).
- Scinder / fusionner / renommer un champ personnalisé (question ouverte
  CLAUDE.md).
- Renommer une cote sur toute une collection.
- Déplacer des éléments en lot.

## Cas pilote : bulk-fill (propagation de *valeur*)

Clarification clé (2026-06-24) : « propagation » a **deux sens**, à ne pas
confondre.

| Niveau | Quoi | État |
| --- | --- | --- |
| **Entrée (le champ)** | champ défini sur la collection → présent (vide) sur **tous** les items | **existe déjà** (le scaffold ; c'est ce que l'utilisateur appelait « propagation ») |
| **Valeur par défaut** | auto-remplit les **nouveaux** items à la création (per-item, autonomie #8 préservée) | à faire (petit ; extension de `valeurs_par_defaut` d'import) |
| **Backfill** | écrit une valeur sur les items **existants** | à faire (= bulk-fill, membre du socle) |

→ Le besoin « champ présent partout » est **déjà couvert**. Le bulk-fill ne
concerne que la **valeur** sur les items déjà là.

**Garde-fous du backfill** (membre destructif du socle) :

1. **Périmètre** = filtres de collection courants d'abord (réutilise
   l'existant) ; multi-sélection explicite ensuite (sert *tous* les membres).
2. **Écrasement** : ne remplir que les **vides** par défaut ; écraser =
   opt-in explicite.
3. **Aperçu** (#3) : « X remplis · Y ignorés/écrasés » avant commit.
4. **Batch + undo** (#4) : `batch_id`, annulable en bloc.
5. Bloqué en lecture seule (mutation).

Propagation = écriture **par item** (jamais d'héritage dynamique) → cohérent
autonomie #8 ; un item peut diverger après coup.

## Fork architectural (DÉCISION DIFFÉRÉE)

**Décision (2026-06-24) : on ne tranche PAS le fork maintenant.** Le choix
(a)/(b)/(c) se fera **au moment où on attaquera concrètement le chantier
renamer / modification par lot** — pré-architecturer le socle dans l'abstrait
serait présumer la complexité (principe #6). L'analyse ci-dessous est
conservée comme matière à décision pour ce moment-là ; *leaning* actuel = (c),
éventuellement (c) **sans rétro-adapter le renamer tout de suite**.

Comment réaliser le socle ?

- **(a) Généraliser le renamer** : y faire entrer aussi les opérations
  métadonnées/entités. ⚠️ mauvais ajustement : l'`execution.py` du renamer est
  **spécifique au système de fichiers** (phases src→tmp→dst, cycles de
  chemins) — y greffer des ops métadonnées le gonflerait de logique étrangère.
- **(b) Module neuf inspiré** : un `bulk/` parallèle qui recopie le pattern.
  ⚠️ duplique l'échafaudage batch/undo/aperçu → deux socles divergents.
- **(c) Extraire un socle d'abstractions partagé** *(leaning)* : une couche
  fine (sélection = `Perimetre` *déjà* partagé ; protocole batch/undo ;
  contrat aperçu/diff ; cycle `plan → aperçu → appliquer → annuler`) que **le
  renamer ET les nouvelles ops implémentent**. Le renamer devient *un* citoyen
  du socle (refactor à bas risque : on garde son exécution FS, on le conforme
  juste au protocole), les nouvelles ops sont de nouvelles implémentations.

**Contrainte forte (décision existante)** : il y a **trois journaux** —
`OperationFichier` (fichiers), `ModificationItem` (métadonnées item),
`OperationEntite` (suppressions d'entités) — et le CLAUDE.md a **explicitement
décidé de NE PAS les unifier** (« migration risquée, zéro gain immédiat »).
Donc le socle ne doit **pas** imposer un journal unique : il définit un
**protocole** commun (`batch_id` + undo + aperçu), chaque domaine gardant son
**exécution + son journal** propres (fichiers → `OperationFichier`,
métadonnées → `ModificationItem`, entités → `OperationEntite`). Ce qui se
mutualise = **l'orchestration et la sélection**, pas le stockage.

→ (c) respecte cette contrainte (#6 : la complexité s'ajoute, ne se présume
pas) ; (a) et (b) la heurtent.

## Questions ouvertes

- [~] **Fork (a)/(b)/(c)** — **différé** au démarrage du chantier renamer /
      modif-par-lot (cf. § Fork). Leaning (c).
- [ ] Granularité de la sélection partagée : filtres d'abord, multi-sélection
      après — confirmer l'ordre.
- [ ] Forme du « contrat aperçu/diff » commun (à dériver de ce que produit
      déjà `renamer/plan.py`).
- [ ] Ordre de chantier dans la famille (bulk-fill semble le plus simple +
      le plus demandé).

## Liens

- Cas d'usage Nakala :
  [`champs-personnalises-nakala-future.md`](champs-personnalises-nakala-future.md)
  (le bulk-fill sert à propager des valeurs mappées avant push).
- `renamer/` — `plan.py` / `execution.py` / `annulation.py` /
  `historique.py` (le pattern existant).
- `OperationFichier`, `ModificationItem`, `OperationEntite` — les trois
  journaux (non unifiés, par décision).
- CLAUDE.md : V2 « refactoring de métadonnées en masse » + question ouverte
  « scinder/fusionner/renommer un champ personnalisé ».
