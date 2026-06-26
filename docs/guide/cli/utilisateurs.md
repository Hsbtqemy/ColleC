# archives-tool utilisateurs

Administration des **comptes utilisateur** — le référentiel d'identités
nommées du futur **mode serveur partagé**.

!!! note "Phase 1 — fondation"
    Cette commande livre le **modèle + l'administration** des comptes.
    En **mode local** (mode actuel, mono-utilisateur), l'identité vient
    toujours de `config_local.yaml` : cette table n'est **pas consultée**.
    Le login / la session (mode serveur) sont une **Phase 2** à venir
    (cf. [`deploiement-future.md`]). Créer des comptes maintenant prépare
    le terrain sans rien changer au comportement local.

Périmètre des comptes en V1.0 : **permanent + éditeur + global**
(`nom`, `actif`, `peut_editer`). La matrice scope / invité / expiration
viendra par une migration ultérieure, quand la fonctionnalité sera
réellement construite.

## ajouter

Crée un compte (actif, éditeur par défaut). Le `nom` est **unique**
(c'est l'identifiant de connexion).

```bash
archives-tool utilisateurs ajouter "Marie"
archives-tool utilisateurs ajouter "Hugo" --lecteur
```

| Option | Défaut | Sens |
|---|---|---|
| `NOM` (argument) | requis | Nom du compte, unique. Normalisé (NFC + trim). |
| `--lecteur` | off | Crée le compte en lecture seule (`peut_editer=False`). |
| `--db-path PATH` | `data/archives.db` | Chemin de la base SQLite. |

## lister

Affiche les comptes (nom, droit, état), triés par nom.

```bash
archives-tool utilisateurs lister
archives-tool utilisateurs lister --actifs-seuls
```

| Option | Défaut | Sens |
|---|---|---|
| `--actifs-seuls` | off | N'afficher que les comptes actifs (comme au login). |

## modifier

Renomme, change le droit d'écriture ou (ré)active un compte. Les
options non fournies laissent le champ **inchangé** (tri-state).

```bash
archives-tool utilisateurs modifier "Marie" --nom "Marie D."
archives-tool utilisateurs modifier "Hugo" --editeur
archives-tool utilisateurs modifier "Hugo" --inactif
```

| Option | Sens |
|---|---|
| `NOM` (argument) | Compte à modifier. |
| `--nom NOUVEAU` | Renommer (refusé si le nouveau nom est déjà pris). |
| `--editeur` / `--lecteur` | Donner / retirer le droit d'écriture. |
| `--actif` / `--inactif` | Réactiver / désactiver le compte. |

## desactiver

Soft delete : `actif=False`. Le compte est **masqué du login** mais
**conservé** pour la traçabilité (un compte qui a agi n'est jamais
supprimé physiquement). Réversible via `modifier --actif`.

```bash
archives-tool utilisateurs desactiver "Hugo"
```

## Codes de sortie

- `0` — succès
- `1` — erreur métier (nom déjà pris, compte introuvable)
- `2` — saisie invalide (nom vide)

## Bootstrap (mode serveur, futur)

Quand le mode serveur arrivera, le tout premier compte se créera par
cette CLI (il n'y a pas encore de session pour passer par le web) :

```bash
archives-tool utilisateurs ajouter "Hugo"
```

## Voir aussi

- [`deploiement-future.md`] — décisions auth/déploiement (document interne).
- [Identité simplifiée](../../reference/schema.md) — les champs d'audit
  `cree_par` / `modifie_par` restent des chaînes libres ; la table
  `utilisateur` est un référentiel de connexion, pas une contrainte sur
  ces champs.

[`deploiement-future.md`]: https://github.com/Hsbtqemy/ColleC/blob/main/docs/developpeurs/deploiement-future.md
