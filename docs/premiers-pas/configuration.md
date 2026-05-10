# Configuration

ColleC distingue deux niveaux de configuration :

- **Locale par poste** (`config_local.yaml`) : nom de l'utilisateur,
  chemins absolus vers les scans et les dérivés. Hors dépôt Git.
- **Partagée** (en base, dans le dépôt) : profils d'import,
  vocabulaires, templates de nommage. Versionnée.

Cette page concerne la config locale, à faire une fois par poste.

## Le fichier `config_local.yaml`

À la racine du projet, créer un fichier `config_local.yaml`. La
CLI le lit par défaut depuis cet emplacement ; chaque commande
accepte aussi `--config <chemin>` pour pointer ailleurs.

### Exemple minimal

```yaml
utilisateur: "Marie Dupont"
racines:
  scans: /Users/marie/Archives/Scans
```

- `utilisateur` : nom inscrit dans les champs d'audit (`cree_par`,
  `modifie_par`, etc.). Chaîne libre — pas de contrôle d'unicité.
  Si plusieurs personnes utilisent le même poste, changer cette
  valeur en début de session.
- `racines` : map nom logique → chemin absolu. Au moins une
  racine, typiquement `scans` pour les fichiers source.

### Exemple plus riche

```yaml
utilisateur: "Marie Dupont"

racines:
  scans_revues: /Users/marie/Archives/Revues
  scans_archives: /Volumes/NAS/Archives/Manuscrits
  miniatures: /Users/marie/Archives/.miniatures
  externe_cd: /Volumes/CD-1995/Scans
```

Plusieurs racines permettent de répartir les scans selon leur
nature ou leur emplacement physique. Les profils d'import et la
configuration des dérivés référencent les racines par leur nom
logique, jamais par chemin absolu.

## Pourquoi des racines logiques ?

Le modèle stocke les fichiers sous forme `(racine logique, chemin
relatif)` — jamais en absolu. Conséquences :

- **Portabilité Mac / Windows / Linux** : le même base SQLite
  fonctionne sur n'importe quel poste, chacun configurant ses
  propres racines.
- **Mobilité** : si vos scans bougent vers un nouveau disque, il
  suffit de modifier `config_local.yaml`. Aucune mise à jour en
  base nécessaire.
- **Travail en équipe** : la base peut être partagée (sur un
  serveur), chaque collègue garde ses propres racines locales.

## La base de données

Par défaut, la CLI utilise `data/archives.db` à la racine du
projet. Le fichier est créé automatiquement au premier
`archives-tool importer`, ou par `archives-tool demo init`
qui produit une base peuplée prête à explorer. Pour utiliser un
autre chemin :

- une fois sur la commande : `archives-tool montrer fonds --db-path /chemin/vers/base.db`,
- via la variable d'environnement `ARCHIVES_DB` (lue par
  l'interface web, pratique pour pointer la base de démo) :

  === "macOS / Linux"

      ```bash
      export ARCHIVES_DB=data/demo.db
      ```

  === "Windows (PowerShell)"

      ```powershell
      $env:ARCHIVES_DB = "data/demo.db"
      ```

La base est en SQLite, mode WAL activé, foreign keys ON. Pas de
serveur à démarrer — un fichier suffit.

### Migrations

Le schéma évolue par migrations Alembic. Après un `git pull` qui
contient de nouvelles migrations :

```bash
uv run alembic upgrade head
```

À l'initialisation de la base demo (`archives-tool demo init`),
les migrations sont appliquées automatiquement.

## Variables d'environnement

| Variable      | Effet                                                   |
| ------------- | ------------------------------------------------------- |
| `ARCHIVES_DB` | Chemin de la base SQLite lue par l'API web (utile pour pointer la base de démo). La CLI, elle, prend le chemin via `--db-path`. |

## Vérification

Lister les fonds (après `demo init` ou un premier import) :

```bash
uv run archives-tool montrer fonds
```

Si le résultat est cohérent et que la commande termine en `0`,
votre configuration est OK.

## Et ensuite ?

[Premier import](premier-import.md) : importer un vrai (ou faux)
fonds depuis un tableur et un dossier de scans.
