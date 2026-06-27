# Console de modération Nakala dans ColleC — note de design (non tranchée)

> **Statut : proposition à arbitrer.** Document de cadrage produit avant
> toute implémentation (principe directeur « proposer les décisions
> structurantes avant de coder »). Décrit la faisabilité, les tensions de
> positionnement et un périmètre MVP possible. **Rien n'est implémenté** ;
> seul le **tampon de modération read-only** sur la fiche item l'est déjà
> (cf. `nakala-savoir-api.md` §6 *→ côté ColleC*).

## 1. Motivation

ColleC ne s'adresse pas qu'à des déposants : **certains membres de l'équipe
sont modérateurs Nakala** (`ROLE_MODERATOR`, ~1 par MSHS en prod). Pour ces
personnes, traiter la file de modération *depuis ColleC* — au lieu d'un script
séparé — aurait une vraie valeur ergonomique (un outil au lieu de deux).

La demande émane d'une question : « le fonctionnement du script de Chloé
[MSHB] ne pourrait-il pas être intégré ? pouvoir pousser un statut `moderated`
avec le token du modérateur ».

## 2. Ce que fait l'outil officiel MSHB (et ce qu'on peut en reprendre)

Script `script_nakala_moderation_lot.py` du dépôt
`gitlab.huma-num.fr/Plateforme-HN-MSHB/moderation-lot-nakala` (Chloé Choquet).
Il fait **une seule chose, côté modérateur** : *traiter* des demandes déjà
posées — récupérer la file (`POST /users/datas/moderable`) puis boucler
`PUT /datas/{id}/status/moderated`, avec un CSV de sortie. Il **ne crée pas**
la demande (son README : « en réponse à une demande de modération effectuée au
préalable par l'utilisateur·ice »).

**Licence : CC BY-NC-SA 4.0.** ColleC n'ayant **pas** de licence déclarée,
copier/adapter ce code y déclencherait NonCommercial + ShareAlike
(contamination). → **jamais de vendorisation ni d'adaptation du code.** En
revanche les **faits d'API** (endpoints, statuts, codes) ne sont pas couverts
par le droit d'auteur et sont déjà caractérisés en clean-room (§6 +
`scripts/explorer_moderation_nakala.py`). Toute implémentation serait une
**réimplémentation clean-room**, pas un portage.

## 3. Faits d'API établis (live apitest 2026-06-26 / 2026-06-27)

| Étape | Endpoint | API publique ? | ColleC peut ? |
|---|---|---|---|
| **Demander** la modération (déposant) | — (`moderationRequester`/`lastModerationRequestDate` en lecture seule) | ❌ non (UI test.nakala.fr / `depot-lot-nakala`) | **non** |
| **Lister** la file | `POST /users/datas/moderable` (`{page,limit,orders,status}`) | ✅ | oui |
| **Modérer** (sur demande existante) | `PUT /datas/{id}/status/moderated` → 204 | ✅ | oui |
| Lire les tâches d'une ressource | `GET /users/resources/{id}/action` → `Task[]` | ✅ | oui |
| Vérifier le rôle du compte | `GET /users/me` (`roles`) | ✅ | oui |

Contraintes dures (re-sondées) :

- **`ROLE_MODERATOR` nécessaire mais NON suffisant** : `PUT status/moderated`
  → **403** « not allowed to change the data status » s'il n'y a **pas de
  demande** en attente — y compris en **auto-modération** (un modérateur sur
  son propre dépôt : testé, 403). Le **discriminant est la demande, pas le
  rôle**.
- **La demande n'est pas créable via l'API** → ColleC, client pur-API, **ne
  peut ni initier ni court-circuiter** l'amont. Il ne peut que *traiter* des
  demandes posées ailleurs.
- La file `moderable` est **Huma-Num-wide, tous-déposants-confondus** — sans
  lien avec les Fonds/Collections de l'instance.
- Modérer pose `lastModerator`/`lastModerationDate` **indélébiles** (pas de
  suppression de la trace via API ; le statut, lui, revient à `published`
  par une édition du déposant).

**Conclusion de faisabilité** : la fonction du script de Chloé (le
*traitement* de la file) **est** réimplémentable en clean-room. L'amont (la
demande) ne l'est pas — mais ce n'est pas non plus ce que fait le script.

## 4. Tensions de positionnement (le vrai sujet)

1. **Périmètre Huma-Num ≠ périmètre ColleC.** La file est à l'échelle de la
   plateforme, orthogonale au modèle Fonds/Collection/Item. Ce serait une
   **console autonome** greffée sur ColleC (comme `/nakala` est une page à
   part), pas une extension du catalogage. Risque de brouiller le
   positionnement « espace de travail catalographique ».
2. **Doublon d'un outil officiel maintenu.** Réimplémenter impose à ColleC de
   suivre les évolutions de l'API modération. Le principe maison (cf. décision
   BD_ditor : « copie → possession → divergence ») penche contre la
   duplication d'un outil tiers vivant.
3. **Action de gouvernance à fort enjeu** (valider la donnée publiée d'autrui,
   trace indélébile) → preview + confirmation forte obligatoires (principe
   n°3), et un token plus privilégié qu'une simple clé déposant.

**Contre-argument valide** : si des modérateurs de l'équipe vivent dans
ColleC, centraliser la file y est un gain réel. La réversibilité est
favorable — on peut **ajouter** une zone modérateur plus tard sans rien
casser, l'inverse (retirer) est plus coûteux.

## 5. Périmètre MVP proposé (si on y va)

**Zone modérateur séparée**, clairement distincte du catalogage :

- **Gate** : visible/active uniquement si le compte courant a `ROLE_MODERATOR`
  (vérifié via `GET /users/me`). Sinon, zone absente.
- **Lecture** : page `/moderation` listant la file `moderable` (pagination,
  `depositor.username`, titre, DOI, date de demande). Lecture seule, lazy.
- **Action** : modérer une donnée (ou un lot sélectionné) via
  `PUT status/moderated`, **derrière un aperçu + confirmation explicite**
  (liste des DOI concernés, rappel « trace indélébile »), bloqué en lecture
  seule (423) comme le reste.
- **Token** : la clé `ROLE_MODERATOR` est un secret plus sensible qu'une clé
  déposant → la traiter selon la **doctrine secrets** (RAM web / env CLI,
  jamais en clair affichée/loggée ; cf. `deploiement-future.md` § coffre
  multi-comptes). Idéalement distincte de la clé déposant de
  `config_local.yaml`.
- **Réimplémentation clean-room** réutilisant le client Nakala existant
  (`external/nakala/`), pas le code MSHB.
- **Journalisation** des actions de modération (principe n°4) : table analogue
  à `OperationPushNakala`.

### Hors scope (explicite)

- **Créer une demande** de modération (non-API ; reste UI/`depot-lot`).
- **Refuser** une modération (pas d'API ; le « retour » se fait par édition
  côté déposant).
- Toute intrication avec le modèle Fonds/Collection/Item (la file est
  Huma-Num-wide ; éventuelle intersection avec les DOI liés à l'instance =
  raffinement ultérieur, pas le MVP).

## 6. Points de décision ouverts

- **Faut-il vraiment l'intégrer**, ou laisser l'outil MSHB officiel faire le
  travail ? (positionnement — cf. §4).
- Si oui : **CLI d'abord** (cohérent avec « masse/admin = power-user CLI »,
  cf. roadmap Chantier UI⁺) ou **UI d'emblée** ?
- Gestion du **token modérateur** : où le ranger (V1.0 coffre chiffré) ? En
  attendant, RAM/env comme ShareDocs ?
- **Intersection avec le catalogue** : se limiter aux DOI que l'instance a
  rapatriés/liés, ou exposer toute la file Huma-Num du modérateur ?

## 7. Renvois

- Faits & cycle : [`nakala-savoir-api.md`](nakala-savoir-api.md) §6.
- Sonde live : `scripts/explorer_moderation_nakala.py` (précondition-aware).
- Source de référence (CC BY-NC-SA, non vendorisable) :
  `gitlab.huma-num.fr/Plateforme-HN-MSHB/moderation-lot-nakala`.
- Doctrine secrets / token : [`deploiement-future.md`](deploiement-future.md).
- Tampon read-only déjà livré : `dashboard._moderation_nakala` +
  `item_fiche.html`.
