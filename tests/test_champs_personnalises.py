"""Tests du service et des routes de gestion des champs personnalisés
(V0.9.4 — comble le gap V0.7 backlog : créer / modifier / renommer
avec propagation aux items / déprécier / réactiver depuis l'UI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from archives_tool.api.main import app
from archives_tool.api.services.champs_personnalises import (
    ChampInvalide,
    FormulaireChamp,
    creer_champ,
    deprecier_champ,
    lister_champs,
    modifier_champ,
    reactiver_champ,
    renommer_champ,
    supprimer_champ,
)
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import ChampPersonnalise, Collection, Item, ItemCollection


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _miroir_id(db_path: Path, fonds_cote: str = "HK") -> int:
    """Renvoie l'id de la miroir d'un fonds (utilisée comme support
    par défaut dans les tests : items, items_collection câblés)."""
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        from archives_tool.models import Fonds, TypeCollection
        fonds = s.scalar(select(Fonds).where(Fonds.cote == fonds_cote))
        col = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        cid = col.id
    engine.dispose()
    return cid


# ---------------------------------------------------------------------------
# Service : créer / lister
# ---------------------------------------------------------------------------


def test_creer_champ_persiste_avec_defauts(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        champ = creer_champ(
            s, cid, FormulaireChamp(cle="auteur", libelle="Auteur")
        )
        assert champ.id is not None
        assert champ.cle == "auteur"
        assert champ.libelle == "Auteur"
        assert champ.actif is True
        assert champ.type == "texte"
    engine.dispose()


def test_creer_champ_refuse_cle_invalide(base_demo: Path) -> None:
    """Slug strict : pas de majuscule, pas de tiret, doit commencer
    par une lettre."""
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        with pytest.raises(ChampInvalide) as exc:
            creer_champ(s, cid, FormulaireChamp(cle="Auteur-Principal", libelle="X"))
        assert "cle" in exc.value.erreurs
    engine.dispose()


def test_creer_champ_refuse_doublon_cle(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="A"))
        with pytest.raises(ChampInvalide) as exc:
            creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="B"))
        assert "déjà" in exc.value.erreurs["cle"]
    engine.dispose()


def test_creer_champ_refuse_libelle_vide(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        with pytest.raises(ChampInvalide) as exc:
            creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle=""))
        assert "libelle" in exc.value.erreurs
    engine.dispose()


def test_lister_champs_tri_par_ordre_puis_cle(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_champ(s, cid, FormulaireChamp(cle="zebre", libelle="Z", ordre=2))
        creer_champ(s, cid, FormulaireChamp(cle="abeille", libelle="A", ordre=2))
        creer_champ(s, cid, FormulaireChamp(cle="moustique", libelle="M", ordre=1))
        cles = [c.cle for c in lister_champs(s, cid)]
        # ordre=1 d'abord (moustique), puis ordre=2 trié par cle
        # (abeille puis zebre)
        assert cles == ["moustique", "abeille", "zebre"]
    engine.dispose()


def test_lister_champs_exclut_deprecies_si_demande(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_champ(s, cid, FormulaireChamp(cle="actif", libelle="A"))
        c2 = creer_champ(s, cid, FormulaireChamp(cle="vieux", libelle="V"))
        deprecier_champ(s, c2.id)
        sans = lister_champs(s, cid, inclure_deprecies=False)
        avec = lister_champs(s, cid, inclure_deprecies=True)
        assert {c.cle for c in sans} == {"actif"}
        assert {c.cle for c in avec} == {"actif", "vieux"}
    engine.dispose()


# ---------------------------------------------------------------------------
# Service : modifier (sans toucher cle) / déprécier / réactiver
# ---------------------------------------------------------------------------


def test_modifier_champ_change_libelle_pas_cle(base_demo: Path) -> None:
    """`modifier_champ` ignore la cle du formulaire (passer par
    `renommer_champ` pour la changer). Sans ce contrat, un POST sur
    /modifier pourrait renommer sans propager."""
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="Auteur"))
        modifier_champ(
            s, c.id,
            FormulaireChamp(cle="essai_rename", libelle="Auteur principal"),
        )
        s.refresh(c)
        assert c.cle == "auteur"  # inchangé
        assert c.libelle == "Auteur principal"  # mis à jour
    engine.dispose()


def test_deprecier_puis_reactiver_idempotent(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="A"))
        deprecier_champ(s, c.id)
        deprecier_champ(s, c.id)  # idempotent
        s.refresh(c)
        assert c.actif is False
        reactiver_champ(s, c.id)
        reactiver_champ(s, c.id)  # idempotent
        s.refresh(c)
        assert c.actif is True
    engine.dispose()


# ---------------------------------------------------------------------------
# Service : renommer + propagation
# ---------------------------------------------------------------------------


def test_renommer_propage_dans_metadonnees_items(base_demo: Path) -> None:
    """Le rename déplace la valeur dans Item.metadonnees de tous les
    items de la collection. Bump modifie_par/le et version."""
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        # Pose une valeur sous l'ancienne clé sur un item de la
        # collection (l'importer le ferait normalement).
        item = s.scalar(
            select(Item)
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == cid)
            .limit(1)
        )
        meta = dict(item.metadonnees or {})
        meta["auteur"] = "Topor"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()
        version_avant = item.version

        # Crée le champ formel.
        c = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="Auteur"))
        # Rename.
        champ, propages = renommer_champ(s, c.id, "createur", modifie_par="Test")
        assert champ.cle == "createur"
        assert propages == 1

        # L'item a la nouvelle clé.
        s.refresh(item)
        assert "auteur" not in item.metadonnees
        assert item.metadonnees["createur"] == "Topor"
        assert item.modifie_par == "Test"
        assert item.version > version_avant
    engine.dispose()


def test_renommer_refuse_cle_existant_meme_collection(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c1 = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="A"))
        creer_champ(s, cid, FormulaireChamp(cle="createur", libelle="C"))
        with pytest.raises(ChampInvalide) as exc:
            renommer_champ(s, c1.id, "createur")
        assert "déjà" in exc.value.erreurs["cle"]
    engine.dispose()


def test_renommer_meme_cle_noop(base_demo: Path) -> None:
    """Renommer en la valeur courante = noop sans erreur (idempotent)."""
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="A"))
        _, propages = renommer_champ(s, c.id, "auteur")
        assert propages == 0
    engine.dispose()


def test_renommer_saute_items_avec_collision(base_demo: Path) -> None:
    """Si la nouvelle clé existe déjà en libre sur un item, l'item
    est sauté (pas d'écrasement silencieux). Les autres items sont
    propagés normalement."""
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        items = list(
            s.scalars(
                select(Item)
                .join(ItemCollection, ItemCollection.item_id == Item.id)
                .where(ItemCollection.collection_id == cid)
                .limit(2)
            ).all()
        )
        assert len(items) >= 2
        # Item 1 : pose `auteur` seulement → propagation OK.
        meta1 = dict(items[0].metadonnees or {})
        meta1["auteur"] = "Topor"
        items[0].metadonnees = meta1
        flag_modified(items[0], "metadonnees")
        # Item 2 : pose `auteur` ET `createur` → collision, skip.
        meta2 = dict(items[1].metadonnees or {})
        meta2["auteur"] = "X"
        meta2["createur"] = "Y"
        items[1].metadonnees = meta2
        flag_modified(items[1], "metadonnees")
        s.commit()

        c = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="A"))
        _, propages = renommer_champ(s, c.id, "createur")
        assert propages == 1  # item 1 propagé, item 2 sauté
        s.refresh(items[0])
        s.refresh(items[1])
        # Item 1 : auteur → createur
        assert items[0].metadonnees["createur"] == "Topor"
        assert "auteur" not in items[0].metadonnees
        # Item 2 : les deux préservés (pas d'écrasement)
        assert items[1].metadonnees["auteur"] == "X"
        assert items[1].metadonnees["createur"] == "Y"
    engine.dispose()


def test_renommer_refuse_cle_invalide(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="A"))
        with pytest.raises(ChampInvalide):
            renommer_champ(s, c.id, "Auteur Principal")
    engine.dispose()


# ---------------------------------------------------------------------------
# Service : déprécié → cartouche item le retire (mais valeur reste)
# ---------------------------------------------------------------------------


def test_composer_metadonnees_ignore_champs_deprecies(base_demo: Path) -> None:
    """Un champ déprécié ne doit pas apparaître dans la section
    formelle ; sa valeur tombe dans le fallback clé libre — la donnée
    reste affichable sur la page item."""
    from archives_tool.api.services.dashboard import composer_page_item
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        # Pose une valeur en metadonnees + crée le champ formel.
        item = s.scalar(
            select(Item)
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == cid)
            .limit(1)
        )
        meta = dict(item.metadonnees or {})
        meta["auteur"] = "Topor"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()
        c = creer_champ(
            s, cid, FormulaireChamp(cle="auteur", libelle="Auteur formel")
        )
        cote = item.cote
        fonds_obj = lire_fonds_par_cote(s, "HK")
        fonds = fonds_obj

        # Cas actif : le champ formel doit être présent.
        detail = composer_page_item(s, cote, fonds)
        cles_perso_actif = {
            c.cle for c in detail.metadonnees_par_section["Champs personnalisés"]
        }
        assert "auteur" in cles_perso_actif
        # Le libellé formel est utilisé.
        champ_objet = next(
            ch for ch in detail.metadonnees_par_section["Champs personnalisés"]
            if ch.cle == "auteur"
        )
        assert champ_objet.libelle == "Auteur formel"

        # Maintenant déprécier puis recomposer : le champ doit
        # passer en fallback clé libre (libellé synthétisé).
        deprecier_champ(s, c.id)
        detail2 = composer_page_item(s, cote, fonds)
        champs_apres = detail2.metadonnees_par_section["Champs personnalisés"]
        cles_apres = {ch.cle for ch in champs_apres}
        # La clé est toujours visible (la valeur reste en metadonnees).
        assert "auteur" in cles_apres
        # Mais le libellé est synthétisé (« Auteur »), pas le formel.
        champ_apres = next(ch for ch in champs_apres if ch.cle == "auteur")
        assert champ_apres.libelle != "Auteur formel"
    engine.dispose()


# ---------------------------------------------------------------------------
# Service : supprimer
# ---------------------------------------------------------------------------


def test_supprimer_champ_supprime_definitivement(base_demo: Path) -> None:
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="A"))
        champ_id = c.id
        supprimer_champ(s, champ_id)
        absent = s.scalar(
            select(ChampPersonnalise).where(ChampPersonnalise.id == champ_id)
        )
        assert absent is None
    engine.dispose()


# ---------------------------------------------------------------------------
# Routes web
# ---------------------------------------------------------------------------


def test_route_champs_page_liste_charge(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK/champs?fonds=HK")
    assert resp.status_code == 200
    # Page bien rendue (header présent).
    assert "Champs personnalisés" in resp.text
    assert "Créer un nouveau champ" in resp.text


def test_route_champs_creer_redirige_sur_succes(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/collection/HK/champs/creer?fonds=HK",
        data={
            "cle": "ancienne_cote",
            "libelle": "Ancienne cote",
            "type": "texte",
            "obligatoire": "false",
            "ordre": "0",
            "aide": "",
            "description_interne": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/collection/HK/champs" in resp.headers["location"]


def test_route_champs_creer_400_si_cle_invalide(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/collection/HK/champs/creer?fonds=HK",
        data={
            "cle": "X-MAJ",
            "libelle": "Test",
            "type": "texte",
            "ordre": "0",
            "aide": "",
            "description_interne": "",
        },
    )
    assert resp.status_code == 400
    # Le message d'erreur est dans la page rendue.
    assert "minuscule" in resp.text.lower() or "underscore" in resp.text


def test_route_champ_modifier_garde_anti_confused_deputy(base_demo: Path) -> None:
    """Si l'id du champ n'appartient pas à la collection du chemin,
    on doit recevoir 404 — pas un succès silencieux qui modifierait
    le champ d'une autre collection."""
    cid_fa = _miroir_id(base_demo, "FA")
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c_fa = creer_champ(s, cid_fa, FormulaireChamp(cle="auteur", libelle="A"))
        champ_fa_id = c_fa.id
    engine.dispose()
    client = TestClient(app)
    # Tente de modifier le champ FA via l'URL HK.
    resp = client.get(f"/collection/HK/champs/{champ_fa_id}/modifier?fonds=HK")
    assert resp.status_code == 404


def test_route_champ_renommer_propage(base_demo: Path) -> None:
    client = TestClient(app)
    # Crée d'abord un champ et pose une valeur sur un item.
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = creer_champ(s, cid, FormulaireChamp(cle="auteur", libelle="A"))
        item = s.scalar(
            select(Item)
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == cid)
            .limit(1)
        )
        meta = dict(item.metadonnees or {})
        meta["auteur"] = "Topor"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()
        champ_id = c.id
        item_id = item.id
    engine.dispose()

    resp = client.post(
        f"/collection/HK/champs/{champ_id}/renommer?fonds=HK",
        data={"nouvelle_cle": "createur"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Vérifie côté DB.
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = s.get(ChampPersonnalise, champ_id)
        assert c.cle == "createur"
        it = s.get(Item, item_id)
        assert "auteur" not in it.metadonnees
        assert it.metadonnees["createur"] == "Topor"
    engine.dispose()
