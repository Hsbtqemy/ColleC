# Services métier

Vue d'ensemble de la couche services et exemples de composabilité
Python. Les services sont la **source de vérité** des opérations
métier — la CLI, l'API web et les importers les réutilisent pour
ne jamais dupliquer la logique des invariants.

## Organisation

```
src/archives_tool/api/services/
├── _erreurs.py            # Hub erreurs métier + helpers
├── fonds.py
├── collections.py
├── items.py
├── collaborateurs_fonds.py
├── dashboard.py           # Composeurs pour pages web/CLI
├── preferences.py         # PreferencesAffichage
├── sources_image.py       # Résolution IIIF Nakala / DZI / aperçu
├── tri.py                 # Listage[T] générique (tri + pagination)
└── ...
```

Chaque service expose typiquement :

- un **formulaire Pydantic** pour les entrées (par ex.
  `FormulaireFonds`, `FormulaireItem`, `FormulaireCollection`) ;
- des **fonctions CRUD** (`creer_X`, `lire_X_par_cote`,
  `modifier_X`, `supprimer_X`, `lister_X`) ;
- des **erreurs métier nommées** (`FondsIntrouvable`,
  `CollectionIntrouvable`, `FormulaireInvalide`,
  `OperationCollectionInterdite`, …).

## Helpers partagés

[`services/_erreurs.py`]({{ repo_main }}/src/archives_tool/api/services/_erreurs.py)
expose :

- bases d'erreurs (`EntiteIntrouvable`, `FormulaireInvalide`,
  `OperationInterdite`) — toutes les erreurs métier en héritent ;
- helpers de validation (`chaine_ou_none`, `PATTERN_COTE`,
  `valider_cote`).

## Composabilité Python

Vous pouvez utiliser les services directement depuis du code
Python sans passer par la CLI ou l'API web. Quelques exemples
courants :

### Lire un fonds et ses items

```python
from sqlalchemy import select

from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Item

engine = creer_engine("data/archives.db")
factory = creer_session_factory(engine)

with factory() as db:
    fonds = lire_fonds_par_cote(db, "HK")
    items = list(
        db.scalars(select(Item).where(Item.fonds_id == fonds.id))
    )
    for item in items:
        print(item.cote, item.titre)
```

### Composer une vue de page (utilisée par CLI `montrer` et l'UI web)

```python
from archives_tool.api.services.dashboard import composer_page_item
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.api.services.items import lire_item_par_cote

with factory() as db:
    fonds = lire_fonds_par_cote(db, "HK")
    item = lire_item_par_cote(db, "HK-001", fonds.id)
    page = composer_page_item(db, item)

    print(f"Item dans {len(page.collections)} collection(s)")
    for col in page.collections:
        print(f"  - {col.titre} ({col.type_collection})")
```

### Créer un fonds + items via les services

```python
from archives_tool.api.services.fonds import (
    creer_fonds, FormulaireFonds,
)
from archives_tool.api.services.items import (
    creer_item, FormulaireItem,
)

with factory() as db:
    fonds = creer_fonds(db, FormulaireFonds(
        cote="TEST", titre="Fonds test",
    ))
    # La collection miroir est créée automatiquement (INV1).

    item = creer_item(db, FormulaireItem(
        fonds_id=fonds.id,
        cote="TEST-001",
        titre="Item de test",
    ))
    # L'item est ajouté automatiquement à la miroir (INV6).

    db.commit()
```

### Gérer les erreurs métier

```python
from archives_tool.api.services.fonds import (
    FondsIntrouvable, lire_fonds_par_cote,
)

try:
    fonds = lire_fonds_par_cote(db, "INCONNU")
except FondsIntrouvable:
    print("Pas trouvé.")
```

Les erreurs métier sont nommées et hiérarchisées. Captez-les
explicitement plutôt qu'`Exception` générique.

## Conventions

Les services **ne font jamais** :

- d'`INSERT` / `UPDATE` / `DELETE` brut hors d'une fonction CRUD
  documentée ;
- d'écriture sur le système de fichiers (réservé à `files/`,
  `derivatives/`, `renamer/`) ;
- de `commit` implicite — c'est au caller de décider du moment
  (les services font `db.flush()` quand nécessaire pour récupérer
  un id, mais laissent le `commit` au caller pour permettre la
  composition transactionnelle).

Les services **font toujours** :

- valider les entrées via Pydantic (formulaires) ;
- lever des erreurs métier nommées (pas `Exception` générique) ;
- respecter les invariants (idempotence, transactions atomiques).

## Voir aussi

- [Modèle de données](modele.md) — tables, invariants, FK.
- [Tests](tests.md) — comment les invariants sont validés.
- Code source :
  [`src/archives_tool/api/services/`](https://github.com/Hsbtqemy/ColleC/tree/main/src/archives_tool/api/services).
