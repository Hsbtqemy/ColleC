"""Tests des préférences de colonnes (services + routes).

Couvre la lecture/écriture/reset, la validation par whitelist,
le calcul des champs métadonnées dynamiques, et les endpoints HTTP
(GET panneau, POST save, POST reset).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.preferences import (
    COLONNES_DEFAUT_ITEMS,
    champs_metadonnees_disponibles,
    colonnes_disponibles_items,
    lire_preferences_colonnes,
    metas_valides_pour,
    reinitialiser_preferences_colonnes,
    resoudre_colonnes_actives,
    sauvegarder_preferences_colonnes,
)
from archives_tool.demo import peupler_base
from archives_tool.models import Collection, Item, ItemCollection, TypeCollection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creer_fonds_avec_miroir(session: Session, cote: str = "TST") -> Collection:
    """Crée un fonds + sa miroir auto, retourne la miroir.

    `creer_fonds` du service métier garantit l'invariant 1 (une miroir
    unique par fonds avec `type_collection='miroir'`).
    """
    fonds = creer_fonds(session, FormulaireFonds(cote=cote, titre=cote))
    miroir = session.scalar(
        select(Collection).where(
            Collection.fonds_id == fonds.id,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )
    return miroir


def _ajouter_item(
    session: Session,
    miroir: Collection,
    cote: str,
    metadonnees: dict | None = None,
) -> Item:
    """Crée un item rattaché au fonds parent + à la miroir."""
    item = Item(
        fonds_id=miroir.fonds_id,
        cote=cote,
        titre=cote,
        metadonnees=metadonnees,
    )
    session.add(item)
    session.flush()
    session.add(ItemCollection(item_id=item.id, collection_id=miroir.id))
    session.commit()
    return item


# ---------------------------------------------------------------------------
# Services — lecture / écriture / reset
# ---------------------------------------------------------------------------


@pytest.fixture
def collection_simple(session: Session) -> Collection:
    return _creer_fonds_avec_miroir(session, "C")


def test_lire_retourne_defauts_si_rien_en_base(
    session: Session, collection_simple: Collection
) -> None:
    prefs = lire_preferences_colonnes(session, "marie", collection_simple.id)
    assert prefs.par_defaut is True
    assert prefs.colonnes_ordonnees == list(COLONNES_DEFAUT_ITEMS)


def test_sauvegarder_puis_lire_round_trip(
    session: Session, collection_simple: Collection
) -> None:
    sauvegarder_preferences_colonnes(
        session,
        "marie",
        collection_simple.id,
        "items",
        ["cote", "titre", "langue"],
    )
    prefs = lire_preferences_colonnes(session, "marie", collection_simple.id)
    assert prefs.par_defaut is False
    assert prefs.colonnes_ordonnees == ["cote", "titre", "langue"]


def test_sauvegarder_reinjecte_cote_si_absente(
    session: Session, collection_simple: Collection
) -> None:
    sauvegarder_preferences_colonnes(
        session,
        "marie",
        collection_simple.id,
        "items",
        ["titre", "etat"],
    )
    prefs = lire_preferences_colonnes(session, "marie", collection_simple.id)
    assert prefs.colonnes_ordonnees[0] == "cote"
    assert "titre" in prefs.colonnes_ordonnees and "etat" in prefs.colonnes_ordonnees


def test_sauvegarder_filtre_colonnes_inconnues(
    session: Session, collection_simple: Collection
) -> None:
    sauvegarder_preferences_colonnes(
        session,
        "marie",
        collection_simple.id,
        "items",
        ["cote", "titre", "ne_existe_pas", "etat"],
    )
    prefs = lire_preferences_colonnes(session, "marie", collection_simple.id)
    assert "ne_existe_pas" not in prefs.colonnes_ordonnees
    assert prefs.colonnes_ordonnees == ["cote", "titre", "etat"]


def test_sauvegarder_dedoublonne(
    session: Session, collection_simple: Collection
) -> None:
    sauvegarder_preferences_colonnes(
        session,
        "marie",
        collection_simple.id,
        "items",
        ["cote", "titre", "titre", "etat", "cote"],
    )
    prefs = lire_preferences_colonnes(session, "marie", collection_simple.id)
    assert prefs.colonnes_ordonnees == ["cote", "titre", "etat"]


def test_sauvegarder_garde_cote_meme_si_inputs_invalides(
    session: Session, collection_simple: Collection
) -> None:
    """Quand toutes les valeurs sont rejetées, `cote` est réinjectée
    avant le check de vide. La liste finale contient au moins `cote`.
    """
    sauvegarder_preferences_colonnes(
        session,
        "marie",
        collection_simple.id,
        "items",
        ["foo", "bar"],
    )
    prefs = lire_preferences_colonnes(session, "marie", collection_simple.id)
    assert prefs.colonnes_ordonnees == ["cote"]


def test_reinitialiser_supprime_la_ligne(
    session: Session, collection_simple: Collection
) -> None:
    sauvegarder_preferences_colonnes(
        session,
        "marie",
        collection_simple.id,
        "items",
        ["cote", "titre"],
    )
    reinitialiser_preferences_colonnes(session, "marie", collection_simple.id)
    prefs = lire_preferences_colonnes(session, "marie", collection_simple.id)
    assert prefs.par_defaut is True


def test_preferences_independantes_par_utilisateur(
    session: Session, collection_simple: Collection
) -> None:
    sauvegarder_preferences_colonnes(
        session, "marie", collection_simple.id, "items", ["cote", "langue"]
    )
    sauvegarder_preferences_colonnes(
        session, "hugo", collection_simple.id, "items", ["cote", "annee"]
    )
    assert lire_preferences_colonnes(
        session, "marie", collection_simple.id
    ).colonnes_ordonnees == ["cote", "langue"]
    assert lire_preferences_colonnes(
        session, "hugo", collection_simple.id
    ).colonnes_ordonnees == ["cote", "annee"]


def test_preferences_independantes_par_collection(session: Session) -> None:
    c1 = _creer_fonds_avec_miroir(session, "A")
    c2 = _creer_fonds_avec_miroir(session, "B")
    sauvegarder_preferences_colonnes(session, "u", c1.id, "items", ["cote", "titre"])
    sauvegarder_preferences_colonnes(session, "u", c2.id, "items", ["cote", "etat"])
    assert lire_preferences_colonnes(session, "u", c1.id).colonnes_ordonnees == [
        "cote",
        "titre",
    ]
    assert lire_preferences_colonnes(session, "u", c2.id).colonnes_ordonnees == [
        "cote",
        "etat",
    ]


# ---------------------------------------------------------------------------
# Catalogue dynamique
# ---------------------------------------------------------------------------


def test_champs_metadonnees_collection_vide(
    session: Session, collection_simple: Collection
) -> None:
    assert champs_metadonnees_disponibles(session, collection_simple.id) == []


def test_champs_metadonnees_tries_par_frequence(session: Session) -> None:
    miroir = _creer_fonds_avec_miroir(session, "X")
    for i in range(3):
        _ajouter_item(
            session,
            miroir,
            f"X-{i:03d}",
            metadonnees={"frequent": "a", "rare": "b" if i == 0 else None},
        )
    cles = [c.nom for c in champs_metadonnees_disponibles(session, miroir.id)]
    assert "frequent" in cles


def test_champs_metadonnees_limite(session: Session) -> None:
    miroir = _creer_fonds_avec_miroir(session, "L")
    md = {f"f{i}": str(i) for i in range(10)}
    _ajouter_item(session, miroir, "L-001", metadonnees=md)
    res = champs_metadonnees_disponibles(session, miroir.id, limite=3)
    assert len(res) == 3


def test_resoudre_colonnes_actives_filtre_inconnus(
    session: Session, collection_simple: Collection
) -> None:
    dispo = colonnes_disponibles_items(session, collection_simple.id)
    actives = resoudre_colonnes_actives(["cote", "ghost", "titre"], dispo)
    assert [c.nom for c in actives] == ["cote", "titre"]


def test_metas_valides_pour(session: Session) -> None:
    miroir = _creer_fonds_avec_miroir(session, "M")
    _ajouter_item(session, miroir, "M-001", metadonnees={"foo": "1"})
    dispo = colonnes_disponibles_items(session, miroir.id)
    metas = metas_valides_pour(dispo)
    assert "foo" in metas


def test_sauvegarder_meta_valide_passe(session: Session) -> None:
    miroir = _creer_fonds_avec_miroir(session, "K")
    _ajouter_item(session, miroir, "K-001", metadonnees={"editeur": "X"})
    metas = metas_valides_pour(colonnes_disponibles_items(session, miroir.id))
    sauvegarder_preferences_colonnes(
        session,
        "u",
        miroir.id,
        "items",
        ["cote", "editeur", "ghost_meta"],
        metas_valides=metas,
    )
    prefs = lire_preferences_colonnes(session, "u", miroir.id)
    assert "editeur" in prefs.colonnes_ordonnees
    assert "ghost_meta" not in prefs.colonnes_ordonnees


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _id_miroir_hk(client: TestClient) -> int:
    """Récupère l'id de la miroir du fonds HK dans la base demo
    (passe par les `Depends` actifs pour respecter le monkeypatch
    `ARCHIVES_DB`)."""
    from archives_tool.api.deps import _factory_pour, chemin_base_courant

    factory = _factory_pour(chemin_base_courant())
    with factory() as session:
        return session.scalar(
            select(Collection.id).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )


def test_get_panneau_renvoie_modale(base_demo: Path) -> None:
    client = TestClient(app)
    cid = _id_miroir_hk(client)
    resp = client.get(f"/preferences/colonnes/items/{cid}")
    assert resp.status_code == 200
    assert "data-modal-colonnes" in resp.text
    assert "data-cols-active" in resp.text


def test_get_panneau_collection_inexistante_404(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/preferences/colonnes/items/999999")
    assert resp.status_code == 404


def test_post_sauvegarde_renvoie_tableau(base_demo: Path) -> None:
    client = TestClient(app)
    cid = _id_miroir_hk(client)
    resp = client.post(
        f"/preferences/colonnes/items/{cid}",
        data={"colonnes": ["cote", "langue"]},
    )
    assert resp.status_code == 200
    assert "tableau-items" in resp.text
    assert resp.headers.get("HX-Trigger") == "panneau-colonnes-ferme"


def test_post_reset_renvoie_tableau(base_demo: Path) -> None:
    client = TestClient(app)
    cid = _id_miroir_hk(client)
    # Sauvegarde d'abord pour avoir quelque chose à reset.
    client.post(
        f"/preferences/colonnes/items/{cid}",
        data={"colonnes": ["cote", "langue"]},
    )
    resp = client.post(f"/preferences/colonnes/items/{cid}/reset")
    assert resp.status_code == 200
    assert resp.headers.get("HX-Trigger") == "panneau-colonnes-ferme"


# ---------------------------------------------------------------------------
# Branchement drawers + persistance HTMX swap
# ---------------------------------------------------------------------------


def test_page_collection_inclut_drawer_filtres(base_demo: Path) -> None:
    """La page Collection rend le drawer panneau_filtres en HTML, prêt
    à être ouvert par le bouton « Filtrer » via panneau_filtres.js.
    """
    client = TestClient(app)
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    # ID du drawer + attribut data-ouvert
    assert 'id="panneau-filtres"' in resp.text
    assert 'data-ouvert="false"' in resp.text
    # Chargement du JS du drawer + Sortable + htmx
    assert "panneau_filtres.js" in resp.text
    assert "panneau_colonnes.js" in resp.text
    assert "Sortable.min.js" in resp.text
    assert "htmx.min.js" in resp.text


def test_page_collection_branche_url_panneau_colonnes(base_demo: Path) -> None:
    """Le bouton « Colonnes » du tableau pointe vers la route HTMX
    `/preferences/colonnes/items/{id}` (modale ouverte par hx-get).
    """
    client = TestClient(app)
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    assert 'data-action="columns"' in resp.text
    assert 'hx-get="/preferences/colonnes/items/' in resp.text


def test_charger_colonnes_actives_n_emet_pas_plus_de_2_requetes(
    session: Session, collection_simple: Collection
) -> None:
    """Garde-fou : sans préférences sauvegardées, le helper évite le
    scan de `Item.metadonnees` (les défauts ne contiennent que des
    colonnes dédiées). 1 SELECT prefs + 0 SELECT métas = 1 requête.
    Avec une préférence custom, on monte à 2 requêtes.
    """
    from sqlalchemy import event

    from archives_tool.api.services.preferences import charger_colonnes_actives

    queries: list[str] = []

    def _on_execute(_conn, _cur, statement, *_args, **_kwargs):
        queries.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        charger_colonnes_actives(session, "marie", collection_simple.id, "items")
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)

    assert len(queries) <= 2, (
        f"charger_colonnes_actives a émis {len(queries)} requêtes "
        f"(limite : 2). Première : {queries[0][:80] if queries else ''}"
    )


def test_page_collection_n_a_pas_de_details_filtres(base_demo: Path) -> None:
    """Le filtrage passe par le drawer, pas par un `<details>` natif."""
    client = TestClient(app)
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    assert "<summary" not in resp.text


def test_post_preferences_persistance_aller_retour(base_demo: Path) -> None:
    """Sauvegarde des colonnes → reload page → préférences appliquées."""
    client = TestClient(app)
    cid = _id_miroir_hk(client)
    r_post = client.post(
        f"/preferences/colonnes/items/{cid}",
        data={"colonnes": ["cote", "langue", "etat"]},
    )
    assert r_post.status_code == 200
    # Reload de la page collection : les colonnes choisies doivent
    # apparaître dans le tableau (entêtes).
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    # Les en-têtes du tableau (data-sort-key) reflètent les colonnes
    # actives sauvegardées.
    assert 'data-sort-key="langue"' in resp.text
    assert 'data-sort-key="etat"' in resp.text
    # « titre » ne fait pas partie de la sélection persistée.
    assert 'data-sort-key="titre"' not in resp.text
