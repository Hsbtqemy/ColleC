# Backlog — revue générale (2026-06-18)

!!! warning "Document de travail interne"
    Page non publiée sur le site MkDocs (exclue via `exclude_docs`).
    Tickets issus de la **revue générale** (4 axes large + 3 relecteurs
    frais en profondeur) menée après le palier ShareDocs/S6/S7. Les
    findings actionnables non encore traités y sont consignés ; le statut
    est tenu à jour au fil des sessions.

Contexte : la revue large (dette / sécurité / tests / doc) a été suivie
d'une **seconde passe en profondeur** (relecture adversariale du code du
jour + logique métier des zones à risque + invariants/intégrité). La
sécurité (SSRF, validateur, redirections), les invariants (INV1/2/4/6,
atomicité du journal, synchro FTS5 y compris `metadonnees` JSON, verrou
optimiste, `annee` dérivée) sont **vérifiés sains** — aucun ticket ouvert
là-dessus. Les 5 tickets ci-dessous sont les findings résiduels.

Renvois : roadmap `docs/developpeurs/roadmap.md` § *Transverse / continu*
(dette technique) ; principe directeur n°7 du `CLAUDE.md` (tests d'abord
sur les zones à risque).

---

## R1 — Renamer : cycles + compensation phase 2 non testés `HIGH`

**Origine** : préexistant. **Statut** : ✅ **COUVERT (2026-06-18)** — voir
*Résolution* en fin de ticket. Aucun bug code trouvé ; zone désormais testée.
**Fichiers** : `renamer/execution.py` (`_compenser_apres_phase2`, ~131-144 ;
`mkdir`/phase 2 ~205) ; `renamer/plan.py` (`_detecter_cycles`) ;
`tests/test_renamer.py` (trou de couverture — **aucun** test de cycle ni
de compensation).

**Quoi** : le renommage transactionnel 2-phases (src→tmp→dst) avec
rollback compensateur est la zone la plus destructive du projet (principe
n°7), mais `test_renamer.py` ne couvre **ni les cycles** (A↔B), **ni le
chemin `EN_CYCLE`**, **ni la compensation de phase 2**. Le chemin nominal
de cycle est correct *à la lecture* (tmp uniques via uuid, flush phase 1
sans violation `UNIQUE`, phase 2 dst libérée).

**Risque** : sur une **double panne disque** pendant la compensation (la
1ʳᵉ compensation `dst→tmp` lève une `OSError` avalée dans `erreurs`, puis
la 2ᵉ boucle `tmp→src` opère sur un `tmp` déjà déplacé), un fichier peut
rester sous son nom `dst` final alors que la DB a été rollback-ée vers
l'ancien chemin → **désynchronisation DB↔disque silencieuse** (perte de
données potentielle). Non couvert ⇒ on ne peut pas garantir que le
comportement réel = comportement documenté.

**Esquisse de fix** : tests de panne — `monkeypatch` `Path.rename` pour
lever à la N-ième invocation (phase 1, phase 2, et pendant la
compensation), sur un plan de cycle + un plan à nouvelle arborescence.
Vérifier l'état DB↔disque après échec. Corriger le comportement si la
compensation s'avère lacunaire.

**Résolution (2026-06-18)** — 8 tests ajoutés à `test_renamer.py`
(famille 5), **tous verts**. **Aucun bug** trouvé **dans les chemins
exercés ni dans les topologies cyclique/mixte qui partagent ce code**
(vérifié par 2 relecteurs : la robustesse vient structurellement du pivot
temporaire universel — phase 1 déplace toutes les sources vers des `.tmp`
uniques avant toute écriture de cible, donc swap/cycle/normal empruntent
les mêmes lignes en exécution comme en compensation).
- Détection : `_detecter_cycles` sur swap (A↔B), triple (A→B→C→A) et
  chaîne ouverte (pas de faux cycle).
- Exécution d'un **swap réel** : contenus échangés sur disque (le binaire
  suit), chemins échangés en base, 2 `OperationFichier` journalées.
- **Bout-en-bout `construire_plan` (cycle + renommage normal mélangés) →
  exécution** : exerce le pont détection→tag→exécution complet + le
  remapping d'indices `pret_indices → globaux` (plan.py), non couvert par
  le swap construit à la main.
- **Panne phase 1 / phase 2** (`monkeypatch Path.rename`) → restauration
  complète disque + base, échec signalé, **compte de renames verrouillé**
  (assertion sur le nombre total, pour que l'ajout futur d'un rename casse
  le test au lieu de glisser en silence).
- **Double panne** (rename phase 2 **+** une compensation) → l'opération
  **signale bruyamment** (≥2 erreurs, dont « Compensation impossible ») ;
  une désync disque résiduelle reste possible mais **détectable/flaggée**.
  Contrat **best-effort** d'un FS non-transactionnel — documenté, pas un bug.
- **R4 verrouillé en passant** : le test phase-2 asserte que le dossier
  `renomme/` vide **subsiste** (le moteur ne nettoie pas les répertoires
  créés) — transforme R4 d'angle mort en comportement explicitement testé.

*Reste possible (non engagé)* : réduire la désync double-panne (relire
l'état disque avant rollback DB) — gain marginal, à peser plus tard.

---

## R2 — Config : un `nakala.base_url` invalide fait tomber TOUTE la config `MEDIUM`

**Origine** : comportement préexistant **élargi par le Lot 3** (49c5e0d :
le validateur SSRF de `NakalaConfig` rejette désormais `http://` et les
hôtes hors allowlist). **Statut** : ✅ **RÉSOLU (2026-06-18)** — voir
*Résolution* en fin de ticket.
**Fichiers** : `api/deps.py` (`_charger_config_cache`, ~63 : `except
(YAMLError, ValidationError, ValueError) → return None`) ; `config.py`
(`NakalaConfig._valider_base_url`).

**Quoi** : une `ValidationError` sur n'importe quelle sous-section (ici un
`nakala.base_url` invalide) dégrade **toute** la `ConfigLocale` à `None` →
défauts : `utilisateur="anonyme"`, **`racines` vidées** (images/dérivés ne
résolvent plus), **`lecture_seule` silencieusement repassé à `False`**.
Seul un `logger.warning` le signale.

**Risque** : un utilisateur qui met à jour avec un `nakala.base_url`
non-standard (ex. `http://apitest…` d'un vieux setup dev) perd sa config
entière sans s'en rendre compte — dont le **mode lecture seule** (sûreté).
Probabilité faible (le défaut `https://api.nakala.fr` est valide), mais
l'angle « perte silencieuse de `lecture_seule` » est réel.

**Esquisse de fix** : isoler l'échec de la section Nakala — soit dégrader
**uniquement** le bloc `nakala` à `None` (au lieu de toute la config) en
cas de sous-validation Nakala invalide, soit préserver les champs de
sûreté (`lecture_seule`, `racines`, `utilisateur`) même quand une
sous-section échoue. Émettre un warning plus visible.

**Résolution (2026-06-18)** — `ConfigLocale` reçoit un `field_validator(
"nakala", "sharedocs", mode="before")` `_tolerer_section_distante_invalide` :
une section **optionnelle d'accès distant** invalide est **désactivée**
(→ None) avec un `logger.warning` ciblé, au lieu de faire échouer toute la
`ConfigLocale`. `lecture_seule`, `racines` et l'identité **survivent** donc
à un `nakala.base_url` invalide. `NakalaConfig`/`ShareDocsConfig` restent
**stricts** en construction directe (erreurs précises quand la section est
réellement utilisée). **Scope** : volontairement limité aux 2 sections
distantes optionnelles — un `racines` cassé (dossier absent) reste une
erreur de config à part entière (le `model_validator` la signale), hors R2.

**Passe de revue (corrections)** : (1) **fuite de credential évitée** — le
premier jet loggait la `ValidationError` brute, dont le repr Pydantic inclut
`input_value` (donc l'`api_key`) ; corrigé en ne loggant que `loc`+`msg`
(`e.errors(include_input=False)`) + `repr=False` sur `NakalaConfig.api_key`.
(2) **tolérance étendue aux sections non-dict** (`nakala: "x"` scalaire/liste
→ désactivée aussi, au lieu de ré-effondrer la config). 6 tests
(`test_config.py`) dont un **anti-fuite** (caplog : le secret n'apparaît ni
dans les logs ni dans le repr) + nakala/sharedocs tous deux invalides +
non-dict toléré. **Reste noté (NIT, non engagé)** : message CLI
« section nakala absente » trompeur quand la section existe mais est
invalide — à différencier en V1.0 si besoin.

---

## R3 — plan.py : collision externe détectée par disque seul, pas en base `MEDIUM`

**Origine** : préexistant. **Statut** : ✅ **RÉSOLU (2026-06-19)** — voir
*Résolution* en fin de ticket.
**Fichiers** : `renamer/plan.py` (`construire_plan`, ~279-302) ;
contrainte `uq_fichier_chemin` (`models/fichier.py:137`).

**Quoi** : la détection de collision externe ne teste que l'**existence
disque** (`chemin_existe_nfc_ou_nfd`), jamais la base. Renommer X vers
`dir/Y.tif` où `dir/Y.tif` est déjà le `chemin_relatif` en base d'un
Fichier Y hors-périmètre **dont le binaire est absent du disque** (cas
fréquent : base importée d'un export Nakala, scans pas encore copiés) →
le plan rapporte `PRET` (pas de conflit), puis phase 2 viole
`UNIQUE(racine, chemin_relatif)` au commit → `IntegrityError` → rollback
compensateur (donc déclenche aussi le chemin R1).

**Risque** : non destructif (la compensation récupère), mais **échec
opaque et tardif** au lieu d'un conflit propre détecté en amont.

**Esquisse de fix** : dans `construire_plan`, ajouter une vérification des
cibles contre les `Fichier.chemin_relatif` existants hors-batch (un
`SELECT` sur `(racine, chemin_apres)`), symétrique à la détection de
collision intra-batch.

**Résolution (2026-06-19)** — `construire_plan` (`plan.py`) reçoit, après la
garde disque, une **garde base** : pour chaque cible, on cherche un Fichier
hors-lot qui occupe déjà ce `(racine, chemin_relatif)` → op `BLOQUE` +
`Conflit(COLLISION_EXTERNE, "occupée en base par un autre fichier")`. Les
fichiers du lot sont exclus (ils libèrent leur chemin → un swap/cycle reste
valide ; un NO_OP qui reste en place est un occupant légitime). Tous états
confondus (`uq_fichier_chemin` est une UNIQUE globale). Complémentaire de la
garde disque (les ops déjà bloquées disque sont hors `ops_actives`).

**Passe de revue (corrections)** : (1) **portabilité SQLite (HIGH)** — le
premier jet faisait un `IN`/`NOT IN` unique (~2× le nombre de fichiers
renommés en paramètres liés) ; sur un renommage de fonds entier (PF ~7500
scans) cela dépasse l'ancien plafond `SQLITE_MAX_VARIABLE_NUMBER = 999`
(libsqlite3 < 3.32) → `OperationalError`. Corrigé : requête **chunkée**
(`_TAILLE_LOT_SQL = 900`) + exclusion du lot **en Python** + `select` des
3 colonnes utiles (pas d'hydratation ORM). (2) **test NO_OP-occupant
(MEDIUM)** ajouté — un NO_OP binaire-absent ciblé par une autre op est bien
bloqué par la garde base (ni intra-batch, ni disque), affirmation jusque-là
non testée. 2 tests R3 (collision hors-lot binaire absent + NO_OP occupant) ;
assertion durcie (`== "collision externe en base"`). Aucune régression
(renommages vers de nouveaux chemins ne matchent aucun chemin existant ;
swap couvert par `test_plan_mixte_cycle_et_normal_bout_en_bout`).

---

## R4 — Renamer : `mkdir(parents)` non nettoyé au rollback `LOW`

**Origine** : préexistant. **Statut** : ouvert.
**Fichiers** : `renamer/execution.py` (~205, phase 2).

**Quoi** : quand le template crée une nouvelle arborescence
(`mkdir(parents=True, exist_ok=True)`) et que phase 2 échoue ensuite, la
compensation ne défait que les fichiers (rename inverse) — les
**répertoires créés restent** (dossiers vides parasites).

**Risque** : bénin (pas de perte de données), juste des dossiers orphelins
après un échec. Non testé.

**Esquisse de fix** : tracer les répertoires créés pendant la phase 2,
`rmdir` ceux restés vides lors de la compensation.

---

## R5 — `Fichier.item_id` sans `ON DELETE CASCADE` (asymétrie FK) `LOW`

**Origine** : préexistant. **Statut** : ✅ **RÉSOLU (2026-06-22)** — voir
*Résolution* en fin de ticket.
**Fichiers** : `models/fichier.py:53` ; migration initiale
`alembic/versions/380e05cd7254_initial_schema.py` (~273-276).

**Quoi** : la FK `Fichier.item_id` n'a **pas** d'`ON DELETE CASCADE` au
niveau modèle ni SQL, contrairement à ses sœurs (`Item.fonds_id`,
`item_collection`, `annotation_region.fichier_id`, toutes en cascade). La
suppression des fichiers d'un item repose **uniquement** sur l'ORM
`cascade="all, delete-orphan"`.

**Risque** : aucun aujourd'hui (tous les chemins de suppression passent
par `db.delete(item)` ORM). Latent : un futur `delete()` Core/bulk sur
`item` orphelinerait les `fichier` (et transitivement leurs
`annotation_region`, dont la cascade SQL s'appuie sur un `fichier.id` qui
ne serait jamais supprimé).

**Esquisse de fix** : migration ajoutant `ondelete="CASCADE"` à
`fichier.item_id` (parité défense-en-profondeur avec les FK sœurs).
`batch_alter_table` (SQLite).

**Résolution (2026-06-22)** — `models/fichier.py` : `item_id` passe à
`ForeignKey("item.id", ondelete="CASCADE")`. Migration `v0z1a2b3c4d5`
(`batch_alter_table` sur `fichier`) : la FK initiale étant **anonyme**
(`380e05cd7254` la crée sans `name=`), on fournit une `naming_convention`
SQLAlchemy par défaut pour que la FK reflétée reçoive le nom canonique
`fk_fichier_item_id_item` et puisse être droppée, puis recréée avec
`ondelete="CASCADE"`. **Idempotente** (skip si la FK porte déjà `CASCADE` —
cas d'une base `Base.metadata.create_all` en parallèle) ; **downgrade
fonctionnelle** (recrée la FK sans cascade). Validé empiriquement : cycle
upgrade → downgrade → upgrade, **une seule** FK `item_id` `ON DELETE
CASCADE` dans la DDL finale, **5 index** (`ix_fichier_item`…) + contraintes
UNIQUE/CHECK préservés au recreate. **Pas de `passive_deletes`** : la
cascade ORM `Item.fichiers` (`all, delete-orphan`) reste le chemin nominal,
la cascade SQL est de la défense en profondeur. 1 test de parité ajouté
(`test_migration_fichier_item_id_a_on_delete_cascade` : `CASCADE` côté
Alembic **et** côté modèle) ; suite complète **1997 verts**.

**Note hors scope (observée, non traitée)** : `operation_fichier.fichier_id`
(journal) reste sans action `ON DELETE` (NO ACTION). Un `delete()` bulk sur
`item` cascade donc jusqu'à `fichier` mais **bloquerait** (RESTRICT) si des
`OperationFichier` référencent ces fichiers — comportement *fail-safe* (pas
d'orphelin), pas une régression. La durabilité du journal vs `SET NULL` est
une décision distincte de R5 (principe n°6 : ne pas élargir le scope).

---

## Décision de séquençage (à trancher)

- **R2** : candidat correctif court — régression de sûreté élargie au Lot 3.
- **R1** : candidat « prochain lot de durcissement tests » — le plus
  important sur le fond (zone destructive, principe n°7), mais préexistant.
- **R3 / R4 / R5** : à interleaver avec un futur passage sur le renamer
  (R3+R4) et une migration de cohérence FK (R5).
