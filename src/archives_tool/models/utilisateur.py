"""Compte utilisateur (Phase 1 — couche identité, V1.0).

Référentiel des identités nommées pour le **mode serveur partagé**. En
mode local mono-utilisateur (mode actuel), cette table n'est **pas
consultée** : l'identité vient de `config_local.yaml`. Phase 1 livre le
modèle + la CLI d'administration ; la session/login (mode serveur) est
Phase 2 (cf. `deploiement-future.md` § *Authentification*).

Périmètre V1.0 : **permanent + éditeur + global** (`nom`, `actif`,
`peut_editer`). La matrice scope/invité/expiration (colonnes
`voit_tout`, `fonds_editables`, `expire_le`…) viendra par migration
quand la feature sera réellement construite — pas de colonne dormante
non lue (principe directeur n°6).

`nom` est **unique** : c'est le roster de connexion (on sélectionne par
nom au login ; deux homonymes prêteraient à confusion). Distinct de la
chaîne d'audit libre `cree_par`/`modifie_par` (décision « Identité
simplifiée » du CLAUDE.md) — la table est le référentiel des comptes,
pas une contrainte sur les champs de traçabilité.

⚠ Deux décisions à acter **avant le branchement de la Phase 2** (login /
session), relevées par la revue sécurité — latentes aujourd'hui (aucun
code ne lit ces champs comme une autorité) :

- **`peut_editer` par défaut = `True`** (ident-1, MOYENNE-latent). Quand
  la session lira ce flag, tout compte créé sans `--lecteur` sera éditeur.
  Le modèle de menace V1.0 inclut des invités en lecture seule
  (peer-reviewer, consultation) → préférer le **moindre privilège** :
  basculer le défaut vers `peut_editer=False` et rendre l'octroi explicite
  (`--editeur`) au moment où le flag devient une autorisation. Inerte
  aujourd'hui, donc non urgent (changer le défaut casserait les tests
  actuels) — mais à inverser en Phase 2.
- **Unicité de `nom` sensible à la casse** (ident-2, BASSE-latent).
  `_normaliser_nom` fait NFC+strip mais **pas** de casefold : `"Marie"` et
  `"marie"` sont deux comptes distincts. Quand `nom` sera l'identifiant de
  login, trancher la politique de casse (casefold applicatif recommandé —
  `COLLATE NOCASE` SQLite ne couvre que l'ASCII).
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Utilisateur(Base):
    __tablename__ = "utilisateur"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Nom affiché et identifiant de connexion (sélection dans la liste).
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Compte désactivé = masqué du login, conservé pour la traçabilité
    #: (soft delete ; jamais de hard delete d'un compte ayant agi).
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Droit d'écriture. False = lecture seule pour ce compte (le mode
    #: serveur composera ce flag avec `est_lecture_seule` — Phase 2).
    #: ⚠ défaut `True` à réévaluer vers le moindre privilège avant la
    #: Phase 2 (ident-1, cf. docstring du module).
    peut_editer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("nom", name="uq_utilisateur_nom"),)
