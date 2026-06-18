# ShareDocs (CLI)

ShareDocs est le partage de fichiers WebDAV de la TGIR Huma-Num. ColleC
sait **parcourir** un partage et **importer** des fichiers vers un item,
**sans le monter** comme lecteur réseau — utile pour récupérer des scans
de travail depuis le partage institutionnel directement dans le catalogue.

Deux sous-commandes sous `archives-tool sharedocs …` :

1. [`lister`](#lister) — parcourir un dossier distant (lecture seule).
2. [`importer`](#importer) — télécharger des fichiers et les rattacher à
   un item (dry-run par défaut).

Une **variante web** équivalente existe sur la page `/sharedocs` (cf.
[Variante web](#variante-web)).

## Pré-requis

Une section `sharedocs:` dans le `config_local.yaml` fournit la base_url
et, optionnellement, une **liste blanche d'hôtes** autorisés :

```yaml
utilisateur: "Marie"
sharedocs:
  base_url: https://sharedocs.huma-num.fr/dav/votre-espace
  hotes_autorises:            # optionnel — restreint les hôtes joignables
    - sharedocs.huma-num.fr
racines:
  scans: /Users/marie/Archives/Scans   # racine cible de l'import
```

Les **identifiants** (utilisateur + mot de passe Basic Auth du compte
Huma-Num) ne sont **jamais** stockés sur disque ni en config. Ils se
passent par variables d'environnement, le temps de la commande :

```bash
export COLLEC_SHAREDOCS_USER="prenom.nom"
export COLLEC_SHAREDOCS_PASS="•••••••"     # mot de passe Huma-Num
```

!!! warning "Sécurité des identifiants"
    Le mot de passe ShareDocs est un secret de compte (pas un jeton
    révocable comme la clé API Nakala). ColleC ne l'écrit jamais sur
    disque, ne le journalise jamais, ne le renvoie jamais au navigateur.
    En CLI il vit dans l'environnement du shell ; en web, uniquement en
    mémoire du process (perdu au redémarrage). Le stockage chiffré
    multi-comptes est prévu pour la V1.0 (cf. déploiement).

Sécurité réseau (anti-SSRF), appliquée à chaque appel : **HTTPS exigé**,
hôte dans la liste blanche (si fournie), pas d'IP interne, pas de
`userinfo` dans l'URL, redirections non suivies, segments `..` refusés.

## Vue d'ensemble

| Commande   | Écrit ?            | Effet                                              |
| ---------- | ------------------ | -------------------------------------------------- |
| `lister`   | Non (lecture seule) | Liste un dossier distant (dossiers + fichiers).    |
| `importer` | Oui (`--no-dry-run`) | Télécharge des fichiers → `Fichier` rattachés à un item. |

**Format de sortie** : `--format text` (défaut) ou `--format json`
(scripts). **Codes de sortie** : `0` succès · `2` config / saisie
invalide (base_url ou identifiants absents, hôte interdit, chemin `..`,
racine inconnue) · `1` erreur d'exécution (identifiants refusés,
partage injoignable, item introuvable).

## `lister`

Parcourt un dossier distant. Aucune écriture (ni base, ni disque).

```bash
# Racine du partage
archives-tool sharedocs lister

# Un sous-dossier
archives-tool sharedocs lister "Revue/1974"

# JSON (nom, chemin, est_dossier, taille, modifie_le)
archives-tool sharedocs lister "Revue" --format json

# Surcharger la base_url de la config (essai ponctuel)
archives-tool sharedocs lister --base-url https://sharedocs.huma-num.fr/dav/autre
```

Sortie texte : `[D]` préfixe les dossiers, la taille en octets suit les
fichiers. Un dossier vide affiche `(dossier vide)`.

## `importer`

Télécharge des fichiers distants et crée des `Fichier` rattachés à un
item, sous `<racine>/<cote>/<nom>`. **Dry-run par défaut** : sans
`--no-dry-run`, ColleC affiche un aperçu fidèle (ce qui serait retenu /
sauté) sans rien télécharger ni écrire.

```bash
# Aperçu (dry-run) — rien n'est écrit
archives-tool sharedocs importer PF-014 "Revue/1974/pf014/p01.jpg" "Revue/1974/pf014/p02.jpg" \
    --fonds PF --racine scans

# Import réel
archives-tool sharedocs importer PF-014 "Revue/1974/pf014/p01.jpg" \
    --fonds PF --racine scans --no-dry-run --utilisateur "Marie"
```

| Option            | Rôle                                                            |
| ----------------- | --------------------------------------------------------------- |
| `COTE` (argument) | Cote de l'item cible.                                            |
| `CHEMINS…` (args) | Un ou plusieurs chemins distants à importer.                    |
| `--fonds` / `-f`  | Cote du fonds de l'item (désambiguïse la cote).                 |
| `--racine`        | Racine logique cible (déclarée dans `config_local.yaml`).      |
| `--no-dry-run`    | Applique (sinon : aperçu sans écriture).                        |
| `--utilisateur`   | Renseigne `ajoute_par` sur les `Fichier` créés.                |

**Idempotent et auto-réparant.** Ré-importer les mêmes fichiers ne crée
pas de doublon (raison `deja_en_base`) ; un binaire déjà présent sur
disque sans pendant en base (import précédent interrompu) est **adopté**
sans re-téléchargement (`rattache_disque`). **Succès partiel** : un
fichier en échec (téléchargement ou écriture) est consigné et sauté, le
reste du lot continue. L'aperçu et le rapport listent par fichier la
raison de chaque saut (`nom_invalide`, `chemin_invalide`, `collision_nom`,
`deja_en_base`, `echec_telechargement`, `echec_ecriture`).

L'écriture disque est **atomique** (fichier temporaire puis `replace`),
les noms sont normalisés en NFC, et un chemin distant contenant `..` est
rejeté (anti-traversal) — conforme aux principes directeurs (jamais de
modification de fichier utilisateur sans aperçu, portabilité des chemins).

## Variante web

La page `/sharedocs` (lien **ShareDocs** dans l'en-tête) offre le même
flux dans le navigateur :

1. **Connexion** — base_url + identifiants, **validés par un PROPFIND**
   avant d'être mémorisés (en RAM uniquement). Masquée en lecture seule.
2. **Parcours** — navigation dans les dossiers + fil d'Ariane.
3. **Import** — cases à cocher sur les fichiers, choix de la cible (fonds
   + item + racine), **aperçu dry-run** puis **confirmation**. L'import
   est bloqué (423) en mode lecture seule.

La CLI reste l'outil de référence pour les imports volumineux ou
scriptés (journalisation, reprise simple, pas de risque d'onglet fermé).
