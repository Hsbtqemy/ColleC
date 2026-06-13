# ColleC depuis un notebook Python

ColleC est **déjà** une bibliothèque Python utilisable depuis n'importe
quel script ou notebook Jupyter. Les services métier (`api/services/`),
les exporters et les modèles ORM sont importables et stables. Cette
page formalise cet usage, présente l'API publique et propose des
recettes courantes.

!!! info "Pourquoi cet usage"
    Pour les recherches qui demandent une exploration ad-hoc (DataFrame
    pandas, croisement avec une bibliothèque Zotero, statistiques
    chantier, enrichissement par API d'autorité, exports
    personnalisés), la CLI et l'UI suffisent rarement. L'API Python
    expose la même couche métier que la CLI et l'interface web — pas
    de duplication, pas de wrapper supplémentaire à apprendre.

## Setup

ColleC vit dans un environnement Python géré par
[uv](https://docs.astral.sh/uv/). Pour ouvrir un notebook qui peut
importer `archives_tool` :

```bash
# Depuis la racine du projet
uv pip install jupyter pandas
uv run jupyter lab
```

Dans le notebook :

```python
from archives_tool.db import obtenir_session
from archives_tool.api.services.fonds import lister_fonds

with obtenir_session() as db:
    for fonds in lister_fonds(db):
        print(fonds.cote, "·", fonds.titre)
```

### Choisir la base

`obtenir_session()` lit en priorité la variable d'environnement
`ARCHIVES_DB`, sinon `data/archives.db` par défaut. Pour cibler une
base spécifique sans toucher l'environnement :

```python
with obtenir_session("data/demo.db") as db:
    ...
```

L'engine est mis en cache par chemin (4 entrées max) — appels
répétitifs en notebook réutilisent le pool de connexions.

### Engagement de stabilité

L'API publique listée plus bas (services métier + exporters + ORM en
lecture) **ne casse pas entre versions mineures**. Ajout possible ;
suppression ou renommage uniquement en versions majeures, avec note
explicite dans le [changelog](../annexes/changelog.md).

Les modules `archives_tool.api.routes.*`, `archives_tool.api.deps.*`,
`archives_tool.web.*` et toute fonction préfixée `_` sont **internes**
et peuvent changer sans préavis.

## API publique

| Module | Contenu |
|---|---|
| `archives_tool.db` | `obtenir_session`, `creer_engine`, `creer_session_factory` |
| `archives_tool.api.services.fonds` | `lister_fonds`, `lire_fonds_par_cote`, `creer_fonds`, `modifier_fonds`, `supprimer_fonds` |
| `archives_tool.api.services.collections` | CRUD collections libres + transversales |
| `archives_tool.api.services.items` | `lister_items_fonds`, `lister_items_collection`, `lire_item_par_cote`, `creer_item`, `creer_items_en_serie`, `modifier_item`, `supprimer_item` |
| `archives_tool.api.services.dashboard` | `composer_dashboard`, `composer_page_fonds`, `composer_page_collection`, `composer_page_item` |
| `archives_tool.api.services.recherche` | `rechercher`, `Scope` |
| `archives_tool.api.services.collaborateurs_fonds` | Lister, ajouter, supprimer |
| `archives_tool.exporters._commun` | `composer_export(db, collection)` |
| `archives_tool.exporters.dublin_core` / `nakala` / `excel` | Exporters canoniques |
| `archives_tool.models` | `Fonds`, `Collection`, `Item`, `Fichier`, etc. — ORM SQLAlchemy |

Lecture libre via l'ORM, **écriture via les services** : les services
garantissent les invariants du modèle (Fonds ↔ miroir, cote unique par
fonds, journal des modifications, verrou optimiste).

## Six recettes

### 1. Charger les items d'un fonds en DataFrame pandas

```python
import pandas as pd
from archives_tool.db import obtenir_session
from archives_tool.api.services.items import lister_items_fonds
from archives_tool.api.services.fonds import lire_fonds_par_cote

with obtenir_session() as db:
    fonds = lire_fonds_par_cote(db, "HK")
    items = lister_items_fonds(db, fonds.id, par_page=0).items

df = pd.DataFrame([{
    "cote": i.cote,
    "titre": i.titre,
    "annee": i.annee,
    "langue": i.langue,
    "etat": i.etat,  # str (brouillon|a_verifier|verifie|valide|a_corriger)
} for i in items])

df.head()
```

`lister_items_fonds` retourne un `Listage[ItemResume]`. Quand
`par_page=0`, la liste est complète (pas de pagination). Pour itérer
page par page sur un gros fonds :

```python
def tous_items(db, fonds_id):
    page = 1
    while True:
        listage = lister_items_fonds(db, fonds_id, page=page, par_page=200)
        yield from listage.items
        if page >= listage.pages():
            return
        page += 1
```

### 2. Export CSV personnalisé non couvert par les exporters canoniques

Les exporters Dublin Core / Nakala / xlsx sortent des formats
canoniques. Pour un format ad-hoc (analyse interne, export vers un
outil tiers) :

```python
import csv
from pathlib import Path
from archives_tool.db import obtenir_session
from archives_tool.api.services.fonds import lire_fonds_par_cote
from archives_tool.api.services.items import lister_items_fonds

with obtenir_session() as db:
    fonds = lire_fonds_par_cote(db, "HK")
    items = lister_items_fonds(db, fonds.id, par_page=0).items

    sortie = Path("/tmp/hk_export.csv")
    with sortie.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cote", "titre", "année", "auteur principal"])
        for item in items:
            auteurs = (item.metadonnees or {}).get("createurs", [])
            w.writerow([
                item.cote, item.titre, item.annee or "",
                auteurs[0] if auteurs else "",
            ])
```

Pour un export à granularité fichier (1 ligne par scan), passer par
`composer_export(db, collection)` qui retourne un `CollectionPourExport` :

```python
from archives_tool.exporters._commun import composer_export
from archives_tool.api.services.collections import lire_collection_par_cote

with obtenir_session() as db:
    col = lire_collection_par_cote(db, "HK", fonds_cote="HK")
    paquet = composer_export(db, col)
    for ipe in paquet.items:  # ItemPourExport (item + fonds d'origine)
        for f in ipe.item.fichiers:
            print(ipe.item.cote, f.nom_fichier, f.hash_sha256)
```

### 3. Statistiques de chantier (jalons, complétion par état)

`composer_page_fonds` retourne déjà tous les agrégats du dashboard
fonds — utiles directement pour des graphes.

```python
from archives_tool.db import obtenir_session
from archives_tool.api.services.dashboard import composer_page_fonds

with obtenir_session() as db:
    detail = composer_page_fonds(db, "HK")
    jalons = detail.avancement_jalons
    print(f"Planifiés : {jalons.planifies}")
    print(f"Numérisés : {jalons.numerises} ({jalons.pourcentage(jalons.numerises):.0f}%)")
    print(f"Vérifiés  : {jalons.verifies}")
    print(f"Validés   : {jalons.valides}")
    print(f"Répartition par état : {detail.repartition_etats}")
```

Tracer la complétion comme stacked bar avec matplotlib :

```python
import matplotlib.pyplot as plt

rep = detail.repartition_etats
labels = list(rep.keys())
valeurs = [rep[k] for k in labels]
plt.figure(figsize=(8, 2))
plt.barh(["HK"], [sum(valeurs)], color="#e5e7eb")
offset = 0
for lab, val in zip(labels, valeurs):
    plt.barh(["HK"], [val], left=[offset], label=lab)
    offset += val
plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left")
plt.tight_layout()
```

### 4. Recherche full-text scriptée

`rechercher` expose le même moteur FTS5 que la barre globale de l'UI.
Le scope `Scope` cible un fonds, une collection ou tout.

```python
from archives_tool.db import obtenir_session
from archives_tool.api.services.recherche import Scope, rechercher

with obtenir_session() as db:
    rapport = rechercher(
        db, "Franco",
        scope=Scope(fonds_id=None, collection_id=None),  # global
        types={"item"},
    )
    for r in rapport.resultats:
        print(r.cote, "·", r.titre, "·", r.snippet)
```

Pour scoper sur un fonds précis :

```python
from archives_tool.api.services.fonds import lire_fonds_par_cote

with obtenir_session() as db:
    fonds = lire_fonds_par_cote(db, "HK")
    rapport = rechercher(
        db, "Cavanna",
        scope=Scope(fonds_id=fonds.id, collection_id=None),
        types={"item", "collection"},
    )
```

### 5. Croisement avec une bibliothèque Zotero (BibTeX local)

Avec `pyzotero` ou un parse `.bib` local, on peut résoudre un auteur
Zotero contre les items ColleC :

```python
from pathlib import Path
import bibtexparser
from archives_tool.db import obtenir_session
from archives_tool.api.services.items import lister_items_fonds
from archives_tool.api.services.fonds import lire_fonds_par_cote

bib = bibtexparser.load(Path("ma_biblio.bib").open(encoding="utf-8"))
auteurs_zotero = {
    auteur.strip()
    for entry in bib.entries
    for auteur in entry.get("author", "").split(" and ")
}

with obtenir_session() as db:
    fonds = lire_fonds_par_cote(db, "HK")
    items = lister_items_fonds(db, fonds.id, par_page=0).items
    for item in items:
        crea = (item.metadonnees or {}).get("createurs", [])
        recouvrement = set(crea) & auteurs_zotero
        if recouvrement:
            print(item.cote, "·", recouvrement)
```

Voir [`zotero-future.md`](https://github.com/Hsbtqemy/ColleC/blob/main/docs/developpeurs/zotero-future.md)
(doc interne) pour la stratégie d'intégration Zotero plus complète.

### 6. Enrichissement par API d'autorité (Wikidata)

Pour résoudre un libellé en URI Wikidata, utilisable ensuite dans une
annotation IIIF ou un export enrichi :

```python
import httpx

def chercher_wikidata(libelle: str, lang: str = "fr") -> str | None:
    """Première QID retournée par wbsearchentities, ou None."""
    r = httpx.get("https://www.wikidata.org/w/api.php", params={
        "action": "wbsearchentities",
        "search": libelle,
        "language": lang,
        "format": "json",
        "limit": 1,
    }, timeout=10)
    r.raise_for_status()
    hits = r.json().get("search", [])
    return f"https://www.wikidata.org/entity/{hits[0]['id']}" if hits else None

# Utilisation : enrichir un export
with obtenir_session() as db:
    fonds = lire_fonds_par_cote(db, "HK")
    items = lister_items_fonds(db, fonds.id, par_page=0).items
    for item in items[:5]:  # rate-limiter, pas plus de 5 essais
        crea = (item.metadonnees or {}).get("createurs", [])
        for nom in crea:
            uri = chercher_wikidata(nom)
            print(item.cote, "·", nom, "→", uri)
```

Pour un usage massif, prévoir cache local + rate limiting (Wikidata
demande max 5 requêtes/seconde sans User-Agent identifié).

## Pièges à éviter

### Ne pas concurrencer l'UI en écriture

Si un utilisateur édite un item via le navigateur pendant qu'un
notebook le modifie, le verrou optimiste (`version` sur `Item` /
`Collection` / `Fonds`) lève `ConflitVersion`. C'est correct — la
notice n'est pas écrasée silencieusement.

```python
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.api.services.items import (
    FormulaireItem, formulaire_depuis_item, modifier_item,
)

with obtenir_session() as db:
    item = lire_item_par_cote(db, "HK-001", fonds_id=fonds.id)
    form = formulaire_depuis_item(item)
    form.titre = "Nouveau titre"
    try:
        modifier_item(db, item.id, form, modifie_par="notebook-hugo")
    except ConflitVersion as e:
        print("Conflit :", e)
```

### Ne pas laisser une session ouverte sur la durée du notebook

Un notebook vit des heures. Une session SQLAlchemy ouverte tout du
long génère des verrous résiduels et bloque les autres lecteurs.

```python
# BIEN : context manager autour de chaque opération
with obtenir_session() as db:
    fonds = lister_fonds(db)
# session fermée, l'engine reste pooled pour le prochain `with`

# MAUVAIS : session ouverte indéfiniment
db = next(obtenir_session().__enter__().__enter__())  # ne pas faire
```

### Ne pas écrire directement via l'ORM

Les services métier (`modifier_item`, `creer_fonds`, etc.) **doivent**
être utilisés pour toute écriture. Ils :

- Vérifient les invariants (cote unique, fonds ↔ miroir, etc.).
- Posent la traçabilité (`modifie_par`, `modifie_le`).
- Tournent dans une transaction propre.
- Journalisent dans `OperationEntite` / `ModificationItem` pour les
  opérations destructives ou structurelles.

Écrire `item.titre = "X"; db.commit()` directement court-circuite tout
ça — la base se retrouve dans un état que la CLI et la web croient
impossible.

### Ne pas réécrire la logique des services

Si vous vous retrouvez à réécrire dans un notebook l'équivalent de
`lister_items_collection` avec un filtre additionnel, c'est sans
doute que la fonction de service mérite un nouveau paramètre. Ouvrir
une [issue GitHub](https://github.com/anthropics/claude-code/issues)
plutôt que de maintenir un workaround.

## Renvois

- [Exporters canoniques](../reference/exports.md) — Dublin Core,
  Nakala CSV, xlsx.
- [Recherche FTS5](recherche.md) — moteur partagé entre UI et API.
- [Annotations IIIF](annotations.md) — modèle W3C + autocomplete
  vocabulaire avec pivot URI.
