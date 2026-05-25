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
    CleNonPromouvable,
    FormulaireChamp,
    creer_champ,
    deprecier_champ,
    lister_champs,
    modifier_champ,
    promouvoir_cle_libre_en_champ,
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


# ---------------------------------------------------------------------------
# Promotion clé libre (Lot 2)
# ---------------------------------------------------------------------------


def test_promouvoir_cle_libre_cree_champ_sur_miroir(base_demo: Path) -> None:
    """`promouvoir_cle_libre_en_champ` crée un ChampPersonnalise sur la
    miroir du fonds de l'item, avec libellé synthétisé via
    `_libelle_depuis_cle`."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(
            select(Item).where(Item.cote == "HK-001")
        )
        # Pose une clé libre.
        meta = dict(item.metadonnees or {})
        meta["ancienne_cote"] = "HK/1960/01"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()

        champ, miroir = promouvoir_cle_libre_en_champ(s, item, "ancienne_cote")
        assert champ.cle == "ancienne_cote"
        assert champ.libelle == "Ancienne cote"  # synthétisé
        assert champ.actif is True
        # Miroir du fonds HK.
        assert miroir.cote == "HK"
    engine.dispose()


def test_promouvoir_idempotent(base_demo: Path) -> None:
    """Re-clicker « Formaliser » ne casse pas — retourne le champ existant."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["ancienne_cote"] = "X"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()

        c1, _ = promouvoir_cle_libre_en_champ(s, item, "ancienne_cote")
        c2, _ = promouvoir_cle_libre_en_champ(s, item, "ancienne_cote")
        assert c1.id == c2.id  # même champ
    engine.dispose()


def test_promouvoir_idempotent_meme_si_deprecie(base_demo: Path) -> None:
    """Si un champ déprécié existe déjà sur la miroir, on retourne
    le champ déprécié sans réactiver — l'utilisateur conserve le
    contrôle (peut vouloir maintenir le champ caché)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        from archives_tool.models import Collection, Fonds, TypeCollection
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        # Crée + déprécie un champ.
        c = creer_champ(s, miroir.id, FormulaireChamp(cle="auteur", libelle="A"))
        deprecier_champ(s, c.id)

        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["auteur"] = "X"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()

        retourne, _ = promouvoir_cle_libre_en_champ(s, item, "auteur")
        assert retourne.id == c.id
        assert retourne.actif is False  # PAS réactivé
    engine.dispose()


def test_promouvoir_refuse_cle_invalide(base_demo: Path) -> None:
    """Slug invalide : pas de promotion automatique. L'utilisateur
    doit nettoyer la clé en amont."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["Mots-Clés"] = "X"  # majuscules + tiret + accent
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()

        with pytest.raises(CleNonPromouvable):
            promouvoir_cle_libre_en_champ(s, item, "Mots-Clés")
    engine.dispose()


def test_promouvoir_refuse_cle_absente(base_demo: Path) -> None:
    """Si la clé n'existe pas dans item.metadonnees, on refuse (la
    page item ne devrait jamais soumettre une cle absente, mais la
    garde est utile contre le bricolage URL)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        with pytest.raises(CleNonPromouvable):
            promouvoir_cle_libre_en_champ(s, item, "inexistante")
    engine.dispose()


def test_composer_marque_formels_non_promouvables(base_demo: Path) -> None:
    """Un ChampPersonnalise formel doit avoir `est_libre_promouvable=False`
    (le bouton « Formaliser » serait absurde — il l'est déjà). Garde-fou
    contre une régression future qui aurait set le flag par défaut à True."""
    from archives_tool.api.services.dashboard import composer_page_item
    from archives_tool.models import Collection, Fonds, TypeCollection

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        # Crée un champ formel ET pose la valeur sur un item.
        creer_champ(s, miroir.id, FormulaireChamp(cle="auteur", libelle="Auteur"))
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["auteur"] = "Topor"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()

        detail = composer_page_item(s, "HK-001", fonds)
        champs_perso = detail.metadonnees_par_section["Champs personnalisés"]
        auteur = next(c for c in champs_perso if c.cle == "auteur")
        assert auteur.est_libre_promouvable is False
    engine.dispose()


def test_composer_marque_libre_promouvable_pour_slugs_valides(base_demo: Path) -> None:
    """Vérifie que `est_libre_promouvable=True` pour les clés libres
    avec slug valide, False pour les clés invalides."""
    from archives_tool.api.services.dashboard import composer_page_item
    from archives_tool.api.services.fonds import lire_fonds_par_cote

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["ancienne_cote"] = "X"  # valide
        meta["Mots-Clés"] = "Y"  # invalide
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()

        fonds = lire_fonds_par_cote(s, "HK")
        detail = composer_page_item(s, "HK-001", fonds)
        champs_perso = detail.metadonnees_par_section["Champs personnalisés"]
        par_cle = {c.cle: c for c in champs_perso}
        assert par_cle["ancienne_cote"].est_libre_promouvable is True
        assert par_cle["Mots-Clés"].est_libre_promouvable is False
    engine.dispose()


def test_route_promouvoir_cle_redirige_vers_item(base_demo: Path) -> None:
    """POST `/item/<cote>/promouvoir-cle?fonds=X` crée le champ et
    redirige vers la page item."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["ancienne_cote"] = "X"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()
    engine.dispose()

    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/promouvoir-cle?fonds=HK",
        data={"cle": "ancienne_cote"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/item/HK-001" in resp.headers["location"]

    # Vérifie côté DB : champ créé sur la miroir HK.
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        from archives_tool.models import Collection, Fonds, TypeCollection
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        champ = s.scalar(
            select(ChampPersonnalise).where(
                ChampPersonnalise.collection_id == miroir.id,
                ChampPersonnalise.cle == "ancienne_cote",
            )
        )
        assert champ is not None
        assert champ.libelle == "Ancienne cote"
    engine.dispose()


def test_route_promouvoir_silencieux_sur_erreur(base_demo: Path) -> None:
    """Une promotion invalide (slug malformé, clé absente) ne plante
    pas la page — redirect silencieux vers l'item. Le bouton n'est
    pas censé être rendu pour ces cas, c'est une protection contre
    le bricolage URL."""
    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/promouvoir-cle?fonds=HK",
        data={"cle": "inexistante"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/item/HK-001" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Routes (suite Lot 1)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Lot 3b : wire valeurs_controlees_id depuis le formulaire
# ---------------------------------------------------------------------------


def test_creer_champ_avec_vocabulaire(base_demo: Path) -> None:
    """Crée un ChampPersonnalise avec un vocabulaire personnalisé
    attaché. Le wire passe via le formulaire."""
    from archives_tool.api.services.vocabulaires_db import (
        FormulaireVocabulaire,
        creer_vocabulaire,
    )

    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(
            s, FormulaireVocabulaire(code="tag", libelle="Tags")
        )
        c = creer_champ(
            s, cid,
            FormulaireChamp(
                cle="tag",
                libelle="Tag",
                valeurs_controlees_id=v.id,
            ),
        )
        s.refresh(c)
        assert c.valeurs_controlees_id == v.id
    engine.dispose()


def test_formulaire_normalise_vocab_id_chaine_vide(base_demo: Path) -> None:
    """Le form HTML envoie '' quand l'utilisateur choisit « aucun ».
    Pydantic doit traiter '' comme None sans planter."""
    formulaire = FormulaireChamp.model_validate({
        "cle": "tag", "libelle": "Tag", "valeurs_controlees_id": ""
    })
    assert formulaire.valeurs_controlees_id is None


def test_modifier_champ_change_vocabulaire(base_demo: Path) -> None:
    """Modifier un champ peut changer (ou détacher) son vocabulaire."""
    from archives_tool.api.services.vocabulaires_db import (
        FormulaireVocabulaire,
        creer_vocabulaire,
    )

    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(
            s, FormulaireVocabulaire(code="tag", libelle="Tags")
        )
        c = creer_champ(s, cid, FormulaireChamp(cle="tag", libelle="Tag"))
        # Attach
        modifier_champ(
            s, c.id,
            FormulaireChamp(
                cle="tag", libelle="Tag", valeurs_controlees_id=v.id
            ),
        )
        s.refresh(c)
        assert c.valeurs_controlees_id == v.id
        # Détacher
        modifier_champ(
            s, c.id,
            FormulaireChamp(cle="tag", libelle="Tag", valeurs_controlees_id=None),
        )
        s.refresh(c)
        assert c.valeurs_controlees_id is None
    engine.dispose()


# ---------------------------------------------------------------------------
# Lot V0.9.5 : item modifier expose les champs personnalisés
# ---------------------------------------------------------------------------


def test_route_item_modifier_affiche_champs_personnalises(base_demo: Path) -> None:
    """La page de modification d'un item rend une section pour chaque
    ChampPersonnalise actif des collections de l'item."""
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_champ(
            s, cid,
            FormulaireChamp(cle="ancienne_cote", libelle="Ancienne cote"),
        )
    engine.dispose()

    client = TestClient(app)
    resp = client.get("/item/HK-001/modifier?fonds=HK")
    assert resp.status_code == 200
    assert "Champs personnalisés" in resp.text
    assert 'name="meta_ancienne_cote"' in resp.text
    assert "Ancienne cote" in resp.text


def test_route_item_modifier_persiste_meta(base_demo: Path) -> None:
    """POST avec `meta_<cle>=valeur` fusionne dans item.metadonnees.
    Saisie vide = clé supprimée (sémantique cohérente avec l'import
    et l'affichage « non renseigné »)."""
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_champ(
            s, cid,
            FormulaireChamp(cle="ancienne_cote", libelle="Ancienne cote"),
        )
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        version = item.version
    engine.dispose()

    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/modifier?fonds=HK",
        data={
            "cote": "HK-001",
            "titre": "Titre",
            "fonds_id": 1,
            "version": version,
            "etat_catalogage": "brouillon",
            "meta_ancienne_cote": "HK/1960/01",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Vérifie côté DB.
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        assert (item.metadonnees or {}).get("ancienne_cote") == "HK/1960/01"
    engine.dispose()


def test_route_item_modifier_liste_multiple_persiste_list(base_demo: Path) -> None:
    """Un champ type `liste_multiple` rend des checkboxes. POST avec
    plusieurs valeurs du même name → list[str] dans
    item.metadonnees[cle]."""
    from archives_tool.api.services.vocabulaires_db import (
        FormulaireValeur,
        FormulaireVocabulaire,
        ajouter_valeur,
        creer_vocabulaire,
    )

    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        # Vocab avec 3 valeurs.
        v = creer_vocabulaire(
            s, FormulaireVocabulaire(code="tags", libelle="Tags")
        )
        ajouter_valeur(s, v.id, FormulaireValeur(code="a", libelle="A"))
        ajouter_valeur(s, v.id, FormulaireValeur(code="b", libelle="B"))
        ajouter_valeur(s, v.id, FormulaireValeur(code="c", libelle="C"))
        # Champ multi-select sur ce vocab.
        creer_champ(
            s, cid,
            FormulaireChamp(
                cle="tags", libelle="Tags", type="liste_multiple",
                valeurs_controlees_id=v.id,
            ),
        )
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        version = item.version
    engine.dispose()

    client = TestClient(app)
    # 2 checkboxes cochées : "a" et "c". httpx + TestClient envoie
    # une list[str] pour la même clé en multipart form-urlencoded.
    resp = client.post(
        "/item/HK-001/modifier?fonds=HK",
        data={
            "cote": "HK-001",
            "titre": "Titre HK-001",
            "fonds_id": 1,
            "version": version,
            "etat_catalogage": "brouillon",
            "meta_tags": ["a", "c"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        # Liste preservee dans metadonnees.
        tags = (item.metadonnees or {}).get("tags")
        assert isinstance(tags, list)
        assert set(tags) == {"a", "c"}
    engine.dispose()


def test_route_item_modifier_liste_multiple_zero_coche_efface(
    base_demo: Path,
) -> None:
    """Zéro checkbox coché → clé supprimée de metadonnees (cohérent
    avec la sémantique « vide = absent » des single-value)."""
    from archives_tool.api.services.vocabulaires_db import (
        FormulaireVocabulaire, creer_vocabulaire,
    )

    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(s, FormulaireVocabulaire(code="tags", libelle="T"))
        creer_champ(
            s, cid,
            FormulaireChamp(
                cle="tags", libelle="Tags", type="liste_multiple",
                valeurs_controlees_id=v.id,
            ),
        )
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["tags"] = ["a", "b"]
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()
        version = item.version
    engine.dispose()

    client = TestClient(app)
    # Aucune meta_tags soumise = 0 checkbox.
    resp = client.post(
        "/item/HK-001/modifier?fonds=HK",
        data={
            "cote": "HK-001", "titre": "T", "fonds_id": 1,
            "version": version, "etat_catalogage": "brouillon",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        assert "tags" not in (item.metadonnees or {})
    engine.dispose()


def test_route_item_modifier_meta_vide_supprime_cle(base_demo: Path) -> None:
    """Soumettre meta_<cle>="" efface la clé de Item.metadonnees."""
    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_champ(
            s, cid, FormulaireChamp(cle="auteur", libelle="Auteur")
        )
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        # Pose une valeur initiale.
        meta = dict(item.metadonnees or {})
        meta["auteur"] = "Topor"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()
        version = item.version
    engine.dispose()

    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/modifier?fonds=HK",
        data={
            "cote": "HK-001", "titre": "Titre", "fonds_id": 1,
            "version": version, "etat_catalogage": "brouillon",
            "meta_auteur": "",  # vide → efface
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        assert "auteur" not in (item.metadonnees or {})
    engine.dispose()


# ---------------------------------------------------------------------------
# Lot 3c : composer cartouche utilise vocab DB pour libellé humain
# ---------------------------------------------------------------------------


def test_composer_resout_libelle_humain_depuis_vocabulaire_db(base_demo: Path) -> None:
    """Quand un ChampPersonnalise pointe sur un vocab DB et que l'item
    porte une valeur correspondant à un code de ce vocab, le composer
    expose le libellé humain dans `valeur_affichee`."""
    from archives_tool.api.services.dashboard import composer_page_item
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.api.services.vocabulaires_db import (
        FormulaireValeur,
        FormulaireVocabulaire,
        ajouter_valeur,
        creer_vocabulaire,
    )

    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        # Vocabulaire avec 1 valeur.
        v = creer_vocabulaire(
            s, FormulaireVocabulaire(code="genre", libelle="Genres")
        )
        ajouter_valeur(s, v.id, FormulaireValeur(code="bd", libelle="Bande dessinée"))
        # Champ associé.
        creer_champ(
            s, cid,
            FormulaireChamp(
                cle="genre",
                libelle="Genre littéraire",
                valeurs_controlees_id=v.id,
            ),
        )
        # Item avec une valeur correspondante.
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["genre"] = "bd"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()

        fonds = lire_fonds_par_cote(s, "HK")
        detail = composer_page_item(s, "HK-001", fonds)
        perso = detail.metadonnees_par_section["Champs personnalisés"]
        genre = next(c for c in perso if c.cle == "genre")
        assert genre.valeur == "bd"  # brut stocké
        assert genre.valeur_affichee == "Bande dessinée"  # libellé humain
        assert genre.options is not None
        assert ("bd", "Bande dessinée") in genre.options
    engine.dispose()


def test_composer_valeur_hors_vocab_garde_brut(base_demo: Path) -> None:
    """Si l'item porte une valeur qui n'est pas dans le vocab (legacy
    ou déprécié), `valeur_affichee` retombe sur la valeur brute. Pas
    de perte de donnée."""
    from archives_tool.api.services.dashboard import composer_page_item
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.api.services.vocabulaires_db import (
        FormulaireValeur,
        FormulaireVocabulaire,
        ajouter_valeur,
        creer_vocabulaire,
    )

    cid = _miroir_id(base_demo)
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        v = creer_vocabulaire(
            s, FormulaireVocabulaire(code="genre", libelle="Genres")
        )
        ajouter_valeur(s, v.id, FormulaireValeur(code="bd", libelle="Bande dessinée"))
        creer_champ(
            s, cid,
            FormulaireChamp(
                cle="genre", libelle="Genre", valeurs_controlees_id=v.id
            ),
        )
        # Valeur HORS vocab.
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        meta = dict(item.metadonnees or {})
        meta["genre"] = "inconnu"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()

        fonds = lire_fonds_par_cote(s, "HK")
        detail = composer_page_item(s, "HK-001", fonds)
        perso = detail.metadonnees_par_section["Champs personnalisés"]
        genre = next(c for c in perso if c.cle == "genre")
        assert genre.valeur == "inconnu"
        assert genre.valeur_affichee == "inconnu"  # fallback brut
    engine.dispose()


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
