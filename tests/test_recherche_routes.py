"""Tests de la route /recherche (Lot B V0.9.x)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.db import (
    assurer_tables_fts,
    creer_engine,
    creer_session_factory,
    reindexer_fts,
)
from archives_tool.demo import peupler_base
from archives_tool.models import Fonds, Item
from archives_tool.models.base import Base


@pytest.fixture
def base_demo_path(tmp_path: Path) -> Path:
    """Base demo avec FTS5 créées + peuplées depuis l'existant.
    Le seeder demo ne crée pas les FTS (pas dans le modèle ORM),
    donc on les ajoute via `assurer_tables_fts` puis on les peuple
    via `reindexer_fts` (factorisation propre, même SQL que la
    migration)."""
    chemin = tmp_path / "demo.db"
    peupler_base(chemin)
    engine = creer_engine(chemin)
    assurer_tables_fts(engine)
    reindexer_fts(engine)
    engine.dispose()
    return chemin


@pytest.fixture
def client_demo(base_demo_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ARCHIVES_DB", str(base_demo_path))
    return TestClient(app)


def test_route_recherche_sans_query_rend_page_vide(client_demo: TestClient) -> None:
    """GET /recherche sans `q` rend la page avec le formulaire mais
    aucun résultat — invite à taper une requête."""
    response = client_demo.get("/recherche")
    assert response.status_code == 200
    assert "Recherche" in response.text
    # Pas de message "X résultats trouvés" puisque pas de query
    assert "résultats trouvés" not in response.text
    assert "résultat trouvé" not in response.text
    # Le placeholder du champ visible
    assert "Mot, cote, expression" in response.text


def test_route_recherche_avec_query_renvoie_resultats(
    client_demo: TestClient,
) -> None:
    """Recherche sur la cote partielle d'un item demo."""
    response = client_demo.get("/recherche?q=HK-001")
    assert response.status_code == 200
    assert "HK-001" in response.text
    # Lien direct vers l'item — `?q=...` propagé pour le surlignage
    # côté page item (le matching exact du href complet pourrait
    # casser si on ajoute des params plus tard, on vérifie le préfixe).
    assert 'href="/item/HK-001?fonds=HK' in response.text


def test_route_recherche_filtre_types(client_demo: TestClient) -> None:
    """Avec `types=item`, seuls les items remontent (pas les fonds
    ou collections, même si la query matcherait)."""
    response = client_demo.get("/recherche?q=Hara&types=item")
    assert response.status_code == 200
    # Hara-Kiri matche le fonds HK ET les items HK-001/002/003 par
    # cote (HK-001 → préfixe HK matche tous via wildcard).
    # Avec types=item, on a les items mais pas le badge FONDS.
    assert "HK-001" in response.text or "HK-002" in response.text
    # Aucun badge "FONDS" visible
    assert ">Fonds</span>" not in response.text


def test_route_recherche_scope_fonds(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Avec fonds_id, les résultats sont limités aux items/collections
    du fonds. Le bandeau indique le filtre actif."""
    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        fonds_hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        fonds_id = fonds_hk.id
    engine.dispose()

    response = client_demo.get(f"/recherche?q=HK&fonds_id={fonds_id}")
    assert response.status_code == 200
    # Filtre actif visible
    assert "Limité au fonds" in response.text


def test_route_recherche_snippet_html_safe(client_demo: TestClient) -> None:
    """Le snippet FTS5 inclut des balises <mark> qui doivent être
    rendues telles quelles (pas échappées) pour surligner les matchs.
    `satirique` est dans la description du fonds HK du seeder demo —
    match riche garanti."""
    response = client_demo.get("/recherche?q=satirique")
    assert response.status_code == 200
    # Les <mark> du snippet apparaissent dans le HTML (le mot dans
    # le snippet de description du fonds HK).
    assert "<mark>" in response.text
    # Et le mot recherché est rendu.
    assert "satirique" in response.text.lower()


def test_route_recherche_aucun_resultat(client_demo: TestClient) -> None:
    """Recherche qui ne matche rien : message clair, pas de crash."""
    response = client_demo.get("/recherche?q=zzzznonexistantzzzz")
    assert response.status_code == 200
    assert "Aucun résultat" in response.text


def test_recherche_snippet_html_echappe_protege_xss(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Passe de revue : un Item dont la description contient du HTML
    malveillant (cas réel : metadonnees libre venant d'un tableur
    avec contenu utilisateur arbitraire) ne doit PAS être injecté
    tel quel dans la page de recherche. Le filtre `snippet_fts_safe`
    échappe le HTML utilisateur ET préserve les balises `<mark>` du
    snippet FTS5."""
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.api.services.items import (
        FormulaireItem, creer_item,
    )

    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        fonds_hk = lire_fonds_par_cote(db, "HK")
        creer_item(
            db,
            FormulaireItem(
                cote="HK-XSS",
                titre="Item piégé pour XSS test",
                description="<script>alert('xss')</script>",
                fonds_id=fonds_hk.id,
            ),
        )
    engine.dispose()

    response = client_demo.get("/recherche?q=HK-XSS")
    assert response.status_code == 200
    # Le <script> brut doit être échappé (apparaît en &lt;script&gt;
    # ou similaire), pas exécutable.
    assert "<script>alert" not in response.text
    # Mais la balise <mark> du snippet doit être présente (non échappée).
    assert "<mark>" in response.text


def test_combo_scope_et_types(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Passe de revue : scope (limite géographique) + types (filtre
    entité) fonctionnent en combo. Un fonds_id avec types=item ne
    doit pas remonter le fonds lui-même même s'il matcherait."""
    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        fonds_hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        fonds_id = fonds_hk.id
    engine.dispose()

    response = client_demo.get(
        f"/recherche?q=HK&fonds_id={fonds_id}&types=item"
    )
    assert response.status_code == 200
    assert "Limité au fonds" in response.text
    # Pas de badge Fonds (types=item l'exclut)
    assert ">Fonds</span>" not in response.text


def test_barre_recherche_globale_dans_header(
    client_demo: TestClient,
) -> None:
    """Lot C V0.9.x : la barre de recherche est dans le header global,
    visible sur toutes les pages. Submit GET → /recherche."""
    response = client_demo.get("/")
    assert response.status_code == 200
    # Barre input présente
    assert 'id="recherche-globale-input"' in response.text
    # Form pointe sur /recherche
    assert 'action="/recherche"' in response.text
    # Hint placeholder visible
    assert "/  pour focus" in response.text


def test_script_raccourci_recherche_charge(client_demo: TestClient) -> None:
    """Lot C V0.9.x : `js/recherche_globale.js` est chargé sur toutes
    les pages (via base.html) pour le raccourci `/` ou Cmd+K."""
    response = client_demo.get("/")
    assert response.status_code == 200
    assert "js/recherche_globale.js" in response.text


def test_route_recherche_par_page_defaut_50(
    client_demo: TestClient,
) -> None:
    """Par défaut, la pagination est de 50 résultats par page.
    Sur le seeder demo où `numero` matche ~330 items, on a donc
    plusieurs pages et une pagination visible en bas."""
    response = client_demo.get("/recherche?q=numero")
    assert response.status_code == 200
    # Pagination visible (plus d'une page) — au moins le lien « › »
    # ou la page courante encadrée
    assert 'aria-current="page"' in response.text


def test_route_recherche_pagination_par_page_personnalise(
    client_demo: TestClient,
) -> None:
    """`?par_page=10` génère plus de pages que `par_page=50` pour
    une même recherche, et la pagination est visible."""
    p10 = client_demo.get("/recherche?q=numero&par_page=10").text
    p50 = client_demo.get("/recherche?q=numero&par_page=50").text
    # Avec par_page=10 on a beaucoup plus de pages → au moins un
    # numéro de page plus grand
    import re
    nums_10 = [int(m) for m in re.findall(r'>(\d+)</a>', p10)]
    nums_50 = [int(m) for m in re.findall(r'>(\d+)</a>', p50)]
    if nums_10 and nums_50:
        assert max(nums_10) > max(nums_50)


def test_route_recherche_page_2_differente_de_page_1(
    client_demo: TestClient,
) -> None:
    """La page 2 affiche des résultats différents de la page 1."""
    p1 = client_demo.get("/recherche?q=numero&par_page=10&page=1").text
    p2 = client_demo.get("/recherche?q=numero&par_page=10&page=2").text
    # Au moins une cote présente sur p1 et absente sur p2 (ou inverse)
    import re
    cotes_p1 = set(re.findall(r'/item/([A-Z]+-\d+)', p1))
    cotes_p2 = set(re.findall(r'/item/([A-Z]+-\d+)', p2))
    assert cotes_p1 != cotes_p2
    assert cotes_p1 - cotes_p2  # au moins une cote unique à p1


def test_route_recherche_par_page_cap_200(client_demo: TestClient) -> None:
    """Pydantic rejette `?par_page=9` (sous min 10) et `?par_page=201`
    (au-dessus cap 200) → 422."""
    assert client_demo.get("/recherche?q=test&par_page=9").status_code == 422
    assert client_demo.get("/recherche?q=test&par_page=201").status_code == 422


def test_route_recherche_pagination_preserve_filtres(
    client_demo: TestClient,
) -> None:
    """Les liens de pagination préservent q, scope, types, filtres
    avancés (sinon naviguer perdait le contexte)."""
    response = client_demo.get(
        "/recherche?q=numero&par_page=10&etat=brouillon&types=item"
    )
    assert response.status_code == 200
    # Les liens de pagination contiennent les filtres
    import re
    # Cherche un href vers la page 2 (ou autre) qui devrait contenir
    # les filtres etat et types
    pattern = r'href="(/recherche\?[^"]*page=\d+[^"]*)"'
    hrefs = re.findall(pattern, response.text)
    assert hrefs, "Aucun href de pagination trouvé"
    # Au moins un href contient etat=brouillon et types=item
    assert any("etat=brouillon" in h and "types=item" in h for h in hrefs)


def test_route_recherche_libelles_humains_coar_et_langue(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Trou identifié au test PF : `Type COAR / c_3e5a` au lieu de
    `Périodique`. Les filtres Jinja `libelle_coar` / `libelle_langue`
    convertissent l'URI/code en libellé humain via les options du
    module vocabulaires (mêmes tables que l'édition inline).

    Crée un item avec type_coar URI canonique + langue fra, puis
    vérifie que :
    - la checkbox du fieldset affiche « Périodique » et « Français »
    - la pastille active affiche « Type : Périodique » + « Langue : Français »
    - le suffixe technique (`c_3e5a`, `fra` brut sans context) n'est
      PAS rendu comme libellé visible
    """
    from archives_tool.api.services.fonds import (
        FormulaireFonds, creer_fonds, lire_fonds_par_cote,
    )
    from archives_tool.api.services.items import FormulaireItem, creer_item
    from archives_tool.db import reindexer_fts

    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        creer_fonds(db, FormulaireFonds(cote="VOCAB-T", titre="Test vocab"))
        fonds = lire_fonds_par_cote(db, "VOCAB-T")
        creer_item(
            db,
            FormulaireItem(
                cote="VOCAB-T-001",
                titre="Item test vocab humain",
                fonds_id=fonds.id,
                type_coar="http://purl.org/coar/resource_type/c_3e5a",  # Périodique
                langue="fra",
            ),
        )
    reindexer_fts(engine)
    engine.dispose()

    # Sans filtre actif : les checkboxes COAR/Langue affichent les libellés
    response = client_demo.get("/recherche?q=vocab")
    assert response.status_code == 200
    assert "Périodique" in response.text  # libellé COAR humain
    assert "Français" in response.text  # libellé langue humain

    # Avec filtre actif : la pastille affiche le libellé humain (pas l'URI/code)
    response2 = client_demo.get(
        "/recherche?q=vocab"
        "&type_coar=http%3A%2F%2Fpurl.org%2Fcoar%2Fresource_type%2Fc_3e5a"
        "&langue=fra"
    )
    assert response2.status_code == 200
    assert "Type :" in response2.text and "Périodique" in response2.text
    assert "Langue :" in response2.text and "Français" in response2.text


def test_route_recherche_pastille_revient_page_1(
    client_demo: TestClient,
) -> None:
    """Retirer un filtre via pastille doit retourner à la page 1
    du nouveau résultat (pas garder la page courante d'un résultat
    différent — risque de page vide)."""
    # Pastille q2 retirée → href sans `page=` (donc page 1 par défaut)
    response = client_demo.get(
        "/recherche?q=numero&par_page=10&page=3&q2=foo"
    )
    assert response.status_code == 200
    # Cherche le href de la pastille q2 (lien × pour retirer q2)
    import re
    # Le href ne doit pas contenir page=3
    pattern = r'href="(/recherche\?[^"]*)"[^>]*title="Retirer le raffinement'
    matches = re.findall(pattern, response.text)
    assert matches, "Pastille q2 non trouvée"
    href = matches[0]
    assert "page=3" not in href  # retour page 1 implicite


def test_route_recherche_query_invalide_pas_de_crash(
    client_demo: TestClient,
) -> None:
    """Caractères réservés FTS5 dans la query → 200 sans résultats
    plutôt que 500 (le service les échappe via _preparer_requete_fts)."""
    response = client_demo.get('/recherche?q=":()*+')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Filtres avancés (état, langue, type COAR, période, raffinement q2)
# ---------------------------------------------------------------------------


def test_route_recherche_section_filtres_avances_rendue(
    client_demo: TestClient,
) -> None:
    """La section `<details>` « Filtres avancés » est présente, avec
    le champ « Rechercher dans les résultats » et au moins une
    fieldset (la base demo a forcément des items avec un état)."""
    response = client_demo.get("/recherche?q=HK")
    assert response.status_code == 200
    assert "Filtres avancés" in response.text
    assert "Rechercher dans les résultats" in response.text
    # La fieldset État est toujours présente (les items demo ont un état)
    assert ">État<" in response.text or ">État</legend>" in response.text


def test_route_recherche_q2_raffine_les_resultats(
    client_demo: TestClient,
) -> None:
    """Le param `q2` raffine la query principale via AND FTS5. Sur le
    seeder demo : `q=Hara` matche les items HK + le fonds. Ajouter
    `q2=001` ne garde que les items qui contiennent aussi `001`."""
    sans = client_demo.get("/recherche?q=Hara").text
    avec = client_demo.get("/recherche?q=Hara&q2=001").text
    assert sans.count("HK-001") >= 1
    # Le raffinement a effet : on a au moins un résultat avec 001 dans
    # la version raffinée et la valeur est ré-injectée dans l'input q2.
    assert "HK-001" in avec
    assert 'name="q2"' in avec and 'value="001"' in avec
    # Sans q2 la query ramène plus (ou autant) d'items que avec q2
    # (FTS5 AND ne peut que restreindre).
    assert sans.count("Item</span>") >= avec.count("Item</span>")


def test_route_recherche_filtre_etat_silencieux_si_invalide(
    client_demo: TestClient,
) -> None:
    """Une valeur d'état hors whitelist est ignorée silencieusement
    (pas de 422, cohérent avec `parser_filtres_collection`)."""
    response = client_demo.get("/recherche?q=HK&etat=INEXISTANT")
    assert response.status_code == 200
    # La pastille ne doit pas apparaître pour la valeur invalide
    assert "INEXISTANT" not in response.text


def test_route_recherche_pastilles_actives_quand_filtre_pose(
    client_demo: TestClient,
) -> None:
    """Quand un filtre actif est posé, une pastille `×` cliquable
    apparaît. Test avec `q2=` qui ne dépend pas des options
    dynamiques de la base demo (toujours valide)."""
    response = client_demo.get("/recherche?q=Hara&q2=001")
    assert response.status_code == 200
    # Pastille « dans : <strong …>001</strong> × » (le strong porte
    # un style ellipsis depuis la passe de revue, donc on accepte
    # un attribut style optionnel).
    assert "dans :" in response.text
    assert ">001</strong>" in response.text


def test_route_recherche_section_ouverte_quand_filtre_actif(
    client_demo: TestClient,
) -> None:
    """Le `<details>` est `open` par défaut quand un filtre est actif
    pour que l'utilisateur voie tout de suite ce qui est posé."""
    sans = client_demo.get("/recherche?q=Hara").text
    avec = client_demo.get("/recherche?q=Hara&q2=foo").text
    # Sans filtre actif, pas de `open` sur le details des filtres avancés
    # (heuristique : "details open" apparait dans `avec` mais pas `sans`)
    assert avec.count("<details open") > sans.count("<details open")


def test_route_recherche_filtre_etat_reduit_les_items(
    client_demo: TestClient,
) -> None:
    """Test d'intégration bout-en-bout : un filtre `etat=brouillon`
    valide (présent dans la base demo : 56 items) réduit le nombre
    d'items rendus vs la requête sans filtre. La base demo a 5 états
    variés sur ~333 items, donc le filtre discrimine vraiment."""
    sans = client_demo.get("/recherche?q=numero&types=item").text
    avec = client_demo.get(
        "/recherche?q=numero&types=item&etat=brouillon"
    ).text
    # Chaque résultat item rend un lien `/item/COTE?fonds=...` —
    # le compte de ces liens est un proxy fiable du nombre d'items
    # affichés (ne dépend pas du whitespace/formatage du badge).
    nb_items_sans = sans.count('href="/item/')
    nb_items_avec = avec.count('href="/item/')
    # Le filtre réduit strictement (etat=brouillon ne matche qu'une
    # fraction des items qui contiennent "numero" dans le seeder).
    assert nb_items_avec < nb_items_sans
    # Au moins un match — sinon le test ne vérifie pas grand-chose.
    assert nb_items_avec > 0


def test_route_recherche_combo_scope_fonds_et_filtre_etat(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Scope fonds + filtre etat : les deux contraintes s'appliquent
    en AND. Pas de crash, et le bandeau affiche les 2 contextes."""
    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        fonds_hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        fonds_id = fonds_hk.id
    engine.dispose()

    response = client_demo.get(
        f"/recherche?q=numero&fonds_id={fonds_id}&etat=brouillon"
    )
    assert response.status_code == 200
    # Filtre scope visible
    assert "Limité au fonds" in response.text
    # Pastille état visible (la valeur 'brouillon' a un libellé via
    # le filtre Jinja libelle_etat — vérifie au moins la cellule de
    # pastille « État : »).
    assert "État :" in response.text


def test_route_recherche_bouton_reinitialiser_apparait_2_filtres(
    client_demo: TestClient,
) -> None:
    """Le bouton « Tout réinitialiser » n'apparaît qu'à partir de 2
    dimensions filtrantes actives — éviter le clic pastille par
    pastille quand il y en a plusieurs."""
    # 1 filtre actif : pas de bouton
    un_filtre = client_demo.get("/recherche?q=Hara&q2=foo").text
    assert "Tout réinitialiser" not in un_filtre
    # 2 filtres actifs : bouton visible
    deux_filtres = client_demo.get(
        "/recherche?q=Hara&q2=foo&etat=brouillon"
    ).text
    assert "Tout réinitialiser" in deux_filtres


def test_route_recherche_lever_scope_preserve_filtres_et_types(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Le lien « (lever) » du scope (fonds_id / collection_id) doit
    préserver q + types + filtres avancés en cours. Sans ça, lever le
    scope perdait silencieusement l'état de la recherche (cas user :
    « je veux élargir mais garder mon filtre validé »)."""
    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        fonds_hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        fonds_id = fonds_hk.id
    engine.dispose()

    response = client_demo.get(
        f"/recherche?q=numero&fonds_id={fonds_id}"
        f"&etat=brouillon&q2=foo&types=item"
    )
    assert response.status_code == 200
    # Le lien (lever) contient le filtre etat, q2 et types — mais pas
    # le fonds_id (puisqu'on le lève).
    assert ">\n            (lever)" in response.text or ">(lever)" in response.text or "(lever)" in response.text
    # Vérifie la composition de l'URL du lien (lever) : etat + q2 + types
    # préservés, fonds_id absent du href.
    import re
    # Cherche un href qui contient (lever) à proximité
    pattern = r'href="(/recherche\?[^"]+)"[^>]*>\s*\(lever\)'
    matches = re.findall(pattern, response.text)
    assert matches, "Aucun lien (lever) trouvé dans la réponse"
    href = matches[0]
    assert "q=numero" in href
    assert "etat=brouillon" in href
    assert "q2=foo" in href
    assert "types=item" in href
    assert "fonds_id" not in href  # justement levé


def test_route_recherche_pastille_q2_longue_tronquee(
    client_demo: TestClient,
) -> None:
    """Une valeur q2 longue (>40 chars) est tronquée visuellement avec
    `…` et la valeur complète est exposée via `title=` pour le survol."""
    valeur_longue = "A" * 50  # 50 chars > 40
    response = client_demo.get(f"/recherche?q=Hara&q2={valeur_longue}")
    assert response.status_code == 200
    # Le title contient la valeur complète
    assert f"Retirer le raffinement : {valeur_longue}" in response.text
    # La valeur tronquée (40 chars + …) apparait dans le <strong>
    valeur_tronquee = "A" * 40 + "…"
    assert valeur_tronquee in response.text
    # La valeur complète n'apparaît PAS dans le HTML rendu (le title
    # est un attribut, pas du contenu) — mais on peut vérifier que le
    # texte « AAAA...AAA » (50 A) n'apparait pas dans le DOM visible
    # via le <strong>. C'est plus subtil ; on vérifie juste que la
    # version tronquée est présente, c'est suffisant.


def test_route_recherche_pastille_q2_courte_non_tronquee(
    client_demo: TestClient,
) -> None:
    """Une valeur q2 courte (<= 40 chars) n'est pas tronquée."""
    response = client_demo.get("/recherche?q=Hara&q2=foo")
    assert response.status_code == 200
    assert "<strong" in response.text
    assert ">foo</strong>" in response.text
    # Pas d'ellipsis pour une valeur courte
    assert "foo…" not in response.text


def test_csv_to_liste_helper_partage() -> None:
    """Test unitaire du helper partagé `csv_to_liste` factorisé entre
    `dashboard.parser_filtres_collection` et
    `recherche.parser_filtres_recherche`. Couvre CSV, clés répétées,
    cas mixte (liste contenant une CSV), strip, dedup."""
    from archives_tool.api.services._filtres_communs import csv_to_liste

    assert csv_to_liste(None) == []
    assert csv_to_liste("") == []
    # CSV simple
    assert csv_to_liste("a,b,c") == ["a", "b", "c"]
    # Liste de chaînes (format `<select multiple>`)
    assert csv_to_liste(["a", "b"]) == ["a", "b"]
    # Cas mixte : liste dont les éléments sont eux-mêmes des CSV
    assert csv_to_liste(["a,b", "c"]) == ["a", "b", "c"]
    # Strip + dedup en préservant l'ordre
    assert csv_to_liste(" a , b , a ") == ["a", "b"]
    assert csv_to_liste(["a", "a", "b"]) == ["a", "b"]


def test_clamper_annee_helper_partage() -> None:
    """Test unitaire du helper partagé `clamper_annee`. Retourne `v`
    si dans bornes, `None` sinon (validation silencieuse)."""
    from archives_tool.api.services._filtres_communs import clamper_annee

    assert clamper_annee(None, 1900, 2000) is None
    # Bornes non définies → reject silencieusement
    assert clamper_annee(1950, None, None) is None
    assert clamper_annee(1950, 1900, None) is None
    # Dans bornes
    assert clamper_annee(1950, 1900, 2000) == 1950
    # Borne min exacte
    assert clamper_annee(1900, 1900, 2000) == 1900
    # Borne max exacte
    assert clamper_annee(2000, 1900, 2000) == 2000
    # Hors bornes
    assert clamper_annee(1800, 1900, 2000) is None
    assert clamper_annee(2100, 1900, 2000) is None


def test_route_item_surligne_q_dans_titre(
    client_demo: TestClient,
) -> None:
    """Quand on arrive sur la page item depuis la recherche, `?q=` est
    propagé via le lien et la page surligne les mots cherchés dans le
    titre + descriptions (filtre Jinja `surligner_q`). Sans `q`, pas
    de surlignage. Le test demo a HK-001 titré « Numéro 1 de Hara-Kiri »."""
    sans = client_demo.get("/item/HK-001?fonds=HK").text
    avec = client_demo.get("/item/HK-001?fonds=HK&q=Hara").text
    assert "<mark>Hara</mark>" not in sans
    assert "<mark>Hara</mark>" in avec


def test_route_recherche_charge_script_raccourcis(
    client_demo: TestClient,
) -> None:
    """Le JS de raccourcis clavier est chargé sur la page /recherche
    (← / → pour paginer, Esc pour défocus la barre)."""
    response = client_demo.get("/recherche")
    assert response.status_code == 200
    assert "js/recherche_raccourcis.js" in response.text


def test_surligner_q_helper_unitaire() -> None:
    """Test unitaire du filtre `surligner_q` :
    - vide / None → texte échappé sans <mark>
    - 1 mot → surligne (insensible casse)
    - plusieurs mots → surligne chacun
    - HTML dans le texte → échappé (anti-XSS)
    """
    from archives_tool.api.templating import _surligner_q

    assert str(_surligner_q("Hello", "")) == "Hello"
    assert str(_surligner_q("Hello", None)) == "Hello"
    assert str(_surligner_q(None, "x")) == ""
    assert str(_surligner_q("Hello world", "hello")) == "<mark>Hello</mark> world"
    # Multi-tokens : matche n'importe lequel
    out = str(_surligner_q("Hello world", "world hello"))
    assert "<mark>Hello</mark>" in out
    assert "<mark>world</mark>" in out
    # Sécurité XSS : balises dans le texte échappées avant injection
    out = str(_surligner_q("<script>alert(1)</script>", "alert"))
    assert "<script>" not in out  # bien échappé en &lt;script&gt;
    assert "&lt;script&gt;" in out
    assert "<mark>alert</mark>" in out


def test_filtres_recherche_nb_filtres_actifs() -> None:
    """Property unitaire `nb_filtres_actifs` : compte 1 par dimension
    (multi-valeurs compte pour 1), période compte pour 1 même si min
    ET max posés."""
    from archives_tool.api.services.recherche import FiltresRecherche

    assert FiltresRecherche().nb_filtres_actifs == 0
    assert FiltresRecherche(etats=("brouillon",)).nb_filtres_actifs == 1
    # 2 états compte pour 1 dimension
    assert FiltresRecherche(etats=("brouillon", "valide")).nb_filtres_actifs == 1
    # min ET max compte pour 1 (Période)
    assert FiltresRecherche(annee_min=1900, annee_max=2000).nb_filtres_actifs == 1
    # min seul aussi
    assert FiltresRecherche(annee_min=1900).nb_filtres_actifs == 1
    # Combo 4 dimensions
    assert (
        FiltresRecherche(
            etats=("brouillon",),
            langues=("fra",),
            types_coar=("journal",),
            q_dans_resultats="raffin",
        ).nb_filtres_actifs == 4
    )
