"""Tests du palier P3+b — détection versioning fichiers (lecture seule).

Couvre les 5 catégories de classification de `comparer_fichiers_item` :
nouveaux, modifies, inchanges, nakala_only_sans_local, orphelins_distants.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_fichiers import (
    ComparaisonImpossible,
    comparer_fichiers_item,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fichier, Item


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
    avec `files=[{sha1, name}]` configurable."""

    def __init__(self, files: list[dict[str, Any]]) -> None:
        self._files = files
        self.appels: list[str] = []

    def lire_depot(self, doi: str) -> dict[str, Any]:
        self.appels.append(doi)
        return {"identifier": doi, "files": self._files}


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
