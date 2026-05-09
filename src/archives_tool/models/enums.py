"""Énumérations métier."""

from __future__ import annotations

import enum


class EtatCatalogage(enum.StrEnum):
    BROUILLON = "brouillon"
    A_VERIFIER = "a_verifier"
    VERIFIE = "verifie"
    VALIDE = "valide"
    A_CORRIGER = "a_corriger"


class EtatFichier(enum.StrEnum):
    ACTIF = "actif"
    REMPLACE = "remplace"
    CORBEILLE = "corbeille"


class TypePage(enum.StrEnum):
    COUVERTURE = "couverture"
    DOS_COUVERTURE = "dos_couverture"
    PAGE_TITRE = "page_titre"
    PAGE = "page"
    PLANCHE = "planche"
    SUPPLEMENT = "supplement"
    QUATRIEME = "quatrieme"
    AUTRE = "autre"


class TypeOperationFichier(enum.StrEnum):
    RENAME = "rename"
    MOVE = "move"
    DELETE = "delete"
    RESTORE = "restore"
    REPLACE = "replace"


class StatutOperation(enum.StrEnum):
    SIMULEE = "simulee"
    REUSSIE = "reussie"
    ECHOUEE = "echouee"
    ANNULEE = "annulee"


class TypeChamp(enum.StrEnum):
    TEXTE = "texte"
    TEXTE_LONG = "texte_long"
    DATE_EDTF = "date_edtf"
    LISTE = "liste"
    LISTE_MULTIPLE = "liste_multiple"
    REFERENCE = "reference"
    NOMBRE = "nombre"


class PhaseChantier(enum.StrEnum):
    NUMERISATION = "numerisation"
    CATALOGAGE = "catalogage"
    REVISION = "revision"
    FINALISATION = "finalisation"
    ARCHIVEE = "archivee"
    EN_PAUSE = "en_pause"

    @property
    def libelle(self) -> str:
        return {
            "numerisation": "numérisation",
            "catalogage": "catalogage",
            "revision": "révision",
            "finalisation": "finalisation",
            "archivee": "archivée",
            "en_pause": "en pause",
        }[self.value]


class TypeRelationExterne(enum.StrEnum):
    MEME_RESSOURCE = "meme_ressource"
    PARTIE_DE = "partie_de"
    SUPPLEMENT_DE = "supplement_de"
    EVOQUE = "evoque"


class RoleCollaborateur(enum.StrEnum):
    NUMERISATION = "numerisation"
    TRANSCRIPTION = "transcription"
    INDEXATION = "indexation"
    CATALOGAGE = "catalogage"


LIBELLES_ROLE: dict[str, str] = {
    RoleCollaborateur.NUMERISATION.value: "Numérisation",
    RoleCollaborateur.TRANSCRIPTION.value: "Transcription",
    RoleCollaborateur.INDEXATION.value: "Indexation",
    RoleCollaborateur.CATALOGAGE.value: "Catalogage",
}
