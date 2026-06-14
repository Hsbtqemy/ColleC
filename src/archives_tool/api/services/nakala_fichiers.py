"""Service de versioning fichiers Nakala (palier P3+, cf.
`docs/developpeurs/nakala-depot-future.md` difficulté #4).

- **P3+a** : fondation `Fichier.sha1_nakala` (colonne + migration +
  capture upload + capture pull).
- **P3+b** : ``comparer_fichiers_item`` — détection (lecture seule).
- **P3+c** : ``pousser_fichiers_item`` — push effectif (upload des
  nouveaux/modifies + ``PUT /datas/{id}`` avec ``files[]`` cible +
  mise à jour ``sha1_nakala``).

Les hypothèses Nakala validées contre apitest (script
``scripts/explorer_put_files_nakala.py`` 2026-06-14) sont :

- **H1** : ``PUT files=[...]`` remplace intégralement la liste.
- **H2A** : ``PUT`` sans clé ``metas`` préserve les metas distantes.
- **H3** : ``PUT files=[]`` est silencieusement ignoré → garde-fou
  `PushImpossible` si la liste cible est vide.
- **H4** : ``PUT`` avec un sha1 inconnu lève HTTP 404 explicite →
  cleanup des uploads orphelins en cas d'échec.
- **H5** : ordre ``files[]`` préservé (envoyé = restitué).
- **H6** : idempotence du PUT (re-push identique = no-op silencieux).
- **H7** : ``PUT {sha1: existant, name: nouveau}`` renomme côté Nakala
  sans re-upload (gratuit pour les ``inchanges`` dont l'utilisateur a
  changé le ``nom_fichier`` local).
- **H10** : ``lire_depot`` immédiat post-PUT reflète les changements
  (pas d'eventual consistency à gérer).
- **H11** : champ ``description`` par fichier accepté et préservé.
  **Pas exposé en MVP** (ColleC n'a pas encore `Fichier.description_externe`),
  à intégrer en V2+ (cf. CLAUDE.md *Questions ouvertes*).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.mapper import mapper_depot
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Fichier, Item
from archives_tool.models.enums import EtatFichier

#: Taille de chunk pour le streaming SHA-1 — 8 KiB.
_TAILLE_CHUNK_SHA1 = 8192


class ComparaisonImpossible(Exception):
    """Item sans `doi_nakala` : pas de dépôt distant à comparer."""


class OrphelinsDetectes(Exception):
    """Refus du push : des fichiers Nakala existent sans pendant local.

    Le ``PUT /datas/{id}`` retirerait automatiquement ces fichiers
    côté distant (catastrophique pour items publiés). L'appelant doit
    repasser avec ``retirer_orphelins=True`` pour confirmer l'intention.

    Attribut ``orphelins`` : liste ``FichierOrphelin`` pour permettre à
    l'appelant (CLI / route) d'afficher la liste à l'utilisateur.
    """

    def __init__(self, orphelins: list["FichierOrphelin"]) -> None:
        self.orphelins = orphelins
        noms = ", ".join(f"{o.nom_fichier} (sha1: {o.sha1[:12]}…)" for o in orphelins[:5])
        suffixe = "" if len(orphelins) <= 5 else f" (+ {len(orphelins) - 5} autres)"
        super().__init__(
            f"{len(orphelins)} orphelin(s) distant(s) détecté(s) : {noms}{suffixe}. "
            "Repasser avec retirer_orphelins=True pour confirmer."
        )


class PushImpossible(Exception):
    """Refus du push pour un cas non supporté côté Nakala.

    Cas principal : ``files_cible == []`` (tous les fichiers locaux
    retirés ET ``retirer_orphelins=True``). L'hypothèse H3 confirme
    que ``PUT files=[]`` est silencieusement ignoré côté Nakala —
    la liste cible ne peut pas être vide. Pour vider un dépôt, passer
    par ``supprimer_depot`` puis re-déposer.
    """


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
      mais sans binaire local résolvable. **Préservés par défaut au
      push** (P3+c.1) : `pousser_fichiers_item` les inclut dans
      `files[]` cible avec leur `sha1_nakala` connu, évitant qu'ils
      soient retirés côté distant.
    - **orphelins_distants** : sha1 côté Nakala sans Fichier ColleC
      correspondant. Cas typique : fichier supprimé localement. Au
      push, **refusés par défaut** ; flag `retirer_orphelins=True`
      requis pour confirmer leur retrait côté Nakala.
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
    # Validation defensive : Nakala doit retourner un dict avec `files`
    # en list de dicts. Si bug API ou proxy qui munge la reponse (vu
    # `{"files": "not_a_list"}` ou `{"files": {"k": "v"}}`), un truthy-or-
    # default `or []` ne suffit pas : la boucle itererait sur les chars
    # / keys et `fd.get` planterait en AttributeError. On normalise a
    # `[]` toute valeur non-list.
    files_brut = depot.get("files")
    files_distants = files_brut if isinstance(files_brut, list) else []
    # Index sha1 → entrée distante. On filtre les sha1 vides (cas
    # dégénéré côté Nakala, ne devrait pas arriver). **Normalise en
    # lowercase** : `hexdigest()` côté ColleC produit toujours du
    # lowercase, et Nakala renvoie le sha1 en lowercase aujourd'hui.
    # La normalisation est défensive — si Nakala bascule un jour vers
    # uppercase, le matching continue de fonctionner. On normalise aussi
    # `f.sha1_nakala` à la comparaison plus bas pour la même raison.
    sha1_index: dict[str, dict[str, Any]] = {}
    for fd in files_distants:
        # Double couche : skip toute entree non-dict (defense vs liste
        # heterogene `[{...}, "str_in_middle", null]`).
        if not isinstance(fd, dict):
            continue
        sha1 = (fd.get("sha1") or "").strip().lower()
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
        # Filtre `etat=ACTIF` : un Fichier en `REMPLACE` ou `CORBEILLE`
        # ne participe pas à la comparaison (cohérence avec
        # `derivatives/generateur.py:166` et `renamer/plan.py:108`).
        # Au futur push (palier c), ces Fichier ne seront pas envoyés
        # — le PUT Nakala les retirera donc côté distant (cohérent avec
        # la sémantique de la corbeille : suppression effective au
        # prochain dépôt).
        if f.etat != EtatFichier.ACTIF.value:
            continue

        # Binaire local résolvable et lisible ?
        # On élargit le try/except au calcul SHA-1 lui-même :
        # - `KeyError` : racine absente du dict de config
        # - `ValueError` : `resoudre_chemin` rejette le chemin (path
        #   traversal, racine vide, etc.)
        # - `OSError` (parent de FileNotFoundError, PermissionError,
        #   IsADirectoryError) : TOCTOU entre `is_file()` et `open()`,
        #   ou permissions refusées, ou NFS down. Le fichier n'est pas
        #   utilisable → on le traite comme Nakala-only sans local
        #   (sémantique correcte : pas de binaire local exploitable).
        chemin: Path | None = None
        sha1_local: str | None = None
        if f.racine and f.chemin_relatif:
            try:
                resolu = resoudre_chemin(racines, f.racine, f.chemin_relatif)
                if resolu.is_file():
                    sha1_local = _sha1_du_binaire(resolu)
                    chemin = resolu
            except (KeyError, ValueError, OSError):
                pass

        compare = FichierCompare(
            fichier_id=f.id,
            cote_item=item.cote,
            nom_fichier=f.nom_fichier,
            ordre=f.ordre,
            sha1_local=sha1_local,
            sha1_distant=f.sha1_nakala,
        )

        # Normalise `f.sha1_nakala` en lowercase pour le matching
        # (défensif vs. base legacy avec sha1 uppercase ; cf. note
        # ci-dessus sur l'index distant).
        sha1_nakala_norm = f.sha1_nakala.lower() if f.sha1_nakala else None

        if chemin is None:
            # Nakala-only (ou perdu sur disque) : signal d'attention.
            # Si sha1_nakala connu, marquer apparié pour ne pas le
            # considérer comme orphelin distant — il est juste sans
            # binaire local.
            if sha1_nakala_norm and sha1_nakala_norm in sha1_index:
                sha1s_apparies.add(sha1_nakala_norm)
            rapport.nakala_only_sans_local.append(compare)
            continue

        # Binaire local présent — `sha1_local` est garanti non-None.
        assert compare.sha1_local is not None
        if compare.sha1_local in sha1_index:
            sha1s_apparies.add(compare.sha1_local)
            rapport.inchanges.append(compare)
        elif sha1_nakala_norm and sha1_nakala_norm in sha1_index:
            # Modifié : on retrouve l'ancien sha1 côté distant, mais
            # le binaire local en porte un nouveau.
            sha1s_apparies.add(sha1_nakala_norm)
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


# ---------------------------------------------------------------------------
# P3+c — Push fichiers (écriture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanPushFichier:
    """Une entrée du `files[]` cible envoyée au `PUT /datas/{id}`.

    Concentre les 3 sources possibles : un Fichier déjà connu de Nakala
    (inchangé, ou inchangé renommé via H7), un fichier uploadé pendant
    le push (nouveau ou modifié), un Fichier Nakala-only sans local.
    """

    fichier_id: int | None  # None pour Nakala-only et orphelins préservés
    nom_fichier: str
    sha1: str
    categorie: str  # "inchange" | "rename" | "nouveau" | "modifie" | "nakala_only"


@dataclass
class RapportPushFichiers:
    """Résultat d'un ``pousser_fichiers_item``."""

    cote_item: str
    doi: str
    dry_run: bool
    applique: bool = False
    raison: str | None = None  # "aucun_changement" | "orphelins_refuses" | ...
    compare: RapportComparaisonFichiers | None = None
    # Plan d'exécution rendu lisible pour l'utilisateur (dry-run et réel).
    plan: list[PlanPushFichier] = field(default_factory=list)
    # Listes des sha1 effectivement uploadés (vide en dry-run).
    sha1s_uploades: list[str] = field(default_factory=list)
    # Listes des sha1 distants retirés via PUT (= orphelins exclus).
    sha1s_retires: list[str] = field(default_factory=list)


def _construire_plan(
    rapport_cmp: RapportComparaisonFichiers,
) -> list[PlanPushFichier]:
    """Calcule le plan d'exécution (hors uploads) à partir du rapport
    de comparaison. Les entrées `nouveau` et `modifie` portent le
    `sha1_local` (recalculé local) comme sha1 prévisionnel — il sera
    remplacé par le sha1 retourné par `uploader_fichier` au moment de
    l'application réelle.

    Les `orphelins_distants` sont **toujours** exclus du plan : ne pas
    les inclure dans `files[]` cible les retire automatiquement
    (cohérent avec H1). Le garde-fou métier (`retirer_orphelins`
    requis) est appliqué en amont par l'appelant — ce helper ne
    re-vérifie pas.
    """
    plan: list[PlanPushFichier] = []
    for fc in rapport_cmp.inchanges:
        plan.append(PlanPushFichier(
            fichier_id=fc.fichier_id, nom_fichier=fc.nom_fichier,
            sha1=fc.sha1_local or "",  # garanti non-None côté inchanges
            categorie="inchange",
        ))
    for fc in rapport_cmp.modifies:
        plan.append(PlanPushFichier(
            fichier_id=fc.fichier_id, nom_fichier=fc.nom_fichier,
            sha1=fc.sha1_local or "",  # sera ré-uploadé
            categorie="modifie",
        ))
    for fc in rapport_cmp.nouveaux:
        plan.append(PlanPushFichier(
            fichier_id=fc.fichier_id, nom_fichier=fc.nom_fichier,
            sha1=fc.sha1_local or "",  # sera uploadé
            categorie="nouveau",
        ))
    for fc in rapport_cmp.nakala_only_sans_local:
        # Préservés : on les inclut avec leur sha1_nakala connu.
        if fc.sha1_distant:
            plan.append(PlanPushFichier(
                fichier_id=fc.fichier_id, nom_fichier=fc.nom_fichier,
                sha1=fc.sha1_distant,
                categorie="nakala_only",
            ))
    return plan


def pousser_fichiers_item(
    db: Any,
    client_lecture: ClientLectureNakala,
    client_ecriture: NakalaEcritureClient,
    item: Item,
    *,
    racines: Mapping[str, Path],
    dry_run: bool = True,
    retirer_orphelins: bool = False,
    modifie_par: str | None = None,
) -> RapportPushFichiers:
    """Pousse les fichiers locaux d'un Item vers son dépôt Nakala existant.

    Pipeline :

    1. Comparer (réutilise ``comparer_fichiers_item``).
    2. Garde-fous :
       - ``aucun_changement`` → return early, ``applique=False``.
       - ``orphelins_distants > 0`` et ``not retirer_orphelins`` →
         ``OrphelinsDetectes``.
    3. Construire le plan (``inchanges`` + ``modifies`` + ``nouveaux`` +
       ``nakala_only_sans_local``, les orphelins étant exclus).
    4. Garde-fou H3 : ``len(plan) == 0`` → ``PushImpossible``.
    5. Si ``dry_run`` : return avec le plan, sans écriture distante.
    6. Réel : upload des ``nouveaux + modifies`` via
       ``uploader_fichier`` (sha1 capturé). PUT
       ``/datas/{id} {files: cible}`` avec la liste finalisée.
    7. Met à jour ``Fichier.sha1_nakala`` pour ``modifies + nouveaux``.
    8. Commit.

    En cas d'erreur après upload(s) : cleanup des uploads orphelins
    via ``supprimer_upload``. Les écritures DB (``sha1_nakala``) ne
    sont commitées qu'**après** le PUT réussi — pas de divergence en
    base si le distant ne s'est pas mis à jour.

    Args:
        retirer_orphelins: requis pour confirmer le retrait silencieux
            de fichiers présents côté Nakala mais absents en local.
            Sans ce flag, lève ``OrphelinsDetectes``.
        modifie_par: propagé à ``mettre_en_cache_depot`` (champ
            ``cree_par`` de la ressource cachée) après le PUT réussi.
            Non propagé au format ``files[]`` (Nakala n'a pas de champ
            par-fichier pour l'auteur de la modification).

    Returns:
        ``RapportPushFichiers`` — riche en métadonnées d'exécution
        (plan, sha1s uploadés, raison de no-op…).

    Raises:
        DepotImpossible: ``item.doi_nakala`` est None.
        ComparaisonImpossible: propagé depuis ``comparer_fichiers_item``.
        OrphelinsDetectes: orphelins distants sans flag.
        PushImpossible: ``files_cible == []`` (cas H3).
        ErreurNakala: échec du ``lire_depot``, ``uploader_fichier`` ou
            ``modifier_depot`` (propagé).
    """
    if not item.doi_nakala:
        from archives_tool.api.services.nakala_depot import DepotImpossible

        raise DepotImpossible(
            f"Item {item.cote!r} sans doi_nakala — utiliser `deposer` d'abord."
        )

    # 1. Comparer
    rapport_cmp = comparer_fichiers_item(
        db, client_lecture, item, racines=racines,
    )

    rapport = RapportPushFichiers(
        cote_item=item.cote, doi=item.doi_nakala, dry_run=dry_run,
        compare=rapport_cmp,
    )

    # 2. Garde-fous métier
    if rapport_cmp.aucun_changement:
        rapport.raison = "aucun_changement"
        return rapport

    if rapport_cmp.orphelins_distants and not retirer_orphelins:
        raise OrphelinsDetectes(list(rapport_cmp.orphelins_distants))

    # 3. Plan d'exécution (hors uploads)
    rapport.plan = _construire_plan(rapport_cmp)

    # 4. Garde-fou H3 : files cible vide → Nakala ignorerait silencieusement
    if not rapport.plan:
        raise PushImpossible(
            f"Item {item.cote!r} : files_cible vide après garde-fous. "
            "Nakala ignore silencieusement `PUT files=[]` (H3). Pour vider "
            "un dépôt, utiliser `supprimer_depot` + redéposer."
        )

    # Pré-calcul des sha1 distants pour le rapport `sha1s_retires`.
    rapport.sha1s_retires = [o.sha1 for o in rapport_cmp.orphelins_distants]

    # 5. Dry-run : on ne touche pas au distant.
    if dry_run:
        return rapport

    # 6. Réel : upload des nouveaux + modifies.
    # Map fichier_id → sha1 fraîchement uploadé, pour mettre à jour
    # `Fichier.sha1_nakala` après le PUT réussi.
    nouveaux_sha1_par_fichier: dict[int, str] = {}
    sha1s_uploades: list[str] = []
    from archives_tool.files.paths import resoudre_chemin

    try:
        for fc in list(rapport_cmp.nouveaux) + list(rapport_cmp.modifies):
            if fc.fichier_id is None:
                continue  # ne devrait pas arriver (catégories à fichier local)
            # Récupère le binaire local (le service a déjà calculé son
            # sha1 dans la phase de comparaison, mais on re-upload depuis
            # le binaire actuel — pas de cache).
            # Le Fichier ORM doit toujours avoir `racine` et
            # `chemin_relatif` valides à ce stade (sinon il aurait été
            # classé en Nakala-only par la comparaison).
            fichier_orm = db.get(Fichier, fc.fichier_id)
            assert fichier_orm is not None
            assert fichier_orm.racine and fichier_orm.chemin_relatif
            chemin = resoudre_chemin(
                racines, fichier_orm.racine, fichier_orm.chemin_relatif,
            )
            desc = client_ecriture.uploader_fichier(chemin, fc.nom_fichier)
            sha1_neuf = desc["sha1"].strip().lower()
            sha1s_uploades.append(sha1_neuf)
            nouveaux_sha1_par_fichier[fc.fichier_id] = sha1_neuf

        # Construire le `files[]` final avec les sha1 fraîchement uploadés
        # pour `nouveau` et `modifie`. Les `inchange`/`rename`/`nakala_only`
        # gardent leur sha1 du plan.
        files_cible: list[dict[str, Any]] = []
        for entree in rapport.plan:
            sha1 = entree.sha1
            if entree.categorie in ("nouveau", "modifie"):
                # Override avec sha1 fraîchement uploadé
                assert entree.fichier_id is not None
                sha1 = nouveaux_sha1_par_fichier[entree.fichier_id]
            files_cible.append({"sha1": sha1, "name": entree.nom_fichier})

        # 7. PUT
        client_ecriture.modifier_depot(item.doi_nakala, files=files_cible)

    except Exception:
        # Cleanup uploads orphelins (best-effort).
        for sha1 in sha1s_uploades:
            try:
                client_ecriture.supprimer_upload(sha1)
            except Exception:  # noqa: BLE001
                pass
        raise

    rapport.sha1s_uploades = sha1s_uploades

    # 8. Met à jour Fichier.sha1_nakala pour modifies + nouveaux.
    # Pose `modifie_le` pour tracer la mutation et incrémente `version`
    # (sans verrou optimiste actif sur Fichier — cf. dette signalee
    # CLAUDE.md, mais on respecte le pattern).
    maintenant = datetime.now()
    for fichier_id, sha1_neuf in nouveaux_sha1_par_fichier.items():
        fichier = db.get(Fichier, fichier_id)
        if fichier is not None:
            fichier.sha1_nakala = sha1_neuf
            fichier.modifie_le = maintenant
            fichier.version = (fichier.version or 1) + 1

    # 9. Cache invalidation : rafraichir `RessourceExterne.metadonnees
    # _brutes` + `LienExterneItem.recupere_le` pour que les autres
    # consommateurs (route web, autres CLI) ne lisent pas un cache stale
    # apres le PUT. Pattern aligne sur `pousser_item` (P3).
    from archives_tool.api.services.nakala import mettre_en_cache_depot

    brut2 = client_lecture.lire_depot(item.doi_nakala)
    mettre_en_cache_depot(db, mapper_depot(brut2), brut2, cree_par=modifie_par)

    db.commit()

    rapport.applique = True
    return rapport
