# Renommage transactionnel

Le module `archives_tool.renamer` orchestre le renommage de fichiers
en quatre temps :

1. **Template** — `template.py` évalue un template de nommage Python
   (`str.format`) avec les variables d'un fichier et de son item.
2. **Plan** — `plan.py` calcule la cible de chaque fichier, détecte
   les conflits (collisions intra-batch, externes, cycles).
3. **Exécution** — `execution.py` applique le plan en deux phases
   (`src → tmp`, `tmp → dst`) sur disque et en base, avec rollback
   compensateur en cas d'erreur mid-batch.
4. **Annulation** — `annulation.py` rejoue le batch à l'envers via
   son `batch_id`.

Le journal est tenu dans `OperationFichier`.

## Variables du template

| Variable           | Source                                       |
| ------------------ | -------------------------------------------- |
| `{cote}`           | `Item.cote`                                  |
| `{numero}`         | `Item.numero`                                |
| `{titre}`          | `Item.titre`                                 |
| `{date}`           | `Item.date` (format EDTF brut)               |
| `{annee}`          | `Item.annee`                                 |
| `{langue}`         | `Item.langue`                                |
| `{type_coar}`      | `Item.type_coar`                             |
| `{ordre}`          | `Fichier.ordre` (entier)                     |
| `{type_page}`      | `Fichier.type_page`                          |
| `{folio}`          | `Fichier.folio`                              |
| `{nom_original}`   | `Fichier.nom_fichier` sans extension         |
| `{ext}`            | extension en minuscules, sans le point       |
| `{ext_majuscule}`  | extension en majuscules                      |
| `{cote_collection}`| `Collection.cote_collection`                 |
| `{titre_collection}`| `Collection.titre`                          |

Les valeurs `None` sont substituées par une chaîne vide. Le format
`{ordre:02d}` Python est supporté (zéro-padding, etc.).

Exemples :

- `{cote}-{ordre:02d}.{ext}` → `HK-1960-01-01.png`
- `{annee}/{cote}-{ordre:02d}.{ext}` → `1960/HK-1960-01-01.png`
- `{nom_original}_canonique.{ext}` → `scan_42_canonique.jpg`

## CLI

```bash
# Aperçu (dry-run par défaut) — n'écrit rien.
archives-tool renommer appliquer \
    --template "{cote}-{ordre:02d}.{ext}" \
    --collection HK

# Cibler un seul item.
archives-tool renommer appliquer \
    --template "{cote}.{ext}" \
    --item HK-1960-01

# Cibler des fichiers précis.
archives-tool renommer appliquer \
    --template "{cote}-{ordre:02d}.{ext}" \
    --fichier-id 42 --fichier-id 43

# Appliquer pour de vrai après revue du plan.
archives-tool renommer appliquer \
    --template "{cote}-{ordre:02d}.{ext}" \
    --collection HK --recursif --no-dry-run \
    --utilisateur "Marie"

# Annuler un batch.
archives-tool renommer annuler --batch-id <UUID> --no-dry-run

# Voir l'historique des batchs.
archives-tool renommer historique --limite 20
```

**Codes de sortie** :

- `0` : aucune anomalie ; le plan a été affiché ou exécuté.
- `1` : plan non applicable (conflits) ou échec à l'exécution.
- `2` : erreur d'invocation (collection introuvable, etc.).

## Conflits détectés

| Code                    | Description                                                                          | Action                          |
| ----------------------- | ------------------------------------------------------------------------------------ | ------------------------------- |
| `template_invalide`     | Variable inconnue, format invalide, résultat vide, ou tentative de sortir via `..`. | Op marquée `bloque`.            |
| `collision_intra_batch` | Plusieurs fichiers visent la même cible.                                            | Toutes les ops du groupe `bloque`. |
| `collision_externe`     | La cible existe déjà sur disque, hors du batch.                                     | Op `bloque`.                     |

Les **cycles** (A→B et B→A) ne sont *pas* des conflits : ils sont
marqués `en_cycle` et résolus à l'exécution par un nom temporaire
(`.tmp_rename_<uuid>_…`). Les opérations en `no_op` (cible == source)
sont ignorées sans bruit.

## Stratégie d'exécution en deux phases

L'exécution traite les renommages en deux passes pour absorber
naturellement les cycles, à la fois sur disque et en base (la
contrainte `UNIQUE(racine, chemin_relatif)` ne tolère pas les états
intermédiaires) :

1. **Phase 1** — chaque source est déplacée vers un nom temporaire
   unique sur disque ; `Fichier.chemin_relatif` est mis à jour vers
   ce temporaire ; `flush`. À ce stade, tous les rangs ont un chemin
   unique (les UUID des temps).
2. **Phase 2** — chaque temporaire est déplacé vers sa cible finale ;
   `chemin_relatif` réécrit ; une `OperationFichier(reussie)`
   journalisée par renommage. `commit` à la fin.

Si une erreur survient en phase 2, le **rollback compensateur** rejoue
les déplacements inverses pour les opérations déjà appliquées avant
de propager l'erreur. La transaction SQLAlchemy est `rollback`-ée :
le journal n'est pas persisté sur échec.

## Annulation

Une opération d'annulation prend un `batch_id` original et :

1. Vérifie que chaque fichier est encore dans son état post-renommage
   (chemin en base et sur disque conformes au journal). Si la base ou
   le disque a divergé entre-temps, l'annulation refuse de partir.
2. Rejoue les renommages inverses en deux phases (mêmes garanties
   transactionnelles que l'exécution).
3. Marque les `OperationFichier` originales avec
   `annule_par_batch_id = <nouveau batch>`.
4. Insère de nouvelles `OperationFichier(type=restore)` dans le
   nouveau batch.

L'annulation est idempotente : un batch déjà annulé ne peut pas
l'être à nouveau (les opérations originales ont
`annule_par_batch_id` non nul, donc sont filtrées).

## Limites connues V1

- Le template est obligatoire en argument CLI ; la lecture depuis
  le profil de la collection (`profil_import.contenu.fichiers.
  template_nommage_canonique`) est prévue mais l'importer n'alimente
  pas encore `Collection.profil_import_id`.
- L'exécution charge en mémoire la totalité du plan. Pour des fonds
  géants (>100k fichiers), envisager un streaming par lot.
