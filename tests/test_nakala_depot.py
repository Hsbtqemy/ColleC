"""Tests du service de dépôt Nakala (P2/A4) — write client mocké."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds, lire_fonds_par_cote
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import (
    DepotImpossible,
    deposer_item,
    item_vers_slugs,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.depot_mapper import MetaInvalide
from archives_tool.models import Base, Fichier, Item

_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"


class _FakeWriteClient:
    """Enregistre les uploads + le corps de création ; renvoie un DOI."""

    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.depot_cree: dict | None = None
        self.supprimes: list[str] = []

    def uploader_fichier(self, chemin, nom=None):
        self.uploads.append(nom or Path(chemin).name)
        return {"name": nom or Path(chemin).name, "sha1": f"sha-{len(self.uploads)}"}

    def creer_depot(self, *, metas, files, status="pending", collections_ids=None):
        self.depot_cree = {
            "metas": metas, "files": files, "status": status,
            "collectionsIds": collections_ids,
        }
        return {"payload": {"id": "10.34847/nkl.cree1"}}

    def supprimer_upload(self, sha1):
        self.supprimes.append(sha1)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _item_avec_fichier_local(
    s, tmp_path: Path, *, createurs=("Somers, Armonía",), date="1984"
) -> Item:
    """Crée un fonds + item + 1 Fichier dont le binaire existe sur disque."""
    f = creer_fonds(s, FormulaireFonds(cote="AS", titre="Armonía Somers"))
    item = creer_item(s, FormulaireItem(
        cote="AS-001", titre="La mujer desnuda", fonds_id=f.id,
        date=date, langue="spa", description="Roman",
        type_coar="http://purl.org/coar/resource_type/c_2f33",
        metadonnees={"createurs": list(createurs), "sujets": ["Literatura"]},
    ))
    # Fichier avec binaire local.
    (tmp_path / "scans").mkdir(exist_ok=True)
    (tmp_path / "scans" / "as001.jpg").write_bytes(b"\xff\xd8\xff img")
    s.add(Fichier(
        item_id=item.id, nom_fichier="as001.jpg", racine="scans",
        chemin_relatif="as001.jpg", ordre=1,
    ))
    s.commit()
    return item


def test_item_vers_slugs_coeur() -> None:
    class _I:
        titre = "T"
        langue = "spa"
        date = "1984"
        description = "Desc"
        type_coar = "http://purl.org/coar/resource_type/c_2f33"
        metadonnees = {"createurs": ["Somers, Armonía"], "sujets": ["Lit"],
                       "dcterms_publisher": "CNRS", "dcterms_issued": "1984"}
    slugs = item_vers_slugs(_I())
    # Langue convertie 639-3 → RFC5646 pour Nakala (spa → es) : sur la VALEUR
    # `dcterms:language` ET sur l'attribut `lang` des littéraux multilingues
    # (sinon dépôt/push rejeté 422 — `spa` absent du vocab Nakala).
    assert slugs["nkl_title"] == [{"value": "T", "lang": "es"}]
    assert slugs["nkl_creator"] == ["Somers, Armonía"]
    assert slugs["nkl_created"] == "1984"
    assert slugs["nkl_type"].endswith("c_2f33")
    assert slugs["dcterms_subject"] == [{"value": "Lit", "lang": "es"}]
    assert slugs["dcterms_language"] == ["es"]
    # Extra multilingue coercé, extra date en liste de chaînes.
    assert slugs["dcterms_publisher"] == [{"value": "CNRS", "lang": "es"}]
    assert slugs["dcterms_issued"] == ["1984"]


def test_langue_vers_nakala() -> None:
    """ColleC stocke en 639-3 ; Nakala veut du RFC5646 (≈ 639-1)."""
    from archives_tool.external.nakala.mapper import langue_vers_nakala

    assert langue_vers_nakala("spa") == "es"  # bug live #422 corrigé
    assert langue_vers_nakala("fra") == "fr"
    assert langue_vers_nakala("eng") == "en"
    assert langue_vers_nakala("es") == "es"  # déjà 639-1 → inchangé
    assert langue_vers_nakala("fr-FR") == "fr"  # sous-tag région ignoré
    assert langue_vers_nakala("spq") == "spq"  # 639-3 sans 639-1 → tel quel
    assert langue_vers_nakala(None) is None
    assert langue_vers_nakala("") is None


def test_dry_run_ne_depose_rien(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        rapport = deposer_item(s, client, item, racines=racines, dry_run=True)
    assert rapport.dry_run and rapport.doi is None
    assert rapport.nb_fichiers == 1 and rapport.fichiers == ["as001.jpg"]
    # metas contient titre + créateur + date.
    uris = [m["propertyUri"] for m in rapport.metas]
    assert f"{_NKL}title" in uris and f"{_NKL}creator" in uris
    assert client.uploads == [] and client.depot_cree is None  # rien envoyé


def test_reel_upload_et_cree_depot(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        rapport = deposer_item(s, client, item, racines=racines, dry_run=False,
                               collection_doi="10.34847/nkl.col1", cree_par="T")
    assert rapport.doi == "10.34847/nkl.cree1"
    assert client.uploads == ["as001.jpg"]
    assert client.depot_cree["status"] == "pending"
    assert client.depot_cree["files"] == [{"sha1": "sha-1", "name": "as001.jpg"}]
    assert client.depot_cree["collectionsIds"] == ["10.34847/nkl.col1"]
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        assert item.doi_nakala == "10.34847/nkl.cree1"
        # P3+a : sha1 capturé à l'upload et persisté sur le Fichier.
        fichier = next(iter(item.fichiers))
        assert fichier.sha1_nakala == "sha-1"


def test_sha1_nakala_pas_persiste_si_creer_depot_echoue(
    db_path: Path, tmp_path: Path,
) -> None:
    """Si `creer_depot` lève après les uploads, les `sha1_nakala` mis en
    mémoire sur les Fichier ne sont pas commités (db.commit() jamais
    atteint). Garantit qu'un échec mid-flow ne laisse pas de sha1
    incohérent en base (les uploads orphelins ont été supprimés côté
    Nakala, on serait avec des sha1 pointant sur du vide)."""
    from archives_tool.api.services.nakala_depot import ErreurNakala

    class _ClientQuiFaitFlop(_FakeWriteClient):
        def creer_depot(self, **kwargs):
            raise ErreurNakala("Simulation échec POST /datas")

    racines = {"scans": tmp_path / "scans"}
    client = _ClientQuiFaitFlop()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        with pytest.raises(ErreurNakala):
            deposer_item(s, client, item, racines=racines, dry_run=False)
    # Cleanup orphelins effectif côté Nakala.
    assert client.supprimes == ["sha-1"]
    # `sha1_nakala` non persisté en base (rollback de fait via absence de commit).
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        fichier = next(iter(item.fichiers))
        assert fichier.sha1_nakala is None


def test_deja_depose_saute(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        item.doi_nakala = "10.34847/nkl.deja"
        s.commit()
        rapport = deposer_item(s, client, item, racines=racines, dry_run=False)
    assert rapport.deja_depose and rapport.doi == "10.34847/nkl.deja"
    assert client.depot_cree is None  # rien créé


def test_sans_fichier_local_refuse(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        item = creer_item(s, FormulaireItem(cote="AS-002", titre="T", fonds_id=f.id,
                                            date="1984", metadonnees={"createurs": ["X, Y"]}))
        # Fichier Nakala-only (pas de chemin local).
        s.add(Fichier(item_id=item.id, nom_fichier="x.jpg", ordre=1,
                      iiif_url_nakala="https://api.nakala.fr/iiif/a/b/info.json"))
        s.commit()
        with pytest.raises(DepotImpossible):
            deposer_item(s, client, item, racines=racines, dry_run=True)


def test_preflight_echoue_sans_createur_ni_date(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClient()
    with _session(db_path) as s:
        # Pas de créateur, pas de date → cascade preflight insatisfiable.
        item = _item_avec_fichier_local(s, tmp_path, createurs=(), date="")
        with pytest.raises(MetaInvalide):
            deposer_item(s, client, item, racines=racines, dry_run=True)


def test_echec_creation_nettoie_les_uploads_orphelins(
    db_path: Path, tmp_path: Path
) -> None:
    """Si POST /datas échoue après upload, les uploads sont supprimés et
    l'erreur propage (Item.doi_nakala non posé)."""
    from archives_tool.external.nakala.write_client import NakalaSoumissionInvalide

    class _ClientCreationKO(_FakeWriteClient):
        def creer_depot(self, *, metas, files, status="pending", collections_ids=None):
            raise NakalaSoumissionInvalide("422 boom")

    racines = {"scans": tmp_path / "scans"}
    client = _ClientCreationKO()
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        with pytest.raises(NakalaSoumissionInvalide):
            deposer_item(s, client, item, racines=racines, dry_run=False)
    # L'upload a eu lieu puis a été nettoyé ; le DOI n'est pas posé.
    assert client.uploads == ["as001.jpg"]
    assert client.supprimes == ["sha-1"]
    with _session(db_path) as s:
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        assert item.doi_nakala is None


# ---------------------------------------------------------------------------
# deposer_collection (B2)
# ---------------------------------------------------------------------------


class _FakeWriteClientCol(_FakeWriteClient):
    def __init__(self) -> None:
        super().__init__()
        self.collections: list[dict] = []

    def creer_collection(self, *, metas, status="private", datas=None):
        self.collections.append({"status": status, "metas": metas})
        return {"payload": {"id": "10.34847/nkl.colNEW"}}


def _collection_miroir(s, cote: str):
    from archives_tool.models import Collection, TypeCollection

    return s.scalar(
        select(Collection).where(
            Collection.cote == cote,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )


def test_deposer_collection_dry_run_ne_cree_rien(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    with _session(db_path) as s:
        _item_avec_fichier_local(s, tmp_path)
        miroir = _collection_miroir(s, "AS")
        rapport = deposer_collection(s, client, miroir, racines=racines, dry_run=True)
    assert rapport.dry_run and not rapport.collection_creee
    assert len(rapport.deposes) == 1
    assert client.collections == [] and client.depot_cree is None  # rien envoyé
    with _session(db_path) as s:
        assert _collection_miroir(s, "AS").doi_nakala is None


def test_deposer_collection_reel_cree_et_pose_doi(db_path: Path, tmp_path: Path) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    with _session(db_path) as s:
        _item_avec_fichier_local(s, tmp_path)
        miroir = _collection_miroir(s, "AS")
        rapport = deposer_collection(s, client, miroir, racines=racines, dry_run=False,
                                     cree_par="T")
    assert rapport.collection_creee and rapport.collection_doi == "10.34847/nkl.colNEW"
    assert len(rapport.deposes) == 1
    with _session(db_path) as s:
        assert _collection_miroir(s, "AS").doi_nakala == "10.34847/nkl.colNEW"
        # P3+a : la propagation via `deposer_collection → deposer_item`
        # doit aussi capturer `sha1_nakala` sur les fichiers. Garantit
        # qu'un dépôt par collection reste couvert (pas seulement par
        # le test direct `test_reel_upload_et_cree_depot`).
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        fichier = next(iter(item.fichiers))
        assert fichier.sha1_nakala == "sha-1"


def _NKL_T(v: str, lang: str | None = None) -> dict:
    m: dict = {"propertyUri": f"{_NKL}title", "value": v}
    if lang:
        m["lang"] = lang
    return m


class _FakeRWClient:
    """Client combiné lecture+écriture pour les tests de push."""

    def __init__(self, metas_distantes: list[dict], mod_date: str = "2024-01-01",
                 metas_collection: list[dict] | None = None,
                 status: str = "pending") -> None:
        self._metas = metas_distantes
        self._mod = mod_date
        self._metas_col = metas_collection if metas_collection is not None else []
        self._status = status
        self.put: dict | None = None
        self.put_collection: dict | None = None

    def lire_depot(self, doi: str) -> dict:
        return {"identifier": doi, "metas": self._metas, "modDate": self._mod,
                "files": [], "status": self._status}

    def modifier_depot(self, identifiant, *, metas, status=None):
        self.put = {"metas": metas, "status": status}
        # après PUT, le distant reflète les nouvelles metas (re-pull).
        self._metas = metas
        self._mod = "2024-06-01"
        return {}

    def lire_collection(self, doi: str) -> dict:
        return {"identifier": doi, "metas": list(self._metas_col), "status": "private"}

    def modifier_collection(self, identifiant, *, metas, status=None):
        self.put_collection = {"metas": metas, "status": status}
        self._metas_col = metas
        return {}


def _item_depose(s, tmp_path: Path, *, titre="Titre local", doi="10.34847/nkl.x1") -> Item:
    item = _item_avec_fichier_local(s, tmp_path)
    item.titre = titre
    item.doi_nakala = doi
    s.commit()
    return item


def test_diff_push_idempotent_vide() -> None:
    from archives_tool.api.services.nakala_depot import diff_push

    metas = [_NKL_T("T"), {"propertyUri": f"{_DCT}subject", "value": "S"}]
    assert diff_push(metas, list(reversed(metas))) == []  # ordre-insensible


def test_diff_push_createur_enrichi_par_nakala_ignore() -> None:
    """Nakala enrichit les créateurs (authorId/fullName/orcid:null) au
    stockage — le diff ne doit pas voir de faux changement."""
    from archives_tool.api.services.nakala_depot import diff_push

    distant = [{"propertyUri": f"{_NKL}creator", "value": {
        "authorId": "abc-123", "fullName": "Test, ColleC",
        "givenname": "ColleC", "orcid": None, "surname": "Test"}}]
    local = [{"propertyUri": f"{_NKL}creator",
              "value": {"givenname": "ColleC", "surname": "Test"}}]
    assert diff_push(distant, local) == []


def test_diff_push_createur_orcid_url_vs_nu_idempotent() -> None:
    """Nakala normalise l'ORCID en URL (`https://orcid.org/X`) au stockage ;
    ColleC l'émet nu (`X`). Sans normalisation, un créateur avec ORCID donne
    un faux diff à chaque push. Vérifié live (apitest 2026-06-15)."""
    from archives_tool.api.services.nakala_depot import diff_push

    distant = [{"propertyUri": f"{_NKL}creator", "value": {
        "authorId": "df8edbe2", "fullName": "Julio Cortázar",
        "givenname": "Julio", "surname": "Cortázar",
        "orcid": "https://orcid.org/0000-0001-2345-6789"}}]
    local = [{"propertyUri": f"{_NKL}creator", "value": {
        "givenname": "Julio", "surname": "Cortázar",
        "orcid": "0000-0001-2345-6789"}}]
    assert diff_push(distant, local) == []


def test_diff_push_detecte_modif_titre() -> None:
    from archives_tool.api.services.nakala_depot import diff_push

    diffs = diff_push([_NKL_T("Ancien")], [_NKL_T("Nouveau")])
    assert len(diffs) == 1
    assert diffs[0].property_uri == f"{_NKL}title"
    assert diffs[0].avant == ["Ancien"] and diffs[0].apres == ["Nouveau"]


def test_pousser_item_sans_doi_refuse(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import pousser_item

    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)  # pas de doi_nakala
        client = _FakeRWClient([])
        with pytest.raises(DepotImpossible):
            pousser_item(s, client, client, item, dry_run=True)


def test_pousser_item_dry_run_montre_diff_sans_ecrire(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        # Distant a un titre différent → diff attendu.
        client = _FakeRWClient([_NKL_T("Titre distant", lang="spa")])
        rapport = pousser_item(s, client, client, item, dry_run=True)
    assert rapport.a_des_changements
    assert client.put is None  # rien écrit


def test_pousser_item_reel_applique_put(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        client = _FakeRWClient([_NKL_T("Titre distant", lang="spa")])
        rapport = pousser_item(s, client, client, item, dry_run=False)
    assert rapport.applique
    assert client.put is not None
    # le PUT envoie les metas locales (titre local).
    titres = [m["value"] for m in client.put["metas"] if m["propertyUri"] == f"{_NKL}title"]
    assert "Titre local" in titres


def test_pousser_item_sans_diff_n_ecrit_pas(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import _metas_locales, pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        # Distant = exactement les metas locales → diff vide → pas de PUT.
        client = _FakeRWClient(_metas_locales(item))
        rapport = pousser_item(s, client, client, item, dry_run=False)
    assert not rapport.a_des_changements and not rapport.applique


# ---------------------------------------------------------------------------
# Passe 22 — Dette T-cousine bouclee : check published sur pousser_item
# (symetrie avec pousser_fichiers_item passe 9 Trou T)
# ---------------------------------------------------------------------------


def test_pousser_item_published_refuse_par_defaut(
    db_path: Path, tmp_path: Path,
) -> None:
    """Trou T-cousine — item publie cote Nakala + diff metas → refus
    `DepotPublie`. Symetrie avec pousser_fichiers_item."""
    from archives_tool.api.services.nakala_depot import DepotPublie, pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        # Distant publie + titre different → diff non vide → refus
        client = _FakeRWClient(
            [_NKL_T("Titre distant", lang="spa")],
            status="published",
        )
        with pytest.raises(DepotPublie) as exc_info:
            pousser_item(s, client, client, item, dry_run=False)
    # L'exception expose le contexte
    assert exc_info.value.statut == "published"
    assert exc_info.value.cote == "AS-001"
    assert "citation" in str(exc_info.value).lower()
    # Aucun PUT envoye
    assert client.put is None


def test_pousser_item_published_avec_forcer_publie_passe(
    db_path: Path, tmp_path: Path,
) -> None:
    """Avec `forcer_publie=True`, le push procede normalement."""
    from archives_tool.api.services.nakala_depot import pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        client = _FakeRWClient(
            [_NKL_T("Titre distant", lang="spa")],
            status="published",
        )
        rapport = pousser_item(
            s, client, client, item, dry_run=False, forcer_publie=True,
        )
    assert rapport.applique is True
    assert client.put is not None


def test_pousser_item_published_aucun_changement_ne_leve_pas(
    db_path: Path, tmp_path: Path,
) -> None:
    """Item publie SANS diff metas → no-op idempotent, PAS de
    DepotPublie. Le garde-fou est court-circuite par
    `aucun_changement` (cohérent avec pousser-fichiers passe 14
    Trou Z).

    Sans cette protection, un script qui pousse 2x consecutifs sur
    un item publie sans modification reveillerait inutilement le
    garde-fou.
    """
    from archives_tool.api.services.nakala_depot import _metas_locales, pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        # Distant = metas locales exactes → diff vide
        client = _FakeRWClient(_metas_locales(item), status="published")
        rapport = pousser_item(s, client, client, item, dry_run=False)
    # Pas d'exception. Pas de PUT.
    assert not rapport.a_des_changements
    assert not rapport.applique
    assert client.put is None


def test_pousser_item_pending_n_active_pas_le_garde_fou(
    db_path: Path, tmp_path: Path,
) -> None:
    """Symetrie negative : status=pending ne declenche pas le
    garde-fou (comportement existant prejudice 22)."""
    from archives_tool.api.services.nakala_depot import pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        client = _FakeRWClient(
            [_NKL_T("Titre distant", lang="spa")],
            status="pending",
        )
        rapport = pousser_item(s, client, client, item, dry_run=False)
    assert rapport.applique is True


def test_pousser_collection_propage_forcer_publie(
    db_path: Path, tmp_path: Path,
) -> None:
    """`pousser_collection` propage `forcer_publie` à `pousser_item`
    dans la boucle. Sans flag, items publies → erreur collectee
    (n'arrete pas le lot)."""
    from archives_tool.api.services.nakala_depot import pousser_collection
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.api.services.collections import (
        FormulaireCollection, creer_collection_libre,
    )

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        f = lire_fonds_par_cote(s, "AS")
        col = creer_collection_libre(s, FormulaireCollection(
            cote="AS-PUB", titre="C", fonds_id=f.id,
        ))
        col.items.append(item)
        s.commit()

        client = _FakeRWClient(
            [_NKL_T("Titre distant", lang="spa")],
            status="published",
        )
        # Sans flag : item publie collecte en erreur (n'arrete pas la
        # boucle)
        rapport = pousser_collection(
            s, client, client, col, dry_run=False, forcer_publie=False,
        )
    assert len(rapport.erreurs) == 1
    assert "AS-001" in rapport.erreurs[0][0]
    assert "publié" in rapport.erreurs[0][1] or "published" in rapport.erreurs[0][1]


def test_depot_publie_re_export_depuis_nakala_fichiers(
    db_path: Path, tmp_path: Path,
) -> None:
    """Compat retro : `DepotPublie` reste importable depuis
    nakala_fichiers (re-export). Garde-fou anti-régression sur la
    relocation passe 22."""
    from archives_tool.api.services.nakala_fichiers import (
        DepotPublie as DP_fichiers,
    )
    from archives_tool.api.services.nakala_depot import (
        DepotPublie as DP_depot,
    )
    # Meme classe (re-export)
    assert DP_fichiers is DP_depot


def test_publier_item_reel(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import publier_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path)
        client = _FakeRWClient([])
        rapport = publier_item(s, client, client, item, dry_run=False)
    assert rapport.applique
    assert client.put is not None and client.put["status"] == "published"


def test_publier_collection(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import publier_collection

    with _session(db_path) as s:
        _item_depose(s, tmp_path)  # AS-001 lié (doi)
        f = lire_fonds_par_cote(s, "AS")
        creer_item(s, FormulaireItem(cote="AS-002", titre="T2", fonds_id=f.id,
                                     date="1985", metadonnees={"createurs": ["X, Y"]}))
        s.commit()
        miroir = _collection_miroir(s, "AS")
        client = _FakeRWClient([])
        rapport = publier_collection(s, client, client, miroir, dry_run=False)
    assert rapport.publies == ["AS-001"]
    assert rapport.non_lies == ["AS-002"]  # pas de doi → non publié
    assert client.put is not None and client.put["status"] == "published"


def _NKL_TITLE(v: str) -> dict:
    return {"propertyUri": f"{_NKL}title", "value": v}


def test_pousser_metadonnees_collection_sans_doi_refuse(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import pousser_metadonnees_collection

    with _session(db_path) as s:
        _item_avec_fichier_local(s, tmp_path)  # crée fonds AS + miroir (sans doi)
        miroir = _collection_miroir(s, "AS")
        client = _FakeRWClient([])
        with pytest.raises(DepotImpossible):
            pousser_metadonnees_collection(s, client, client, miroir, dry_run=True)


def test_pousser_metadonnees_collection_diff_put_et_preservation(
    db_path: Path, tmp_path: Path
) -> None:
    from archives_tool.api.services.nakala_depot import pousser_metadonnees_collection

    with _session(db_path) as s:
        _item_avec_fichier_local(s, tmp_path)
        miroir = _collection_miroir(s, "AS")  # titre "Armonía Somers"
        miroir.doi_nakala = "10.34847/nkl.col1"
        s.commit()
        # Distant : titre différent (à remplacer) + un sujet (non géré → à préserver).
        client = _FakeRWClient([], metas_collection=[
            _NKL_TITLE("Ancien titre"),
            {"propertyUri": f"{_DCT}subject", "value": "Préservé"},
        ])
        rapport = pousser_metadonnees_collection(s, client, client, miroir, dry_run=False)
    assert rapport.applique and rapport.a_des_changements
    assert client.put_collection is not None
    metas = client.put_collection["metas"]
    titres = [m["value"] for m in metas if m["propertyUri"] == f"{_NKL}title"]
    sujets = [m["value"] for m in metas if m["propertyUri"] == f"{_DCT}subject"]
    assert "Armonía Somers" in titres  # titre remplacé par celui de ColleC
    assert "Préservé" in sujets  # sujet non géré → préservé (fusion, pas remplacement)


def test_pousser_collection_inclut_entite(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import pousser_collection

    with _session(db_path) as s:
        _item_depose(s, tmp_path, titre="Titre local")  # AS-001 lié
        miroir = _collection_miroir(s, "AS")
        miroir.doi_nakala = "10.34847/nkl.col1"
        s.commit()
        # Distant : collection titre différent + item titre différent.
        client = _FakeRWClient([_NKL_T("Distant item")],
                               metas_collection=[_NKL_TITLE("Distant col")])
        rapport = pousser_collection(s, client, client, miroir, dry_run=True)
    # L'entité collection a un diff + l'item aussi.
    assert rapport.meta_collection is not None and rapport.meta_collection.a_des_changements
    assert len(rapport.pousses) == 1


def _seed_cache(s, doi: str, mod_date: str) -> None:
    """Amorce une RessourceExterne cachée (baseline de fraîcheur) pour un DOI."""
    from archives_tool.models import RessourceExterne, SourceExterne

    src = SourceExterne(code="nakala", libelle="Nakala", type_api="nakala",
                        url_base="https://api.nakala.fr")
    s.add(src)
    s.flush()
    s.add(RessourceExterne(source_id=src.id, identifiant_externe=doi,
                           metadonnees_brutes={"modDate": mod_date}))
    s.commit()


def test_pousser_item_signale_derive(db_path: Path, tmp_path: Path) -> None:
    """Distant plus récent que la baseline cachée → dérive signalée."""
    from archives_tool.api.services.nakala_depot import pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")
        _seed_cache(s, item.doi_nakala, "2024-01-01")  # dernier fetch ancien
        client = _FakeRWClient([_NKL_T("Titre distant")], mod_date="2024-06-01")
        rapport = pousser_item(s, client, client, item, dry_run=True)
    assert rapport.derive is True


def test_pousser_item_sans_cache_pas_de_derive(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import pousser_item

    with _session(db_path) as s:
        item = _item_depose(s, tmp_path, titre="Titre local")  # pas de cache
        client = _FakeRWClient([_NKL_T("Titre distant")], mod_date="2024-06-01")
        rapport = pousser_item(s, client, client, item, dry_run=True)
    assert rapport.derive is False


def test_pousser_collection_mixte(db_path: Path, tmp_path: Path) -> None:
    from archives_tool.api.services.nakala_depot import pousser_collection

    with _session(db_path) as s:
        _item_depose(s, tmp_path, titre="Titre local")  # AS-001 lié (a un doi)
        f = lire_fonds_par_cote(s, "AS")
        creer_item(s, FormulaireItem(cote="AS-002", titre="T2", fonds_id=f.id,
                                     date="1985", metadonnees={"createurs": ["X, Y"]}))
        s.commit()
        miroir = _collection_miroir(s, "AS")
        client = _FakeRWClient([_NKL_T("Titre distant")])  # AS-001 → diff
        rapport = pousser_collection(s, client, client, miroir, dry_run=True)
    assert len(rapport.pousses) == 1  # AS-001 (a un diff)
    assert rapport.non_lies == ["AS-002"]  # pas de doi_nakala
    assert rapport.erreurs == []


def test_pousser_collection_erreur_metas_collectee(db_path: Path, tmp_path: Path) -> None:
    """Un item lié dont les métadonnées sont insuffisantes (preflight) →
    collecté dans erreurs, n'arrête pas le lot."""
    from archives_tool.api.services.nakala_depot import pousser_collection

    with _session(db_path) as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS"))
        # Item lié (doi) mais sans créateur ni date → preflight lèvera.
        item = creer_item(s, FormulaireItem(cote="AS-009", titre="Casse", fonds_id=f.id))
        item.doi_nakala = "10.34847/nkl.casse"
        s.commit()
        miroir = _collection_miroir(s, "AS")
        client = _FakeRWClient([_NKL_T("Distant")])
        rapport = pousser_collection(s, client, client, miroir, dry_run=True)
    assert rapport.pousses == [] and rapport.inchanges == []
    assert len(rapport.erreurs) == 1 and rapport.erreurs[0][0] == "AS-009"


def test_deposer_collection_item_sans_fichier_local_collecte(
    db_path: Path, tmp_path: Path
) -> None:
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    with _session(db_path) as s:
        # 1 item avec fichier local + 1 item Nakala-only (non déposable).
        _item_avec_fichier_local(s, tmp_path)
        f = lire_fonds_par_cote(s, "AS")
        item2 = creer_item(s, FormulaireItem(cote="AS-002", titre="T2", fonds_id=f.id,
                                             date="1985", metadonnees={"createurs": ["X, Y"]}))
        s.add(Fichier(item_id=item2.id, nom_fichier="y.jpg", ordre=1,
                      iiif_url_nakala="https://api.nakala.fr/iiif/a/b/info.json"))
        s.commit()
        miroir = _collection_miroir(s, "AS")
        rapport = deposer_collection(s, client, miroir, racines=racines, dry_run=False)
    assert len(rapport.deposes) == 1
    assert rapport.non_deposables == ["AS-002"]
    assert rapport.erreurs == []


# ---------------------------------------------------------------------------
# D1 (backlog dépôt UI) — hook de progression `progress=callback`
# ---------------------------------------------------------------------------


def test_deposer_collection_progress_callback_appele_par_item(
    db_path: Path, tmp_path: Path
) -> None:
    """Le callback est invoqué une fois par item, dans l'ordre, avec
    `(cote, index_1based, total)`. Le total est fixe et reflete le nombre
    d'items de la collection (3 ici)."""
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    appels: list[tuple[str, int, int]] = []

    with _session(db_path) as s:
        # 3 items dont 1 deposable, 1 non-deposable (Nakala-only), 1
        # deja deposable mais sans createur → erreur de mapping.
        _item_avec_fichier_local(s, tmp_path)
        f = lire_fonds_par_cote(s, "AS")
        # Item 2 : Nakala-only, sera classe non_deposables
        item2 = creer_item(s, FormulaireItem(
            cote="AS-002", titre="T2", fonds_id=f.id, date="1985",
            metadonnees={"createurs": ["X, Y"]},
        ))
        s.add(Fichier(
            item_id=item2.id, nom_fichier="y.jpg", ordre=1,
            iiif_url_nakala="https://api.nakala.fr/iiif/a/b/info.json",
        ))
        # Item 3 : avec fichier local mais SANS createur ET sans editeur
        # → MetaInvalide (preflight echoue), classe `erreurs`.
        item3 = creer_item(s, FormulaireItem(
            cote="AS-003", titre="T3", fonds_id=f.id, date="1986",
        ))
        (tmp_path / "scans" / "as003.jpg").write_bytes(b"\xff\xd8\xff img3")
        s.add(Fichier(
            item_id=item3.id, nom_fichier="as003.jpg", racine="scans",
            chemin_relatif="as003.jpg", ordre=1,
        ))
        s.commit()
        miroir = _collection_miroir(s, "AS")
        rapport = deposer_collection(
            s, client, miroir, racines=racines, dry_run=True,
            progress=lambda cote, idx, total: appels.append((cote, idx, total)),
        )

    # Le callback a fire exactement 3 fois (1 par item).
    # On asserte le CONTRAT (indexes 1..N, total constant, toutes les
    # cotes traitees une fois) plutot que l'ordre exact des cotes :
    # `Collection.items` n'a pas de `order_by` explicite, donc l'ordre
    # depend de la convention SQLite (insertion order par defaut, non
    # garantie). Si quelqu'un ajoute `order_by` au modele un jour, ce
    # test ne casse pas pour une mauvaise raison.
    assert len(appels) == 3
    indexes = [a[1] for a in appels]
    assert indexes == [1, 2, 3]
    assert all(a[2] == 3 for a in appels)
    assert {a[0] for a in appels} == {"AS-001", "AS-002", "AS-003"}
    # Le rapport en dry-run montre les 3 categories (deposable plan,
    # non_deposable, erreur preflight).
    assert len(rapport.deposes) == 1  # AS-001 (plan dry-run)
    assert rapport.non_deposables == ["AS-002"]
    # AS-003 : preflight catch via MetaInvalide → erreurs
    assert any(cote == "AS-003" for cote, _ in rapport.erreurs)


def test_deposer_collection_progress_2e_run_tout_saute(
    db_path: Path, tmp_path: Path
) -> None:
    """Reprise idempotente : si tous les items ont deja un `doi_nakala`
    et la collection aussi, le 2e run ne refait aucun appel client, mais
    le callback fire quand meme par item (UI a besoin de signaler
    `cote_courante = "AS-001"` puis sauter). Tous les items remontent
    dans `sautes`."""
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    with _session(db_path) as s:
        _item_avec_fichier_local(s, tmp_path)
        # Pre-pose tous les DOI : simule un 2e run apres interruption.
        miroir = _collection_miroir(s, "AS")
        miroir.doi_nakala = "10.34847/nkl.colDEJA"
        item = s.scalar(select(Item).where(Item.cote == "AS-001"))
        item.doi_nakala = "10.34847/nkl.itemDEJA"
        s.commit()
        appels: list[tuple[str, int, int]] = []
        rapport = deposer_collection(
            s, client, miroir, racines=racines, dry_run=False,
            progress=lambda c, i, t: appels.append((c, i, t)),
        )

    # 2e run : aucune ecriture client
    assert client.collections == []
    assert client.depot_cree is None
    # La collection n'est pas re-creee (DOI deja pose)
    assert rapport.collection_creee is False
    assert rapport.collection_doi == "10.34847/nkl.colDEJA"
    # L'item est saute
    assert rapport.sautes == ["AS-001"]
    assert rapport.deposes == []
    # Le callback a quand meme fire pour signaler la progression
    assert appels == [("AS-001", 1, 1)]


def test_deposer_collection_progress_default_none_pas_de_callback(
    db_path: Path, tmp_path: Path
) -> None:
    """Sans `progress` (defaut), le service marche comme avant — preuve
    que l'ajout de D1 est strictement additif (les callers actuels ne
    voient aucun changement)."""
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    with _session(db_path) as s:
        _item_avec_fichier_local(s, tmp_path)
        miroir = _collection_miroir(s, "AS")
        rapport = deposer_collection(s, client, miroir, racines=racines, dry_run=True)
    # Comportement identique a test_deposer_collection_dry_run_ne_cree_rien
    assert rapport.dry_run and not rapport.collection_creee
    assert len(rapport.deposes) == 1


def test_deposer_collection_progress_collection_vide(
    db_path: Path, tmp_path: Path
) -> None:
    """Collection sans aucun item : le callback n'est jamais appele,
    pas de division par zero ni d'edge case. Le rapport reste valide
    avec toutes les listes vides."""
    racines = {"scans": tmp_path / "scans"}
    client = _FakeWriteClientCol()
    from archives_tool.api.services.nakala_depot import deposer_collection

    appels: list = []
    with _session(db_path) as s:
        # Cree juste le fonds + miroir, sans items.
        creer_fonds(s, FormulaireFonds(cote="VIDE", titre="Vide"))
        miroir = _collection_miroir(s, "VIDE")
        rapport = deposer_collection(
            s, client, miroir, racines=racines, dry_run=False,
            progress=lambda c, i, t: appels.append((c, i, t)),
        )
    # Aucun appel progress + collection cree (1er run, dry_run=False)
    assert appels == []
    assert rapport.collection_creee is True
    assert rapport.deposes == [] and rapport.sautes == []
    assert rapport.non_deposables == [] and rapport.erreurs == []


# ---------------------------------------------------------------------------
# Passe 21 — Dette logging transverse sur nakala_depot.py
# Pattern aligne sur passe 8 (`nakala_fichiers`). Garde-fous minimaux :
# les events critiques sont bien emis pour debug post-mortem.
# ---------------------------------------------------------------------------


class _FakeReadClient:
    """Stub client lecture pour les tests pousser/publier.

    Retourne un depot minimal avec les metas locales d'AS-001 deja
    presentes pour produire un diff vide par defaut. Les tests qui
    modifient l'item le declenchent en changeant titre / autre champ.
    """

    def lire_depot(self, doi):
        return {
            "identifier": doi,
            "modDate": "2026-01-01T00:00:00",
            "status": "pending",
            "metas": [],  # vide → tout local apparait en "ajout"
            "files": [],
        }


class _FakeWriteClientP3(_FakeWriteClient):
    """Etend `_FakeWriteClient` avec `modifier_depot` (PUT) - utilise
    pour les tests pousser_item / publier_item passe 21."""

    def __init__(self) -> None:
        super().__init__()
        self.puts: list[dict] = []

    def modifier_depot(self, identifiant, *, metas=None, files=None, status=None):
        self.puts.append({"id": identifiant, "metas": metas, "files": files,
                          "status": status})
        return {}


def test_deposer_item_logging_dry_run(
    db_path: Path, tmp_path: Path, caplog,
) -> None:
    """Dry-run emet INFO 'depot item dry-run' avec compteurs."""
    import logging as _logging
    caplog.set_level(_logging.INFO, logger="archives_tool.api.services.nakala_depot")

    racines = {"scans": tmp_path / "scans"}
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        deposer_item(s, _FakeWriteClient(), item, racines=racines, dry_run=True)

    messages = [r.message for r in caplog.records
                if r.name == "archives_tool.api.services.nakala_depot"]
    assert any("depot item dry-run" in m for m in messages)
    assert any("AS-001" in m for m in messages)


def test_deposer_item_logging_commit_reel(
    db_path: Path, tmp_path: Path, caplog,
) -> None:
    """Reel : emet START + COMMIT (au moins)."""
    import logging as _logging
    caplog.set_level(_logging.INFO, logger="archives_tool.api.services.nakala_depot")

    racines = {"scans": tmp_path / "scans"}
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        deposer_item(s, _FakeWriteClient(), item, racines=racines, dry_run=False)

    messages = [r.message for r in caplog.records
                if r.name == "archives_tool.api.services.nakala_depot"]
    assert any("depot item START" in m for m in messages)
    assert any("depot item COMMIT" in m for m in messages)


def test_deposer_item_logging_echec_cleanup(
    db_path: Path, tmp_path: Path, caplog,
) -> None:
    """Echec du POST /datas : warning explicite avec cleanup compteur."""
    import logging as _logging
    caplog.set_level(_logging.WARNING, logger="archives_tool.api.services.nakala_depot")

    from archives_tool.api.services.nakala_depot import ErreurNakala

    class _ClientFlop(_FakeWriteClient):
        def creer_depot(self, **kwargs):
            raise ErreurNakala("simule")

    racines = {"scans": tmp_path / "scans"}
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        with pytest.raises(ErreurNakala):
            deposer_item(s, _ClientFlop(), item, racines=racines, dry_run=False)

    messages = [r.message for r in caplog.records
                if r.name == "archives_tool.api.services.nakala_depot"]
    assert any("depot item ECHEC" in m and "cleanup=1" in m for m in messages)


def test_publier_item_logging_warning_irreversible(
    db_path: Path, tmp_path: Path, caplog,
) -> None:
    """`publier_item` reel emet un WARNING explicite IRREVERSIBLE -
    differencie d'un INFO normal car appel paiyant et non-annulable.
    """
    import logging as _logging
    caplog.set_level(_logging.INFO, logger="archives_tool.api.services.nakala_depot")

    from archives_tool.api.services.nakala_depot import publier_item

    racines = {"scans": tmp_path / "scans"}
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        # Depose d'abord pour avoir doi_nakala
        deposer_item(s, _FakeWriteClient(), item, racines=racines, dry_run=False)
        caplog.clear()

        # Maintenant publie
        publier_item(
            s, _FakeReadClient(), _FakeWriteClientP3(), item, dry_run=False,
        )

    records = [r for r in caplog.records
               if r.name == "archives_tool.api.services.nakala_depot"]
    # WARNING IRREVERSIBLE emis
    warnings_irr = [r for r in records if r.levelno == _logging.WARNING
                    and "IRREVERSIBLE" in r.message]
    assert len(warnings_irr) >= 1
    # INFO publication OK emis aussi
    assert any("publication item OK" in r.message for r in records)


def test_deposer_collection_logging_start_end(
    db_path: Path, tmp_path: Path, caplog,
) -> None:
    """`deposer_collection` emet START au debut et END a la fin avec
    compteurs des 4 categories de resultat."""
    import logging as _logging
    caplog.set_level(_logging.INFO, logger="archives_tool.api.services.nakala_depot")

    from archives_tool.api.services.nakala_depot import deposer_collection

    racines = {"scans": tmp_path / "scans"}
    with _session(db_path) as s:
        # Setup : collection libre + item avec fichier local
        item = _item_avec_fichier_local(s, tmp_path)
        from archives_tool.api.services.collections import (
            FormulaireCollection, creer_collection_libre,
        )
        col = creer_collection_libre(s, FormulaireCollection(
            cote="AS-COLLE", titre="C", fonds_id=item.fonds_id,
        ))
        col.items.append(item)
        s.commit()

        deposer_collection(s, _FakeWriteClient(), col, racines=racines,
                          dry_run=True)

    messages = [r.message for r in caplog.records
                if r.name == "archives_tool.api.services.nakala_depot"]
    assert any("depot collection START" in m for m in messages)
    assert any("depot collection END" in m for m in messages)


def test_pousser_item_logging_dry_run_vs_commit(
    db_path: Path, tmp_path: Path, caplog,
) -> None:
    """`pousser_item` emet dry-run ou no-op selon scenario, COMMIT en
    cas de push reel."""
    import logging as _logging
    caplog.set_level(_logging.INFO, logger="archives_tool.api.services.nakala_depot")

    from archives_tool.api.services.nakala_depot import pousser_item

    racines = {"scans": tmp_path / "scans"}
    with _session(db_path) as s:
        item = _item_avec_fichier_local(s, tmp_path)
        deposer_item(s, _FakeWriteClient(), item, racines=racines, dry_run=False)
        caplog.clear()

        # Modifier titre pour forcer un diff
        item.titre = "Nouveau titre"
        s.commit()

        pousser_item(
            s, _FakeReadClient(), _FakeWriteClientP3(), item, dry_run=False,
        )

    messages = [r.message for r in caplog.records
                if r.name == "archives_tool.api.services.nakala_depot"]
    assert any("push item metas START" in m for m in messages)
    assert any("push item metas COMMIT" in m for m in messages)

