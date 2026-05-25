# Décisions d'architecture — déploiement et multi-utilisation

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises à l'issue du cycle V0.9.0 stable, en
    préparation de V0.9.1 (renforcement local) et V1.0
    (déploiement VPS + multi-utilisateurs).

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Trois contextes d'usage cibles

ColleC est conçu pour fonctionner dans trois contextes coexistants.
Chaque contexte a sa propre base SQLite et sa propre configuration
de racines de stockage. **Pas de partage de base SQLite entre
instances** (incompatible avec SQLite sur réseau partagé).

### 1. Mode local solo

Poste Hugo ou collègue isolé.

- App lancée localement (`uvicorn` ou CLI).
- Base SQLite locale (`data/archives.db`).
- Fichiers sur disques locaux et/ou ShareDocs monté en WebDAV.
- Une seule personne travaille sur cette base.
- Aucune authentification : utilisateur lu de `config_local.yaml`.
- C'est le mode actuellement supporté en V0.9.0 stable.

### 2. Mode local CLI seulement

Sous-cas du mode local, sans UI web. Pour des opérations FS pures :
renommage, dérivés, contrôles. Sur fichiers locaux ou ShareDocs.

### 3. Mode serveur partagé

VPS (Infomaniak ou équivalent), accessible via HTTPS.

- App déployée sur VPS, base SQLite sur le VPS (60 Go suffisent
  largement pour base + sauvegardes).
- Fichiers sur ShareDocs monté en WebDAV sur le VPS.
- Plusieurs utilisateurs (Hugo + 1-2 collègues) via leur
  navigateur.
- **Authentification simple** : table `Utilisateur`, page de
  login, cookie. Pas de mot de passe en V1.0 — c'est de
  l'attribution, pas de la sécurité forte.
- **Verrou optimiste** actif sur les éditions concurrentes.

## Stockage des fichiers

ShareDocs (Huma-Num) accessible en WebDAV est la solution
principale pour les fonds partagés et certains fonds personnels.
Volumétrie disponible : 300 Go par compte projet. Hugo a déjà un
compte ShareDocs.

Stratégie selon les fonds :

- **Fonds personnels lourds** (TIFF haute résolution) : disques
  locaux Hugo.
- **Fonds modestes ou destinés au partage** : ShareDocs.
- **Bascule local → ShareDocs** : possible (transfert manuel,
  mise à jour de la racine dans `config_local.yaml`).

Le modèle `Fichier` actuel (`racine` + `chemin_relatif`) est
**déjà compatible** : la racine est une clé qui pointe vers un
emplacement configuré séparément. Aucune modification du modèle
nécessaire pour supporter ShareDocs — seulement de la
configuration côté `config_local.yaml`.

Exemple `config_local.yaml` multi-racines :

```yaml
utilisateur: "Hugo"
racines:
  scans_locaux: D:/Archives/scans
  scans_ainsa: E:/Aínsa/TIFF
  miniatures_locales: D:/Archives/miniatures
  sharedocs_revues: /mnt/sharedocs/revues-numerisees
  sharedocs_manet: /mnt/sharedocs/manet
```

### Test de faisabilité ShareDocs WebDAV

À faire avant V1.0 (~30 min) :

1. Monter ShareDocs sur le poste Hugo.
2. Copier un fonds modeste.
3. Vérifier la latence d'ouverture des images dans la
   visionneuse.

Si trop lent, prévoir une stratégie de synchronisation locale
avec rsync plutôt qu'un mount direct.

## Authentification

### Mode local

Utilisateur lu de `config_local.yaml`. Pas de login. Identité
purement informative (`cree_par`, `modifie_par` en string libre —
déjà en place dans `TracabiliteMixin`).

### Mode serveur

Table `Utilisateur` simple : `id`, `nom`, `actif`, `peut_editer`.

- Page « Qui êtes-vous ? » à la première visite.
- Sélection dans la liste des utilisateurs actifs.
- Mémorisé en cookie de session.
- **Pas de mot de passe en V1.0** — c'est de l'attribution, pas de
  la sécurité forte.

Les utilisateurs sont créés par admin via CLI :

```bash
archives-tool utilisateurs ajouter --nom "Marie"
```

### Matrice d'identités (extension future)

Tirée des scénarios discutés en mai 2026 (consultation externe
pour vérification, contribution spécialiste, archivistes d'une
même institution travaillant sur fonds partiellement disjoints).

Tout utilisateur se positionne sur trois axes orthogonaux :

| Axe | Valeurs | Sémantique |
|---|---|---|
| **Permanence** | permanent / invité (date d'expiration) | Membre de l'équipe ou collaborateur ponctuel |
| **Droit** | éditeur / lecteur seul | Peut modifier ou seulement consulter |
| **Scope** | global / restreint (liste de `fonds_id`) | Voit tout / voit un sous-ensemble |

Rôles typiques comme combinaisons des trois axes :

- **Membre permanent de l'équipe** = permanent + éditeur +
  global. C'est le seul rôle livré en V1.0.
- **Membre avec scope** = permanent + éditeur + restreint.
  Future Marie qui édite uniquement HK et Manet, pas PF.
- **Conservateur observateur** = permanent + lecteur + global.
  Un directeur scientifique qui suit tout sans modifier.
- **Invité contributeur** = invité (avec date d'expiration) +
  éditeur + restreint (typiquement à un fonds). Le spécialiste
  externe qui corrige et propose des ajouts sur un fonds dont
  il est expert.
- **Invité consultation** = invité + lecteur + restreint. Le
  peer-reviewer qui vient vérifier l'état catalographique
  (`etat_catalogage`, items à corriger, traçabilité), ce qui
  n'est pas dans le portail public.

#### Modèle de données

Extension de `Utilisateur` avec quatre colonnes additionnelles
(à préparer en V1.0, à activer progressivement) :

```python
class Utilisateur(Base):
    id: Mapped[int]
    nom: Mapped[str]
    actif: Mapped[bool]
    peut_editer: Mapped[bool]              # existant V1.0

    # Extensions matrice (V1.x ou V2 selon besoin)
    permanent: Mapped[bool] = True         # invité si False
    expire_le: Mapped[date | None] = None  # date d'expiration si invité
    voit_tout: Mapped[bool] = True         # scope global si True
    fonds_editables: Mapped[list[int]]     # JSON array, vide si voit_tout
    fonds_visibles: Mapped[list[int]]      # JSON array, vide si voit_tout
    invite_par: Mapped[int | None]         # FK Utilisateur, qui a invité
```

`voit_tout=True` est la valeur par défaut compatible avec V1.0 ;
les listes `fonds_editables` / `fonds_visibles` ne sont
consultées que si `voit_tout=False`. Le passage à `voit_tout=False`
active le filtrage sans casser les comptes existants.

#### Plan de livraison

**V1.0** livre uniquement la combinaison **permanent + éditeur +
global** — c'est la cible « Hugo + 1-2 collègues » d'une même
institution travaillant en confiance. Les conflits sur fonds
partagés sont gérés par le **verrou optimiste** (`StaleDataError`
sur les champs `version`) déjà en place V0.9.1.

**V1.x — invité consultation** (lecture seule, scope restreint,
expiration). Plus simple à activer car le mode lecture seule
existe déjà (`middleware_lecture_seule`), il s'agit de le
restreindre par scope au lieu d'être global.

**V1.x ou V2 — invité contributeur** (édition avec scope
restreint, expiration). Demande l'activation effective du
filtrage par scope dans les services métier (`Item.fonds_id in
user.fonds_editables` avant toute opération d'écriture). Plus
de tests à écrire.

**V2+ — membre avec scope** (éditeur permanent, scope
restreint). Active le même filtrage, mais sans expiration.
Pertinent quand l'équipe grossit (5+ archivistes) ou quand
certains fonds doivent être éditables seulement par certains.

**V2+ — conservateur observateur** (lecteur permanent, scope
global). Cas particulier, peut s'activer en même temps que les
autres.

#### Cas concret : deux archivistes, fonds en commun

Hugo et Marie travaillent dans la même institution :

- Hugo édite PF et Manet par habitude.
- Marie édite HK et Manet par habitude.
- Manet est partagé.

**V1.0** : tous deux sont permanent + éditeur + global. Ils
voient les trois fonds. Convention sociale : on ne touche pas au
fonds de l'autre sauf Manet. Le verrou optimiste protège des
écrasements silencieux sur Manet (« cet item a été modifié par
Hugo depuis votre ouverture, recharger ou forcer ? »). Le
journal trace tout. Suffisant à cette échelle.

**Si jamais l'équipe grossit** (V1.x) : on bascule Hugo et Marie
en scope restreint (`fonds_editables = [PF, Manet]` pour Hugo,
`fonds_editables = [HK, Manet]` pour Marie). Les boutons
« Modifier » se désactivent visuellement sur les fonds hors
scope, mais la consultation reste possible. Aucune migration
douloureuse — juste deux champs à renseigner.

#### Filtrage des champs sensibles selon le rôle

Les `notes_internes` (privé chantier) restent invisibles même
pour les invités lecture, sauf flag explicite sur leur compte
(`voit_notes_internes: bool`). Les autres champs catalographiques
restent visibles. Cette filtration se fait au niveau du service
de composition (`composer_page_item` etc.), pas au niveau ORM —
pour ne pas dupliquer la logique de chargement.

## Verrou optimiste

Le champ `version: int` existe déjà sur `TracabiliteMixin` (toutes
tables éditables). Mais il n'est pas encore exploité comme verrou.

À câbler en V0.9.1 :

- À chaque sauvegarde, comparer la version reçue du formulaire
  avec la version actuelle en base.
- Si différentes : message « Cet item a été modifié par X depuis
  votre ouverture du formulaire. Recharger ou forcer ? »
- Si identiques : sauvegarder + incrémenter `version`.

Utile dans les deux modes — même en mode local, deux onglets
ouverts sur le même item peuvent créer un conflit.

## Mode lecture seule

Mode explicite désactivant tous les boutons d'édition. Activé
via :

- **Mode local** : option dans `config_local.yaml`
  (`mode: lecture_seule`).
- **Mode serveur** : flag sur la table `Utilisateur`
  (`peut_editer: bool`).

Utile pour exposer ColleC à un consultant occasionnel sans risque
de modification accidentelle.

## SQLite WAL

À vérifier dans `db.py` : `PRAGMA journal_mode = WAL` doit être
activé. Cela permet à SQLite de gérer correctement un écrivain +
plusieurs lecteurs concurrents sans bloquer.

Si pas activé : à activer en V0.9.1 (5 minutes de travail).

## Déploiement VPS (mode serveur)

Stack proposée :

- **Docker** + **docker-compose** pour empaqueter ColleC.
- **Caddy** ou **nginx** en reverse proxy avec HTTPS via
  Let's Encrypt.
- **Volume Docker** pour la base SQLite (persistance).
- **Mount WebDAV ShareDocs** configuré sur le VPS au démarrage du
  conteneur (via `davfs2` ou solution équivalente).
- **Sauvegarde quotidienne** de la base SQLite via `systemd timer`
  ou `cron` (cp daté + rsync vers stockage tiers, ou `restic` vers
  Backblaze B2).

Domaine à acquérir avant déploiement V1.0 (~12 € / an).

## Plan de développement

### V0.9.1 — Renforcement mode local (1 session ~6h)

Objectifs :

- Vérifier / activer SQLite WAL.
- Câbler le verrou optimiste sur `Item`, `Collection`, `Fonds` (le
  champ `version` existe déjà via `TracabiliteMixin`, à exploiter
  au save).
- Mode lecture seule explicite (activable via config en mode
  local ; en mode serveur via flag User mais l'auth User vient en
  V1.0, donc en V0.9.1 seulement le pattern config).
- Adaptation des routes pour gérer le verrou optimiste.
- Tests d'intégration vérifiant les conflits d'édition.
- Documentation utilisateur : « Installation locale + ShareDocs
  en WebDAV » pas-à-pas (Windows, macOS, Linux).

**Ne PAS traiter en V0.9.1** :

- Table `Utilisateur`, login, sessions (V1.0).
- Déploiement Docker / VPS (V1.0).
- Variable `ARCHIVES_MODE` (V1.0, on en a pas besoin tant qu'il
  n'y a pas de mode serveur).

### Test d'usage entre V0.9.1 et V1.0

Une à deux semaines avec V0.9.1 sur un mini-fonds réel. Identifier
les frictions UX avant déploiement. Si frictions bloquantes,
V0.9.2 avant V1.0.

### V1.0 — Déploiement VPS + multi-utilisateurs (2 sessions ~12h)

**Session 1 : Auth et adaptation modèle**

- Variable `ARCHIVES_MODE` (`local` | `serveur`), détectée au
  démarrage.
- Table `Utilisateur` (id, nom, actif, peut_editer).
- Migration Alembic.
- Page de login simple (sélection dans liste, cookie de session).
- Middleware FastAPI pour gérer la session.
- Adaptation des services pour utiliser l'utilisateur de session
  en mode serveur, `config_local.yaml` en mode local.
- CLI `archives-tool utilisateurs` (ajouter, lister, modifier,
  désactiver).
- Tests d'intégration des deux modes.
- Documentation de l'auth.

**Session 2 : Déploiement**

- `Dockerfile` multi-stage pour ColleC.
- `docker-compose.yml` avec ColleC + Caddy / nginx.
- Configuration mount WebDAV ShareDocs (`davfs2` dans le
  conteneur ou côté hôte selon la complexité).
- Configuration TLS Let's Encrypt.
- Script de déploiement (pull, build, restart).
- Script de sauvegarde quotidienne (cron + `restic` ou solution
  simple).
- Documentation déploiement complète :
  `docs/deploiement/vps.md`.
- Procédure de mise à jour : `docs/deploiement/maj.md`.
- Procédure de récupération depuis sauvegarde :
  `docs/deploiement/restore.md`.

## Décisions à conserver

- **Pas de partage de SQLite entre instances.** Chaque mode a sa
  propre base.
- **Modèle Fichier inchangé** pour supporter ShareDocs.
- **Auth V1.0 = attribution, pas sécurité forte** (réseau interne
  de confiance, pas d'auth forte avant un éventuel V2+).
- **Trois contextes coexistent** — code conditionnel sur
  `ARCHIVES_MODE` à éviter au maximum, préférer les services
  identiques partout avec injection de l'utilisateur courant
  par dépendance.
