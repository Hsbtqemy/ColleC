# Contrôles de cohérence

Le module `archives_tool.qa` regroupe les contrôles de cohérence
base ↔ disque. Tout est en **lecture seule** : aucun contrôle
n'écrit en base, aucun ne touche aux fichiers sur disque.

Quatre contrôles sont disponibles en V1.

| Code                  | Vérifie                                              |
| --------------------- | ---------------------------------------------------- |
| `fichiers-manquants`  | Fichiers référencés en base, absents du disque       |
| `orphelins-disque`    | Fichiers présents sous une racine, non référencés    |
| `items-vides`         | Items sans aucun fichier rattaché                    |
| `doublons`            | Groupes de fichiers partageant un même `hash_sha256` |

## CLI

```bash
# Tous les contrôles, sur toute la base.
archives-tool controler

# Restreindre à une collection (et ses sous-collections).
archives-tool controler --collection HK --recursif

# Ne lancer qu'un sous-ensemble de contrôles.
archives-tool controler --check items-vides --check doublons

# Personnaliser les extensions scannées pour les orphelins disque.
archives-tool controler --extensions png,jpg,tif

# Plafonner l'affichage des détails par contrôle (0 = illimité).
archives-tool controler --limite-details 50
```

**Codes de sortie** :

- `0` : aucune anomalie.
- `1` : au moins une anomalie remontée.
- `2` : erreur d'invocation (collection introuvable, config invalide,
  code de contrôle inconnu).

## Périmètre par contrôle

### `fichiers-manquants`

Pour chaque `Fichier` actif, on vérifie l'existence physique sous la
racine logique configurée. Comparaison stable NFC/NFD : les noms
décomposés sur disque (macOS) sont reconnus depuis Windows.

- Racine référencée mais non présente dans la config locale →
  **avertissement** (« non vérifiable »), pas une anomalie.
- Le filtre `--collection` restreint aux fichiers des items de la
  collection ciblée.

### `orphelins-disque`

Parcourt récursivement les racines configurées et signale les fichiers
*non* référencés en base. Filtre par extension (défaut :
`png, jpg, jpeg, tif, tiff, pdf`). Les fichiers cachés (commençant par
`.`, type `.DS_Store`) sont ignorés.

- Sans config locale ou sans racines → contrôle ignoré avec
  avertissement.
- Avec `--collection`, on ne scanne **que les racines effectivement
  utilisées** par les fichiers de la collection. La déduplication
  (« est-ce référencé ? ») reste calculée sur **toutes** les
  collections : un fichier appartenant à une autre collection n'est
  pas vu comme orphelin.

### `items-vides`

Items sans aucune ligne `Fichier` active rattachée. Utile en sortie
d'import pour repérer des cotes mal résolues.

### `doublons`

Groupes de ≥ 2 fichiers actifs partageant le même `hash_sha256`.
Les fichiers dont le hash est `NULL` (pas demandé à l'import, ou
calcul impossible) sont remontés en avertissement : on ne peut rien
en dire.

## Module Python

```python
from archives_tool.qa import (
    controler_tout,
    controler_doublons_par_hash,
    controler_fichiers_manquants_disque,
    controler_items_sans_fichier,
    controler_orphelins_disque,
)

rapport = controler_tout(
    session,
    racines={"scans": Path("/data/scans")},
    collection_cote="HK",
    recursif=True,
)
print(rapport.nb_anomalies)
for ctrl in rapport.controles:
    print(ctrl.code, ctrl.nb_anomalies)
```

Chaque fonction individuelle peut être appelée séparément depuis du
code applicatif (V2, par exemple pour exposer un dashboard web).
