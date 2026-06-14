"""Tests du palier P3+b — détection versioning fichiers (lecture seule).

Couvre les 5 catégories de classification de `comparer_fichiers_item` :
nouveaux, modifies, inchanges, nakala_only_sans_local, orphelins_distants.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_fichiers import (
    BackfillIncomplet,
    ComparaisonImpossible,
    DepotPublie,
    FichierFantomeDistant,
    IncoherenceFichierORM,
    OrphelinsDetectes,
    PushImpossible,
    ReponseLectureInvalide,
    UploadInvalide,
    comparer_fichiers_item,
    pousser_fichiers_item,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fichier, Item
from archives_tool.models.enums import EtatFichier


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path) -> Session:
    return creer_session_factory(creer_engine(db))()


def _sha1(contenu: bytes) -> str:
    h = hashlib.sha1(usedforsecurity=False)  # noqa: S324
    h.update(contenu)
    return h.hexdigest()


def _ecrire_binaire(scans: Path, nom: str, contenu: bytes) -> tuple[Path, str]:
    """Écrit un fichier de contenu donné, renvoie (path, sha1)."""
    scans.mkdir(exist_ok=True)
    chemin = scans / nom
    chemin.write_bytes(contenu)
    return chemin, _sha1(contenu)


class _FakeClientLecture:
    """Stub de `ClientLectureNakala` : `lire_depot(doi)` renvoie un dict
    avec `files=[{sha1, name}]` configurable. `modDate` optionnel pour
    tester la dérive."""

    def __init__(
        self, files: list[dict[str, Any]], *,
        mod_date: str | None = None,
        statut: str | None = None,
    ) -> None:
        self._files = files
        self._mod_date = mod_date
        self._statut = statut
        self.appels: list[str] = []

    def lire_depot(self, doi: str) -> dict[str, Any]:
        self.appels.append(doi)
        depot = {"identifier": doi, "files": self._files}
        if self._mod_date is not None:
            depot["modDate"] = self._mod_date
        if self._statut is not None:
            depot["status"] = self._statut
        return depot


def _setup_item_avec_fichiers(
    s: Session, tmp_path: Path,
    *, fichiers_specs: list[dict[str, Any]],
    doi_nakala: str = "10.34847/nkl.x1",
) -> Item:
    """Crée fonds AS + miroir + 1 item AS-001 avec `doi_nakala` posé +
    les Fichier indiqués.

    `fichiers_specs` : chaque spec est un dict avec :
      - `ordre` (int)
      - `nom` (str)
      - `contenu` (bytes | None) : si None, pas de binaire local
      - `racine` (str | None, défaut "scans")
      - `sha1_nakala` (str | None) : valeur de la colonne dédiée
    """
    f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
    item = creer_item(s, FormulaireItem(
        cote="AS-001", titre="X", fonds_id=f.id,
    ))
    item.doi_nakala = doi_nakala
    for spec in fichiers_specs:
        nom = spec["nom"]
        if spec.get("contenu") is not None:
            _ecrire_binaire(tmp_path / "scans", nom, spec["contenu"])
            racine = spec.get("racine", "scans")
            chemin_rel = nom
        else:
            racine = None
            chemin_rel = None
        s.add(Fichier(
            item_id=item.id,
            nom_fichier=nom,
            racine=racine,
            chemin_relatif=chemin_rel,
            iiif_url_nakala=spec.get("iiif_url_nakala"),
            ordre=spec["ordre"],
            sha1_nakala=spec.get("sha1_nakala"),
        ))
    s.commit()
    return item


# ---------------------------------------------------------------------------
# Cas dégénérés
# ---------------------------------------------------------------------------


def test_comparer_leve_si_pas_de_doi_nakala(
    db_path: Path, tmp_path: Path,
) -> None:
    """Item sans `doi_nakala` → ComparaisonImpossible (aucun pull
    distant ne peut être fait)."""
    client = _FakeClientLecture(files=[])
    with _session(db_path) as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="X", fonds_id=f.id,
        ))
        # `doi_nakala` reste None.
        with pytest.raises(ComparaisonImpossible):
            comparer_fichiers_item(
                s, client, item, racines={"scans": tmp_path / "scans"},
            )
    # Aucun pull tenté côté distant.
    assert client.appels == []


def test_comparer_item_vide_avec_distant_vide_aucun_changement(
    db_path: Path, tmp_path: Path,
) -> None:
    """Item sans Fichier ColleC ni distant : aucun changement à signaler."""
    client = _FakeClientLecture(files=[])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert rapport.aucun_changement
    assert (
        rapport.nouveaux == rapport.modifies == rapport.inchanges
        == rapport.nakala_only_sans_local == rapport.orphelins_distants == []
    )


# ---------------------------------------------------------------------------
# Les 5 catégories
# ---------------------------------------------------------------------------


def test_inchange_quand_sha1_local_egal_sha1_distant(
    db_path: Path, tmp_path: Path,
) -> None:
    """Binaire local existant, sha1 calculé matche un sha1 distant → inchangé.
    Cas typique : fichier déposé, jamais modifié depuis."""
    contenu = b"hello world"
    sha1 = _sha1(contenu)
    client = _FakeClientLecture(files=[{"sha1": sha1, "name": "a.jpg"}])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg", "contenu": contenu, "sha1_nakala": sha1},
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert len(rapport.inchanges) == 1
    assert rapport.inchanges[0].nom_fichier == "a.jpg"
    assert rapport.inchanges[0].sha1_local == sha1
    assert rapport.aucun_changement


def test_modifie_quand_sha1_local_diff_mais_sha1_nakala_connu_cote_distant(
    db_path: Path, tmp_path: Path,
) -> None:
    """Binaire local changé : sha1 local nouveau mais sha1_nakala (ancien)
    encore présent côté distant → modifié."""
    ancien_contenu = b"ancien"
    sha1_ancien = _sha1(ancien_contenu)
    nouveau_contenu = b"nouveau"
    sha1_nouveau = _sha1(nouveau_contenu)

    # Le distant a encore l'ancien sha1, ColleC l'a aussi dans sha1_nakala,
    # mais le binaire local porte le nouveau.
    client = _FakeClientLecture(files=[{"sha1": sha1_ancien, "name": "a.jpg"}])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg",
             "contenu": nouveau_contenu, "sha1_nakala": sha1_ancien},
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert len(rapport.modifies) == 1
    fc = rapport.modifies[0]
    assert fc.sha1_local == sha1_nouveau
    assert fc.sha1_distant == sha1_ancien
    assert rapport.inchanges == []
    assert rapport.nouveaux == []


def test_nouveau_quand_sha1_local_jamais_connu(
    db_path: Path, tmp_path: Path,
) -> None:
    """Binaire local, pas de sha1_nakala posé, sha1 calculé absent du
    distant → nouveau (à uploader)."""
    contenu = b"jamais_depose"
    sha1 = _sha1(contenu)
    # Distant vide.
    client = _FakeClientLecture(files=[])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert len(rapport.nouveaux) == 1
    assert rapport.nouveaux[0].sha1_local == sha1
    assert rapport.nouveaux[0].sha1_distant is None


def test_nakala_only_sans_local_signale_separement(
    db_path: Path, tmp_path: Path,
) -> None:
    """Fichier Nakala-only (pas de binaire local) : ne tombe pas en
    nouveau/modifié/inchangé — dans `nakala_only_sans_local`. Préserve le
    sha1 distant pour le palier c."""
    sha1 = "deadbeef" * 5  # 40 hex
    client = _FakeClientLecture(files=[{"sha1": sha1, "name": "a.jpg"}])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/iiif/x/y/info.json",
             "sha1_nakala": sha1},
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert len(rapport.nakala_only_sans_local) == 1
    nol = rapport.nakala_only_sans_local[0]
    assert nol.sha1_local is None
    assert nol.sha1_distant == sha1
    # PAS classé en orphelin (il est apparié au distant via sha1_nakala).
    assert rapport.orphelins_distants == []
    # Aucun changement à pousser, mais signal nakala_only_sans_local actif.
    assert rapport.aucun_changement


def test_orphelin_distant_quand_fichier_local_absent(
    db_path: Path, tmp_path: Path,
) -> None:
    """Sha1 distant sans Fichier ColleC apparié → orphelin distant.
    Cas typique : fichier supprimé localement. Au push, serait retiré
    côté Nakala (refusé sans flag explicite au palier c)."""
    sha1_orphan = "cafebabe" * 5
    client = _FakeClientLecture(files=[
        {"sha1": sha1_orphan, "name": "perdu.jpg"},
    ])
    with _session(db_path) as s:
        # Item sans aucun Fichier.
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert len(rapport.orphelins_distants) == 1
    assert rapport.orphelins_distants[0].sha1 == sha1_orphan
    assert rapport.orphelins_distants[0].nom_fichier == "perdu.jpg"
    assert not rapport.aucun_changement


def test_distant_avec_sha1_vide_est_ignore(
    db_path: Path, tmp_path: Path,
) -> None:
    """Cas dégénéré côté Nakala : un `files[i]` distant sans sha1 (ou
    avec sha1 vide). Le code défensif `if sha1:` skip cette entrée du
    sha1_index — ne provoque ni crash, ni faux match. Le test garantit
    que l'entrée dégénérée n'apparaît pas en orphelin et que le reste
    de la comparaison fonctionne normalement."""
    contenu = b"hello"
    sha1 = _sha1(contenu)
    client = _FakeClientLecture(files=[
        {"sha1": sha1, "name": "a.jpg"},
        {"sha1": "", "name": "degenere.jpg"},      # sha1 vide
        {"sha1": None, "name": "null.jpg"},        # sha1 absent
    ])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg", "contenu": contenu, "sha1_nakala": sha1},
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    # Le fichier valide est inchangé. Les 2 distants dégénérés ne
    # remontent pas en orphelins (ils ne font pas partie du sha1_index).
    assert len(rapport.inchanges) == 1
    assert rapport.orphelins_distants == []
    assert rapport.aucun_changement


def test_racine_inconnue_dans_config_traite_comme_nakala_only(
    db_path: Path, tmp_path: Path,
) -> None:
    """Cas réaliste : la config locale a une racine manquante pour ce
    poste. `resoudre_chemin` lève `KeyError` — le code catch silencieux
    et classe le fichier en `nakala_only_sans_local` (pas crash, pas
    classification erronée).

    Cas typique : un fichier ColleC a `racine='scans_serveur'` mais
    la config locale d'un dev n'a pas configuré cette racine — on
    veut quand même pouvoir comparer les autres."""
    sha1 = "abc" * 13 + "f"  # 40 hex
    client = _FakeClientLecture(files=[{"sha1": sha1, "name": "x.jpg"}])
    with _session(db_path) as s:
        # Setup avec iiif_url_nakala pour passer le CHECK
        # `ck_fichier_source_au_moins_une`, puis on override racine/
        # chemin_relatif après insertion pour pointer sur une racine
        # absente de la config — situation qu'on rencontre quand un
        # dev a une config_local.yaml partielle.
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": None,
             "iiif_url_nakala": "https://x/y", "sha1_nakala": sha1},
        ])
        fichier = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).one()
        fichier.racine = "racine_qui_nexiste_pas"
        fichier.chemin_relatif = "fichier_quelconque.jpg"
        s.commit()
        # Racines de config ne contiennent PAS "racine_qui_nexiste_pas"
        # → resoudre_chemin lève KeyError, catché par le service.
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    # Le KeyError est catché → fichier traité comme Nakala-only
    # (pas de binaire local résolvable).
    assert len(rapport.nakala_only_sans_local) == 1
    assert rapport.nakala_only_sans_local[0].sha1_local is None
    # Le sha1 distant est apparié au nakala_only (pas orphelin).
    assert rapport.orphelins_distants == []


def test_sha1_normalise_lowercase_cote_distant_et_stockage(
    db_path: Path, tmp_path: Path,
) -> None:
    """Garde-fou défensif : si Nakala renvoie un sha1 en uppercase
    (changement futur improbable) OU si la base legacy a un
    `sha1_nakala` en uppercase, le matching doit fonctionner quand
    même — on normalise tout en lowercase à la comparaison.

    Sans cette normalisation, le bug serait silencieux et
    catastrophique : tous les items déjà déposés apparaîtraient en
    "nouveau" ou "modifié" → un push effectif ré-uploaderait inutilement
    (ou pire, perdrait des fichiers via le retrait orphelins)."""
    contenu = b"hello uppercase"
    sha1_lower = _sha1(contenu)
    sha1_upper = sha1_lower.upper()

    # Cas 1 : sha1 distant en UPPER, sha1_nakala stocké en lower.
    # `hexdigest()` du binaire local = lower ; doit matcher.
    client_distant_upper = _FakeClientLecture(files=[
        {"sha1": sha1_upper, "name": "x.jpg"},
    ])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu,
             "sha1_nakala": sha1_lower},
        ])
        rapport = comparer_fichiers_item(
            s, client_distant_upper, item,
            racines={"scans": tmp_path / "scans"},
        )
    assert len(rapport.inchanges) == 1
    assert rapport.aucun_changement

    # Cas 2 : sha1 distant en lower, sha1_nakala stocké en UPPER (legacy).
    # Le matching doit fonctionner via la normalisation `.lower()`.
    db2 = tmp_path / "case2.db"
    engine = creer_engine(db2)
    Base.metadata.create_all(engine)
    engine.dispose()
    client_distant_lower = _FakeClientLecture(files=[
        {"sha1": sha1_lower, "name": "x.jpg"},
    ])
    nouveau_contenu = b"contenu_modifie"
    nouveau_sha1 = _sha1(nouveau_contenu)
    with _session(db2) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "y.jpg", "contenu": nouveau_contenu,
             "sha1_nakala": sha1_upper},  # stocké UPPER (legacy)
        ])
        rapport = comparer_fichiers_item(
            s, client_distant_lower, item,
            racines={"scans": tmp_path / "scans"},
        )
    # Le sha1_local (lower) != sha1_distant. Mais sha1_nakala (upper)
    # normalisé matche le sha1_distant → classification "modifié".
    assert len(rapport.modifies) == 1
    assert rapport.modifies[0].sha1_local == nouveau_sha1


@pytest.mark.parametrize(
    "files_malforme",
    [
        "not_a_list",       # string : iter sur chars
        {"k": "v"},         # dict : iter sur keys
        None,               # null
        42,                 # int
    ],
    ids=["str", "dict", "null", "int"],
)
def test_files_distants_non_list_ne_crashe_pas(
    tmp_path: Path, files_malforme,
) -> None:
    """Defense contre une API Nakala / proxy qui retourne un `files`
    non-list — ne doit pas crash en `AttributeError: 'X' object has
    no attribute 'get'`.

    Cas reproduits par run direct du service :
    - `{"files": "non_array"}` → iteration sur chars → crash sur
      `"n".get("sha1")`
    - `{"files": {"k": "v"}}` → iteration sur keys → crash idem

    Comportement attendu : traiter comme `files=[]` (cote distant
    vide) → tous les fichiers locaux deviennent `nouveaux`."""
    contenu = b"local only"
    sha1_local = _sha1(contenu)
    # Une DB par run (parametrize → 4 runs distincts) pour eviter le
    # cleanup foireux (Fonds + miroir + CHECK constraint).
    db = tmp_path / f"test_{type(files_malforme).__name__}.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()

    class StubAvecFilesMalforme:
        def lire_depot(self, doi):
            return {"identifier": doi, "files": files_malforme}

    factory = creer_session_factory(creer_engine(db))
    with factory() as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        # Pas de crash, classification cote distant vide.
        rapport = comparer_fichiers_item(
            s, StubAvecFilesMalforme(), item,
            racines={"scans": tmp_path / "scans"},
        )
        assert len(rapport.nouveaux) == 1
        assert rapport.nouveaux[0].sha1_local == sha1_local
        assert rapport.orphelins_distants == []


def test_fd_individuel_non_dict_ignore(
    db_path: Path, tmp_path: Path,
) -> None:
    """Defense double : si la liste `files` est valide mais contient
    des entrees heterogenes (`[{...}, "str_in_middle", null, ...]`),
    skip les non-dict sans crash."""
    contenu = b"hello"
    sha1 = _sha1(contenu)
    client = _FakeClientLecture(files=[
        {"sha1": sha1, "name": "a.jpg"},
        "string_at_index_1",  # entree degenere
        None,                  # null au milieu
        {"sha1": "b" * 40, "name": "b.jpg"},
    ])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg", "contenu": contenu,
             "sha1_nakala": sha1},
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    # Le fichier valide cote local matche le 1er distant → inchange.
    assert len(rapport.inchanges) == 1
    # Le 4e distant (b.jpg) est orphelin (pas de pendant local) ;
    # les 2 entrees degenerees (str, null) sont skipped silencieusement.
    assert len(rapport.orphelins_distants) == 1
    assert rapport.orphelins_distants[0].nom_fichier == "b.jpg"


def test_oserror_pendant_lecture_binaire_traite_comme_nakala_only(
    db_path: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si le binaire local existe à `is_file()` mais que la lecture
    elle-même lève `OSError` (TOCTOU : fichier supprimé entre check
    et open, ou PermissionError, ou NFS down, ou IsADirectoryError),
    le service catch et classe le fichier en `nakala_only_sans_local`
    (sémantique : pas de binaire local exploitable). Pas de crash, pas
    de traceback brut chez l'utilisateur.

    Le seul moyen portable de tester ça (Windows + Linux + macOS) est
    de monkeypatch `_sha1_du_binaire` pour lever, en gardant la racine
    et le chemin valides côté `is_file()`."""
    from archives_tool.api.services import nakala_fichiers as nf_mod

    contenu = b"binary content"
    sha1 = _sha1(contenu)
    client = _FakeClientLecture(files=[{"sha1": sha1, "name": "x.jpg"}])

    def _sha1_qui_leve(chemin):
        raise PermissionError(f"simulated read-denied on {chemin}")

    monkeypatch.setattr(nf_mod, "_sha1_du_binaire", _sha1_qui_leve)

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": sha1},
        ])
        # Le binaire existe à `is_file()` (`_setup_item_avec_fichiers`
        # l'a créé via `_ecrire_binaire`), mais `_sha1_du_binaire` lève.
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )

    # Pas de crash → catché par le `except OSError`.
    # Fichier classé en `nakala_only_sans_local` (pas de binaire local
    # exploitable), pas en `inchanges` ni `nouveau` ni `modifies`.
    assert len(rapport.nakala_only_sans_local) == 1
    assert rapport.nakala_only_sans_local[0].sha1_local is None
    assert rapport.inchanges == []
    assert rapport.modifies == []
    assert rapport.nouveaux == []
    # Le sha1_nakala connu apparie le distant (pas orphelin) — cohérent
    # avec le cas Nakala-only nominal.
    assert rapport.orphelins_distants == []


def test_fichiers_non_actif_sont_ignores(
    db_path: Path, tmp_path: Path,
) -> None:
    """Cohérence projet : `comparer_fichiers_item` ignore les Fichier
    dont `etat != ACTIF` (REMPLACE, CORBEILLE). Pattern aligne sur
    `derivatives/generateur.py` et `renamer/plan.py` qui filtrent
    explicitement `Fichier.etat == EtatFichier.ACTIF.value`.

    Sans ce filtre, un fichier mis en CORBEILLE par l'utilisateur :
    - apparaîtrait en `inchanges` (si binaire dispo) → resterait sur
      Nakala au push, contredisant l'intention utilisateur ;
    - ou en `nouveau` (si binaire retiré) → serait re-uploadé.

    Avec le filtre, le fichier corbeille n'apparaît pas → au push, le
    PUT Nakala ne l'inclut pas → suppression effective côté distant
    (sémantique correcte de la corbeille ColleC)."""
    contenu_actif = b"actif content"
    sha1_actif = _sha1(contenu_actif)
    contenu_remplace = b"remplace content"
    sha1_remplace = _sha1(contenu_remplace)
    contenu_corbeille = b"corbeille content"
    sha1_corbeille = _sha1(contenu_corbeille)

    # Distant connaît les 3 sha1.
    client = _FakeClientLecture(files=[
        {"sha1": sha1_actif, "name": "actif.jpg"},
        {"sha1": sha1_remplace, "name": "remplace.jpg"},
        {"sha1": sha1_corbeille, "name": "corbeille.jpg"},
    ])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "actif.jpg", "contenu": contenu_actif,
             "sha1_nakala": sha1_actif},
            {"ordre": 2, "nom": "remplace.jpg", "contenu": contenu_remplace,
             "sha1_nakala": sha1_remplace},
            {"ordre": 3, "nom": "corbeille.jpg", "contenu": contenu_corbeille,
             "sha1_nakala": sha1_corbeille},
        ])
        # Pose les états non-ACTIF sur les fichiers 2 et 3.
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        fichiers[1].etat = EtatFichier.REMPLACE.value
        fichiers[2].etat = EtatFichier.CORBEILLE.value
        s.commit()

        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )

    # Seul le fichier ACTIF est dans `inchanges`.
    assert len(rapport.inchanges) == 1
    assert rapport.inchanges[0].nom_fichier == "actif.jpg"
    # Les fichiers REMPLACE et CORBEILLE sont **absents** des autres
    # catégories ordinaires (ils ne participent pas du tout au matching).
    assert rapport.modifies == []
    assert rapport.nouveaux == []
    assert rapport.nakala_only_sans_local == []
    # Trou O (passe 6) : les Fichier non-ACTIF avec `sha1_nakala` qui
    # matche un sha1 distant sortent en `non_actifs_a_retirer` (PAS en
    # orphelin anonyme) — traçabilité explicite du retrait à venir au
    # PUT (le user voit que ces fichiers ColleC sont la raison du
    # retrait, pas un mystère).
    assert len(rapport.non_actifs_a_retirer) == 2
    noms_non_actifs = {nac.nom_fichier for nac in rapport.non_actifs_a_retirer}
    assert noms_non_actifs == {"remplace.jpg", "corbeille.jpg"}
    sha1s_non_actifs = {nac.sha1_distant for nac in rapport.non_actifs_a_retirer}
    assert sha1_remplace in sha1s_non_actifs
    assert sha1_corbeille in sha1s_non_actifs
    # Les sha1 distants correspondants NE sont PAS dans orphelins (ils
    # ont été consommés du sha1_index par le Fichier ColleC non-ACTIF).
    sha1s_orphelins = {fo.sha1 for fo in rapport.orphelins_distants}
    assert sha1_remplace not in sha1s_orphelins
    assert sha1_corbeille not in sha1s_orphelins
    # `aucun_changement` est False car il y a des non-actifs à retirer.
    assert not rapport.aucun_changement


def test_combinaison_des_5_categories_simultanees(
    db_path: Path, tmp_path: Path,
) -> None:
    """Item avec un cas de chaque catégorie : vérifie qu'aucune classification
    n'écrase une autre + qu'`aucun_changement=False`."""
    inchange = b"inchange"
    sha_inchange = _sha1(inchange)
    nouveau = b"nouveau"
    sha_nouveau = _sha1(nouveau)
    modif_nouveau = b"modif_nouveau"
    sha_modif_local = _sha1(modif_nouveau)
    sha_modif_ancien = "ancien_modif" + "0" * 28
    sha_nakala_only = "nakaonly" + "0" * 32
    sha_orphan = "orphan00" + "0" * 32

    client = _FakeClientLecture(files=[
        {"sha1": sha_inchange, "name": "a.jpg"},
        {"sha1": sha_modif_ancien, "name": "b.jpg"},
        {"sha1": sha_nakala_only, "name": "c.jpg"},
        {"sha1": sha_orphan, "name": "d.jpg"},
    ])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg", "contenu": inchange,
             "sha1_nakala": sha_inchange},  # inchangé
            {"ordre": 2, "nom": "b.jpg", "contenu": modif_nouveau,
             "sha1_nakala": sha_modif_ancien},  # modifié
            {"ordre": 3, "nom": "c.jpg", "contenu": None,
             "iiif_url_nakala": "https://x/y", "sha1_nakala": sha_nakala_only},  # nakala-only
            {"ordre": 4, "nom": "e.jpg", "contenu": nouveau,
             "sha1_nakala": None},  # nouveau (e.jpg pas dans distant)
            # `d.jpg` du distant n'a pas de pendant local → orphelin
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert [fc.nom_fichier for fc in rapport.inchanges] == ["a.jpg"]
    assert [fc.nom_fichier for fc in rapport.modifies] == ["b.jpg"]
    assert [fc.nom_fichier for fc in rapport.nouveaux] == ["e.jpg"]
    assert [fc.nom_fichier for fc in rapport.nakala_only_sans_local] == ["c.jpg"]
    assert [fo.sha1 for fo in rapport.orphelins_distants] == [sha_orphan]
    assert not rapport.aucun_changement
    # Vérif: sha1 local correctement recalculé.
    assert rapport.inchanges[0].sha1_local == sha_inchange
    assert rapport.modifies[0].sha1_local == sha_modif_local
    assert rapport.nouveaux[0].sha1_local == sha_nouveau


# ---------------------------------------------------------------------------
# P3+c — Push fichiers (écriture)
# ---------------------------------------------------------------------------


class _FakeClientEcriture:
    """Stub `NakalaEcritureClient` : capture les uploads + le PUT.

    Pattern aligné sur `tests/test_nakala_depot.py::_FakeWriteClient`.
    `uploader_fichier` retourne un sha1 séquentiel (`sha-1`, `sha-2`...)
    pour permettre aux tests d'asserter sur la valeur capturée."""

    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.uploads_sha1s: list[str] = []
        self.puts: list[dict] = []
        self.supprimes: list[str] = []

    def uploader_fichier(self, chemin, nom=None):
        n = nom or Path(chemin).name
        self.uploads.append(n)
        # Format sha1 hex 40 chars (valide _valider_sha1_uploade passe 7).
        # Sequence : "0000…001", "0000…002", … pour traçabilité dans
        # les asserts.
        sha1 = f"{len(self.uploads):040x}"
        self.uploads_sha1s.append(sha1)
        return {"name": n, "sha1": sha1}

    def modifier_depot(self, identifiant, *, metas=None, files=None, status=None):
        self.puts.append({"id": identifiant, "metas": metas, "files": files,
                          "status": status})
        return {}

    def supprimer_upload(self, sha1):
        self.supprimes.append(sha1)


def test_pousser_sans_doi_nakala_leve_depot_impossible(
    db_path: Path, tmp_path: Path,
) -> None:
    from archives_tool.api.services.nakala_depot import DepotImpossible

    lecture = _FakeClientLecture(files=[])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="X", fonds_id=f.id,
        ))
        # doi_nakala reste None
        with pytest.raises(DepotImpossible):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
            )
    assert ecriture.puts == []  # aucun PUT


def test_pousser_dry_run_aucun_changement_no_op(
    db_path: Path, tmp_path: Path,
) -> None:
    """Item ou tout matche le distant → no-op, raison="aucun_changement"."""
    contenu = b"identical"
    sha1 = _sha1(contenu)
    lecture = _FakeClientLecture(files=[{"sha1": sha1, "name": "x.jpg"}])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": sha1},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
        )
    assert rapport.dry_run is True
    assert rapport.applique is False
    assert rapport.raison == "aucun_changement"
    assert ecriture.uploads == []
    assert ecriture.puts == []


def test_pousser_orphelins_distants_sans_flag_leve(
    db_path: Path, tmp_path: Path,
) -> None:
    """orphelins_distants > 0 et retirer_orphelins=False → OrphelinsDetectes."""
    contenu = b"local content"
    sha1 = _sha1(contenu)
    sha1_orphan = "deadbeef" * 5
    lecture = _FakeClientLecture(files=[
        {"sha1": sha1, "name": "x.jpg"},
        {"sha1": sha1_orphan, "name": "orphan.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": sha1},
        ])
        with pytest.raises(OrphelinsDetectes) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                retirer_orphelins=False,
            )
    # L'exception porte la liste d'orphelins (utilisable par CLI/route).
    assert len(exc_info.value.orphelins) == 1
    assert exc_info.value.orphelins[0].sha1 == sha1_orphan
    assert ecriture.uploads == []
    assert ecriture.puts == []


def test_pousser_avec_flag_retirer_orphelins_les_exclut(
    db_path: Path, tmp_path: Path,
) -> None:
    """retirer_orphelins=True + dry_run=False → orphelin exclu de files[],
    PUT envoyé, fichier inchangé préservé."""
    contenu = b"local content"
    sha1 = _sha1(contenu)
    sha1_orphan = "deadbeef" * 5
    lecture = _FakeClientLecture(files=[
        {"sha1": sha1, "name": "x.jpg"},
        {"sha1": sha1_orphan, "name": "orphan.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": sha1},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False, retirer_orphelins=True,
        )
    assert rapport.applique is True
    assert len(ecriture.puts) == 1
    files_envoyes = ecriture.puts[0]["files"]
    sha1s_envoyes = [f["sha1"] for f in files_envoyes]
    # L'orphelin n'est pas dans files[] (sera retire par Nakala via H1)
    assert sha1_orphan not in sha1s_envoyes
    # L'inchange est preserve
    assert sha1 in sha1s_envoyes
    # Le rapport documente le retrait
    assert sha1_orphan in rapport.sha1s_retires


def test_pousser_effectif_upload_nouveau_et_modifie_et_pose_sha1_nakala(
    db_path: Path, tmp_path: Path,
) -> None:
    """Cycle complet : 1 inchange + 1 modifie + 1 nouveau →
    2 uploads (modifie + nouveau), PUT avec 3 entrees,
    sha1_nakala mis a jour pour modifie + nouveau."""
    contenu_inchange = b"unchanged"
    sha1_inchange = _sha1(contenu_inchange)
    contenu_modifie_nouveau = b"new modified content"
    sha1_modifie_ancien = "a" * 40
    contenu_nouveau = b"brand new file"

    lecture = _FakeClientLecture(files=[
        {"sha1": sha1_inchange, "name": "i.jpg"},
        {"sha1": sha1_modifie_ancien, "name": "m.jpg"},
    ])
    ecriture = _FakeClientEcriture()

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "i.jpg", "contenu": contenu_inchange,
             "sha1_nakala": sha1_inchange},
            {"ordre": 2, "nom": "m.jpg", "contenu": contenu_modifie_nouveau,
             "sha1_nakala": sha1_modifie_ancien},  # ancien sha1 connu
            {"ordre": 3, "nom": "n.jpg", "contenu": contenu_nouveau,
             "sha1_nakala": None},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False, modifie_par="hugo",
        )

    assert rapport.applique is True
    # 2 uploads (modifie + nouveau, pas inchange)
    assert sorted(ecriture.uploads) == ["m.jpg", "n.jpg"]
    # 1 PUT avec 3 entrees dans files[]
    assert len(ecriture.puts) == 1
    files = ecriture.puts[0]["files"]
    assert len(files) == 3
    # L'inchange garde son sha1
    inchange_envoye = next(f for f in files if f["name"] == "i.jpg")
    assert inchange_envoye["sha1"] == sha1_inchange
    # Le modifie + nouveau ont leur sha1 fraichement uploade par le
    # stub (format hex 40 chars, cf. _FakeClientEcriture). On verifie
    # qu'ils sont dans la liste des sha1s capturees par le stub.
    modifie_envoye = next(f for f in files if f["name"] == "m.jpg")
    assert modifie_envoye["sha1"] in ecriture.uploads_sha1s
    nouveau_envoye = next(f for f in files if f["name"] == "n.jpg")
    assert nouveau_envoye["sha1"] in ecriture.uploads_sha1s
    # 2 sha1s capturés
    assert len(rapport.sha1s_uploades) == 2

    # Verif DB : sha1_nakala mis a jour pour modifie + nouveau, inchange
    # garde son ancien
    with _session(db_path) as s:
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        assert fichiers[0].sha1_nakala == sha1_inchange  # inchange
        assert fichiers[1].sha1_nakala in ecriture.uploads_sha1s  # modifie
        assert fichiers[2].sha1_nakala in ecriture.uploads_sha1s  # nouveau


def test_pousser_preserve_ordre_fichier_dans_plan_et_put(
    db_path: Path, tmp_path: Path,
) -> None:
    """Passe revue P3+c.1 : le plan envoye au PUT respecte
    `Fichier.ordre`, pas l'ordre des categories.

    H5 validee contre apitest confirme que Nakala preserve l'ordre du
    `files[]` envoye. Sans tri explicite, le plan serait : inchanges
    puis modifies puis nouveaux puis nakala_only → perte de coherence
    d'affichage ColleC ↔ Nakala.

    Cas test : 4 fichiers ordres 1/2/3/4 repartis dans differentes
    categories. Verifie que le plan ET le PUT envoye respectent
    l'ordre 1/2/3/4."""
    contenu_inchange = b"unchanged at order 2"
    sha1_inchange = _sha1(contenu_inchange)
    contenu_modifie = b"new content at order 1"
    sha1_modifie_ancien = "z" * 40
    contenu_nouveau = b"new file at order 4"
    sha1_nakala_only = "y" * 40

    # Distant : sha1_inchange + sha1_modifie_ancien + sha1_nakala_only
    lecture = _FakeClientLecture(files=[
        {"sha1": sha1_modifie_ancien, "name": "ordre1.jpg"},
        {"sha1": sha1_inchange, "name": "ordre2.jpg"},
        {"sha1": sha1_nakala_only, "name": "ordre3.jpg"},
    ])
    ecriture = _FakeClientEcriture()

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            # ordre=1 : modifie (binaire change + sha1_nakala ancien connu)
            {"ordre": 1, "nom": "ordre1.jpg", "contenu": contenu_modifie,
             "sha1_nakala": sha1_modifie_ancien},
            # ordre=2 : inchange (sha1 matche distant)
            {"ordre": 2, "nom": "ordre2.jpg", "contenu": contenu_inchange,
             "sha1_nakala": sha1_inchange},
            # ordre=3 : nakala-only (binaire local absent)
            {"ordre": 3, "nom": "ordre3.jpg", "contenu": None,
             "iiif_url_nakala": "https://x/y",
             "sha1_nakala": sha1_nakala_only},
            # ordre=4 : nouveau (jamais depose)
            {"ordre": 4, "nom": "ordre4.jpg", "contenu": contenu_nouveau,
             "sha1_nakala": None},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )

    # Le plan respecte l'ordre Fichier (1-2-3-4)
    assert [p.ordre for p in rapport.plan] == [1, 2, 3, 4]
    assert [p.nom_fichier for p in rapport.plan] == [
        "ordre1.jpg", "ordre2.jpg", "ordre3.jpg", "ordre4.jpg",
    ]
    # Et le PUT envoye preserve aussi cet ordre (H5)
    files_envoyes = ecriture.puts[0]["files"]
    assert [f["name"] for f in files_envoyes] == [
        "ordre1.jpg", "ordre2.jpg", "ordre3.jpg", "ordre4.jpg",
    ]


def test_pousser_pose_modifie_le_et_incremente_version_sur_modifies_nouveaux(
    db_path: Path, tmp_path: Path,
) -> None:
    """Passe revue P3+c.1 : verifier la tracabilite de la mutation.

    Apres un push effectif :
    - `Fichier.modifie_le` est pose (non-None) pour modifies + nouveaux
    - `Fichier.version` est incremente (etait 1, devient 2)
    - Les `inchanges` NE sont PAS touches (modifie_le inchange,
      version inchange)
    """
    contenu_inchange = b"unchanged"
    sha1_inchange = _sha1(contenu_inchange)
    contenu_nouveau = b"brand new"

    lecture = _FakeClientLecture(files=[
        {"sha1": sha1_inchange, "name": "i.jpg"},
    ])
    ecriture = _FakeClientEcriture()

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "i.jpg", "contenu": contenu_inchange,
             "sha1_nakala": sha1_inchange},
            {"ordre": 2, "nom": "n.jpg", "contenu": contenu_nouveau,
             "sha1_nakala": None},
        ])
        # Snapshot avant push
        avant = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        version_i_avant = avant[0].version
        version_n_avant = avant[1].version
        modifie_le_i_avant = avant[0].modifie_le

        pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )

    # Apres push : verif tracabilite
    with _session(db_path) as s:
        apres = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        # Inchange : non touche
        assert apres[0].modifie_le == modifie_le_i_avant
        assert apres[0].version == version_i_avant
        # Nouveau : modifie_le pose + version incrementee
        assert apres[1].modifie_le is not None
        assert apres[1].version == version_n_avant + 1


def test_pousser_cleanup_uploads_si_put_echoue(
    db_path: Path, tmp_path: Path,
) -> None:
    """Si le PUT leve apres N uploads → supprimer_upload pour chaque
    sha1 uploade (best-effort). Les Fichier.sha1_nakala n'ont pas ete
    commites (commit apres PUT reussi)."""
    contenu = b"content for upload"

    class _EcritureQuiFaitFlopAuPut(_FakeClientEcriture):
        def modifier_depot(self, *args, **kwargs):
            from archives_tool.external.nakala.client import ErreurNakala

            raise ErreurNakala("Simulation echec PUT")

    lecture = _FakeClientLecture(files=[])  # distant vide → tout en nouveau
    ecriture = _EcritureQuiFaitFlopAuPut()
    from archives_tool.external.nakala.client import ErreurNakala
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        with pytest.raises(ErreurNakala):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )
    # Cleanup : 1 sha1 supprime cote Nakala (le seul uploade avant
    # l'echec PUT, formate par le stub en hex 40 chars).
    assert ecriture.supprimes == [f"{1:040x}"]
    # `sha1_nakala` non commite (rollback de fait via absence de commit)
    with _session(db_path) as s:
        fichier = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).one()
        assert fichier.sha1_nakala is None


def test_pousser_dry_run_construit_plan_sans_uploader(
    db_path: Path, tmp_path: Path,
) -> None:
    """dry_run=True (defaut) : plan complet mais aucun upload ni PUT."""
    contenu = b"new file content"
    lecture = _FakeClientLecture(files=[])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
        )
    assert rapport.dry_run is True
    assert rapport.applique is False
    assert ecriture.uploads == []
    assert ecriture.puts == []
    # Le plan est calcule (1 nouveau)
    assert len(rapport.plan) == 1
    assert rapport.plan[0].categorie == "nouveau"
    assert rapport.plan[0].nom_fichier == "a.jpg"


def test_pousser_garde_fou_h3_files_cible_vide_leve_push_impossible(
    db_path: Path, tmp_path: Path,
) -> None:
    """Cas extreme : tous les fichiers locaux deviennent orphelins
    distants (ex. binaires supprimes localement, distants encore la)
    + flag retirer_orphelins → files_cible == [] → PushImpossible
    (Nakala ignore silencieusement PUT files=[])."""
    sha1_orphan_a = "a" * 40
    sha1_orphan_b = "b" * 40
    lecture = _FakeClientLecture(files=[
        {"sha1": sha1_orphan_a, "name": "a.jpg"},
        {"sha1": sha1_orphan_b, "name": "b.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        # Item sans aucun Fichier local (tous les binaires
        # remote-only ont ete deplaces / supprimes).
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[])
        with pytest.raises(PushImpossible) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False, retirer_orphelins=True,
            )
    assert "files_cible vide" in str(exc_info.value)
    assert "supprimer_depot" in str(exc_info.value)
    assert ecriture.puts == []


def test_pousser_rename_gratuit_via_inchange_si_autre_changement_declenche_put(
    db_path: Path, tmp_path: Path,
) -> None:
    """Bonus H7 : un Fichier inchange (sha1 matche le distant) mais
    avec un `nom_fichier` local different → le PUT envoie le nouveau
    nom, Nakala renomme sans re-upload.

    **Limitation MVP** : le rename est propagé au PUT seulement s'il y a
    AU MOINS un autre changement structurel (nouveau / modifie / orphelin
    sous flag). Un rename pur (sha1 inchange, juste le nom change, pas
    d'autre delta) tomberait en `aucun_changement` et ne declencherait
    pas de PUT — limitation a lever en V2+ via extension du rapport
    de comparaison (mapper sha1 distant → nom distant).

    Pour ce test : combiner 1 rename (sha1 inchange + nom local
    different) + 1 nouveau pour qu'aucun_changement soit False.
    """
    contenu_renomme = b"unchanged binary"
    sha1_renomme = _sha1(contenu_renomme)
    contenu_nouveau = b"new file"
    # Le distant a fichier renomme avec un autre nom.
    lecture = _FakeClientLecture(files=[
        {"sha1": sha1_renomme, "name": "ancien_nom.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            # Fichier renomme (sha1 inchange, nom different)
            {"ordre": 1, "nom": "nouveau_nom.jpg", "contenu": contenu_renomme,
             "sha1_nakala": sha1_renomme},
            # Fichier nouveau pour declencher le PUT
            {"ordre": 2, "nom": "n.jpg", "contenu": contenu_nouveau,
             "sha1_nakala": None},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    # 1 upload pour le nouveau, pas pour le rename
    assert ecriture.uploads == ["n.jpg"]
    # 1 PUT avec 2 entrees : le rename (avec nouveau nom) + le nouveau
    assert len(ecriture.puts) == 1
    files = ecriture.puts[0]["files"]
    noms = {f["name"] for f in files}
    assert noms == {"nouveau_nom.jpg", "n.jpg"}
    # Le rename garde son sha1 (pas re-uploade)
    rename_envoye = next(f for f in files if f["name"] == "nouveau_nom.jpg")
    assert rename_envoye["sha1"] == sha1_renomme
    assert rapport.applique is True


# ---------------------------------------------------------------------------
# P3+c.2 passe 4 — BackfillIncomplet + drift detection
# ---------------------------------------------------------------------------


def test_pousser_backfill_incomplet_leve_avant_put(
    db_path: Path, tmp_path: Path,
) -> None:
    """Trou J — perte silencieuse de fichier sur scenario legacy mixte.

    Un Fichier ColleC en `nakala_only_sans_local` sans `sha1_nakala`
    peuplé (cas pré-P3+a, backfill non rejoué) ne peut pas être
    réconcilié avec le distant. Sans garde-fou, `_construire_plan` le
    skipperait silencieusement → le fichier distant correspondant
    serait retiré côté Nakala SANS être listé en orphelin (il était
    indexé par `sha1_index` mais jamais ajouté à `sha1s_apparies`
    faute de sha1 connu côté ColleC).

    Le garde-fou refuse le push avec `BackfillIncomplet`, listant
    les Fichier concernés.
    """
    # Fichier A : legacy, sha1_nakala=None, pas de binaire local.
    # Fichier B : sain, binaire local matche distant.
    contenu_b = b"sain"
    sha1_b = _sha1(contenu_b)
    sha1_a_distant = "aaaaaaaaaaaa" + "0" * 28  # 40 hex chars

    lecture = _FakeClientLecture(files=[
        {"sha1": sha1_a_distant, "name": "A.jpg"},
        {"sha1": sha1_b, "name": "B.jpg"},
    ])
    ecriture = _FakeClientEcriture()

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "A.jpg",
             "contenu": None,  # pas de binaire local
             "iiif_url_nakala": "https://api.nakala.fr/iiif/.../info.json",
             "sha1_nakala": None},  # LEGACY : backfill pas joué
            {"ordre": 2, "nom": "B.jpg",
             "contenu": contenu_b, "sha1_nakala": sha1_b},
        ])
        with pytest.raises(BackfillIncomplet) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )

    # L'exception expose la liste des Fichier concernés.
    assert len(exc_info.value.fichiers) == 1
    assert exc_info.value.fichiers[0].nom_fichier == "A.jpg"
    assert exc_info.value.fichiers[0].sha1_distant is None
    # Aucun PUT envoyé — refus loud.
    assert ecriture.puts == []
    assert ecriture.uploads == []


def test_pousser_backfill_incomplet_message_liste_les_fichiers(
    db_path: Path, tmp_path: Path,
) -> None:
    """Le message d'erreur de BackfillIncomplet liste les noms (≤5)."""
    lecture = _FakeClientLecture(files=[
        {"sha1": "aa" + "0" * 38, "name": "A.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "A.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/iiif/.../info.json",
             "sha1_nakala": None},
        ])
        with pytest.raises(BackfillIncomplet) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False, retirer_orphelins=True,
            )
    msg = str(exc_info.value)
    assert "A.jpg" in msg
    assert "sha1_nakala" in msg
    assert "backfill" in msg.lower()


def test_pousser_derive_detection_signalee_dans_rapport(
    db_path: Path, tmp_path: Path,
) -> None:
    """Trou K — drift detection (symétrie avec `pousser_item` P3).

    Si le `modDate` distant a avancé depuis le dernier cache
    `RessourceExterne.metadonnees_brutes.modDate`, on signale dans
    `rapport.derive`. Consultatif : n'empêche pas le push.
    """
    from archives_tool.models import RessourceExterne, SourceExterne

    contenu = b"new"
    sha1_ancien = "bb" + "0" * 38

    # Distant : `modDate` recent (2026-06-14)
    lecture = _FakeClientLecture(
        files=[{"sha1": sha1_ancien, "name": "x.jpg"}],
        mod_date="2026-06-14T12:00:00",
    )
    ecriture = _FakeClientEcriture()

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg",
             "contenu": contenu, "sha1_nakala": sha1_ancien},
        ])
        # Cache RessourceExterne avec modDate ancien.
        source = SourceExterne(
            code="nakala",
            libelle="Nakala test",
            type_api="rest",
            url_base="https://api.nakala.fr",
        )
        s.add(source)
        s.flush()
        s.add(RessourceExterne(
            source_id=source.id,
            identifiant_externe=item.doi_nakala,
            metadonnees_brutes={"modDate": "2026-01-01T08:00:00"},
        ))
        s.commit()

        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=True,
        )

    # Dérive détectée (distant > baseline).
    assert rapport.derive is True


def test_pousser_pas_de_derive_si_baseline_egale_distant(
    db_path: Path, tmp_path: Path,
) -> None:
    """Pas de cache ou cache à jour → `derive=False`."""
    contenu = b"sain"
    sha1 = _sha1(contenu)
    lecture = _FakeClientLecture(
        files=[{"sha1": sha1, "name": "x.jpg"}],
        mod_date="2026-01-01T08:00:00",
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg",
             "contenu": contenu, "sha1_nakala": sha1},
        ])
        # Pas de RessourceExterne → baseline=None → derive=False
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
        )
    assert rapport.derive is False


# ---------------------------------------------------------------------------
# P3+c.2 passe 5 — doublons sha1 distants (cas archivistique legitime)
# ---------------------------------------------------------------------------


def test_comparer_preserve_doublons_sha1_distants_inchanges_apparies(
    db_path: Path, tmp_path: Path,
) -> None:
    """Trou M — deux fichiers distants ont le même sha1 (cas légitime :
    deux pages blanches scannees, deux planches vides…).

    Cote ColleC : deux Fichier portant le même binaire local.

    Avant le fix : `sha1_index = dict[sha1, fd]` écrasait le 2e doublon,
    et la boucle orphelins itérait sur l'index (1 entrée) → le 2e doublon
    était silencieusement perdu.

    Après le fix : `sha1_index = dict[sha1, list[fd]]` avec consommation
    par `pop(0)`. Chaque Fichier ColleC consomme 1 entrée distante,
    le compte final est correct.
    """
    contenu = b"page blanche"
    sha1 = _sha1(contenu)
    # Distant : 2 fichiers avec le MEME sha1, noms differents.
    lecture = _FakeClientLecture(files=[
        {"sha1": sha1, "name": "page-blanche-debut.jpg"},
        {"sha1": sha1, "name": "page-blanche-fin.jpg"},
    ])
    with _session(db_path) as s:
        # Cote ColleC : 2 Fichier avec le meme contenu binaire.
        # Reutilise le helper en posant 2 binaires de meme contenu.
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "page-blanche-debut.jpg",
             "contenu": contenu, "sha1_nakala": sha1},
            {"ordre": 2, "nom": "page-blanche-fin.jpg",
             "contenu": contenu, "sha1_nakala": sha1},
        ])
        rapport = comparer_fichiers_item(
            s, lecture, item, racines={"scans": tmp_path / "scans"},
        )
    # 2 inchanges (1 par Fichier ColleC).
    assert len(rapport.inchanges) == 2
    # 0 orphelin : chaque doublon distant a ete consomme.
    assert rapport.orphelins_distants == []
    # 0 nouveau, 0 modifie.
    assert rapport.nouveaux == []
    assert rapport.modifies == []


def test_comparer_doublons_sha1_distants_avec_1_seul_fichier_local_classe_2e_en_orphelin(
    db_path: Path, tmp_path: Path,
) -> None:
    """Distant a 2 fichiers avec meme sha1, ColleC n'a qu'1 Fichier
    correspondant. Le 2e doublon distant DOIT ressortir en orphelin
    (regression test : avant le fix il etait silencieusement perdu)."""
    contenu = b"page blanche"
    sha1 = _sha1(contenu)
    lecture = _FakeClientLecture(files=[
        {"sha1": sha1, "name": "premier.jpg"},
        {"sha1": sha1, "name": "doublon-perdu.jpg"},
    ])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "premier.jpg",
             "contenu": contenu, "sha1_nakala": sha1},
        ])
        rapport = comparer_fichiers_item(
            s, lecture, item, racines={"scans": tmp_path / "scans"},
        )
    assert len(rapport.inchanges) == 1
    # CRITIQUE : le 2e doublon distant ressort en orphelin propre.
    assert len(rapport.orphelins_distants) == 1
    assert rapport.orphelins_distants[0].sha1 == sha1
    # Le nom transporte est celui du doublon non-apparie (le 2e dans
    # l'ordre Nakala car le 1er a ete consomme par `pop(0)`).
    assert rapport.orphelins_distants[0].nom_fichier == "doublon-perdu.jpg"


def test_pousser_doublons_sha1_distants_preserves_dans_files_cible(
    db_path: Path, tmp_path: Path,
) -> None:
    """Trou M scenario push : si distant a 2 fichiers meme sha1 et que
    ColleC a 2 Fichier appariés, le PUT doit envoyer 2 entrées dans
    `files[]` avec ce sha1 (Nakala accepte les doublons sha1, H1 confirme
    que `files[]` est remplacé intégralement). Sinon le 2e serait retiré.

    On declenche un PUT en ajoutant un Fichier modifie en plus.
    """
    contenu_doublon = b"identique"
    sha1_doublon = _sha1(contenu_doublon)
    contenu_modif = b"a modifier"
    sha1_ancien = _sha1(b"ancien contenu")  # pre-modif

    lecture = _FakeClientLecture(files=[
        {"sha1": sha1_doublon, "name": "a.jpg"},
        {"sha1": sha1_doublon, "name": "b.jpg"},  # MEME sha1
        {"sha1": sha1_ancien, "name": "c.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "a.jpg",
             "contenu": contenu_doublon, "sha1_nakala": sha1_doublon},
            {"ordre": 2, "nom": "b.jpg",
             "contenu": contenu_doublon, "sha1_nakala": sha1_doublon},
            {"ordre": 3, "nom": "c.jpg",
             "contenu": contenu_modif, "sha1_nakala": sha1_ancien},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    # 1 PUT envoye, 1 upload (pour c.jpg modifie).
    assert len(ecriture.puts) == 1
    files_envoyes = ecriture.puts[0]["files"]
    # 3 entrees dans `files[]` (les 2 doublons + le modifie).
    assert len(files_envoyes) == 3
    # Les 2 entrees a.jpg / b.jpg avec sha1_doublon sont preservees.
    sha1s_envoyes = [f["sha1"] for f in files_envoyes]
    assert sha1s_envoyes.count(sha1_doublon) == 2
    noms = [f["name"] for f in files_envoyes]
    assert "a.jpg" in noms
    assert "b.jpg" in noms
    assert rapport.applique is True


# ---------------------------------------------------------------------------
# P3+c.2 passe 6 — Trou O : Fichier non-ACTIF explicites au lieu de
# silence ("orphelins anonymes")
# ---------------------------------------------------------------------------


def test_comparer_fichier_corbeille_sans_pendant_distant_pas_de_categorie(
    db_path: Path, tmp_path: Path,
) -> None:
    """Un Fichier CORBEILLE sans `sha1_nakala` posé OU sans matching
    distant n'apparait dans aucune categorie - il n'y a rien a retirer
    de Nakala.

    (Filet de regression : eviter qu'on ajoute par erreur ces Fichier
    a `non_actifs_a_retirer` sans verifier qu'ils ont vraiment un
    pendant distant.)
    """
    client = _FakeClientLecture(files=[])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "deja_supprime.jpg",
             "contenu": b"x", "sha1_nakala": None},
        ])
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).all()
        fichiers[0].etat = EtatFichier.CORBEILLE.value
        s.commit()
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert rapport.non_actifs_a_retirer == []
    assert rapport.aucun_changement


def test_pousser_non_actifs_inclus_dans_sha1s_retires_au_put(
    db_path: Path, tmp_path: Path,
) -> None:
    """Un Fichier CORBEILLE avec sha1_nakala matchant le distant est
    retire au PUT (exclus de `files_cible`) ET trace dans
    `sha1s_retires` (au lieu d'un retrait silencieux).

    Couvre la jonction Trou O (passe 6) + traçabilité utilisateur.
    Combine avec un Fichier ACTIF modifie pour declencher le PUT.
    """
    contenu_corbeille = b"a supprimer"
    sha1_corbeille = _sha1(contenu_corbeille)
    contenu_actif_neuf = b"modifie"
    sha1_actif_ancien = _sha1(b"ancien actif")

    lecture = _FakeClientLecture(files=[
        {"sha1": sha1_corbeille, "name": "corbeille.jpg"},
        {"sha1": sha1_actif_ancien, "name": "actif.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "actif.jpg",
             "contenu": contenu_actif_neuf, "sha1_nakala": sha1_actif_ancien},
            {"ordre": 2, "nom": "corbeille.jpg",
             "contenu": contenu_corbeille, "sha1_nakala": sha1_corbeille},
        ])
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        fichiers[1].etat = EtatFichier.CORBEILLE.value
        s.commit()

        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )

    # Le fichier corbeille est trace dans non_actifs_a_retirer
    assert rapport.compare is not None
    assert len(rapport.compare.non_actifs_a_retirer) == 1
    assert rapport.compare.non_actifs_a_retirer[0].nom_fichier == "corbeille.jpg"
    # sha1_corbeille est listee dans sha1s_retires (traçabilité user)
    assert sha1_corbeille.lower() in rapport.sha1s_retires
    # PUT envoye, files_cible ne contient PAS le sha1 corbeille
    assert len(ecriture.puts) == 1
    files_envoyes = ecriture.puts[0]["files"]
    sha1s_envoyes = [f["sha1"] for f in files_envoyes]
    assert sha1_corbeille.lower() not in sha1s_envoyes
    # Les autres traitements normaux (modif actif) ont eu lieu
    assert rapport.applique is True


def test_comparer_dry_run_aucun_changement_si_seul_non_actif_existe(
    db_path: Path, tmp_path: Path,
) -> None:
    """Item ne contenant QUE des Fichier non-ACTIF avec pendant distant
    → `aucun_changement` est False (un retrait est planifie)."""
    contenu = b"x"
    sha1 = _sha1(contenu)
    client = _FakeClientLecture(files=[{"sha1": sha1, "name": "x.jpg"}])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg",
             "contenu": contenu, "sha1_nakala": sha1},
        ])
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).all()
        fichiers[0].etat = EtatFichier.CORBEILLE.value
        s.commit()
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    assert len(rapport.non_actifs_a_retirer) == 1
    assert not rapport.aucun_changement


# ---------------------------------------------------------------------------
# P3+c.2 passe 7 — Trou P : defense en profondeur sur le retour
# uploader_fichier (sha1 vide / malforme / non-string)
# ---------------------------------------------------------------------------


class _FakeClientEcritureUploadMalforme:
    """Stub `NakalaEcritureClient` qui retourne une reponse degradee
    sur `uploader_fichier`. Le `pattern_reponse` controle le scenario."""

    def __init__(self, pattern_reponse: dict | None | str) -> None:
        self.pattern = pattern_reponse
        self.uploads: list[str] = []
        self.puts: list[dict] = []
        self.supprimes: list[str] = []

    def uploader_fichier(self, chemin, nom=None):
        n = nom or Path(chemin).name
        self.uploads.append(n)
        return self.pattern

    def modifier_depot(self, identifiant, *, metas=None, files=None, status=None):
        self.puts.append({"id": identifiant, "metas": metas, "files": files,
                          "status": status})
        return {}

    def supprimer_upload(self, sha1):
        self.supprimes.append(sha1)


@pytest.mark.parametrize("reponse,motif", [
    (None, "dict"),  # pas un dict
    ({}, "absent"),  # sha1 absent
    ({"sha1": None}, "non-string"),  # sha1 None
    ({"sha1": ""}, "longueur 0"),  # sha1 vide
    ({"sha1": "   "}, "longueur 0"),  # sha1 whitespace
    ({"sha1": "abc"}, "longueur 3"),  # sha1 trop court
    ({"sha1": "z" * 40}, "non-hex"),  # 40 chars mais non-hex
])
def test_pousser_upload_invalide_leve_exception_propre(
    db_path: Path, tmp_path: Path, reponse, motif,
) -> None:
    """Toute reponse degradee d'`uploader_fichier` doit lever
    `UploadInvalide` AVANT le PUT, pas planter en KeyError / TypeError /
    AttributeError au coeur du code.
    """
    contenu = b"nouveau fichier"
    lecture = _FakeClientLecture(files=[])  # distant vide → tout est nouveau
    ecriture = _FakeClientEcritureUploadMalforme(reponse)

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        with pytest.raises(UploadInvalide) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )

    # Le message d'erreur cite la cause (motif partiel attendu)
    assert motif in str(exc_info.value).lower() or motif in str(exc_info.value)
    # Aucun PUT envoye (echec avant)
    assert ecriture.puts == []


def test_pousser_upload_invalide_declenche_cleanup_des_uploads_precedents(
    db_path: Path, tmp_path: Path,
) -> None:
    """Si on a N fichiers a uploader et que le 2e retourne un sha1
    invalide, le 1er upload reussi doit etre nettoye via
    `supprimer_upload` (best-effort) avant que l'exception propage.

    Defense en profondeur contre les fuites d'uploads orphelins cote
    Nakala. Le cleanup ne nettoie QUE les sha1 valides accumules avant
    l'echec - le sha1 invalide n'est jamais ajoute a `sha1s_uploades`
    (validation prealable).
    """

    class _StubAvecPremierOK:
        def __init__(self):
            self.compteur_upload = 0
            self.uploads: list[str] = []
            self.puts: list[dict] = []
            self.supprimes: list[str] = []

        def uploader_fichier(self, chemin, nom=None):
            self.compteur_upload += 1
            self.uploads.append(nom or Path(chemin).name)
            if self.compteur_upload == 1:
                # 1er upload : sha1 valide
                return {"sha1": "a" * 40, "name": nom}
            # 2e upload : sha1 vide → UploadInvalide
            return {"sha1": ""}

        def modifier_depot(self, identifiant, *, metas=None, files=None,
                          status=None):
            self.puts.append({"id": identifiant})
            return {}

        def supprimer_upload(self, sha1):
            self.supprimes.append(sha1)

    lecture = _FakeClientLecture(files=[])
    ecriture = _StubAvecPremierOK()

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "premier.jpg",
             "contenu": b"premier", "sha1_nakala": None},
            {"ordre": 2, "nom": "second.jpg",
             "contenu": b"second", "sha1_nakala": None},
        ])
        with pytest.raises(UploadInvalide):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )

    # Le 1er upload reussi est nettoye, le 2e (invalide) ne l'est pas
    # (jamais ajoute a `sha1s_uploades`).
    assert ecriture.supprimes == ["a" * 40]
    # Aucun PUT envoye (echec apres upload du 2e, avant PUT)
    assert ecriture.puts == []


# ---------------------------------------------------------------------------
# P3+c.2 passe 8 — Trou Q : assertions → exceptions propres
# (race conditions Fichier ORM entre comparer et pousser)
# ---------------------------------------------------------------------------


def test_pousser_fichier_supprime_apres_comparer_leve_incoherence(
    db_path: Path, tmp_path: Path,
) -> None:
    """Race condition : une autre session supprime un Fichier entre
    `comparer_fichiers_item` (qui le classe en "nouveau") et le
    re-fetch dans `pousser_fichiers_item`. Avant Trou Q : `assert
    fichier_orm is not None` → AssertionError mince. Apres :
    `IncoherenceFichierORM` avec message diagnostique.

    Simule en patchant `db.get(Fichier, ...)` pour qu'il retourne None.
    """
    contenu = b"a uploader"
    lecture = _FakeClientLecture(files=[])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        # Patche db.get pour simuler une suppression concurrente.
        original_get = s.get

        def get_qui_simule_suppression(model_class, ident, **kwargs):
            if model_class is Fichier:
                return None  # simule Fichier supprime
            return original_get(model_class, ident, **kwargs)

        s.get = get_qui_simule_suppression  # type: ignore[method-assign]

        with pytest.raises(IncoherenceFichierORM) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )

    assert "supprime" in str(exc_info.value).lower()
    assert "race" in str(exc_info.value).lower()
    # Aucun upload ni PUT (echec avant)
    assert ecriture.uploads == []
    assert ecriture.puts == []


def test_pousser_fichier_perdu_racine_apres_comparer_leve_incoherence(
    db_path: Path, tmp_path: Path,
) -> None:
    """Race condition variant : le Fichier existe encore mais a perdu
    sa `racine` ou son `chemin_relatif` (une autre session a bascule
    en CORBEILLE et reset les chemins, par exemple). Detection +
    `IncoherenceFichierORM` propre."""
    contenu = b"a uploader"
    lecture = _FakeClientLecture(files=[])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        # Patche db.get pour retourner un Fichier mute (racine effacee).
        # On garde le Fichier ORM original mais on simule la perte de
        # racine APRES le comparer.
        from sqlalchemy.orm import attributes

        original_get = s.get

        def get_qui_simule_perte_racine(model_class, ident, **kwargs):
            obj = original_get(model_class, ident, **kwargs)
            if model_class is Fichier and obj is not None:
                # Force racine = None sans toucher en DB
                attributes.set_attribute(obj, "racine", None)
            return obj

        s.get = get_qui_simule_perte_racine  # type: ignore[method-assign]

        with pytest.raises(IncoherenceFichierORM) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )

    assert "racine" in str(exc_info.value).lower() or "perdu" in str(exc_info.value).lower()
    assert ecriture.uploads == []
    assert ecriture.puts == []


# ---------------------------------------------------------------------------
# P3+c.2 passe 8 — Trou R : observabilité runtime (logging structuré)
# ---------------------------------------------------------------------------


def test_pousser_emet_log_info_au_demarrage_et_commit(
    db_path: Path, tmp_path: Path, caplog,
) -> None:
    """Verifie qu'un push reel emet bien les logs INFO de demarrage et
    de COMMIT. Niveau minimum pour debug post-mortem en prod."""
    import logging as _logging
    caplog.set_level(_logging.INFO, logger="archives_tool.api.services.nakala_fichiers")

    contenu = b"a uploader"
    lecture = _FakeClientLecture(files=[])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )

    messages = [rec.message for rec in caplog.records if rec.name.endswith("nakala_fichiers")]
    assert any("push fichiers START" in m for m in messages)
    assert any("push fichiers PUT OK" in m for m in messages)
    assert any("push fichiers COMMIT" in m for m in messages)


def test_pousser_emet_log_warning_au_cleanup(
    db_path: Path, tmp_path: Path, caplog,
) -> None:
    """Si le PUT echoue apres uploads reussis, log WARNING explicite +
    cleanup tente."""
    import logging as _logging
    caplog.set_level(_logging.WARNING, logger="archives_tool.api.services.nakala_fichiers")

    class _StubPUTKO:
        def __init__(self):
            self.uploads: list[str] = []
            self.supprimes: list[str] = []

        def uploader_fichier(self, chemin, nom=None):
            self.uploads.append(nom or Path(chemin).name)
            return {"sha1": f"{len(self.uploads):040x}", "name": nom}

        def modifier_depot(self, identifiant, **kwargs):
            from archives_tool.external.nakala.client import ErreurNakala
            raise ErreurNakala("PUT simule KO")

        def supprimer_upload(self, sha1):
            self.supprimes.append(sha1)

    lecture = _FakeClientLecture(files=[])
    ecriture = _StubPUTKO()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": b"x", "sha1_nakala": None},
        ])
        from archives_tool.external.nakala.client import ErreurNakala
        with pytest.raises(ErreurNakala):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )

    messages = [rec.message for rec in caplog.records if rec.name.endswith("nakala_fichiers")]
    assert any("ECHEC" in m and "cleanup=1" in m for m in messages)
    # Cleanup effectivement tente
    assert ecriture.supprimes == [f"{1:040x}"]


# ---------------------------------------------------------------------------
# P3+c.2 passe 9 — Trou T : item published refuse par defaut (DOI DataCite)
# ---------------------------------------------------------------------------


def test_pousser_refuse_item_publie_par_defaut(
    db_path: Path, tmp_path: Path,
) -> None:
    """Un item `status=published` cote Nakala a des DOIs DataCite mintes
    sur ses fichiers. Toute modif de `files[]` casse l'integrite des
    citations externes. Sans `forcer_publie=True`, refus loud."""
    contenu_neuf = b"a uploader"
    sha1_ancien = _sha1(b"ancien contenu")
    lecture = _FakeClientLecture(
        files=[{"sha1": sha1_ancien, "name": "x.jpg"}],
        statut="published",  # PUBLIE → DOI DataCite minté
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            # binaire modifie
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu_neuf,
             "sha1_nakala": sha1_ancien},
        ])
        with pytest.raises(DepotPublie) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )

    # L'exception expose le contexte
    assert exc_info.value.statut == "published"
    assert exc_info.value.cote == "AS-001"
    assert "citation" in str(exc_info.value).lower()
    # Aucun upload ni PUT (refus avant)
    assert ecriture.uploads == []
    assert ecriture.puts == []


def test_pousser_avec_forcer_publie_passe_quand_meme(
    db_path: Path, tmp_path: Path,
) -> None:
    """Avec `forcer_publie=True`, le user a explicitement accepte le
    risque. Le push procede normalement (= upload + PUT)."""
    contenu_neuf = b"a uploader"
    sha1_ancien = _sha1(b"ancien contenu")
    lecture = _FakeClientLecture(
        files=[{"sha1": sha1_ancien, "name": "x.jpg"}],
        statut="published",
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu_neuf,
             "sha1_nakala": sha1_ancien},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
            forcer_publie=True,
        )

    assert rapport.applique is True
    assert len(ecriture.uploads) == 1
    assert len(ecriture.puts) == 1
    # Le rapport expose le statut pour traçabilité user.
    assert rapport.compare is not None
    assert rapport.compare.statut_distant == "published"


def test_pousser_dry_run_publie_pas_de_refus_pas_de_lievre(
    db_path: Path, tmp_path: Path,
) -> None:
    """Dry-run sur item publié : refus quand meme (l'exception sert
    aussi d'aperçu - le user comprend qu'il faut `--force-published`
    AVANT de lancer le `--no-dry-run`)."""
    contenu = b"x"
    sha1 = _sha1(contenu)
    contenu_neuf = b"nouveau"
    lecture = _FakeClientLecture(
        files=[{"sha1": sha1, "name": "x.jpg"}],
        statut="published",
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            # binaire modifie pour declencher push
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu_neuf,
             "sha1_nakala": sha1},
        ])
        # Refus en dry-run aussi (sans flag) - dry-run ne contourne pas
        # les garde-fous metiers, seulement les ecritures distantes.
        with pytest.raises(DepotPublie):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=True,
            )


def test_pousser_pending_ne_refuse_pas(
    db_path: Path, tmp_path: Path,
) -> None:
    """Symetrie : sur item `pending` (defaut Nakala apres depot),
    pas de refus, comportement normal."""
    contenu = b"a uploader"
    lecture = _FakeClientLecture(
        files=[],
        statut="pending",  # ← non-published
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    assert rapport.applique is True
    assert rapport.compare.statut_distant == "pending"


def test_pousser_statut_absent_du_distant_ne_refuse_pas(
    db_path: Path, tmp_path: Path,
) -> None:
    """Si Nakala omet le champ `status` (cas degenere ou ancien format),
    on ne refuse pas - on traite comme non-publié (precaution
    asymetrique : refuser sur la base d'une absence serait gener
    inutilement le user)."""
    contenu = b"a uploader"
    lecture = _FakeClientLecture(files=[])  # pas de statut
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    assert rapport.applique is True
    assert rapport.compare.statut_distant is None


# ---------------------------------------------------------------------------
# P3+c.2 passe 10 — Trou U : sha1_nakala fantome (desync DB ↔ Nakala)
# ---------------------------------------------------------------------------


def test_comparer_classe_fichier_fantome_distinct_de_nakala_only(
    db_path: Path, tmp_path: Path,
) -> None:
    """Fichier ColleC sans binaire local avec `sha1_nakala="abc"` ET
    distant ne contient plus "abc" (mais "def" autre fichier) →
    categorie `fichiers_fantomes` propre, PAS `nakala_only_sans_local`.

    Distingue 3 cas (post-Trou U) :
    - sha1_nakala MATCHE distant → nakala_only_sans_local (legitime)
    - sha1_nakala SANS MATCH → fichiers_fantomes (desync)
    - sha1_nakala absent (None) → nakala_only_sans_local (backfill
      incomplet, sera attrape par BackfillIncomplet au push)
    """
    sha1_fantome = "abc" + "0" * 37
    sha1_present = "def" + "0" * 37
    client = _FakeClientLecture(files=[
        # Distant a "def" mais pas "abc".
        {"sha1": sha1_present, "name": "actuel.jpg"},
    ])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            # Fichier ColleC : sha1_nakala=fantome, pas de binaire local.
            {"ordre": 1, "nom": "fantome.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/.../info.json",
             "sha1_nakala": sha1_fantome},
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )

    # Classe en fantome, pas en nakala_only_sans_local
    assert len(rapport.fichiers_fantomes) == 1
    assert rapport.fichiers_fantomes[0].nom_fichier == "fantome.jpg"
    assert rapport.fichiers_fantomes[0].sha1_distant == sha1_fantome
    assert rapport.nakala_only_sans_local == []
    # Le "def" du distant ressort en orphelin (cote Nakala non
    # reconcilie avec un Fichier ColleC).
    assert len(rapport.orphelins_distants) == 1
    assert rapport.orphelins_distants[0].sha1 == sha1_present


def test_pousser_refuse_si_fichiers_fantomes(
    db_path: Path, tmp_path: Path,
) -> None:
    """Au push, lever `FichierFantomeDistant` avant tout PUT.

    Sans ce garde-fou : le plan contiendrait `{sha1: fantome, name: X}`,
    le PUT recevrait H4 (sha1 inconnu) → HTTP 404 cryptique cote user.
    """
    sha1_fantome = "abc" + "0" * 37
    lecture = _FakeClientLecture(files=[])  # distant vide, fantome confirmé
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "fantome.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/.../info.json",
             "sha1_nakala": sha1_fantome},
        ])
        with pytest.raises(FichierFantomeDistant) as exc_info:
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )

    # L'exception expose la liste
    assert len(exc_info.value.fichiers) == 1
    assert exc_info.value.fichiers[0].nom_fichier == "fantome.jpg"
    # Le message d'erreur cite le sha1 tronque et propose rapatrier
    assert "rapatrier" in str(exc_info.value).lower()
    assert sha1_fantome[:12] in str(exc_info.value)
    # Aucun upload ni PUT (echec amont)
    assert ecriture.uploads == []
    assert ecriture.puts == []


def test_pousser_garde_fou_fantome_precede_garde_fou_backfill(
    db_path: Path, tmp_path: Path,
) -> None:
    """Si on a a la fois fantomes ET backfill incomplet, le garde-fou
    fantome se declenche en premier (ordre dans pousser_fichiers_item).

    Documente la priorite des garde-fous : on signale d'abord la
    desync (plus pernicieuse) avant le backfill (qui est juste un
    nettoyage de donnees legacy).
    """
    sha1_fantome = "abc" + "0" * 37
    lecture = _FakeClientLecture(files=[])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            # Fichier 1 : fantome
            {"ordre": 1, "nom": "fantome.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/.../info.json",
             "sha1_nakala": sha1_fantome},
            # Fichier 2 : backfill incomplet
            {"ordre": 2, "nom": "backfill.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/.../info.json",
             "sha1_nakala": None},
        ])
        # Le fantome est leve en premier (BackfillIncomplet jamais atteint)
        with pytest.raises(FichierFantomeDistant):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )
    assert ecriture.puts == []


def test_comparer_aucun_changement_avec_fantome_seul_est_false(
    db_path: Path, tmp_path: Path,
) -> None:
    """Un fantome IMPOSE `aucun_changement = False` (mise a jour
    semantique passe 10) : il y a un probleme a fixer (desync DB ↔
    Nakala), le push ne peut pas se contenter d'un no-op silencieux.

    Sans cette inclusion, le service court-circuiterait le garde-fou
    `FichierFantomeDistant` via le return early sur aucun_changement.
    """
    sha1_fantome = "abc" + "0" * 37
    client = _FakeClientLecture(files=[])
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "f.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/.../info.json",
             "sha1_nakala": sha1_fantome},
        ])
        rapport = comparer_fichiers_item(
            s, client, item, racines={"scans": tmp_path / "scans"},
        )
    # CRITIQUE : fantome force aucun_changement=False (sinon push
    # silencieux ne signale rien).
    assert rapport.aucun_changement is False
    assert len(rapport.fichiers_fantomes) == 1


# ---------------------------------------------------------------------------
# P3+c.2 passe 11 — Trou V : iiif_url_nakala recale apres push
# ---------------------------------------------------------------------------


def test_pousser_met_a_jour_iiif_url_nakala_apres_changement_sha(
    db_path: Path, tmp_path: Path,
) -> None:
    """Apres un push qui change le sha cote Nakala (upload binaire
    modifie), `Fichier.iiif_url_nakala` doit etre recalee — sinon
    l'URL pointe vers l'ancien sha → 404 sur tout viewer ColleC.

    Le service met a jour sha1_nakala + iiif_url_nakala en parallele
    via `remplacer_sha` (Trou V passe 11).
    """
    contenu_ancien = b"ancien contenu"
    sha_ancien = _sha1(contenu_ancien)
    contenu_neuf = b"contenu modifie"
    DOI = "10.34847/nkl.abc"
    iiif_url_ancienne = f"https://api-test.nakala.fr/iiif/{DOI}/{sha_ancien}/info.json"

    lecture = _FakeClientLecture(files=[
        {"sha1": sha_ancien, "name": "x.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu_neuf,
             "sha1_nakala": sha_ancien,
             "iiif_url_nakala": iiif_url_ancienne},
        ])
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )

    # Le sha a change via stub (format 40 hex), recupere du rapport
    assert len(rapport.sha1s_uploades) == 1
    sha_neuf = rapport.sha1s_uploades[0]

    # iiif_url_nakala doit pointer vers le nouveau sha
    with _session(db_path) as s:
        f = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).first()
        assert f is not None
        assert sha_neuf in f.iiif_url_nakala
        assert sha_ancien not in f.iiif_url_nakala
        # Host preserve (api-test reste api-test)
        assert "api-test.nakala.fr" in f.iiif_url_nakala
        # sha1_nakala parallelement mis a jour
        assert f.sha1_nakala == sha_neuf


def test_pousser_ne_touche_pas_iiif_url_si_pas_pose(
    db_path: Path, tmp_path: Path,
) -> None:
    """Si `iiif_url_nakala` est None (Fichier sans URL pré-existante),
    le service n'invente pas d'URL. iiif_url_nakala reste None apres push."""
    contenu = b"a uploader"
    lecture = _FakeClientLecture(files=[])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None,
             "iiif_url_nakala": None},
        ])
        pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    with _session(db_path) as s:
        f = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).first()
        assert f.iiif_url_nakala is None


def test_pousser_inchange_ne_recale_pas_iiif_url(
    db_path: Path, tmp_path: Path,
) -> None:
    """Symetrie negative : si le Fichier est inchange (sha matche
    distant), aucun upload, donc nouveaux_sha1_par_fichier vide, donc
    pas de touch a iiif_url_nakala. L'URL reste celle d'origine.

    Documente la convention : seuls les Fichier dont le sha a vraiment
    change sont recales."""
    contenu = b"inchange"
    sha = _sha1(contenu)
    DOI = "10.34847/nkl.abc"
    url = f"https://api-test.nakala.fr/iiif/{DOI}/{sha}/info.json"

    # On declenche un PUT en ajoutant un 2e Fichier nouveau
    contenu_nouveau = b"nouveau"
    lecture = _FakeClientLecture(files=[
        {"sha1": sha, "name": "i.jpg"},
    ])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "i.jpg", "contenu": contenu, "sha1_nakala": sha,
             "iiif_url_nakala": url},
            {"ordre": 2, "nom": "n.jpg", "contenu": contenu_nouveau,
             "sha1_nakala": None, "iiif_url_nakala": None},
        ])
        pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    with _session(db_path) as s:
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        # Fichier i (inchange) : url inchangee
        assert fichiers[0].iiif_url_nakala == url
        # Fichier n (nouveau) : pas d'URL pre-existante, reste None
        assert fichiers[1].iiif_url_nakala is None


# ---------------------------------------------------------------------------
# P3+c.2 passe 12 — Trous W + X : cohérence cross-champs post-push
# (metadonnees["sha1"] miroir + derives locaux invalides)
# ---------------------------------------------------------------------------


def test_pousser_met_a_jour_metadonnees_sha1_miroir(
    db_path: Path, tmp_path: Path,
) -> None:
    """Trou W — `materialiser_fichiers_nakala` (rapatrier) ecrit le sha1
    en miroir dans `metadonnees["sha1"]` pour compat retro
    (consommateurs qui lisaient la avant P3+a). Apres push qui change
    `sha1_nakala`, le miroir doit etre sync — sinon `sha1_nakala`
    (canonique) et `metadonnees["sha1"]` (miroir) divergent silencieusement.
    """
    contenu_ancien = b"ancien"
    sha_ancien = _sha1(contenu_ancien)
    contenu_neuf = b"nouveau"
    lecture = _FakeClientLecture(files=[{"sha1": sha_ancien, "name": "x.jpg"}])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu_neuf,
             "sha1_nakala": sha_ancien},
        ])
        # Pose le miroir compat retro
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).all()
        fichiers[0].metadonnees = {"sha1": sha_ancien, "size": 123, "embargoed": None}
        s.commit()

        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    sha_neuf = rapport.sha1s_uploades[0]
    with _session(db_path) as s:
        f = s.scalars(select(Fichier).join(Item).where(Item.cote == "AS-001")).first()
        # `sha1_nakala` (canonique) = `metadonnees["sha1"]` (miroir).
        assert f.sha1_nakala == sha_neuf
        assert f.metadonnees["sha1"] == sha_neuf
        # Les AUTRES cles de metadonnees sont preservees (pas wipe complet).
        assert f.metadonnees["size"] == 123
        assert "embargoed" in f.metadonnees


def test_pousser_ne_cree_pas_metadonnees_sha1_si_absent(
    db_path: Path, tmp_path: Path,
) -> None:
    """Si `metadonnees["sha1"]` n'existe pas, le service ne l'invente
    pas (semantique neutre : un Fichier importe via tableur n'a pas
    forcement ce miroir compat retro, on n'ajoute pas une cle qui
    n'existait pas).
    """
    contenu_ancien = b"ancien"
    sha_ancien = _sha1(contenu_ancien)
    contenu_neuf = b"nouveau"
    lecture = _FakeClientLecture(files=[{"sha1": sha_ancien, "name": "x.jpg"}])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu_neuf,
             "sha1_nakala": sha_ancien},
        ])
        # metadonnees vide (cas typique import tableur)
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).all()
        fichiers[0].metadonnees = {"autre": "valeur"}
        s.commit()

        pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    with _session(db_path) as s:
        f = s.scalars(select(Fichier).join(Item).where(Item.cote == "AS-001")).first()
        # `sha1` n'est PAS apparue dans metadonnees
        assert "sha1" not in f.metadonnees
        # L'autre cle est preservee
        assert f.metadonnees["autre"] == "valeur"


def test_pousser_metadonnees_None_pas_d_erreur(
    db_path: Path, tmp_path: Path,
) -> None:
    """Si `Fichier.metadonnees is None` (jamais initialise), le service
    ne plante pas. Filet de robustesse anti-AttributeError."""
    contenu_ancien = b"ancien"
    sha_ancien = _sha1(contenu_ancien)
    contenu_neuf = b"nouveau"
    lecture = _FakeClientLecture(files=[{"sha1": sha_ancien, "name": "x.jpg"}])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu_neuf,
             "sha1_nakala": sha_ancien},
        ])
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).all()
        fichiers[0].metadonnees = None  # cas degenere
        s.commit()

        pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    with _session(db_path) as s:
        f = s.scalars(select(Fichier).join(Item).where(Item.cote == "AS-001")).first()
        # metadonnees reste None (pas invente)
        assert f.metadonnees is None


def test_pousser_invalide_derives_locaux_apres_changement_binaire(
    db_path: Path, tmp_path: Path,
) -> None:
    """Trou X — apres un push qui change le binaire local (categorie
    `modifie`), les derives locaux (vignette, apercu, DZI) generes
    depuis l'ancien binaire sont obsoletes. Pattern aligne sur
    `renamer/execution._invalider_derives` (deja teste pour rename).
    """
    contenu_ancien = b"ancien"
    sha_ancien = _sha1(contenu_ancien)
    contenu_neuf = b"nouveau"
    lecture = _FakeClientLecture(files=[{"sha1": sha_ancien, "name": "x.jpg"}])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu_neuf,
             "sha1_nakala": sha_ancien},
        ])
        # Pose des derives "deja generes" du contenu ancien
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
        ).all()
        fichiers[0].derive_genere = True
        fichiers[0].apercu_chemin = "/cache/apercu/x.jpg"
        fichiers[0].vignette_chemin = "/cache/vignette/x.jpg"
        fichiers[0].dzi_chemin = "/cache/dzi/x.dzi"
        s.commit()

        pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    with _session(db_path) as s:
        f = s.scalars(select(Fichier).join(Item).where(Item.cote == "AS-001")).first()
        # Derives invalides (force regeneration au prochain `deriver appliquer`)
        assert f.derive_genere is False
        assert f.apercu_chemin is None
        assert f.vignette_chemin is None
        assert f.dzi_chemin is None


def test_pousser_inchange_n_invalide_pas_derives(
    db_path: Path, tmp_path: Path,
) -> None:
    """Symetrie negative : Fichier inchange (sha local == sha distant)
    ne voit pas ses derives invalides (le binaire n'a pas change, la
    vignette reste valide). Documente la convention : invalidation
    SEULEMENT pour modifies + nouveaux (= ceux qui ont declenche un
    upload donc une mutation effective)."""
    contenu = b"identique"
    sha = _sha1(contenu)
    # Distant a meme sha → categorie inchange. Declenche un PUT via un
    # 2e Fichier "nouveau"
    contenu_neuf = b"nouveau"
    lecture = _FakeClientLecture(files=[{"sha1": sha, "name": "i.jpg"}])
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "i.jpg", "contenu": contenu, "sha1_nakala": sha},
            {"ordre": 2, "nom": "n.jpg", "contenu": contenu_neuf,
             "sha1_nakala": None},
        ])
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        # Pose un derive sur l'inchange uniquement
        fichiers[0].derive_genere = True
        fichiers[0].vignette_chemin = "/cache/vignette/i.jpg"
        s.commit()

        pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    with _session(db_path) as s:
        fichiers = s.scalars(
            select(Fichier).join(Item).where(Item.cote == "AS-001")
            .order_by(Fichier.ordre)
        ).all()
        # Inchange : derive preserve
        assert fichiers[0].derive_genere is True
        assert fichiers[0].vignette_chemin == "/cache/vignette/i.jpg"


# ---------------------------------------------------------------------------
# P3+c.2 passe 13 — Trou Y : defense en profondeur sur lire_depot
# (symetrie avec _valider_sha1_uploade passe 7)
# ---------------------------------------------------------------------------


class _ClientLectureRetour:
    """Stub `ClientLectureNakala` qui retourne une valeur arbitraire au
    `lire_depot` (None, str, list, dict, etc.) pour piloter les
    scenarios de retour client degrade."""

    def __init__(self, retour: object) -> None:
        self._retour = retour
        self.appels: list[str] = []

    def lire_depot(self, doi):
        self.appels.append(doi)
        return self._retour


@pytest.mark.parametrize("retour,motif", [
    (None, "NoneType"),
    ("just a string", "str"),
    (42, "int"),
    ([1, 2, 3], "list"),
])
def test_comparer_lire_depot_retour_non_dict_leve_proprement(
    db_path: Path, tmp_path: Path, retour, motif,
) -> None:
    """`lire_depot` retournant un non-dict → `ReponseLectureInvalide`
    avec message diagnostique (cite le DOI et le type recu).

    Sans ce filet : AttributeError cryptique au .get() ligne suivante,
    impossible de savoir QUEL DOI a echoue.
    """
    client = _ClientLectureRetour(retour)
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": b"x", "sha1_nakala": None},
        ])
        with pytest.raises(ReponseLectureInvalide) as exc_info:
            comparer_fichiers_item(
                s, client, item, racines={"scans": tmp_path / "scans"},
            )
    msg = str(exc_info.value)
    # Message cite le DOI + le type recu
    assert item.doi_nakala in msg
    assert motif in msg


def test_pousser_lire_depot_initial_retour_non_dict_leve_proprement(
    db_path: Path, tmp_path: Path,
) -> None:
    """Le push utilise `comparer_fichiers_item` en interne — la validation
    se declenche bien au pull initial (pas seulement dans comparer
    isole)."""
    client = _ClientLectureRetour(None)

    class _StubEcriture:
        def uploader_fichier(self, *a, **kw): pass
        def modifier_depot(self, *a, **kw): pass
        def supprimer_upload(self, *a, **kw): pass

    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": b"x", "sha1_nakala": None},
        ])
        with pytest.raises(ReponseLectureInvalide):
            pousser_fichiers_item(
                s, client, _StubEcriture(), item,
                racines={"scans": tmp_path / "scans"},
            )


def test_pousser_lire_depot_post_put_retour_non_dict_leve_proprement(
    db_path: Path, tmp_path: Path,
) -> None:
    """Variant subtil : le re-pull APRES le PUT (refresh cache) retourne
    un non-dict. Le PUT est deja applique cote distant, mais le cache
    DB ne peut pas etre rafraichi → exception propre au lieu de
    AttributeError sur `mapper_depot(None)`.

    Cas de regression : sans validation au site #2 (post-PUT), le
    fix initial (passe 7 sur uploader, passe 13 sur lire pre-PUT)
    serait incomplet.
    """
    contenu = b"a uploader"
    # Le client fait 2 lire_depot dans pousser_fichiers_item :
    # 1. pull initial dans comparer_fichiers_item (OK)
    # 2. refresh cache post-PUT (RETURNS None)
    # Stub a 2 etats successifs.

    class _LectureDeuxEtats:
        def __init__(self):
            self.compteur = 0

        def lire_depot(self, doi):
            self.compteur += 1
            if self.compteur == 1:
                return {"identifier": doi, "files": []}  # pull initial OK
            return None  # post-PUT KO

    lecture = _LectureDeuxEtats()
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "x.jpg", "contenu": contenu, "sha1_nakala": None},
        ])
        with pytest.raises(ReponseLectureInvalide):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )
    # Le PUT a bien ete tente (le distant est a jour, c'est juste le
    # refresh cache qui foire). Le user voit une erreur propre.
    assert len(ecriture.puts) == 1


# ---------------------------------------------------------------------------
# P3+c.2 passe 14 — Trou Z : ordre des garde-fous diagnostic > consent
# ---------------------------------------------------------------------------


def test_garde_fou_fantome_precede_published(
    db_path: Path, tmp_path: Path,
) -> None:
    """Trou Z — si item published ET fichier fantome, c'est le fantome
    qui doit etre signale en premier (diagnostic > consent).

    Sans cet ordre : le user passe `--force-published`, croit que c'est
    juste un opt-in, puis decouvre que le vrai probleme est le fantome
    → double aller-retour.
    """
    sha1_fantome = "abc" + "0" * 37
    lecture = _FakeClientLecture(
        files=[],  # distant vide, sha1_nakala="abc" est fantome
        statut="published",
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "f.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/.../info.json",
             "sha1_nakala": sha1_fantome},
        ])
        # FichierFantomeDistant en premier (DIAGNOSTIC), pas DepotPublie
        # (CONSENT)
        with pytest.raises(FichierFantomeDistant):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )


def test_garde_fou_backfill_precede_published(
    db_path: Path, tmp_path: Path,
) -> None:
    """Symetrie : backfill incomplet est aussi un DIAGNOSTIC, doit
    preceder DepotPublie (CONSENT)."""
    lecture = _FakeClientLecture(
        files=[{"sha1": "x" + "0" * 39, "name": "X.jpg"}],
        statut="published",
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "X.jpg", "contenu": None,
             "iiif_url_nakala": "https://api.nakala.fr/.../info.json",
             "sha1_nakala": None},  # backfill incomplet (sha1 absent)
        ])
        # BackfillIncomplet en premier (DIAGNOSTIC), pas DepotPublie
        with pytest.raises(BackfillIncomplet):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )


def test_garde_fou_published_precede_orphelins(
    db_path: Path, tmp_path: Path,
) -> None:
    """Entre 2 CONSENTS (published + orphelins), published vient en
    premier car il est plus dangereux (DOI DataCite minte vs orphelin
    a retirer)."""
    sha1_orphelin = "or" + "1" * 38
    lecture = _FakeClientLecture(
        files=[{"sha1": sha1_orphelin, "name": "orphan.jpg"}],
        statut="published",
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        # Pas de Fichier ColleC → tout sha1 distant = orphelin
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[])
        # DepotPublie en premier (consent plus dangereux), pas
        # OrphelinsDetectes
        with pytest.raises(DepotPublie):
            pousser_fichiers_item(
                s, lecture, ecriture, item,
                racines={"scans": tmp_path / "scans"},
                dry_run=False,
            )


def test_published_avec_aucun_changement_ne_leve_pas_depot_publie(
    db_path: Path, tmp_path: Path,
) -> None:
    """Cas important : un item published mais SANS changement (push
    no-op idempotent) ne doit PAS lever DepotPublie - rien ne va
    etre modifie cote distant, l'opt-in n'a pas de raison d'etre
    declenche.

    Documente la convention : `aucun_changement` court-circuite
    AVANT les garde-fous metiers (le no-op idempotent est silencieux,
    pas bloque)."""
    contenu = b"identique"
    sha = _sha1(contenu)
    lecture = _FakeClientLecture(
        files=[{"sha1": sha, "name": "i.jpg"}],
        statut="published",
    )
    ecriture = _FakeClientEcriture()
    with _session(db_path) as s:
        item = _setup_item_avec_fichiers(s, tmp_path, fichiers_specs=[
            {"ordre": 1, "nom": "i.jpg", "contenu": contenu, "sha1_nakala": sha},
        ])
        # Aucun changement → return early. DepotPublie PAS leve.
        rapport = pousser_fichiers_item(
            s, lecture, ecriture, item,
            racines={"scans": tmp_path / "scans"},
            dry_run=False,
        )
    assert rapport.raison == "aucun_changement"
    assert rapport.applique is False
    assert ecriture.puts == []
