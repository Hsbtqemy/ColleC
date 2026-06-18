"""Tests du Lot C — résolution des 3 dernières trouvailles de l'audit
front/back.

(4) Bouton « Supprimer » exposé sur collection_champs.html.
(5) Bouton « Exporter » muet retiré du tableau_items.html.
(6) Lien « Liste des fonds » ajouté au dashboard pour exposer /fonds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services.champs_personnalises import (
    FormulaireChamp,
    creer_champ,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import ChampPersonnalise, Collection


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


# ---------------------------------------------------------------------------
# (4) Bouton Supprimer champ personnalisé
# ---------------------------------------------------------------------------


def _amorcer_champ(db_path: Path) -> tuple[str, str, int]:
    """Crée un champ « auteur » sur la miroir HK. Retourne (cote_col,
    cote_fonds, champ_id)."""
    from archives_tool.models import TypeCollection

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        miroir = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        c = creer_champ(
            s,
            miroir.id,
            FormulaireChamp(cle="auteur_test", libelle="Auteur (test)"),
        )
        s.commit()
        return miroir.cote, miroir.fonds.cote, c.id


def test_bouton_supprimer_champ_present_dans_actions(base_demo: Path) -> None:
    """Le bouton Supprimer apparaît dans la colonne actions, à côté de
    Modifier / Déprécier. Confirme dialog explique le fallback clé libre."""
    cote_col, cote_fonds, cid = _amorcer_champ(base_demo)
    client = TestClient(app)
    r = client.get(f"/collection/{cote_col}/champs?fonds={cote_fonds}")
    assert r.status_code == 200
    # Action URL présente
    assert f"/collection/{cote_col}/champs/{cid}/supprimer" in r.text
    # Confirm dialog mentionne le fallback
    assert "SURVIVENT" in r.text or "survivent" in r.text


def test_post_supprimer_champ_via_bouton(base_demo: Path) -> None:
    """Le POST déclenché par le bouton supprime la ligne en base. Les
    valeurs des items ne sont pas vérifiées ici (couvertes par
    test_champs_personnalises) mais le fait qu'elles « survivent » est
    sémantiquement validé par le composer."""
    cote_col, cote_fonds, cid = _amorcer_champ(base_demo)
    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/collection/{cote_col}/champs/{cid}/supprimer?fonds={cote_fonds}")
    assert r.status_code == 303
    # Champ disparu
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        c = s.get(ChampPersonnalise, cid)
        assert c is None
    engine.dispose()


def test_supprimer_champ_avec_valeurs_existantes_les_preserve(
    base_demo: Path,
) -> None:
    """Garde-fou critique : la dialog promet que les valeurs en
    metadonnees SURVIVENT au supprimer_champ (fallback clé libre).
    Si quelqu'un refacto le composer et casse le fallback, la dialog
    ment. Ce test verrouille la sémantique."""
    from sqlalchemy.orm.attributes import flag_modified

    from archives_tool.api.services.dashboard import composer_page_item
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.models import Item, ItemCollection, TypeCollection

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        miroir = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        # Pose une valeur sur un item de la miroir
        item = s.scalar(
            select(Item)
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == miroir.id)
            .limit(1)
        )
        meta = dict(item.metadonnees or {})
        meta["auteur_test"] = "Topor"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()
        cote_item = item.cote

        # Crée le champ formel et vérifie qu'il est rendu en formel
        c = creer_champ(
            s,
            miroir.id,
            FormulaireChamp(cle="auteur_test", libelle="Auteur (test)"),
        )
        cid = c.id

        fonds = lire_fonds_par_cote(s, "HK")
        detail_avant = composer_page_item(s, cote_item, fonds)
        champs_avant = detail_avant.metadonnees_par_section["Champs personnalisés"]
        champ_formel = next(
            (ch for ch in champs_avant if ch.cle == "auteur_test"), None
        )
        assert champ_formel is not None
        assert champ_formel.libelle == "Auteur (test)"

    # Maintenant POST supprimer via la route web (déclenchée par le
    # bouton du Lot C)
    client = TestClient(app, follow_redirects=False)
    r = client.post(
        f"/collection/{miroir.cote}/champs/{cid}/supprimer?fonds={fonds.cote}"
    )
    assert r.status_code == 303

    # Re-vérifie : la valeur Topor doit toujours apparaître sur l'item,
    # cette fois en fallback clé libre (libellé synthétisé).
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item_apres = s.scalar(select(Item).where(Item.cote == cote_item))
        # Valeur préservée en base
        assert item_apres.metadonnees.get("auteur_test") == "Topor"
        # Et rendue par le composer en clé libre
        fonds_apres = lire_fonds_par_cote(s, "HK")
        detail_apres = composer_page_item(s, cote_item, fonds_apres)
        champs_apres = detail_apres.metadonnees_par_section["Champs personnalisés"]
        cles_apres = {ch.cle for ch in champs_apres}
        assert "auteur_test" in cles_apres
        # Le libellé est synthétisé depuis la cle (pas "Auteur (test)")
        champ_libre = next(ch for ch in champs_apres if ch.cle == "auteur_test")
        assert champ_libre.libelle != "Auteur (test)"
    engine.dispose()


def test_bouton_supprimer_champ_absent_en_lecture_seule(
    base_demo: Path, monkeypatch, tmp_path: Path
) -> None:
    """Lecture seule : pas de bouton Supprimer (cohérent avec
    Déprécier/Modifier déjà masqués par la garde existante)."""
    cote_col, cote_fonds, cid = _amorcer_champ(base_demo)
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  d: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    client = TestClient(app)
    r = client.get(f"/collection/{cote_col}/champs?fonds={cote_fonds}")
    assert r.status_code == 200
    # Pas de bouton Supprimer
    assert f"/collection/{cote_col}/champs/{cid}/supprimer" not in r.text


# ---------------------------------------------------------------------------
# (5) Bouton Exporter muet retiré
# ---------------------------------------------------------------------------


def test_bouton_exporter_muet_retire_du_tableau_items(base_demo: Path) -> None:
    """Le bouton « Exporter » du tableau_items n'avait aucun JS ni
    route de support — clic muet. Retiré pour éviter l'UX trompeuse."""
    client = TestClient(app)
    r = client.get("/collection/HK?fonds=HK")
    assert r.status_code == 200
    # Le bouton avec data-action="export" ne doit plus exister
    assert 'data-action="export"' not in r.text


# ---------------------------------------------------------------------------
# (6) Lien Liste des fonds depuis le dashboard
# ---------------------------------------------------------------------------


def test_dashboard_expose_lien_liste_des_fonds(base_demo: Path) -> None:
    """Le dashboard rend un lien « Liste des fonds » à côté de
    « Vocabulaires » — la page /fonds était orpheline jusqu'ici."""
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/fonds"' in r.text
    assert "Liste des fonds" in r.text


def test_page_liste_fonds_repond_200(base_demo: Path) -> None:
    """La page /fonds elle-même répond et liste les fonds de la base."""
    client = TestClient(app)
    r = client.get("/fonds")
    assert r.status_code == 200
    assert "Fonds" in r.text
    # Au moins le fonds HK de la demo
    assert "HK" in r.text
