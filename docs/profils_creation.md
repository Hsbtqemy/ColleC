# Créer un profil d'import — guide pour démarrer

Ce guide s'adresse aux utilisateurs qui n'ont jamais écrit de profil
YAML. Pour la **référence complète du format**, voir
[`profils.md`](profils.md).

## Deux façons de démarrer

### Vous avez déjà un tableur Excel ou CSV

```bash
archives-tool profil analyser inventaire.xlsx --sortie mon_profil.yaml
```

L'outil ouvre votre tableur, liste toutes les colonnes, et produit un
profil pré-rempli :
- les colonnes reconnues (Cote, Titre, Date, …) sont mappées vers les
  champs dédiés correspondants, marquées `# détecté` ;
- les autres colonnes sont rangées dans
  `metadonnees.<nom_normalisé>` ;
- toutes les sections optionnelles sont en commentaire prêtes à être
  décommentées et remplies.

Vous ouvrez ensuite le YAML dans votre éditeur, vérifiez la détection,
et ajustez (en général : séparateurs multivaleurs, agrégations,
métadonnées de la collection).

### Vous n'avez pas encore de tableur

```bash
archives-tool profil init --cote HK --titre "Hara-Kiri" \
    --tableur inventaire.xlsx --sortie mon_profil.yaml
```

Squelette minimal commenté à compléter manuellement. Le mapping
contient un placeholder `cote: "A_REMPLACER"` à remplacer par le nom
de la colonne qui contient les cotes dans votre tableur.

## Rappels rapides sur YAML

Trois règles suffisent pour 90 % des cas :

**Indentation** : 2 espaces, jamais de tab. L'indentation détermine la
hiérarchie.

```yaml
collection:
  cote: "HK"        # 2 espaces avant cote
  titre: "Hara-Kiri"
```

**Clés et valeurs** : `clé: valeur`. Les valeurs textuelles peuvent
être entre guillemets (recommandé) :

```yaml
titre: "Texte avec des espaces et des accents"
```

**Listes** : un tiret par élément, alignés.

```yaml
extensions:
  - ".tif"
  - ".jpg"
  - ".pdf"
```

## Flux recommandé pour un nouveau tableur

1. **Analyser** le tableur :
   ```bash
   archives-tool profil analyser inventaire.xlsx --sortie mon_profil.yaml
   ```

2. **Ouvrir** le YAML dans votre éditeur préféré.

3. **Vérifier les mappings auto**. Les lignes marquées `# détecté`
   sont les seules où l'outil a pris une décision. Une fausse
   détection est rare mais possible — corrigez si besoin (déplacez
   la ligne dans `metadonnees.<x>` ou supprimez-la).

4. **Compléter les métadonnées de collection**. Décommentez les lignes
   pertinentes :
   ```yaml
   collection:
     cote: "HK"
     titre: "Hara-Kiri"
     editeur: "Éditions du Square"        # à décommenter
     periodicite: "mensuel"
     date_debut: "1960"
     date_fin: "1985"
   ```

5. **Ajuster les colonnes multi-valeurs**. Les colonnes contenant des
   listes encodées (avec un séparateur) gagnent à être passées en
   forme objet :
   ```yaml
   metadonnees.collaborateurs:
     source: "Auteurs"
     separateur: " / "
   ```

6. **Activer la section fichiers** si vos scans doivent être
   rattachés. Décommentez et adaptez :
   ```yaml
   fichiers:
     racine: "scans_revues"          # nom logique de votre config locale
     motif_chemin: "{cote}/*.tif"
     type_motif: "template"
   ```

7. **Lancer un import en dry-run** pour contrôler :
   ```bash
   archives-tool importer mon_profil.yaml
   ```
   Le rapport indique combien d'items seraient créés, combien de
   fichiers seraient rattachés, et liste les erreurs ligne par ligne
   sans rien écrire en base. Tant que la sortie n'est pas propre, on
   ajuste le profil et on relance.

8. **Lancer l'import réel** quand tout est vert :
   ```bash
   archives-tool importer mon_profil.yaml --no-dry-run --utilisateur "Marie"
   ```

## Erreurs fréquentes

### Indentation incorrecte

```yaml
# ❌ Mauvais : tabulation
collection:
	cote: "HK"        # tab au lieu de 2 espaces → YAML invalide

# ✓ Bon : 2 espaces
collection:
  cote: "HK"
```

### Mauvais niveau d'imbrication

```yaml
# ❌ Mauvais : éditeur au mauvais niveau, traité comme racine
collection:
  cote: "HK"
editeur: "Éditions du Square"

# ✓ Bon
collection:
  cote: "HK"
  editeur: "Éditions du Square"
```

### Confusion `:` (clé) et `-` (élément de liste)

```yaml
# ❌ Mauvais : "tiff" est une clé sans valeur
extensions:
  tiff:
  jpg:

# ✓ Bon : éléments de liste
extensions:
  - "tiff"
  - "jpg"
```

### Encodage du fichier

Toujours UTF-8. La plupart des éditeurs modernes par défaut. Si vous
voyez des caractères bizarres (`Ã©` au lieu de `é`), c'est un problème
d'encodage.

### Chemin du tableur

Le `chemin` dans la section `tableur` est relatif au dossier
**contenant le profil YAML**, pas au répertoire courant. Si votre
profil est dans `profils/ainsa.yaml` et le tableur dans
`profils/ainsa.xlsx`, écrivez juste `chemin: "ainsa.xlsx"`.

### Le placeholder `A_REMPLACER`

Si vous laissez le placeholder produit par `profil init` :

```yaml
mapping:
  cote: "A_REMPLACER"
```

l'import échouera avec un message du genre `Colonne 'A_REMPLACER'
attendue par le mapping mais absente du tableur`. C'est attendu :
remplacez par le nom réel de la colonne avant de lancer l'import.

## Aller plus loin

- [`profils.md`](profils.md) : référence complète du format YAML, les
  trois formes de mapping, décompositions, transformations.
- [`importer.md`](importer.md) : pipeline d'import et ses options.
- `tests/fixtures/profils/` : quatre profils d'exemple lisibles
  (cas_item_simple, cas_fichier_groupe, cas_hierarchie_cote,
  cas_uri_dc).
