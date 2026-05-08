"""Smoke tests des 10 composants UI du bundle handoff.

Vérifie que chaque macro s'importe et se rend avec des données factices
représentatives (schémas documentés dans `docs/composants_ui.md`).
"""

from __future__ import annotations

import pytest

from archives_tool.api.templating import templates


@pytest.fixture
def env():
    return templates.env


def _render_macro(env, fichier: str, macro: str, *args, **kwargs) -> str:
    template = env.get_template(fichier)
    fn = getattr(template.module, macro)
    return str(fn(*args, **kwargs))


def test_badge_etat_item(env) -> None:
    out = _render_macro(env, "components/badge_etat.html", "badge_etat", "valide")
    assert "Validé" in out
    assert "bg-gray-100" in out


def test_badge_etat_fichier(env) -> None:
    out = _render_macro(
        env, "components/badge_etat.html", "badge_etat", "actif", kind="fichier"
    )
    assert "Actif" in out


def test_avancement_compact(env) -> None:
    out = _render_macro(
        env,
        "components/avancement.html",
        "avancement_compact",
        {"valide": 10, "brouillon": 3},
    )
    assert "height:6px" in out


def test_avancement_detaille_avec_legende(env) -> None:
    out = _render_macro(
        env,
        "components/avancement.html",
        "avancement_detaille",
        {"valide": 10, "a_verifier": 5},
    )
    assert "validé" in out
    assert "à vérifier" in out


def test_avancement_total_zero(env) -> None:
    out = _render_macro(env, "components/avancement.html", "avancement_compact", {})
    # Pas de segment, juste la barre vide.
    assert "bg-gray-100" in out


def test_cellule_modifie(env) -> None:
    out = _render_macro(
        env, "components/cellule_modifie.html", "cellule_modifie", "Marie", "il y a 2h"
    )
    assert "Marie" in out and "il y a 2h" in out


def test_cellule_modifie_vide(env) -> None:
    out = _render_macro(
        env, "components/cellule_modifie.html", "cellule_modifie", None, None
    )
    assert "—" in out


def test_phase_chantier(env) -> None:
    out = _render_macro(
        env, "components/phase_chantier.html", "phase_chantier", "catalogage"
    )
    assert "catalogage" in out


def test_phase_chantier_falsy(env) -> None:
    out = _render_macro(env, "components/phase_chantier.html", "phase_chantier", None)
    assert out.strip() == ""


def test_tableau_collections(env) -> None:
    ctx = {
        "sort": "modifie",
        "collections": [
            {
                "cote": "FA",
                "href": "/collection/FA",
                "titre": "Fonds A",
                "phase": "catalogage",
                "sous_collections": 4,
                "nb_items": 42,
                "nb_fichiers": 200,
                "repartition": {"valide": 10, "a_verifier": 5},
                "modifie_par": "Marie",
                "modifie_depuis": "il y a 2h",
            }
        ],
    }
    out = _render_macro(
        env, "components/tableau_collections.html", "tableau_collections", ctx
    )
    assert "FA" in out and "Fonds A" in out and "il y a 2h" in out


def test_tableau_items(env) -> None:
    ctx = {
        "colonnes": ["cote", "titre", "date", "etat", "fichiers", "modifie"],
        "sort": "cote",
        "items": [
            {
                "cote": "FA-001",
                "href": "/item/FA-001",
                "titre": "Notice un",
                "type_chaine": "Œuvres · Périodiques",
                "type_label": "Periodical issue",
                "date": "1924-01",
                "date_incertaine": False,
                "etat": "valide",
                "nb_fichiers": 12,
                "modifie_par": "Hugo",
                "modifie_depuis": "hier",
                "meta": {},
            }
        ],
        "pagination": {"page": 1, "per_page": 50, "total": 1, "pages": 1},
        "compteur_filtres": "aucun",
        "nb_colonnes_actives": 6,
    }
    out = _render_macro(env, "components/tableau_items.html", "tableau_items", ctx)
    assert "FA-001" in out and "Validé" in out


def test_tableau_items_date_none_pas_de_litteral(env) -> None:
    """Une date None doit afficher un placeholder, pas le mot 'None'."""
    ctx = {
        "colonnes": ["cote", "date"],
        "sort": "cote",
        "items": [
            {
                "cote": "X",
                "href": "/item/X",
                "titre": "x",
                "type_chaine": "",
                "type_label": "",
                "date": None,
                "date_incertaine": False,
                "etat": "valide",
                "nb_fichiers": 0,
                "modifie_par": "",
                "modifie_depuis": "",
                "meta": {},
            }
        ],
        "pagination": {"page": 1, "per_page": 10, "total": 1, "pages": 1},
        "compteur_filtres": "aucun",
        "nb_colonnes_actives": 2,
    }
    out = _render_macro(env, "components/tableau_items.html", "tableau_items", ctx)
    assert "None" not in out
    assert "—" in out


def test_bandeau_item(env) -> None:
    ctx = {
        "breadcrumb": [
            {"label": "Tableau de bord", "href": "/"},
            {"label": "FA", "href": "/collection/FA", "mono": True},
        ],
        "item": {
            "cote": "FA-001",
            "titre": "Notice un",
            "etat": "valide",
            "nb_fichiers": 12,
            "phase": "catalogage",
            "modifie_par": "Hugo",
            "modifie_depuis": "hier",
            "url_vue_fichiers": "/item/FA-001/fichiers",
            "url_precedent": "/item/FA-000",
            "url_suivant": "/item/FA-002",
        },
    }
    out = _render_macro(env, "components/bandeau_item.html", "bandeau_item", ctx)
    assert "FA-001" in out and "Notice un" in out and "Vue fichiers" in out


def test_panneau_fichiers(env) -> None:
    ctx = {
        "etat": "collapsed",
        "nb_fichiers": 3,
        "fichiers": [
            {
                "ordre": 1,
                "nom": "001.tif",
                "type": "couverture",
                "vignette_url": None,
                "courant": True,
                "href": "#",
            },
            {
                "ordre": 3,  # saut détecté entre 1 et 3
                "nom": "003.tif",
                "type": "page",
                "vignette_url": None,
                "courant": False,
                "href": "#",
            },
        ],
        "url_vue_fichiers": "/item/x/fichiers",
        "url_ajout": "/item/x/ajout",
    }
    out = _render_macro(
        env, "components/panneau_fichiers.html", "panneau_fichiers", ctx
    )
    assert 'data-state="collapsed"' in out
    assert "001.tif" in out
    assert "manque entre 1 et 3" in out


def test_panneau_colonnes(env) -> None:
    ctx = {
        "collection_cote": "FA",
        "actives": [{"key": "cote", "label": "Cote", "note": "colonne dédiée"}],
        "available_dedicated": [{"key": "doi_nakala", "label": "DOI Nakala"}],
        "available_meta": [{"key": "fascicule", "label": "Fascicule"}],
    }
    out = _render_macro(
        env, "components/panneau_colonnes.html", "panneau_colonnes", ctx
    )
    assert "Cote" in out and "DOI Nakala" in out and "Fascicule" in out


def test_cartouche_metadonnees(env) -> None:
    """Composition manuelle des sections (pattern documenté)."""
    template_str = """
    {% from 'components/cartouche_metadonnees.html' import
       cartouche_wrapper, section, ligne, valeur_mono, valeur_non_renseigne %}
    {% call cartouche_wrapper() %}
      {% call section("Identification", info="DC qualifié") %}
        {% call ligne("Cote", field="cote") %}{{ valeur_mono("FA-001") }}{% endcall %}
        {% call ligne("ARK") %}{{ valeur_non_renseigne() }}{% endcall %}
      {% endcall %}
    {% endcall %}
    """
    out = env.from_string(template_str).render()
    assert "Identification" in out and "FA-001" in out and "non renseigné" in out
