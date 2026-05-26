# archives-tool items

Gestion en série des items d'un fonds. Pour la création unitaire,
passer par l'interface web ou l'import tableur.

## creer-serie

Crée N items placeholders en une transaction. Cas d'usage : préparer
les fiches d'une revue avant numérisation, pour pouvoir y rattacher
les scans au fil.

```bash
archives-tool items creer-serie \
    --fonds PF \
    --pattern "PF-{n:03d}" \
    --de 1 --a 60 \
    --titre "Por Favor n°{n}"
```

Crée 60 items `PF-001` à `PF-060` dans la miroir du fonds Por Favor,
avec titre `Por Favor n°1` à `Por Favor n°60`, état initial
`brouillon`.

### Options

| Option | Type | Défaut | Description |
|---|---|---|---|
| `--fonds`, `-f` | str | obligatoire | Cote du fonds dans lequel créer les items. |
| `--pattern`, `-p` | str | obligatoire | Template de cote avec variable `{n}` (ou `{n:03d}` pour zéro-padding). |
| `--de` | int | `1` | Numéro de départ (inclus). |
| `--a` | int | obligatoire | Numéro de fin (inclus). |
| `--titre` | str | `""` | Template du titre (variable `{n}`). Vide = titre vide. |
| `--collection`, `-c` | str | miroir | Cote de la collection cible. Omettre pour utiliser la miroir du fonds. |
| `--etat` | str | `brouillon` | État de catalogage initial (`brouillon`, `a_verifier`, `verifie`, `valide`, `a_corriger`). |
| `--type-coar` | str | — | URI COAR appliqué à tous les items. |
| `--langue` | str | — | Code langue (ISO 639-3 ou 639-1) appliqué à tous les items. |
| `--ignorer-existants` | flag | off | Ignorer silencieusement les cotes déjà présentes. |
| `--utilisateur`, `-u` | str | — | Nom à inscrire dans `cree_par`. |

### Pattern de cote

Le pattern est un template Python `str.format` avec la variable `{n}`
(numéro courant, entier). Quelques exemples :

| Pattern | n=1, 2, 50 |
|---|---|
| `PF-{n}` | `PF-1`, `PF-2`, `PF-50` |
| `PF-{n:03d}` | `PF-001`, `PF-002`, `PF-050` |
| `2024-{n:04d}` | `2024-0001`, `2024-0002`, `2024-0050` |

Le pattern doit produire des cotes **distinctes** (variable `{n}`
présente). Un pattern fixe comme `PF-fixe` est refusé en amont (sinon
toutes les cotes seraient identiques → conflit à l'insert).

### Titre template

Mêmes variables que le pattern. Si vide, les items sont créés sans
titre — vous les remplirez plus tard via inline edit.

```bash
--titre "Por Favor n°{n}"      # produit "Por Favor n°1", "Por Favor n°2", ...
--titre ""                       # titre vide pour tous
```

### Conflits de cote

Par défaut, si **une seule** cote de la plage existe déjà dans le
fonds, l'appel est refusé en entier (aucun item créé, message
détaillant les cotes en conflit). Cohérent avec le caractère
transactionnel.

Avec `--ignorer-existants`, les cotes en conflit sont silencieusement
sautées et le reste de la série est créé. Pratique pour rejouer la
commande après une interruption ou compléter une plage existante :

```bash
# 1er appel : crée PF-001 à PF-060
archives-tool items creer-serie -f PF -p "PF-{n:03d}" --de 1 --a 60

# Plus tard : étendre à PF-090, sans toucher les 60 premiers
archives-tool items creer-serie -f PF -p "PF-{n:03d}" \
    --de 1 --a 90 --ignorer-existants
# Sortie : « 30 item(s) créé(s) · 60 cote(s) ignorée(s) »
```

### Cap dur : 1000 items par appel

Garde-fou contre la création accidentelle de 100 000 items. Le besoin
typique (60-200 items par revue) est largement en-dessous. Pour
plus, faire plusieurs appels ou passer par l'import tableur.

### Rattachement à une libre

Avec `--collection`, les items sont rattachés à la collection cible
ET automatiquement à la miroir du fonds (invariant 6 : tout item est
dans sa miroir).

```bash
# Crée PF-EX-01 à PF-EX-05 dans la libre « Exemples » du fonds PF
archives-tool items creer-serie \
    --fonds PF --collection PF-EXEMPLES \
    --pattern "PF-EX-{n:02d}" --de 1 --a 5
```

Une transversale (sans `fonds_id`) accepte aussi des items via
`--collection`, mais le `--fonds` reste obligatoire (la cote item
est unique par fonds).

### Équivalent UI

Bouton **+ Créer une série** sur la page collection
(`/collection/<cote>?fonds=<f>`), à côté de **+ Ajouter des items**.
Le pattern est pré-rempli avec `{cote}-{n:03d}` pour démarrage rapide.

Le bouton est masqué sur les collections transversales (création
nécessite un fonds explicite) et en mode lecture seule. Le POST
direct vers `/collection/<cote>/items/serie` est également bloqué
par le middleware lecture seule (423).

### Codes de sortie

- `0` — succès
- `1` — erreur de validation (pattern invalide, plage trop large,
  cote en conflit sans `--ignorer-existants`, collection
  incompatible avec le fonds)
- `2` — saisie invalide (fonds inconnu, collection introuvable)

## Voir aussi

- [Création unitaire d'item](../interface-web.md) via l'interface web.
- [Import depuis un tableur](../../premiers-pas/premier-import.md) pour
  un démarrage à partir d'un inventaire papier.
- [Workflow type](../../premiers-pas/workflow-type.md) pour la
  position de la création en série dans le pipeline.
