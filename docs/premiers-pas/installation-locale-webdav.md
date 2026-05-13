# Installation locale + ShareDocs en WebDAV

V0.9.1 introduit le **renforcement du mode local** : verrou optimiste,
mode lecture seule activable, format JSON sur toute la CLI. Cette
page décrit le scénario d'usage qui justifie ces ajouts — partager
une base ColleC entre plusieurs catalogueurs **avant** de basculer
sur un déploiement serveur (V1.0).

L'idée : la base SQLite vit sur un partage réseau (ShareDocs / NFS /
SMB), chaque poste de travail monte ce partage en local et y accède
en lecture-écriture. SQLite supporte raisonnablement bien plusieurs
clients en lecture ; le verrou optimiste évite les conflits silencieux
quand deux personnes éditent simultanément le même item.

## Architecture cible

```
                ┌──────────────────────────┐
                │   Serveur ShareDocs      │
                │   /Marie/ColleC/         │
                │     ├── archives.db      │
                │     ├── scans_revues/    │
                │     └── miniatures/      │
                └──────────────────────────┘
                          ▲
                          │ WebDAV (HTTPS)
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   ┌────────┐        ┌────────┐        ┌────────┐
   │ Marie  │        │ Paul   │        │ Léo    │
   │ macOS  │        │ Win    │        │ Linux  │
   └────────┘        └────────┘        └────────┘
```

Chaque poste a ses propres `config_local.yaml` et son propre
nom utilisateur (`utilisateur:` distinct), mais pointe les
mêmes racines vers le partage monté.

## Pas-à-pas Windows

### Monter ShareDocs

1. Ouvrir l'Explorateur de fichiers.
2. Clic droit sur « Ce PC » → « Connecter un lecteur réseau… ».
3. Choisir une lettre (par exemple `Z:`).
4. Saisir l'URL WebDAV : `\\sharedocs.univ-poitiers.fr\DavWWWRoot\fonds\colleC`
   (adapter selon votre infra).
5. Cocher « Se reconnecter à la connexion ».
6. Authentifier avec votre compte universitaire.

Vérifier la connexion :

```powershell
dir Z:\
```

### Configurer ColleC

`config_local.yaml` à la racine du projet :

```yaml
utilisateur: "Marie Dupont"
racines:
  scans_revues: Z:/ColleC/scans_revues
  miniatures: Z:/ColleC/miniatures
```

Définir le chemin de la base partagée :

```powershell
$env:ARCHIVES_DB = "Z:/ColleC/archives.db"
uv run uvicorn archives_tool.api.main:app --reload
```

## Pas-à-pas macOS

### Monter ShareDocs

```bash
mkdir -p ~/mnt/sharedocs
mount_webdav https://sharedocs.univ-poitiers.fr/dav/fonds/colleC ~/mnt/sharedocs
```

Ou via le Finder : `⌘+K` puis l'URL.

### Configurer

```yaml
utilisateur: "Marie Dupont"
racines:
  scans_revues: /Users/marie/mnt/sharedocs/scans_revues
  miniatures: /Users/marie/mnt/sharedocs/miniatures
```

Lancer :

```bash
ARCHIVES_DB=~/mnt/sharedocs/archives.db uv run uvicorn archives_tool.api.main:app --reload
```

## Pas-à-pas Linux

### Monter ShareDocs (davfs2)

```bash
sudo apt install davfs2
sudo mkdir -p /mnt/sharedocs
sudo mount -t davfs https://sharedocs.univ-poitiers.fr/dav/fonds/colleC /mnt/sharedocs
```

Pour un montage automatique, ajouter à `/etc/fstab` :

```
https://sharedocs.univ-poitiers.fr/dav/fonds/colleC /mnt/sharedocs davfs user,noauto 0 0
```

### Configurer

```yaml
utilisateur: "Marie Dupont"
racines:
  scans_revues: /mnt/sharedocs/scans_revues
  miniatures: /mnt/sharedocs/miniatures
```

```bash
ARCHIVES_DB=/mnt/sharedocs/archives.db uv run uvicorn archives_tool.api.main:app --reload
```

## SQLite en mode WAL

ColleC active automatiquement le mode **WAL** (Write-Ahead Logging) à
chaque connexion. Conséquences :

- Plusieurs lecteurs peuvent travailler **en parallèle** sans
  bloquer ; un seul écrivain à la fois.
- Trois fichiers cohabitent à côté de `archives.db` :
  `archives.db-wal` et `archives.db-shm`. **Ne pas les supprimer
  manuellement** : SQLite les recompacte automatiquement.
- Sur un partage SMB/NFS bagging, WAL peut devenir instable.
  Si vous constatez des verrous étranges, repasser en mode `DELETE`
  via `PRAGMA journal_mode=DELETE;` — voir
  [SQLite Atomic Commit](https://sqlite.org/atomiccommit.html).

## Verrou optimiste

Quand deux personnes ouvrent le formulaire d'édition d'un item /
collection / fonds et le soumettent dans la même fenêtre temporelle :

1. Marie ouvre `/item/HK-001/modifier` (version=3).
2. Paul ouvre `/item/HK-001/modifier` (version=3).
3. Marie soumet → version passe à 4.
4. Paul soumet → l'app détecte la divergence, affiche un bandeau
   rouge :
   > **Conflit de version.** Cet item a été modifié entre-temps
   > (version 4 en base, vous avez 3). Vérifiez les valeurs et
   > resoumettez si vous souhaitez écraser.

Paul peut alors voir les modifications de Marie en rechargeant, ou
forcer son écrasement en resoumettant — la version actuelle est
injectée dans le formulaire, donc la seconde soumission passe.

## Mode lecture seule

Pour exposer ColleC à un consultant occasionnel sans risque d'édition
accidentelle, ajouter dans `config_local.yaml` :

```yaml
lecture_seule: true
```

Effets :

- Toute requête HTTP `POST` / `PUT` / `PATCH` / `DELETE` renvoie un
  **423 Locked** avec un message explicite.
- Un bandeau jaune apparaît en haut de chaque page de l'UI.
- Les `GET` continuent à fonctionner : navigation, consultation,
  exports JSON et CSV.

Le mode lecture seule n'est **pas une mesure de sécurité** : un
utilisateur qui édite `config_local.yaml` lui-même peut le
désactiver. C'est un garde-fou utilisable, pas un mécanisme
d'authentification (réservé à V1.0).

## Sauvegarde recommandée

Avant tout chantier de masse (renommage, import, contrôles), faire un
snapshot de la base :

```bash
sqlite3 Z:/ColleC/archives.db ".backup Z:/ColleC/backups/archives-$(date +%F).db"
```

Ce mécanisme respecte le mode WAL : il prend un snapshot cohérent
même pendant les écritures.
