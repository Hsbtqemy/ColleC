# Contribuer

ColleC a été développé pour les archives de l'Université de
Poitiers. Le code est public et les contributions sont les
bienvenues, mais pour l'instant le projet est maintenu par une
seule personne.

## Contexte

L'outil est conçu pour un usage spécifique (archives
universitaires, publication Nakala) mais le modèle de données est
suffisamment générique pour s'adapter à d'autres contextes
patrimoniaux.

## Installer pour développer

```bash
git clone https://github.com/Hsbtqemy/ColleC.git
cd ColleC
uv sync --all-extras
```

Pour lancer les tests, le linter, et prévisualiser la doc en
local : voir [Tests](tests.md).

## Patterns du projet

ColleC suit quelques patterns systématiques :

- **Pydantic Form models** pour toutes les saisies (UI et CLI)
- **Services métier** dans `api/services/` qui encapsulent la
  logique (les routes web et les CLI sont des couches fines)
- **Helpers d'erreurs partagés** dans `services/_erreurs.py`
- **Tests d'invariants** explicites pour le modèle Fonds /
  Collection / Item
- **Pattern PRG** pour les formulaires web

Avant d'ajouter du code, regarder le pattern correspondant dans
le module concerné.

### Migrations Alembic

Deux patterns obligatoires :

**1. Idempotence sur `create_table`.** Toute migration qui crée
une table doit pouvoir s'exécuter sur une base déjà créée via
`Base.metadata.create_all` (cas tests / startup applicatif où
l'engine est créé en parallèle des migrations). Pattern :

```python
def upgrade() -> None:
    if "ma_nouvelle_table" in inspect(op.get_bind()).get_table_names():
        return  # idempotent
    op.create_table(...)
```

Exemples : `q5u6v7w8x9y0_operation_entite`,
`t8x9y0z1a2b3_operation_push_nakala`.

**2. `batch_alter_table` + guard pour `add_column` sur table
existante.** Toute migration qui ajoute une colonne à une table
déjà touchée par un `batch_alter_table` antérieur **doit**
utiliser le guard idempotent + `batch_alter_table` au lieu de
`op.add_column` direct :

```python
def upgrade() -> None:
    bind = op.get_bind()
    if "ma_colonne" in {c["name"] for c in inspect(bind).get_columns("ma_table")}:
        return  # idempotent
    with op.batch_alter_table("ma_table") as batch_op:
        batch_op.add_column(sa.Column("ma_colonne", sa.String(40)))
```

Sans ce guard, les tests `test_migration.py` (parité metadata vs
migrations) plantent car `target_metadata + render_as_batch`
reconstruit la table avec le modèle final dans les migrations
antérieures. Exemples : `n2r3s4t5u6v7`, `s7w8x9y0z1a2`.

**3. `downgrade()` fonctionnelle pour toute migration
post-refonte V0.9.0-alpha.** La refonte (`g7l8m9n0o1p2`) est
non-réversible (décision documentée). Mais toute migration
postérieure DOIT avoir une `downgrade()` propre — validé par
`test_migration_downgrade_apres_refonte_v090_puis_upgrade_head_est_idempotent`
qui parcourt le cycle complet `upgrade head → downgrade
g7l8m9n0o1p2 → upgrade head` et compare les tables résultantes.

Pattern minimal :

```python
def upgrade() -> None:
    op.create_table(...)
    op.create_index(...)

def downgrade() -> None:
    op.drop_index(..., table_name=...)
    op.drop_table(...)
```

Pour un `add_column`, le `downgrade()` doit utiliser le même
`batch_alter_table` :

```python
def downgrade() -> None:
    with op.batch_alter_table("ma_table") as batch_op:
        batch_op.drop_column("ma_colonne")
```

## Niveau de stabilité

V0.9.0 est en release candidate. Le modèle de données est stable,
les fonctionnalités sont complètes. La V1.0 marquera la fin de la
stabilisation après usage en production. Pour des intégrations
critiques, attendre V1.0.

## Ouvrir une PR

- Forker le dépôt
- Créer une branche dédiée à votre changement
- S'assurer que `pytest` et `ruff` passent
- Ajouter des tests pour tout nouveau comportement
- Ouvrir une PR avec une description claire de ce qui change

Le suivi peut prendre du temps (mainteneur unique).

## Déploiement de la documentation

Le site MkDocs est déployé automatiquement sur GitHub Pages
depuis `main` via [`.github/workflows/docs.yml`]({{ repo_main }}/.github/workflows/docs.yml).

**Configuration initiale du dépôt** (à faire une seule fois par
quiconque cloue un fork ou re-déploie sur un autre repo) :

1. Sur GitHub, aller dans **Settings → Pages**.
2. Sous **Build and deployment**, choisir **Source: GitHub Actions**.
3. Ouvrir une PR ou pusher sur `main` qui touche `docs/**` ou
   `mkdocs.yml` — le workflow construit le site, dépose
   l'artefact, et la deuxième job (`deploy`) le publie.

Tant que cette source n'est pas activée, le workflow réussira son
build mais le déploiement ne fera rien de visible. Symptôme : pas
d'URL publique, action verte, `Settings → Pages` vide.

## Note sur la méthode de développement

ColleC est développé en grande partie avec l'assistance de
Claude Code. La méthode privilégiée :

1. Brief de session détaillé avant chaque cycle de travail
2. Implémentation par sessions thématiques (~3-8h)
3. Passe de revue/simplification après chaque session
4. Tests systématiques pour les invariants

Cette discipline permet de garder le code lisible et testable
malgré le rythme de développement soutenu.
