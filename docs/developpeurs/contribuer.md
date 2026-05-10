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

Lancer les tests :

```bash
uv run pytest
uv run ruff check .
```

Lancer la doc en local (live reload) :

```bash
uv run mkdocs serve
```

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
