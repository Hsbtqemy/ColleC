# Contrôles de cohérence

Le module `qa` permet de vérifier la cohérence d'une base
archives-tool. Tous les contrôles sont **en lecture seule** : aucun
`db.add` ni `db.commit`. On peut les exécuter sur une base de
production sans risque.

## Familles de contrôles

| Famille        | Contrôles                                  | Sévérités principales |
|----------------|--------------------------------------------|------------------------|
| `invariants`   | INV1, INV2, INV4, INV6                     | erreur (sauf INV6)     |
| `fichiers`     | FILE-MISSING, FILE-ITEM-VIDE, FILE-HASH-DUPLIQUE, FILE-HASH-MANQUANT | avertissement / info |
| `metadonnees`  | META-COTE-INVALIDE, META-TITRE-VIDE, META-DATE-INVALIDE, META-ANNEE-IMPLAUSIBLE | erreur / avertissement |
| `cross`        | CROSS-COTE-DUPLIQUEE-FONDS, CROSS-FONDS-VIDE | erreur / info        |

## Tableau des contrôles

| ID                          | Sévérité       | Description                                                                  |
|-----------------------------|----------------|------------------------------------------------------------------------------|
| `INV1`                      | erreur         | Tout fonds a exactement une collection miroir.                               |
| `INV2`                      | erreur         | Toute collection miroir a `fonds_id` non null.                               |
| `INV4`                      | erreur         | Tout item a `fonds_id` non null (filet de sécurité — NOT NULL en DB).        |
| `INV6`                      | avertissement  | Tout item est dans la miroir de son fonds (le retrait est légitime, info).   |
| `FILE-MISSING`              | avertissement  | Fichier référencé en base mais absent du disque (ou racine non configurée). |
| `FILE-ITEM-VIDE`            | info           | Item sans fichier rattaché.                                                 |
| `FILE-HASH-DUPLIQUE`        | avertissement  | Plusieurs fichiers ACTIF avec même hash SHA-256.                            |
| `FILE-HASH-MANQUANT`        | info           | Fichier ACTIF sans hash calculé.                                            |
| `META-COTE-INVALIDE`        | erreur         | Cote (fonds/collection/item) hors pattern `^[A-Za-z0-9_-]+$`.               |
| `META-TITRE-VIDE`           | erreur         | Titre vide ou whitespace-only sur fonds/collection/item.                    |
| `META-DATE-INVALIDE`        | avertissement  | `Item.date` ne reconnaît pas la regex EDTF tolérante.                       |
| `META-ANNEE-IMPLAUSIBLE`    | avertissement  | `Item.annee` hors `[1000, 2100]` (plage par défaut).                        |
| `CROSS-COTE-DUPLIQUEE-FONDS`| erreur         | Plusieurs fonds avec la même cote (filet — UNIQUE en DB).                   |
| `CROSS-FONDS-VIDE`          | info           | Fonds créé mais sans aucun item (cas légitime, signalé pour info).          |

## CLI

```bash
# Contrôle complet, sortie texte avec couleurs.
uv run archives-tool controler

# Restreint à un fonds.
uv run archives-tool controler --fonds HK

# Restreint à une collection (avec --fonds pour désambiguïser si
# la cote est partagée).
uv run archives-tool controler --collection HK-FAVORIS --fonds HK

# Sortie JSON pour CI / outillage.
uv run archives-tool controler --format json > rapport.json

# Strict : exit 1 dès qu'un avertissement OU info remonte.
uv run archives-tool controler --strict

# Limiter le nombre d'exemples affichés (compteurs restent exacts).
uv run archives-tool controler --max-exemples 10
```

### Options

| Option               | Défaut             | Sens                                                 |
|----------------------|--------------------|------------------------------------------------------|
| `--fonds COTE`       | (base entière)     | Limite aux entités du fonds. Mutex avec `--collection`. |
| `--collection COTE`  | (base entière)     | Limite aux items de la collection. Mutex avec `--fonds`. |
| `--format text\|json`| `text`             | Format de sortie.                                    |
| `--strict`           | `False`            | Exit 1 dès qu'un avertissement / info remonte.       |
| `--max-exemples N`   | `5`                | Tronque l'échantillon des exemples (text seulement). |
| `--db-path PATH`     | `data/archives.db` | Chemin de la base SQLite.                            |
| `--config PATH`      | `config_local.yaml`| Config locale (racines). Optionnelle.                |

### Codes de sortie

| Code | Sens                                                                   |
|------|------------------------------------------------------------------------|
| `0`  | Aucune erreur (les avertissements/infos passent en mode normal).       |
| `1`  | Erreur métier détectée OU `--strict` avec avertissement/info OU collection/fonds introuvable. |
| `2`  | Erreur de saisie (`--fonds` + `--collection`, format invalide, base absente). |

## Format JSON (intégration CI)

Structure stable, documentée pour intégration CI. Pas de breaking
change avant V1.0 ; toute évolution incompatible bumpera
`version_qa`.

```json
{
  "version_qa": "0.9.0",
  "horodatage": "2026-05-10T14:23:00+00:00",
  "perimetre": {
    "type": "base_complete",
    "fonds_id": null,
    "collection_id": null,
    "fonds_count": 5,
    "collections_count": 10,
    "items_count": 333,
    "fichiers_count": 1298
  },
  "controles": [
    {
      "id": "INV1",
      "famille": "invariants",
      "severite": "erreur",
      "libelle": "Collection miroir unique par fonds",
      "passe": true,
      "compte_total": 5,
      "compte_problemes": 0,
      "exemples": []
    },
    {
      "id": "INV6",
      "famille": "invariants",
      "severite": "avertissement",
      "libelle": "Item dans la collection miroir de son fonds",
      "passe": false,
      "compte_total": 333,
      "compte_problemes": 1,
      "exemples": [
        {
          "message": "Item FA-OEUVRES-005 retiré de la miroir du fonds FA",
          "references": {
            "item_cote": "FA-OEUVRES-005",
            "item_id": 142,
            "fonds_cote": "FA"
          }
        }
      ]
    }
  ],
  "bilan": {
    "erreurs": 0,
    "avertissements": 1,
    "infos": 1
  }
}
```

## Comment interpréter les avertissements

Sur une base demo (chemins fictifs sans fichiers physiques) :

- `FILE-MISSING` (avertissement) : tous les fichiers signalent
  « racine non configurée » → c'est attendu, la base demo ne
  pointe vers aucun disque.
- `FILE-HASH-MANQUANT` (info) : aucun fichier n'a de hash → également
  attendu, le seeder ne calcule pas de SHA-256.
- `INV6` (avertissement) : retirer un item de sa miroir est
  explicitement permis par l'invariant 7 du modèle (l'item reste
  dans le fonds, juste plus dans la sélection « tous les items »).
  Le contrôle informe sans bloquer.

## Sémantique du périmètre

`--fonds` et `--collection` filtrent les contrôles qui peuvent
l'être (familles `invariants`, `fichiers`, `metadonnees`). Les
contrôles `cross` opèrent toujours sur la base entière : la
duplication de cote ou un fonds vide sont des problèmes globaux
dont la détection ne dépend pas du périmètre.

## Composabilité depuis Python

Chaque contrôle est appelable individuellement :

```python
from archives_tool.qa import (
    composer_perimetre,
    controler_inv1_miroir_unique,
)

perimetre = composer_perimetre(session)
resultat = controler_inv1_miroir_unique(session, perimetre)
print(resultat.passe, resultat.compte_problemes)
```

Toute la suite est exportée depuis `archives_tool.qa`. Les
`ResultatControle` sont immuables (`@dataclass(frozen=True)`) et
sérialisables JSON via `formatter_rapport_json`.

## Lecture seule garantie

Aucun contrôle ne fait `db.add` ni `db.commit`. On peut exécuter
`archives-tool controler` sur une base de production sans risque.
