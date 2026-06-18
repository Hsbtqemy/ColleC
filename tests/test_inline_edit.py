"""Tests de la route d'édition inline du cartouche."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Item


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _version_courante(db_path: Path, cote: str) -> int:
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == cote))
        version = item.version
    engine.dispose()
    return version


def test_inline_edit_succes_retourne_fragment(base_demo: Path) -> None:
    """POST sur un champ éditable avec la bonne version : 200 +
    fragment HTML contenant la nouvelle valeur et un marqueur
    `data-edit-new-version`."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/titre?fonds=HK",
        data={"version": str(v), "valeur": "Nouveau titre inline"},
    )
    assert resp.status_code == 200
    assert "Nouveau titre inline" in resp.text
    assert "data-edit-new-version" in resp.text
    assert f'data-edit-new-version="{v + 1}"' in resp.text


def test_inline_edit_version_perimee_409(base_demo: Path) -> None:
    """POST avec une version périmée : 409 + fragment de conflit."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    # Premier save : OK.
    r1 = client.post(
        "/item/HK-001/champ/titre?fonds=HK",
        data={"version": str(v), "valeur": "Premier"},
    )
    assert r1.status_code == 200
    # Second save avec la version d'origine (devenue stale).
    r2 = client.post(
        "/item/HK-001/champ/titre?fonds=HK",
        data={"version": str(v), "valeur": "Stale"},
    )
    assert r2.status_code == 409
    assert "Conflit" in r2.text
    assert "Recharger" in r2.text


def test_inline_edit_champ_hors_whitelist_403(base_demo: Path) -> None:
    """Champs sensibles (cote, fonds_id) interdits — passent par la
    page /modifier complète."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/cote?fonds=HK",
        data={"version": str(v), "valeur": "HK-XXX"},
    )
    assert resp.status_code == 403


def test_inline_edit_etat_catalogage_ok(base_demo: Path) -> None:
    """V0.9.3 : `etat_catalogage` est désormais éditable inline pour
    fluidifier les vérifications en série. Vérifie le succès du POST
    + le libellé humain dans le markup retourné + la valeur brute
    dans `data-edit-raw` (pour pré-remplir le `<select>` au prochain
    clic)."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/etat_catalogage?fonds=HK",
        data={"version": str(v), "valeur": "verifie"},
    )
    assert resp.status_code == 200
    # Libellé humain affiché (« vérifié », pas « verifie »)
    assert "vérifié" in resp.text
    # Valeur brute conservée pour pré-remplir le select
    assert 'data-edit-raw="verifie"' in resp.text


def test_inline_edit_etat_catalogage_valeur_invalide_400(base_demo: Path) -> None:
    """Une valeur d'état hors enum est rejetée par la validation
    Pydantic (renvoie 400 avec le fragment d'erreur)."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/etat_catalogage?fonds=HK",
        data={"version": str(v), "valeur": "XXXX_INVALIDE"},
    )
    assert resp.status_code == 400


def test_inline_edit_date_renvoie_annee_derivee(base_demo: Path) -> None:
    """V0.9.8 : éditer `date` inline renvoie l'année recalculée dans
    `data-annee-derivee` (le JS repeint la cellule lecture seule) et
    synchronise `Item.annee` en base."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/date?fonds=HK",
        data={"version": str(v), "valeur": "1969-09"},
    )
    assert resp.status_code == 200
    assert 'data-annee-derivee="1969"' in resp.text
    # La base est bien synchronisée.
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        assert item.annee == 1969
        assert item.date == "1969-09"
    engine.dispose()


def test_inline_edit_date_imprecise_preserve_annee_et_reflete_hint(
    base_demo: Path,
) -> None:
    """Date imprécise → l'année existante est préservée (pas écrasée), et
    le hint `data-annee-derivee` reflète la valeur réelle stockée (le JS
    repeint la cellule avec la vérité base, pas une chaîne parasite)."""
    client = TestClient(app)
    # Garantir une année connue : on pose d'abord une date précise.
    v = _version_courante(base_demo, "HK-001")
    client.post(
        "/item/HK-001/champ/date?fonds=HK",
        data={"version": str(v), "valeur": "1962-04"},
    )
    # Puis on passe à une date imprécise : 1962 doit être conservé.
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/date?fonds=HK",
        data={"version": str(v), "valeur": "vers 1980"},
    )
    assert resp.status_code == 200
    assert 'data-annee-derivee="1962"' in resp.text
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        assert item.annee == 1962  # préservé, pas effacé
        assert item.date == "vers 1980"
    engine.dispose()


def test_inline_edit_champ_non_date_sans_annee_derivee(base_demo: Path) -> None:
    """Éditer un autre champ ne déclenche pas le hint année — pas de
    repeinte parasite de la cellule année."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/titre?fonds=HK",
        data={"version": str(v), "valeur": "Titre X"},
    )
    assert resp.status_code == 200
    assert "data-annee-derivee" not in resp.text


def test_inline_edit_item_inexistant_404(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/item/N_EXISTE_PAS/champ/titre?fonds=HK",
        data={"version": "1", "valeur": "X"},
    )
    assert resp.status_code == 404


def test_inline_edit_fonds_inexistant_404(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/champ/titre?fonds=N_EXISTE",
        data={"version": "1", "valeur": "X"},
    )
    assert resp.status_code == 404


def test_inline_edit_chaine_vide_efface(base_demo: Path) -> None:
    """Envoyer une chaîne vide efface le champ (rendu « non renseigné »
    dans le fragment retourné)."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/description?fonds=HK",
        data={"version": str(v), "valeur": ""},
    )
    assert resp.status_code == 200
    assert "non renseigné" in resp.text


def test_save_vocabulaire_retourne_libelle_avec_data_edit_raw(
    base_demo: Path,
) -> None:
    """Sauver une langue (« fra ») doit retourner le libellé humain
    « Français » dans le markup affiché, et la valeur brute « fra »
    dans `data-edit-raw` pour que la prochaine édition pré-remplisse
    le <select> correctement."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/langue?fonds=HK",
        data={"version": str(v), "valeur": "fra"},
    )
    assert resp.status_code == 200
    assert 'data-edit-raw="fra"' in resp.text
    assert "Français" in resp.text


def test_cartouche_emet_data_edit_options_pour_langue(base_demo: Path) -> None:
    """`langue` et `type_coar` doivent porter `data-edit-options` (JSON)
    sur la ligne du cartouche, pour que l'édition inline déclenche un
    <select> au lieu d'un <input> libre."""
    client = TestClient(app)
    resp = client.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    # Vocabulaire des langues présent sur la ligne langue.
    assert 'data-edit-field="langue"' in resp.text
    assert 'data-edit-options="' in resp.text
    # Une langue connue figure dans le JSON sérialisé (forceescape).
    assert "Fran" in resp.text  # « Français » dans le libellé
    # Pareil pour type_coar.
    assert 'data-edit-field="type_coar"' in resp.text


def test_whitelist_inline_aligne_sur_cartouche(base_demo: Path) -> None:
    """Garde-fou anti-drift : chaque `ChampMetadonnee.editable=True`
    rendu par le cartouche doit être accepté par la route POST. Sinon
    l'utilisateur cliquerait sur une zone marquée éditable et recevrait
    un 403 silencieux."""
    from archives_tool.api.services.dashboard import (
        CHAMPS_ITEM_EDITABLES_INLINE,
        composer_metadonnees_par_section,
    )

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        sections = composer_metadonnees_par_section(item, [])
    engine.dispose()

    editables_rendues = {
        champ.cle for champs in sections.values() for champ in champs if champ.editable
    }
    # Tout champ rendu éditable est dans la whitelist (le contraire
    # — un champ dans la whitelist non rendu — est OK : champs perso
    # ou champs absents par construction).
    assert editables_rendues <= CHAMPS_ITEM_EDITABLES_INLINE, (
        f"Champs rendus éditables hors whitelist : "
        f"{editables_rendues - CHAMPS_ITEM_EDITABLES_INLINE}"
    )


def test_cartouche_rend_cible_annee_non_editable(base_demo: Path) -> None:
    """Contrat V0.9.8 du repeint inline : la cellule `annee` doit être
    rendue dans le cartouche (cible du `rafraichirAnneeDerivee` JS après
    édition de `date`) ET marquée non-éditable (dérivée, pas saisie). Si
    quelqu'un retire `annee` du cartouche, le repeint no-op en silence —
    ce test casse à la place."""
    from archives_tool.api.services.dashboard import (
        composer_metadonnees_par_section,
    )

    # Cible présente dans le HTML rendu (sélecteur JS
    # `[data-edit-field="annee"] [data-value]`).
    client = TestClient(app)
    resp = client.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    assert 'data-edit-field="annee"' in resp.text

    # `annee` est non-éditable côté composer (lecture seule, dérivée).
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        sections = composer_metadonnees_par_section(item, [])
    engine.dispose()
    champ_annee = next(
        champ
        for champs in sections.values()
        for champ in champs
        if champ.cle == "annee"
    )
    assert champ_annee.editable is False


def test_script_inline_edit_a_un_suffixe_cache_bust(base_demo: Path) -> None:
    """Les inclusions JS sur la page item passent par `static_url()`,
    qui suffixe le src avec `?v=<mtime>`. Permet d'éditer le JS sans
    bataille avec le cache navigateur en dev."""
    client = TestClient(app)
    resp = client.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    assert "inline_edit.js?v=" in resp.text


def test_meta_item_context_dans_page(base_demo: Path) -> None:
    """La page item lecture expose `<meta name="item-context">` lu
    par le JS d'édition inline."""
    client = TestClient(app)
    resp = client.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    assert 'name="item-context"' in resp.text
    assert 'data-cote="HK-001"' in resp.text
    assert 'data-fonds="HK"' in resp.text
    assert "data-version=" in resp.text
    assert "inline_edit.js" in resp.text


# ---------------------------------------------------------------------------
# Inline edit collection (V0.9.6) — bandeau titre / description / phase
# ---------------------------------------------------------------------------


def _version_collection(db_path: Path, cote: str) -> int:
    """Version courante de la miroir HK pour l'optimistic locking."""
    from archives_tool.models import Collection, TypeCollection

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(
                Collection.cote == cote,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        v = col.version
    engine.dispose()
    return v


def test_inline_edit_collection_titre_succes(base_demo: Path) -> None:
    """POST sur titre de la miroir : 200 + fragment, et la nouvelle
    valeur est persistée en base."""
    from archives_tool.models import Collection, TypeCollection

    client = TestClient(app)
    v = _version_collection(base_demo, "HK")
    resp = client.post(
        "/collection/HK/champ/titre?fonds=HK",
        data={"version": str(v), "valeur": "Nouveau titre miroir HK"},
    )
    assert resp.status_code == 200
    assert "Nouveau titre miroir HK" in resp.text
    assert f'data-edit-new-version="{v + 1}"' in resp.text
    # Persisté en base
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        assert col.titre == "Nouveau titre miroir HK"
    engine.dispose()


def test_inline_edit_collection_phase_avec_vocabulaire(base_demo: Path) -> None:
    """Le champ `phase` est résolu via PHASES_OPTIONS — la réponse
    affiche le libellé humain (`révision`) et conserve la valeur brute
    pour la ré-édition."""
    client = TestClient(app)
    v = _version_collection(base_demo, "HK")
    resp = client.post(
        "/collection/HK/champ/phase?fonds=HK",
        data={"version": str(v), "valeur": "revision"},
    )
    assert resp.status_code == 200
    assert "révision" in resp.text  # libellé humain
    assert 'data-edit-raw="revision"' in resp.text  # valeur brute conservée


def test_inline_edit_collection_champ_hors_whitelist_refus(
    base_demo: Path,
) -> None:
    """`cote` n'est pas dans la whitelist — refus 403."""
    client = TestClient(app)
    v = _version_collection(base_demo, "HK")
    resp = client.post(
        "/collection/HK/champ/cote?fonds=HK",
        data={"version": str(v), "valeur": "PIRATE"},
    )
    assert resp.status_code == 403


def test_inline_edit_collection_conflit_version(base_demo: Path) -> None:
    """Version périmée → 409 avec fragment de conflit."""
    client = TestClient(app)
    v = _version_collection(base_demo, "HK")
    resp = client.post(
        "/collection/HK/champ/titre?fonds=HK",
        data={"version": str(v - 99), "valeur": "X"},
    )
    assert resp.status_code == 409


def test_meta_entity_context_dans_page_collection(base_demo: Path) -> None:
    """La page collection lecture expose `<meta name="entity-context">`
    avec cote/fonds/version et URL-template pointant sur la route
    inline collection."""
    client = TestClient(app)
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    assert 'name="entity-context"' in resp.text
    assert 'data-cote="HK"' in resp.text
    assert 'data-fonds="HK"' in resp.text
    assert "/collection/{cote}/champ/{field}" in resp.text
    assert "inline_edit.js" in resp.text


def test_collection_bandeau_hooks_inline_present(base_demo: Path) -> None:
    """Les hooks `data-edit-field` sont posés sur titre / description /
    phase dans le bandeau, et sur doi_nakala / doi_collection_nakala_parent
    dans la boîte Synthèse (déplacement V0.9.6 suite à retour utilisateur :
    le DOI a sa place dans la synthèse, pas dans le bandeau)."""
    client = TestClient(app)
    resp = client.get("/collection/HK?fonds=HK")
    assert resp.status_code == 200
    # Bandeau (au-dessus de la synthèse)
    assert 'data-edit-field="titre"' in resp.text
    assert 'data-edit-field="description"' in resp.text
    assert 'data-edit-field="phase"' in resp.text
    # Synthèse (dans la boîte <details>)
    assert 'data-edit-field="doi_nakala"' in resp.text
    assert 'data-edit-field="doi_collection_nakala_parent"' in resp.text
    # Garde-fou : le DOI ne doit PAS être resté dans le bandeau (l'ancien
    # placement V0.9.6 initial). On vérifie sa position via l'ordre :
    # « DOI Nakala » apparait APRÈS l'en-tête « Synthèse » du composant.
    idx_synthese = resp.text.find("Synthèse")
    idx_doi = resp.text.find("DOI Nakala")
    assert idx_synthese > -1 and idx_doi > idx_synthese


# ---------------------------------------------------------------------------
# Inline edit fonds (V0.9.6) — bandeau titre/description + Identifiants
# ---------------------------------------------------------------------------


def _version_fonds(db_path: Path, cote: str) -> int:
    """Version courante d'un fonds pour l'optimistic locking."""
    from archives_tool.models import Fonds

    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(select(Fonds).where(Fonds.cote == cote))
        v = fonds.version
    engine.dispose()
    return v


def test_inline_edit_fonds_titre_succes(base_demo: Path) -> None:
    """POST sur titre du fonds : 200 + fragment, valeur persistée."""
    from archives_tool.models import Fonds

    client = TestClient(app)
    v = _version_fonds(base_demo, "HK")
    resp = client.post(
        "/fonds/HK/champ/titre",
        data={"version": str(v), "valeur": "Hara-Kiri (édité inline)"},
    )
    assert resp.status_code == 200
    assert "Hara-Kiri (édité inline)" in resp.text
    assert f'data-edit-new-version="{v + 1}"' in resp.text
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        assert fonds.titre == "Hara-Kiri (édité inline)"
    engine.dispose()


def test_inline_edit_fonds_issn_succes(base_demo: Path) -> None:
    """POST sur ISSN : champ revue inline depuis la synthèse."""
    from archives_tool.models import Fonds

    client = TestClient(app)
    v = _version_fonds(base_demo, "HK")
    resp = client.post(
        "/fonds/HK/champ/issn",
        data={"version": str(v), "valeur": "0998-1234"},
    )
    assert resp.status_code == 200
    assert "0998-1234" in resp.text
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        assert fonds.issn == "0998-1234"
    engine.dispose()


def test_inline_edit_fonds_champ_hors_whitelist_refus(base_demo: Path) -> None:
    """`cote` n'est pas dans la whitelist fonds — refus 403."""
    client = TestClient(app)
    v = _version_fonds(base_demo, "HK")
    resp = client.post(
        "/fonds/HK/champ/cote",
        data={"version": str(v), "valeur": "PIRATE"},
    )
    assert resp.status_code == 403


def test_meta_entity_context_dans_page_fonds(base_demo: Path) -> None:
    """La page fonds expose `<meta name="entity-context">` avec
    cote/version et l'URL-template pointant sur la route fonds."""
    client = TestClient(app)
    resp = client.get("/fonds/HK")
    assert resp.status_code == 200
    assert 'name="entity-context"' in resp.text
    assert 'data-cote="HK"' in resp.text
    assert "/fonds/{cote}/champ/{field}" in resp.text
    assert "inline_edit.js" in resp.text


def test_fonds_bandeau_hooks_inline_present(base_demo: Path) -> None:
    """Hooks data-edit-field sur titre + description dans le bandeau
    fonds, et sur les champs revue (issn, editeur, etc.) dans la
    synthèse."""
    client = TestClient(app)
    resp = client.get("/fonds/HK")
    assert resp.status_code == 200
    # Bandeau
    assert 'data-edit-field="titre"' in resp.text
    assert 'data-edit-field="description"' in resp.text
    # Synthèse (Identifiants revue)
    for cle in ("editeur", "issn", "periodicite", "date_debut", "date_fin"):
        assert f'data-edit-field="{cle}"' in resp.text, f"hook manquant : {cle}"


def test_fonds_bandeau_n_a_plus_de_dl_dt_metadata(base_demo: Path) -> None:
    """Garde-fou de non-régression : le `<dl><dt>` du bandeau fonds
    a été supprimé en V0.9.6 au profit du bloc Identifiants dans la
    synthèse. Si quelqu'un remet le pattern, ce test le signale."""
    client = TestClient(app)
    resp = client.get("/fonds/HK")
    assert resp.status_code == 200
    # L'ancien pattern utilisait `<dt class="text-gray-500">Responsable Archives</dt>`
    # et similaires. Aucun de ces dt ne doit subsister dans le bandeau.
    anciens_labels_dl = [
        '<dt class="text-gray-500">Responsable Archives</dt>',
        '<dt class="text-gray-500">Éditeur</dt>',
        '<dt class="text-gray-500">ISSN</dt>',
        '<dt class="text-gray-500">Périodicité</dt>',
    ]
    for marqueur in anciens_labels_dl:
        assert marqueur not in resp.text, f"ancien dl/dt revenu : {marqueur}"


def test_fonds_identifiants_vides_masques_en_lecture_seule(
    base_demo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """En lecture seule, le bloc Identifiants ne montre QUE les champs
    renseignés (pas de placeholder « + ajouter » qui n'a aucun sens si
    on ne peut pas éditer)."""
    # Crée un fonds vierge (sans aucun identifiant) pour pouvoir tester
    # proprement le rendu en lecture seule sans bruit du seeder.
    from archives_tool.api.services.fonds import (
        FormulaireFonds,
        creer_fonds,
    )

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="VIDE", titre="Fonds vide test"))
    engine.dispose()

    # Active le mode lecture seule via le filtre Jinja (le check est
    # dans les globals de l'env templates).
    from archives_tool.api import templating

    monkeypatch.setitem(
        templating.templates.env.globals, "est_lecture_seule", lambda: True
    )

    client = TestClient(app)
    resp = client.get("/fonds/VIDE")
    assert resp.status_code == 200
    # Aucun identifiant rempli + lecture seule → bloc Identifiants
    # entièrement masqué.
    assert "+ ajouter" not in resp.text
    assert 'data-edit-field="editeur"' not in resp.text
    assert 'data-edit-field="issn"' not in resp.text
    # Le bandeau a aussi son meta entity-context masqué en lecture
    # seule (puisqu'on ne peut rien éditer).
    assert 'name="entity-context"' not in resp.text


def test_fonds_identifiants_champs_remplis_visibles_en_lecture_seule(
    base_demo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contre-test : en lecture seule, les champs **remplis** sont bien
    visibles (juste sans hook d'édition). Garantit qu'on ne masque pas
    par excès."""
    from archives_tool.api import templating

    monkeypatch.setitem(
        templating.templates.env.globals, "est_lecture_seule", lambda: True
    )
    client = TestClient(app)
    resp = client.get("/fonds/HK")  # HK demo a editeur/lieu/periodicite remplis
    assert resp.status_code == 200
    # Les valeurs apparaissent
    assert "Éditions du Square" in resp.text
    assert "Paris" in resp.text
    assert "mensuel" in resp.text
    # Mais sans hooks d'édition (data-editable="0")
    assert 'data-editable="0"' in resp.text


def test_inline_edit_collection_doi_nakala_succes(base_demo: Path) -> None:
    """POST sur doi_nakala : 200 + fragment, valeur persistée."""
    from archives_tool.models import Collection, TypeCollection

    client = TestClient(app)
    v = _version_collection(base_demo, "HK")
    nouveau_doi = "10.34847/nkl.test123"
    resp = client.post(
        "/collection/HK/champ/doi_nakala?fonds=HK",
        data={"version": str(v), "valeur": nouveau_doi},
    )
    assert resp.status_code == 200
    assert nouveau_doi in resp.text
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        assert col.doi_nakala == nouveau_doi
    engine.dispose()
