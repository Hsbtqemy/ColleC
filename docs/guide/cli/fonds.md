# `archives-tool fonds`

Gestion des fonds depuis la CLI. Le fonds est l'entité racine du
modèle (cf. [Concepts](../concepts.md)) — il porte les items et
ouvre/ferme une miroir auto-créée. Sa suppression est la cascade
la plus destructive du projet.

## Sous-commandes

| Commande                        | Sens                                                                       |
| ------------------------------- | -------------------------------------------------------------------------- |
| `supprimer COTE`                | Supprime un fonds et toute sa descendance (irréversible, double-confirmation côté UI). |

D'autres sous-commandes (création, listing, modification) passent
actuellement par d'autres voies (UI web, profil d'import,
`archives-tool importer`). La CLI ne propose pour l'instant que
la suppression, qui est l'opération difficilement accessible
autrement quand il faut nettoyer en lot.

## supprimer

Supprime un fonds et toute sa descendance. Demande une confirmation
interactive par défaut, avec un récap détaillé des cascades.

```bash
archives-tool fonds supprimer COTE [OPTIONS]
```

### Arguments

| Argument | Sens                       |
| -------- | -------------------------- |
| `COTE`   | Cote du fonds à supprimer. |

### Options

| Option           | Défaut             | Sens                                |
| ---------------- | ------------------ | ----------------------------------- |
| `--yes`, `-y`    | `False`            | Sauter la confirmation interactive. |
| `--db-path PATH` | `data/archives.db` | Chemin de la base SQLite.           |

### Exemples

Cas typique — annuler un import foireux :

```bash
archives-tool fonds supprimer PF
```

Affiche un récap, puis `Confirmer ? [y/N]` :

```
Supprimer le fonds PF — Por Favor ?
  173 item(s) + 7454 fichier(s) + annotations seront supprimés.
  La miroir 'PF' sera supprimée.
  2 collection(s) libre(s) rattachée(s) deviendront transversales
  (préservées) : PF-EXIL, PF-CARICATURES
```

Sans confirmation (pour scripts) :

```bash
archives-tool fonds supprimer PF --yes
```

### Effets de la suppression

La cascade est dirigée par le modèle ORM et les FK SQL :

- **Items du fonds** : supprimés en cascade (FK `Item.fonds_id`
  `ON DELETE CASCADE`), avec leurs **fichiers** et **annotations**
  IIIF qui suivent.
- **Collection miroir** : supprimée explicitement par le service
  (un CHECK SQL impose `miroir.fonds_id IS NOT NULL`, donc on ne
  peut pas la laisser orpheline).
- **Collaborateurs du fonds** (`CollaborateurFonds`) : supprimés
  en cascade.
- **Collections libres rattachées** au fonds : leur `fonds_id`
  passe à `NULL` (FK `ON DELETE SET NULL`) — elles deviennent
  **transversales**. Le travail de classement manuel est préservé.
  Les items présents dans ces libres sont déjà partis avec le
  fonds.

### Quand utiliser cette commande

- Nettoyer un import qui a foiré avant validation (granularité
  mauvaise, cote de fonds en doublon, etc.).
- Retirer un fonds de test après expérimentation.
- Sortir un fonds qui était hébergé sur la même instance avant
  de le pousser sur une instance dédiée (cf. *Une instance =
  une DB = un contexte* dans CLAUDE.md).

Pour les cas où on veut juste supprimer des fichiers en cascade
sans toucher au fonds entier, utiliser
[`archives-tool items supprimer`](items.md#supprimer).

### Codes de sortie

- `0` — succès
- `1` — fonds inconnu, ou utilisateur a refusé la confirmation
  interactive (`n` au prompt)

## Voir aussi

- [`archives-tool collections supprimer`](collections.md#supprimer)
  pour une collection libre seule.
- [`archives-tool items supprimer`](items.md#supprimer) pour un
  item seul.
- [Concepts](../concepts.md) pour la sémantique miroir / libre
  rattachée / transversale.
