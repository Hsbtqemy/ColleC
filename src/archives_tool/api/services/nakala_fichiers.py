"""Service de versioning fichiers Nakala (palier P3+, cf.
`docs/developpeurs/nakala-depot-future.md` difficulté #4).

Le palier P3+a a posé la fondation : colonne `Fichier.sha1_nakala`
captant le SHA-1 calculé par Nakala à l'upload, et la migration
`s7w8x9y0z1a2` qui backfill les Fichier matérialisés via `rapatrier`.

Ce module porte le palier **P3+b — détection (lecture seule)** :
``comparer_fichiers_item`` classe les fichiers d'un item ColleC vs le
dépôt Nakala distant en 5 catégories (nouveaux, modifies, inchanges,
nakala_only_sans_local, orphelins_distants). Aucune écriture distante,
aucune mutation de base — pure lecture.

Le palier P3+c (push effectif) viendra dans une session dédiée :
upload des nouveaux/modifiés + `PUT /datas/{id}` avec le jeu cible +
mise à jour `sha1_nakala`. Pour l'instant le résultat de ``comparer``
sert juste à l'inspection humaine.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.models import Item

#: Taille de chunk pour le streaming SHA-1 — 8 KiB.
_TAILLE_CHUNK_SHA1 = 8192


class ComparaisonImpossible(Exception):
    """Item sans `doi_nakala` : pas de dépôt distant à comparer."""


@dataclass(frozen=True)
class FichierCompare:
    """Vue figée d'un Fichier ColleC dans une comparaison.

    - ``fichier_id`` : id du Fichier ORM (pour le palier c qui mutera
      ``sha1_nakala`` après le push).
    - ``sha1_local`` : SHA-1 du binaire local recalculé on the fly,
      ou ``None`` si pas de binaire local (cas Nakala-only).
    - ``sha1_distant`` : valeur de ``Fichier.sha1_nakala`` côté local
      (snapshot Nakala connu par ColleC) — la vérité distante actuelle
      vient du ``lire_depot``, pas de cette colonne.
    """

    fichier_id: int
    cote_item: str
    nom_fichier: str
    ordre: int
    sha1_local: str | None
    sha1_distant: str | None


@dataclass(frozen=True)
class FichierOrphelin:
    """Entrée distante (`files[i]` du dépôt) sans Fichier ColleC apparié.

    Risque potentiel au push : un `PUT /datas/{id}` avec une liste cible
    omettant cet orphelin le retire côté Nakala (politique Nakala). Le
    palier c devra refuser sans flag `--retirer-orphelins`.
    """

    sha1: str
    nom_fichier: str


@dataclass
class RapportComparaisonFichiers:
    """Résultat d'un ``comparer_fichiers_item``.

    Classement complet de la confrontation locale vs distante :

    - **nouveaux** : binaire local, sha1_local absent côté distant
      ET pas de sha1_nakala connu pointant ailleurs. Au push, sera
      uploadé + ajouté.
    - **modifies** : binaire local, sha1_local ≠ sha1_distant connu
      qui est encore présent côté Nakala. Au push, sera ré-uploadé
      en remplacement.
    - **inchanges** : sha1_local matche directement un sha1 distant
      présent. Au push, conservé tel quel (juste passer dans `files[]`).
    - **nakala_only_sans_local** : Fichier ColleC pullé depuis Nakala
      mais sans binaire local résolvable. Au push, **danger** : ces
      fichiers seraient perdus côté Nakala si non préservés dans la
      liste cible.
    - **orphelins_distants** : sha1 côté Nakala sans Fichier ColleC
      correspondant. Cas typique : fichier supprimé localement.
    """

    cote_item: str
    doi: str
    nouveaux: list[FichierCompare] = field(default_factory=list)
    modifies: list[FichierCompare] = field(default_factory=list)
    inchanges: list[FichierCompare] = field(default_factory=list)
    nakala_only_sans_local: list[FichierCompare] = field(default_factory=list)
    orphelins_distants: list[FichierOrphelin] = field(default_factory=list)

    @property
    def aucun_changement(self) -> bool:
        """Vrai si pousser ne ferait rien : pas de nouveaux, pas de
        modifs, pas d'orphelins à retirer. Les ``nakala_only_sans_local``
        ne comptent pas comme un changement — ils sont seulement un
        signal d'attention pour le palier c."""
        return (
            not self.nouveaux
            and not self.modifies
            and not self.orphelins_distants
        )


def _sha1_du_binaire(chemin: Path) -> str:
    """SHA-1 streaming d'un fichier sur disque (chunks 8 KiB)."""
    h = hashlib.sha1(usedforsecurity=False)  # noqa: S324 — interop Nakala
    with chemin.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_TAILLE_CHUNK_SHA1), b""):
            h.update(chunk)
    return h.hexdigest()


def comparer_fichiers_item(
    db: Any,
    client: ClientLectureNakala,
    item: Item,
    *,
    racines: Mapping[str, Path],
) -> RapportComparaisonFichiers:
    """Classe les fichiers de ``item`` par rapport au dépôt Nakala distant.

    Pull ``GET /datas/{doi}``, recalcule le SHA-1 de chaque binaire local
    présent, et confronte aux ``files[i].sha1`` distants. Pure lecture
    (aucune écriture base ni distante).

    Stratégie de réconciliation :

    1. Match prioritaire par **sha1 calculé local ↔ sha1 distant** —
       robuste aux renommages.
    2. Fallback par ``sha1_nakala`` connu de ColleC pour détecter une
       **modification** d'un fichier déjà déposé (sha1 a changé en local,
       mais on retrouve l'ancien sha1 côté distant).

    Args:
        db: Session SQLAlchemy (non utilisée directement — ``item`` est
            déjà chargé avec ses fichiers ; argument gardé pour la
            symétrie avec les autres services du module et un éventuel
            usage futur).
        client: Client lecture Nakala (déjà ouvert par l'appelant).
        item: Item ORM avec ``doi_nakala`` non null.
        racines: Mapping racine logique → chemin physique (cf. config
            locale) pour résoudre les binaires locaux.

    Raises:
        ComparaisonImpossible: ``item.doi_nakala`` est None.
        ErreurNakala: échec du ``lire_depot`` distant (propagé tel quel).
    """
    if not item.doi_nakala:
        raise ComparaisonImpossible(
            f"Item {item.cote!r} sans doi_nakala — comparaison impossible."
        )

    # Pull distant (peut lever ErreurNakala, on laisse propager).
    depot = client.lire_depot(item.doi_nakala)
    files_distants = depot.get("files") or []
    # Index sha1 → entrée distante. On filtre les sha1 vides (cas
    # dégénéré côté Nakala, ne devrait pas arriver).
    sha1_index: dict[str, dict[str, Any]] = {}
    for fd in files_distants:
        sha1 = (fd.get("sha1") or "").strip()
        if sha1:
            sha1_index[sha1] = fd

    # On marque les sha1 distants qui trouvent un appariement, pour
    # déduire les orphelins en fin de boucle.
    sha1s_apparies: set[str] = set()

    rapport = RapportComparaisonFichiers(
        cote_item=item.cote, doi=item.doi_nakala,
    )

    # Import paresseux : `resoudre_chemin` charge la config, on évite
    # le coût si on n'a aucun fichier local à classer.
    from archives_tool.files.paths import resoudre_chemin

    for f in sorted(item.fichiers, key=lambda x: x.ordre):
        # Binaire local résolvable ?
        chemin: Path | None = None
        if f.racine and f.chemin_relatif:
            try:
                resolu = resoudre_chemin(racines, f.racine, f.chemin_relatif)
                if resolu.is_file():
                    chemin = resolu
            except (KeyError, ValueError):
                pass

        compare = FichierCompare(
            fichier_id=f.id,
            cote_item=item.cote,
            nom_fichier=f.nom_fichier,
            ordre=f.ordre,
            sha1_local=_sha1_du_binaire(chemin) if chemin else None,
            sha1_distant=f.sha1_nakala,
        )

        if chemin is None:
            # Nakala-only (ou perdu sur disque) : signal d'attention.
            # Si sha1_nakala connu, marquer apparié pour ne pas le
            # considérer comme orphelin distant — il est juste sans
            # binaire local.
            if f.sha1_nakala and f.sha1_nakala in sha1_index:
                sha1s_apparies.add(f.sha1_nakala)
            rapport.nakala_only_sans_local.append(compare)
            continue

        # Binaire local présent — `sha1_local` est garanti non-None.
        assert compare.sha1_local is not None
        if compare.sha1_local in sha1_index:
            sha1s_apparies.add(compare.sha1_local)
            rapport.inchanges.append(compare)
        elif f.sha1_nakala and f.sha1_nakala in sha1_index:
            # Modifié : on retrouve l'ancien sha1 côté distant, mais
            # le binaire local en porte un nouveau.
            sha1s_apparies.add(f.sha1_nakala)
            rapport.modifies.append(compare)
        else:
            # Nouveau : ni sha1_local ni sha1_nakala (s'il existe) n'est
            # côté distant — ce binaire n'est pas encore connu de Nakala.
            rapport.nouveaux.append(compare)

    # Orphelins : sha1 distants sans appariement.
    for sha1, fd in sha1_index.items():
        if sha1 not in sha1s_apparies:
            rapport.orphelins_distants.append(
                FichierOrphelin(sha1=sha1, nom_fichier=fd.get("name") or "")
            )

    return rapport
