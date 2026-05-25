# Plan de chantier — planification catalographique en amont

!!! warning "Document de travail interne"
    Cette page n'est pas publiée sur le site MkDocs (exclue via
    `exclude_docs` dans `mkdocs.yml`). Elle préserve les décisions
    structurantes prises en discussion (mai 2026) sur l'usage de
    ColleC comme outil de planification de chantier en plus de son
    rôle de catalogage.

    Tenue à jour au fil des sessions. Pas une référence utilisateur.

## Constat

L'instinct exprimé en discussion : « pouvoir organiser son
chantier par le travail de catalogue (dire quelles revues seront
dans le fonds, quelle appellation, quelle cote, le nombre
d'items, etc.) ». Question : est-ce redondant avec ce qui existe
déjà ?

**Réponse : non, c'est exactement l'usage prévu** — mais une
grande partie est déjà supportée par le modèle, l'UX a juste
besoin d'être un peu plus assumée et complétée.

## Ce qui existe déjà

Le modèle ColleC distingue :

- **Structure planifiée** : Fonds + Collections + Items existent
  indépendamment des fichiers. La base accepte des items à `0`
  fichier sans broncher (vérifié dans le seeder de démo).
- **Complétion progressive** : `etat_catalogage` sur Item avec 5
  valeurs (`brouillon`, `a_verifier`, `verifie`, `valide`,
  `a_corriger`), `phase` sur Collection (composant
  `phase_chantier`), `repartition_etats` calculée et affichée sur
  le dashboard et la page Fonds.
- **Onramp tableur** : `archives-tool profil analyser
  inventaire.xlsx` + `archives-tool importer profil.yaml` digère
  un Excel saisi à partir d'un inventaire physique. C'est le bon
  point d'entrée pour démarrer un chantier à partir d'une liste
  papier.

Concrètement, on peut dès aujourd'hui créer un fonds « Por
Favor », sa miroir, et 60 items vides PF-001 à PF-060 — la base
ne s'en offusquera pas et le dashboard affichera 0 % d'avancement,
ce qui est exactement ce qu'on veut au démarrage.

## Ce qui manque pour que l'usage devienne ergonomique

Trois manques, par ordre d'utilité décroissante.

### (1) Création en série d'items — V2 roadmap actuelle

Le manquant le plus critique : créer 60 items à la main via l'UI
est rebutant. Déjà inscrit dans la roadmap V2 du `CLAUDE.md`.

CLI à prévoir :

```bash
archives-tool items creer-serie \
    --fonds PF \
    --pattern "PF-{:03d}" \
    --titre "Por Favor n°{n}" \
    --de 1 --a 60 \
    [--collection MIROIR_PF] \
    [--etat brouillon]
```

Équivalent UI : un bouton « Créer une série d'items » sur la page
Fonds ou Collection, formulaire avec pattern + plage + titre
template + champs de valeurs par défaut.

Variables interpolables dans le titre : `{n}` (numéro courant),
`{n:03d}` (formaté), éventuellement `{annee}` calculé depuis une
date de départ + périodicité (mensuel, hebdomadaire) pour les
revues régulières.

### (2) Import inventaire papier — déjà disponible

Le pipeline `profil analyser` + `importer` couvre déjà ce besoin.
Manque éventuel : un assistant UI pour saisir un inventaire
**directement dans le navigateur** quand on n'a pas de tableur
externe (« tape ici un item par ligne, cote tab titre tab date »).

À discuter en V2. Faible priorité tant que l'import Excel
fonctionne.

### (3) Vue de pilotage du chantier — extension de l'existant

Un onglet « Avancement » sur la page Fonds qui ne montrerait pas
juste les compteurs d'états (déjà visibles) mais aussi une lecture
**par jalon** :

- Items planifiés (existent en base).
- Items avec fichiers rattachés (étape de numérisation faite).
- Items avec OCR (à voir si on stocke cette info — pour l'instant
  non, faudrait soit un flag, soit dériver de la présence d'un
  ALTO/PDF text layer).
- Items vérifiés (`etat_catalogage >= verifie`).
- Items validés (`etat_catalogage = valide`).

Avec les écarts visibles (« 60 items, 23 avec fichiers, 18
catalogués »). Une partie est déjà rendue par `avancement_detaille`
sur le bandeau Fonds et `tableau_items` sur la page Collection,
mais il manque la lecture transversale « où en est le chantier
dans son ensemble ».

V2 ou V1.x selon l'usage réel.

## Risque à surveiller : ne pas dériver vers un PM tool

Tentation à refuser :

- Pas de champs « date prévue de numérisation ».
- Pas de champs « assigné à », « priorité 1/2/3 », « deadline ».
- Pas de notifications, pas de relances, pas de Gantt.

C'est un autre métier (Trello, Notion, un simple Excel partagé
font ça mille fois mieux et c'est de la gestion d'équipe, pas du
travail catalographique).

**Règle qui sépare clean :**

- Information qui enrichit la **notice** (auteur, date de
  parution, type, langue, état physique) → place dans ColleC.
- Information qui décrit le **travail à faire sur la notice**
  (qui s'en occupe, quand, par quelle voie) → reste dehors.

La traçabilité historique (qui a modifié quoi, quand) est déjà
capturée par le journal — pas besoin d'un modèle prévisionnel en
plus.

## Décisions à conserver

- **Plan de chantier = usage natif** du modèle ColleC, pas un
  module à inventer.
- **Création en série d'items** : à livrer en V2, CLI + UI,
  pattern + plage + valeurs par défaut.
- **Vue Avancement consolidée** sur la page Fonds : extension de
  l'existant en V2 ou V1.x.
- **Pas de PM tool.** Refuser fermement les champs prévisionnels
  (date prévue, assigné, priorité). La gestion d'équipe vit
  dehors, ColleC reste catalographique.
- **Onramp Excel suffit** pour l'amorçage. Assistant UI de saisie
  directe seulement si l'usage le réclame fortement.

## Renvois

- Workflow amont (le plan de chantier prépare l'étape 1 de la
  chaîne) : `workflow-numerisation.md`.
- Roadmap V2 (« confort du chantier vivant ») dans le `CLAUDE.md`
  racine, section *Plan de développement*.
