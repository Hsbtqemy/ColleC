"""Tests du mapper Nakala → DepotNakala (P1a). Fixture JSON, pas de réseau."""

from __future__ import annotations

from archives_tool.external.nakala.mapper import (
    langue_vers_iso639_3,
    mapper_depot,
    normaliser_orcid,
)

_NKL = "http://nakala.fr/terms#"
_DCT = "http://purl.org/dc/terms/"

# Dépôt réaliste : titres multilingues, créateurs (dict structuré + str +
# anonyme), sujets multiples, langue ISO 639-1, un dcterms libre, 2 fichiers
# dont un sous embargo futur.
_DEPOT = {
    "identifier": "10.34847/nkl.abcdef12",
    "status": "published",
    "metas": [
        {"propertyUri": f"{_NKL}title", "value": "Titre anglais", "lang": "en"},
        {"propertyUri": f"{_NKL}title", "value": "Titre français", "lang": "fr"},
        {"propertyUri": f"{_NKL}type",
         "value": "http://purl.org/coar/resource_type/c_2fe3"},
        {"propertyUri": f"{_NKL}created", "value": "1969-09"},
        {"propertyUri": f"{_NKL}license", "value": "CC-BY-4.0"},
        {"propertyUri": f"{_NKL}creator",
         "value": {"surname": "Topor", "givenname": "Roland", "orcid": "0000-0002"}},
        {"propertyUri": f"{_NKL}creator", "value": "Reiser"},
        {"propertyUri": f"{_NKL}creator", "value": None},  # anonyme → ignoré
        {"propertyUri": f"{_DCT}description", "value": "Une description.", "lang": "fr"},
        {"propertyUri": f"{_DCT}subject", "value": "satire", "lang": "fr"},
        {"propertyUri": f"{_DCT}subject", "value": "presse", "lang": "fr"},
        {"propertyUri": f"{_DCT}language", "value": "fr"},
        {"propertyUri": f"{_DCT}publisher", "value": "Éditions du Square"},
        {"propertyUri": f"{_DCT}temporal", "value": "1960/1985"},
    ],
    "files": [
        # Clé `mime_type` = celle réellement exposée par l'API Nakala.
        {"name": "p001.jpg", "sha1": "aaa", "size": 1024, "mime_type": "image/jpeg"},
        {"name": "secret.pdf", "sha1": "bbb", "size": 2048, "mime_type": "application/pdf",
         "embargoed": "2999-01-01"},
    ],
}


def test_mapper_champs_dedies() -> None:
    d = mapper_depot(_DEPOT)
    assert d.identifiant == "10.34847/nkl.abcdef12"
    assert d.statut == "published"
    assert d.titre == "Titre français"  # fr préféré
    assert d.type_coar == "http://purl.org/coar/resource_type/c_2fe3"
    assert d.date == "1969-09"
    assert d.licence == "CC-BY-4.0"
    assert d.description == "Une description."


def test_mapper_createurs_dict_str_et_anonyme() -> None:
    d = mapper_depot(_DEPOT)
    # dict structuré rendu "Nom, Prénom [ORCID]" ; str gardé ; None ignoré.
    assert d.createurs == ["Topor, Roland [0000-0002]", "Reiser"]


def test_normaliser_orcid_url_vers_nu() -> None:
    """Nakala stocke l'ORCID en URL ; on le ramène à la forme nue (cohérence
    dépôt↔lecture, vérifié au round-trip end-to-end 2026-06-15)."""
    assert normaliser_orcid("https://orcid.org/0000-0001-2345-6789") == "0000-0001-2345-6789"
    assert normaliser_orcid("http://orcid.org/0000-0001-2345-6789") == "0000-0001-2345-6789"
    assert normaliser_orcid("0000-0001-2345-6789") == "0000-0001-2345-6789"  # déjà nu
    assert normaliser_orcid(None) is None and normaliser_orcid("") is None


def test_mapper_createur_orcid_url_rendu_nu() -> None:
    """Un créateur dont l'ORCID est en URL (forme de stockage Nakala) est
    rendu avec l'ORCID nu — cohérent avec la forme déposée par ColleC."""
    depot = mapper_depot({"identifier": "10.34847/nkl.x", "metas": [
        {"propertyUri": f"{_NKL}creator", "value": {
            "surname": "Cortázar", "givenname": "Julio",
            "orcid": "https://orcid.org/0000-0001-2345-6789"}}]})
    assert depot.createurs == ["Cortázar, Julio [0000-0001-2345-6789]"]


def test_mapper_sujets_et_langue_iso3() -> None:
    d = mapper_depot(_DEPOT)
    assert d.sujets == ["satire", "presse"]
    assert d.langues == ["fra"]  # fr (639-1) → fra (639-3)


def test_mapper_metadonnees_catch_all() -> None:
    d = mapper_depot(_DEPOT)
    # Les metas hors champs dédiés sont versées par slug.
    assert d.metadonnees["dcterms_publisher"] == "Éditions du Square"
    assert d.metadonnees["dcterms_temporal"] == "1960/1985"
    # Les champs dédiés ne sont PAS dupliqués dans metadonnees.
    assert "dcterms_description" not in d.metadonnees
    assert "nkl_title" not in d.metadonnees


def test_mapper_fichiers_et_embargo() -> None:
    d = mapper_depot(_DEPOT)
    assert len(d.fichiers) == 2
    p1, p2 = d.fichiers
    assert (p1.nom, p1.sha1, p1.taille, p1.mime) == ("p001.jpg", "aaa", 1024, "image/jpeg")
    assert p1.embargo_actif is False
    assert p2.embargo_actif is True  # embargo 2999 → actif


def test_mapper_fichier_description_par_fichier() -> None:
    """S7 : la `description` par fichier (transcription) est captée dans
    `FichierNakala.description` ; absente → None."""
    d = mapper_depot({"identifier": "10.34847/nkl.x", "files": [
        {"name": "p1.jpg", "sha1": "aaa", "description": "Recto, page de titre."},
        {"name": "p2.jpg", "sha1": "bbb"},  # pas de description
    ]})
    assert d.fichiers[0].description == "Recto, page de titre."
    assert d.fichiers[1].description is None


def test_mapper_depot_minimal_ne_plante_pas() -> None:
    d = mapper_depot({"identifier": "10.34847/nkl.vide"})
    assert d.identifiant == "10.34847/nkl.vide"
    assert d.titre is None
    assert d.createurs == []
    assert d.langues == []
    assert d.fichiers == []
    assert d.metadonnees == {}
    assert d.collections_ids == []


def test_mapper_collections_ids() -> None:
    """S3 : `collectionsIds` est capté dans `DepotNakala.collections_ids`
    (DOIs des collections Nakala d'appartenance). Absent → liste vide ;
    valeurs nulles filtrées."""
    d = mapper_depot({
        "identifier": "10.34847/nkl.x",
        "collectionsIds": ["10.34847/nkl.col1", "10.34847/nkl.col2", None, ""],
    })
    assert d.collections_ids == ["10.34847/nkl.col1", "10.34847/nkl.col2"]
    assert mapper_depot({"identifier": "10.34847/nkl.y"}).collections_ids == []


def test_langue_vers_iso639_3() -> None:
    assert langue_vers_iso639_3("fr") == "fra"
    assert langue_vers_iso639_3("fra") == "fra"  # déjà 639-3 → inchangé
    assert langue_vers_iso639_3("cmn") == "cmn"  # longue traîne 639-3
    assert langue_vers_iso639_3("fr-FR") == "fra"  # RFC5646 région ignorée
    assert langue_vers_iso639_3("en-GB") == "eng"
    assert langue_vers_iso639_3(None) is None
    assert langue_vers_iso639_3("") is None
