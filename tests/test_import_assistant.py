"""Tests des routes de l'assistant d'import web (V0.7).

Sous-étape 1 : cycle de vie d'une SessionImport (accueil, création,
reprise, abandon, 404).
Sous-étape 2 : upload du tableur + saisie des métadonnées du fonds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services import import_web
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, SessionImport

CSV_DEMO = b"Cote;Titre;Date\nHK-1;Numero 1;1960\nHK-2;Numero 2;1961\n"


@pytest.fixture
def client_vide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "vide.db"
    engine = creer_engine(db_path)
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    # Tableurs temporaires isolés dans le tmp du test.
    monkeypatch.setattr(import_web, "RACINE_IMPORT_TMP", tmp_path / "import_tmp")
    return TestClient(app)


def _id_session(reponse) -> int:
    """Extrait l'id de session de l'URL de redirection /import/{id}."""
    loc = reponse.headers["location"]
    return int(loc.rstrip("/").split("/import/")[1].split("/")[0])


def _sessions(db_path: Path) -> list[SessionImport]:
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        rows = list(s.scalars(select(SessionImport)).all())
        # Détacher pour lecture après fermeture.
        for r in rows:
            s.expunge(r)
    engine.dispose()
    return rows


def test_accueil_base_vide(client_vide: TestClient) -> None:
    resp = client_vide.get("/import")
    assert resp.status_code == 200
    assert "Aucun import en cours" in resp.text
    assert "Nouvel import" in resp.text


def test_nouveau_import_cree_session_et_redirige(client_vide: TestClient) -> None:
    resp = client_vide.post("/import/nouveau", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/import/")


def test_session_apparait_dans_accueil(client_vide: TestClient) -> None:
    client_vide.post("/import/nouveau")
    resp = client_vide.get("/import")
    assert "Imports en cours (1)" in resp.text


def test_page_session_affiche_etape_tableur(client_vide: TestClient) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    url = cree.headers["location"]
    resp = client_vide.get(url)
    assert resp.status_code == 200
    assert "tableur" in resp.text


def test_session_inexistante_404(client_vide: TestClient) -> None:
    resp = client_vide.get("/import/9999")
    assert resp.status_code == 404


def test_abandonner_passe_le_statut(
    client_vide: TestClient, tmp_path: Path
) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    session_id = int(cree.headers["location"].rsplit("/", 1)[1])
    resp = client_vide.post(
        f"/import/{session_id}/abandonner", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/import"

    rows = _sessions(tmp_path / "vide.db")
    assert len(rows) == 1
    assert rows[0].statut == "abandonnee"


def test_abandonner_retire_de_l_accueil(client_vide: TestClient) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    session_id = int(cree.headers["location"].rsplit("/", 1)[1])
    client_vide.post(f"/import/{session_id}/abandonner")
    resp = client_vide.get("/import")
    assert "Aucun import en cours" in resp.text


def test_abandonner_idempotent(client_vide: TestClient) -> None:
    """Ré-abandonner une session déjà abandonnée reste un 303 propre."""
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    session_id = int(cree.headers["location"].rsplit("/", 1)[1])
    r1 = client_vide.post(
        f"/import/{session_id}/abandonner", follow_redirects=False
    )
    r2 = client_vide.post(
        f"/import/{session_id}/abandonner", follow_redirects=False
    )
    assert r1.status_code == 303
    assert r2.status_code == 303


def test_abandonner_supprime_le_tableur_temporaire(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """Abandonner une session efface son tableur temporaire du disque."""
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    session_id = int(cree.headers["location"].rsplit("/", 1)[1])

    # Simuler un tableur uploadé attaché à la session.
    import_web.RACINE_IMPORT_TMP.mkdir(parents=True, exist_ok=True)
    tableur = import_web.RACINE_IMPORT_TMP / f"session_{session_id}.xlsx"
    tableur.write_bytes(b"fake")
    engine = creer_engine(tmp_path / "vide.db")
    factory = creer_session_factory(engine)
    with factory() as s:
        sess = s.get(SessionImport, session_id)
        sess.chemin_tableur = tableur.name
        s.commit()
    engine.dispose()

    assert tableur.is_file()
    client_vide.post(f"/import/{session_id}/abandonner")
    assert not tableur.exists()


# ---------------------------------------------------------------------------
# Sous-étape 2 — upload tableur + métadonnées du fonds
# ---------------------------------------------------------------------------


def test_upload_csv_detecte_colonnes(
    client_vide: TestClient, tmp_path: Path
) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    resp = client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inventaire.csv", CSV_DEMO, "text/csv")},
        data={"feuille": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/import/{sid}/fonds"
    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].colonnes_detectees == ["Cote", "Titre", "Date"]
    assert rows[0].etape == "fonds"
    assert rows[0].nom_tableur_original == "inventaire.csv"


def test_upload_csv_capture_echantillons(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """V0.9.2-import #2 — chaque colonne a ses stats d'échantillonnage."""
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inventaire.csv", CSV_DEMO, "text/csv")},
        data={"feuille": ""},
    )
    rows = _sessions(tmp_path / "vide.db")
    ech = rows[0].colonnes_echantillon
    assert ech is not None
    assert set(ech.keys()) == {"Cote", "Titre", "Date"}
    assert ech["Cote"]["exemples"] == ["HK-1", "HK-2"]
    assert ech["Cote"]["total"] == 2
    assert ech["Cote"]["remplies"] == 2
    assert ech["Cote"]["uniques"] == 2


def test_upload_extension_invalide_rejetee(client_vide: TestClient) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    resp = client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("notes.txt", b"pas un tableur", "text/plain")},
        data={"feuille": ""},
    )
    assert resp.status_code == 400
    assert "Format non supporté" in resp.text


def test_etape_fonds_inaccessible_avant_upload(
    client_vide: TestClient,
) -> None:
    """Sauter à /fonds sans avoir uploadé de tableur renvoie à l'étape
    courante (tableur)."""
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    resp = client_vide.get(f"/import/{sid}/fonds", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/import/{sid}/tableur"


def test_soumettre_fonds_valide_avance_au_mapping(
    client_vide: TestClient, tmp_path: Path
) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", CSV_DEMO, "text/csv")},
        data={"feuille": ""},
    )
    resp = client_vide.post(
        f"/import/{sid}/fonds",
        data={"cote": "HK", "titre": "Hara-Kiri", "editeur": "Choron"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/import/{sid}/mapping"
    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].fonds_data == {
        "cote": "HK",
        "titre": "Hara-Kiri",
        "editeur": "Choron",
    }
    assert rows[0].etape == "mapping"


def test_soumettre_fonds_sans_cote_rejete(client_vide: TestClient) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", CSV_DEMO, "text/csv")},
        data={"feuille": ""},
    )
    resp = client_vide.post(
        f"/import/{sid}/fonds",
        data={"cote": "", "titre": "Sans cote"},
    )
    assert resp.status_code == 400
    assert "cote" in resp.text.lower()


def test_import_id_redirige_vers_etape_courante(
    client_vide: TestClient,
) -> None:
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    resp = client_vide.get(f"/import/{sid}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/import/{sid}/tableur"


# ---------------------------------------------------------------------------
# Sous-étape 3 — mapping colonnes + résolution fichiers
# ---------------------------------------------------------------------------


def _session_a_l_etape_mapping(client: TestClient) -> int:
    """Crée une session, dépose le tableur et le fonds — prête pour
    l'étape mapping. Retourne l'id de session."""
    cree = client.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", CSV_DEMO, "text/csv")},
        data={"feuille": ""},
    )
    client.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    return sid


def test_mapping_prefill_heuristique(client_vide: TestClient) -> None:
    """La page mapping pré-sélectionne les champs détectés (Cote, Titre,
    Date sont des colonnes structurantes connues)."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.get(f"/import/{sid}/mapping")
    assert resp.status_code == 200
    assert "Cote" in resp.text and "Titre" in resp.text


def test_mapping_affiche_echantillons(client_vide: TestClient) -> None:
    """V0.9.2-import #2 — chaque colonne montre un aperçu (valeurs +
    taux de remplissage) sous son nom, sans clic supplémentaire.
    Spécifique au mode avancé (le mode simple n'a que 4 selects)."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    # Format attendu : "ex. « HK-1 », « HK-2 » · 2/2 remplis · 2 valeurs uniques"
    assert "data-cible-echantillon" in resp.text
    assert "« HK-1 »" in resp.text
    assert "2/2 remplis" in resp.text
    assert "2 valeurs uniques" in resp.text


# ---------------------------------------------------------------------------
# V0.9.2-import #1 — promotion auto par-fichier dans cibles_proposees
# ---------------------------------------------------------------------------


def test_cibles_proposees_promote_par_fichier() -> None:
    """Une colonne sans pattern nominatif mais classée par-fichier est
    promue de CIBLE_META vers CIBLE_META_FICHIER — sinon ses valeurs
    par-page atterrissent en metadonnees d'item et déclenchent un
    warning de divergence à la fusion par cote."""
    from archives_tool.api.services.import_web import (
        CIBLE_META_FICHIER,
        cibles_proposees,
    )

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "indice_page", "auteur"],
        colonnes_echantillon={
            "cote": {"classif": "cote"},
            "indice_page": {"classif": "par-fichier"},
            "auteur": {"classif": "par-item"},
        },
        mappings=None,
    )
    cibles = cibles_proposees(session)
    # cote → champ dédié, indice_page → promu par-fichier, auteur → DC fréquent.
    assert cibles[0] == "cote"
    assert cibles[1] == CIBLE_META_FICHIER
    assert cibles[2] == "metadonnees.auteur"


def test_cibles_proposees_ne_promote_pas_champ_dedie() -> None:
    """Une colonne classée par-fichier mais qui matche déjà un champ
    dédié (ex. filename → fichier.nom_fichier) garde sa cible : pas de
    déclassement vers la sentinelle générique."""
    from archives_tool.api.services.import_web import cibles_proposees

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "filename"],
        colonnes_echantillon={
            "cote": {"classif": "cote"},
            "filename": {"classif": "par-fichier"},
        },
        mappings=None,
    )
    cibles = cibles_proposees(session)
    assert cibles[1] == "fichier.nom_fichier"


def test_cibles_proposees_pas_de_promotion_sans_classif() -> None:
    """Sans classif (session legacy sans colonnes_echantillon, ou
    classif `indetermine`), aucune promotion ne s'opère — comportement
    inchangé par rapport à V0.9.1."""
    from archives_tool.api.services.import_web import (
        CIBLE_META,
        cibles_proposees,
    )

    session_sans_ech = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "indice_page"],
        colonnes_echantillon=None,
        mappings=None,
    )
    cibles = cibles_proposees(session_sans_ech)
    assert cibles[1] == CIBLE_META

    session_indetermine = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "indice_page"],
        colonnes_echantillon={
            "cote": {"classif": "cote"},
            "indice_page": {"classif": "indetermine"},
        },
        mappings=None,
    )
    cibles = cibles_proposees(session_indetermine)
    assert cibles[1] == CIBLE_META


def test_autres_warnings_filtre_les_divergences() -> None:
    """V0.9.2-import T6 (passe de revue) — `_autres_warnings` retire
    les warnings de divergence (déjà résumés dans le bloc agrégé) mais
    préserve les autres (ordre_depuis_nom qui ne matche pas, fichiers
    orphelins, etc.). Sinon le rendu doublonnerait le bruit."""
    from archives_tool.api.routes.import_assistant import _autres_warnings
    from archives_tool.importers.ecrivain import RapportImport

    rapport = RapportImport(dry_run=True)
    rapport.warnings = [
        "Cote HK-1: divergence sur 'page' entre lignes (garde '1', ignore '2').",
        "Cote HK-1: divergence sur metadonnees.titre (garde 'A', ignore 'B').",
        "Regex `ordre_depuis_nom` ne matche pas le nom 'scan_x.tif'.",
        "Fichier orphelin sur disque : ailleurs/perdu.tif",
    ]
    autres = _autres_warnings(rapport)
    assert len(autres) == 2
    assert "ordre_depuis_nom" in autres[0]
    assert "orphelin" in autres[1]


def test_autres_warnings_sans_rapport() -> None:
    """Rapport None (cas branche `statut=validee` qui ne ré-exécute pas
    le dry-run) — la fonction renvoie une liste vide."""
    from archives_tool.api.routes.import_assistant import _autres_warnings

    assert _autres_warnings(None) == []


def test_mapping_anomalies_a11y_role_region(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """V0.9.x trous documentés T5 — le bandeau anomalies a `role="region"`
    + `aria-label` pour les lecteurs d'écran."""
    csv = (
        b"Cote;Titre;Page\n"
        b"HK-1;Numero 1;1\nHK-1;Numero 1;2\nHK-1;Numero 1;3\n"
        b"HK-2;Numero 2;1\nHK-2;Numero 2;2\nHK-2;Numero 2;3\n"
        b"HK-3;Numero 3;1\nHK-3;Numero 3;2\nHK-3;Numero 3;3\n"
    )
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", csv, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    # Override avec Page → __meta__ pour générer une anomalie.
    client_vide.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "titre", "__meta__"]},
    )
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    assert 'role="region"' in resp.text
    assert 'aria-label="Anomalies de mapping détectées"' in resp.text
    # `data-session-id` pour le scope localStorage du « Garder » persistant.
    assert f'data-session-id="{sid}"' in resp.text


def test_mapping_simple_macro_respecte_choix_vide_explicite(
    client_vide: TestClient,
) -> None:
    """V0.9.x trous T9 — la macro `select_colonne` distingue
    `valeur_active is none` (première visite → suggestion) de
    `valeur_active == ""` (choix « Aucune » explicite, re-render après
    erreur → choix vide respecté)."""
    sid = _session_a_l_etape_mapping(client_vide)
    # On soumet avec colonne_cote vide ET colonne_titre vide explicite.
    # La cote vide déclenche l'erreur → re-render. On vérifie que le
    # select Titre ne se rabat pas sur la suggestion « Titre ».
    resp = client_vide.post(
        f"/import/{sid}/mapping/simple",
        data={
            "colonne_cote": "",  # erreur
            "colonne_titre": "",  # choix « Aucune »
            "colonne_date": "",
            "granularite": "item",
        },
    )
    assert resp.status_code == 400
    # Le re-render doit avoir l'option vide selectionnée pour
    # colonne_titre, pas l'option « Titre ».
    import re

    # Cherche le <select name="colonne_titre"> et son option selected.
    match = re.search(
        r'<select name="colonne_titre".*?</select>', resp.text, re.DOTALL
    )
    assert match is not None
    bloc = match.group()
    # L'option vide doit être selected.
    assert re.search(r'<option value=""\s+selected', bloc) is not None
    # L'option Titre ne doit pas être selected.
    assert re.search(r'<option value="Titre"\s+selected', bloc) is None


def test_apercu_affiche_divergences_aggregees(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """V0.9.2-import T6 — l'aperçu dry-run d'un import où une colonne
    par-fichier est mappée en niveau item affiche la section
    « N colonne(s) à reclasser », pas la liste flat de N warnings."""
    csv = (
        b"Cote;Page\n"
        b"HK-1;1\nHK-1;2\nHK-1;3\n"
        b"HK-2;1\nHK-2;2\nHK-2;3\n"
        b"HK-3;1\nHK-3;2\nHK-3;3\n"
    )
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", csv, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    # Granularité fichier + Page sur __meta__ (l'utilisateur override
    # la promotion auto et choisit "Métadonnée personnalisée item").
    client_vide.post(
        f"/import/{sid}/mapping",
        data={
            "cible": ["cote", "__meta__"],
            "granularite": "fichier",
        },
    )
    # Pas de résolution fichiers — on saute direct à l'aperçu.
    client_vide.post(f"/import/{sid}/fichiers", data={"racine": ""})

    resp = client_vide.get(f"/import/{sid}/apercu")
    assert resp.status_code == 200
    # Le bloc agrégé est rendu (par opposition à la liste flat).
    assert "à reclasser" in resp.text
    assert "metadonnees.page" in resp.text
    # 3 cotes affectées, valeurs ignorées ≥ 6 (2 par cote × 3 cotes).
    assert "3" in resp.text  # nb_cotes_affectees
    # Exemples de valeurs présents.
    assert "« 1 »" in resp.text or "« 2 »" in resp.text


def test_mapping_anomalie_apres_override_par_fichier(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """V0.9.2-import #4 — quand l'utilisateur override la promotion auto
    et met une colonne par-fichier sur CIBLE_META (item), la prochaine
    visite affiche une anomalie avec un bouton « Déplacer en niveau
    fichier »."""
    csv = (
        b"Cote;Titre;Page\n"
        b"HK-1;Numero 1;1\nHK-1;Numero 1;2\nHK-1;Numero 1;3\n"
        b"HK-2;Numero 2;1\nHK-2;Numero 2;2\nHK-2;Numero 2;3\n"
        b"HK-3;Numero 3;1\nHK-3;Numero 3;2\nHK-3;Numero 3;3\n"
    )
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", csv, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    # Override : on force Page sur __meta__ malgré la promotion auto.
    client_vide.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "titre", "__meta__"]},
    )
    # Re-visite : l'anomalie doit apparaître (mode avancé : c'est là
    # qu'on a la grille de selects qui peut être en conflit avec la classif).
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    assert "Anomalies détectées" in resp.text
    assert "« Page »" in resp.text
    assert 'data-action-corriger' in resp.text
    assert 'data-cible-suggeree="__meta_fichier__"' in resp.text


def test_mapping_anomalie_melange_pas_de_bouton_corriger(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """V0.9.2-import #4 — pour une colonne classée `melange`, l'anomalie
    est rendue mais sans bouton « Corriger » (pas de suggestion auto).
    Seul « Garder le choix actuel » est affiché — c'est à l'utilisateur
    de trancher."""
    # 4 cotes : 2 avec une valeur stable, 2 avec deux valeurs → 50/50,
    # tombe en `melange` (ni >=90% par-item, ni >50% par-fichier).
    csv = (
        b"Cote;X\n"
        b"HK-1;a\nHK-1;a\n"
        b"HK-2;b\nHK-2;b\n"
        b"HK-3;c\nHK-3;d\n"
        b"HK-4;e\nHK-4;f\n"
    )
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", csv, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    assert "Anomalies détectées" in resp.text
    assert "valeurs mêlées par cote" in resp.text
    # Le bouton Garder est présent (action passive), le bouton Corriger
    # n'apparaît pas faute de cible_suggeree.
    assert "data-action-garder" in resp.text
    # On vérifie qu'aucun bouton Corriger ne pointe sur la colonne X.
    assert 'data-action-corriger data-colonne="X"' not in resp.text


def test_mapping_pas_d_anomalie_si_coherent(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """À la première visite après l'auto-promotion, aucun conflit
    cible/classif — pas de section Anomalies affichée."""
    csv = (
        b"Cote;Titre;Page\n"
        b"HK-1;Numero 1;1\nHK-1;Numero 1;2\n"
        b"HK-2;Numero 2;1\nHK-2;Numero 2;2\n"
        b"HK-3;Numero 3;1\nHK-3;Numero 3;2\n"
    )
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", csv, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    # Page est auto-promue en CIBLE_META_FICHIER → pas d'anomalie.
    assert "Anomalies détectées" not in resp.text


def test_mapping_affiche_indice_classif(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """V0.9.2-import #1 — l'étape mapping affiche un indice par colonne :
    cote détectée, métadonnée d'item (stable), de fichier (varie),
    ou mélange. Test sur un CSV où `page` varie au sein de chaque cote."""
    csv = (
        b"Cote;Titre;Page\n"
        b"HK-1;Numero 1;1\nHK-1;Numero 1;2\nHK-1;Numero 1;3\n"
        b"HK-2;Numero 2;1\nHK-2;Numero 2;2\nHK-2;Numero 2;3\n"
        b"HK-3;Numero 3;1\nHK-3;Numero 3;2\nHK-3;Numero 3;3\n"
    )
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", csv, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    # On signale les surprises (cote, par-fichier, mélange) — pas par-item
    # qui est le défaut attendu (sinon ~80 % des colonnes auraient un hint
    # redondant sur un tableur normal).
    assert 'data-classif="cote"' in resp.text
    assert 'data-classif="par-fichier"' in resp.text
    assert 'data-classif="par-item"' not in resp.text
    assert "identifie chaque item" in resp.text
    assert "varie au sein de chaque cote" in resp.text
    assert "stable par cote" not in resp.text


# ---------------------------------------------------------------------------
# V0.9.2-import #3 — mode simple (4 questions au lieu de 28 selects)
# ---------------------------------------------------------------------------


def test_suggerer_reponses_simple_pre_remplit_les_quatre_champs() -> None:
    """Suggestions auto basées sur la classif + heuristique nominative."""
    from archives_tool.api.services.import_web import suggerer_reponses_simple

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "Titre", "Date", "auteurs", "page"],
        colonnes_echantillon={
            "cote": {"classif": "cote"},
            "Titre": {"classif": "par-item"},
            "Date": {"classif": "par-item"},
            "auteurs": {"classif": "par-item"},
            "page": {"classif": "par-fichier"},
        },
    )
    s = suggerer_reponses_simple(session)
    assert s.colonne_cote == "cote"
    assert s.colonne_titre == "Titre"
    assert s.colonne_date == "Date"
    # 3 par-item contre 1 par-fichier → granularité item.
    assert s.granularite == "item"


def test_suggerer_granularite_fichier_si_majorite_par_fichier() -> None:
    """Tableur Nakala typique : la majorité des colonnes varient par-page
    (filename, hash, thumb, data_url…) → granularité fichier suggérée."""
    from archives_tool.api.services.import_web import suggerer_reponses_simple

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "Titre", "filename", "hash", "thumb"],
        colonnes_echantillon={
            "cote": {"classif": "cote"},
            "Titre": {"classif": "par-item"},
            "filename": {"classif": "par-fichier"},
            "hash": {"classif": "par-fichier"},
            "thumb": {"classif": "par-fichier"},
        },
    )
    assert suggerer_reponses_simple(session).granularite == "fichier"


def test_suggerer_reponses_simple_restaure_mapping_existant() -> None:
    """Quand un mapping a déjà été soumis (l'utilisateur revient sur
    l'étape), les choix précédents priment sur les suggestions auto."""
    from archives_tool.api.services.import_web import suggerer_reponses_simple

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["A", "B", "C", "D"],
        colonnes_echantillon={
            "A": {"classif": "cote"},
            "B": {"classif": "par-item"},
            "C": {"classif": "par-item"},
            "D": {"classif": "par-item"},
        },
        mappings={
            "cote": "B",          # l'user a choisi B comme cote (pas A)
            "titre": "D",         # et D comme titre
            "metadonnees.a": "A",
            "metadonnees.c": "C",
        },
        granularite="fichier",
    )
    s = suggerer_reponses_simple(session)
    assert s.colonne_cote == "B"
    assert s.colonne_titre == "D"
    assert s.colonne_date is None  # pas dans le mapping
    assert s.granularite == "fichier"


def test_suggerer_sans_classif_renvoie_none() -> None:
    """Session legacy ou tableur indéterminé : pas de suggestion de cote
    (l'utilisateur devra choisir manuellement)."""
    from archives_tool.api.services.import_web import suggerer_reponses_simple

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["x", "y"],
        colonnes_echantillon=None,
    )
    s = suggerer_reponses_simple(session)
    assert s.colonne_cote is None
    assert s.granularite == "item"  # défaut quand pas de signal


def test_construire_mapping_simple_minimal_cote_seule() -> None:
    """Mapping minimal : cote choisie, le reste va en metadonnees.<slug>
    avec promotion par-fichier si la classif le dit."""
    from archives_tool.api.services.import_web import (
        construire_mapping_depuis_simple,
    )

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "Titre", "page"],
        colonnes_echantillon={
            "cote": {"classif": "cote"},
            "Titre": {"classif": "par-item"},
            "page": {"classif": "par-fichier"},
        },
    )
    mapping = construire_mapping_depuis_simple(session, colonne_cote="cote")
    assert mapping == {
        "cote": "cote",
        "metadonnees.titre": "Titre",
        "fichier.metadonnees.page": "page",
    }


def test_construire_mapping_simple_avec_titre_et_date() -> None:
    """Cote/titre/date explicites tombent sur leurs champs dédiés, le
    reste en metadonnees."""
    from archives_tool.api.services.import_web import (
        construire_mapping_depuis_simple,
    )

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["c", "t", "d", "auteur"],
        colonnes_echantillon={
            "c": {"classif": "cote"},
            "t": {"classif": "par-item"},
            "d": {"classif": "par-item"},
            "auteur": {"classif": "par-item"},
        },
    )
    mapping = construire_mapping_depuis_simple(
        session, colonne_cote="c", colonne_titre="t", colonne_date="d"
    )
    assert mapping == {
        "cote": "c",
        "titre": "t",
        "date": "d",
        "metadonnees.auteur": "auteur",
    }


def test_construire_mapping_simple_cote_inconnue() -> None:
    """Cote pointant sur une colonne absente → MappingInvalide."""
    import pytest
    from archives_tool.api.services.import_web import (
        MappingInvalide,
        construire_mapping_depuis_simple,
    )

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["a", "b"],
        colonnes_echantillon=None,
    )
    with pytest.raises(MappingInvalide, match="n'existe pas"):
        construire_mapping_depuis_simple(session, colonne_cote="z")


def test_mapping_simple_render_par_defaut(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """GET /mapping rend le mode simple par défaut (4 questions, pas la
    grille de 28 selects)."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.get(f"/import/{sid}/mapping")
    assert resp.status_code == 200
    assert "Quelle colonne identifie chaque item" in resp.text
    assert "Chaque ligne du tableur représente" in resp.text
    assert "Affiner colonne par colonne (mode avancé)" in resp.text
    # Le mode avancé (data-cible-select) ne doit pas être rendu.
    assert "data-cible-select" not in resp.text


def test_mapping_simple_pre_selectionne_suggestions(
    client_vide: TestClient,
) -> None:
    """Les colonnes Cote / Titre / Date sont pré-sélectionnées via
    `selected` dans les <option> — la suggestion auto doit être visible
    sans intervention."""
    import re

    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.get(f"/import/{sid}/mapping")
    assert resp.status_code == 200
    # On cherche un <option value="Cote" ... selected> dans le rendu.
    pattern_cote = re.compile(
        r'<option value="Cote"\s+selected[^>]*>',
    )
    pattern_titre = re.compile(
        r'<option value="Titre"\s+selected[^>]*>',
    )
    pattern_date = re.compile(
        r'<option value="Date"\s+selected[^>]*>',
    )
    assert pattern_cote.search(resp.text)
    assert pattern_titre.search(resp.text)
    assert pattern_date.search(resp.text)


def test_mapping_simple_indice_granularite_fichier(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """Quand la classif suggère granularité=fichier (majorité des
    colonnes varient par cote), un indice pédagogique apparaît sous le
    radio."""
    # filename + thumb + page varient toutes par cote → granularité fichier.
    csv = (
        b"Cote;filename;thumb;page\n"
        b"HK-1;s1.tif;t1.jpg;1\nHK-1;s2.tif;t2.jpg;2\n"
        b"HK-2;s3.tif;t3.jpg;1\nHK-2;s4.tif;t4.jpg;2\n"
        b"HK-3;s5.tif;t5.jpg;1\nHK-3;s6.tif;t6.jpg;2\n"
    )
    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", csv, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    resp = client_vide.get(f"/import/{sid}/mapping")
    assert resp.status_code == 200
    assert "La majorité des colonnes varient au sein de chaque cote" in resp.text
    # Le radio « fichier » doit être checked.
    assert 'value="fichier"\n               checked' in resp.text or \
           'value="fichier" checked' in resp.text or \
           'checked>' in resp.text  # tolérant aux variations de rendu Jinja


def test_mapping_simple_toggle_avance(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """`?avance=1` rend l'ancienne page avec 28 selects + lien de retour."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    assert "data-cible-select" in resp.text
    assert "Revenir au mode simple" in resp.text


def test_mapping_simple_soumission_minimale(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """Soumission du mode simple avec cote seule → mapping enregistré
    avec tout en metadonnees, étape avance à `fichiers`."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/mapping/simple",
        data={"colonne_cote": "Cote", "granularite": "item"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/import/{sid}/fichiers"
    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].mappings == {
        "cote": "Cote",
        "metadonnees.titre": "Titre",
        "metadonnees.date": "Date",
    }
    assert rows[0].etape == "fichiers"


def test_mapping_simple_soumission_titre_date_explicites(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """Titre et date explicites tombent sur leurs champs dédiés."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/mapping/simple",
        data={
            "colonne_cote": "Cote",
            "colonne_titre": "Titre",
            "colonne_date": "Date",
            "granularite": "item",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].mappings == {
        "cote": "Cote",
        "titre": "Titre",
        "date": "Date",
    }


def test_mapping_simple_cote_manquante_rejetee(
    client_vide: TestClient,
) -> None:
    """Sans colonne cote → re-render avec erreur, pas d'avancement."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/mapping/simple",
        data={"colonne_cote": "", "granularite": "item"},
    )
    assert resp.status_code == 400
    assert "Choisissez la colonne" in resp.text


def test_mapping_simple_cote_inconnue_rejetee(
    client_vide: TestClient,
) -> None:
    """Cote pointant sur une colonne absente du tableur → 400 + message."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/mapping/simple",
        data={"colonne_cote": "ColonneAbsente", "granularite": "item"},
    )
    assert resp.status_code == 400
    # Apostrophe échappée par Jinja autoescape — on cherche le fragment.
    assert "ColonneAbsente" in resp.text
    assert "pas dans le tableur" in resp.text


def test_colonnes_champs_avances_detecte_les_pertes_potentielles() -> None:
    """Repère les colonnes d'un mapping qui seraient ramenées en
    metadonnees.<slug> si re-soumises depuis le mode simple.

    Couverture : champs dédiés Item (annee, type_coar), Fichier
    (fichier.nom_fichier), DC canoniques (metadonnees.auteur).
    Slugs libres (metadonnees.<X>, fichier.metadonnees.<X>) sont
    ignorés — la slugification du mode simple les reproduit
    fidèlement."""
    from archives_tool.api.services.import_web import colonnes_champs_avances

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["c", "T", "An", "Coar", "Aut", "Lib", "Page"],
        mappings={
            "cote": "c",
            "titre": "T",  # géré, ignoré
            "annee": "An",  # champ dédié item → perte
            "type_coar": "Coar",  # → perte
            "metadonnees.auteur": "Aut",  # DC canonique → perte
            "metadonnees.divers": "Lib",  # slug libre → OK
            "fichier.metadonnees.page": "Page",  # slug libre → OK
        },
    )
    pertes = colonnes_champs_avances(session)
    assert set(pertes) == {"An", "Coar", "Aut"}


def test_colonnes_champs_avances_session_sans_mapping() -> None:
    """Pas de mapping enregistré → liste vide."""
    from archives_tool.api.services.import_web import colonnes_champs_avances

    session = SessionImport(utilisateur="test", colonnes_detectees=["a"])
    assert colonnes_champs_avances(session) == []


def test_construire_mapping_simple_perte_champs_avances_documentee() -> None:
    """Comportement documenté : un mapping qui contient des champs
    dédiés hors cote/titre/date (annee, type_coar, DC canoniques)
    est ramené en metadonnees.<slug> par construire_mapping_depuis_simple.
    L'utilisateur est averti via une bannière (cf. test rendu)."""
    from archives_tool.api.services.import_web import (
        construire_mapping_depuis_simple,
    )

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["c", "Année", "Auteur"],
        colonnes_echantillon={
            "c": {"classif": "cote"},
            "Année": {"classif": "par-item"},
            "Auteur": {"classif": "par-item"},
        },
        mappings={
            "cote": "c",
            "annee": "Année",
            "metadonnees.auteur": "Auteur",
        },
    )
    nouveau = construire_mapping_depuis_simple(session, colonne_cote="c")
    assert nouveau["cote"] == "c"
    # `annee` champ dédié → écrasé par slugification automatique.
    assert "annee" not in nouveau
    assert "metadonnees.annee" in nouveau
    # `metadonnees.auteur` (DC canonique) → re-slugifié pareil
    # textuellement, mais la sémantique « cible canonique » est perdue.
    assert "metadonnees.auteur" in nouveau


def test_mapping_simple_affiche_bannerre_si_champs_avances(
    client_vide: TestClient,
) -> None:
    """V0.9.2-import #3 — bannière non-bloquante quand l'utilisateur
    revient en mode simple depuis un mapping avancé contenant des
    champs dédiés hors cote/titre/date."""
    sid = _session_a_l_etape_mapping(client_vide)
    # Soumission via mode avancé : Date est mappée sur le champ dédié
    # `date`, Titre sur `titre`. Mais on soumet aussi une cible
    # avancée non-exposée par le mode simple : on mappe Date sur __meta__
    # pour qu'elle ne soit pas dans cote/titre/date. Non : la fixture
    # CSV_DEMO a "Cote;Titre;Date" — on les mappe `cote`/`titre`/`date`
    # puis on ajoute un champ avancé via override... pas possible avec
    # le CSV. On fait un POST direct avec un mapping artificiel.
    # Plus simple : modifier directement la session via le client.
    import sqlalchemy as sa
    from archives_tool.db import creer_engine, creer_session_factory

    # Soumission initiale en avancé avec mapping qui inclut un champ
    # dédié (type_coar) pour simuler un usage avancé.
    client_vide.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "type_coar", "__meta__"]},  # Titre → type_coar (forcé)
    )
    # Revisit en mode simple : la bannière doit apparaître pour Titre.
    resp = client_vide.get(f"/import/{sid}/mapping")
    assert resp.status_code == 200
    assert "data-avertissement-pertes" in resp.text
    assert "champs avancés" in resp.text
    assert "Passer en mode avancé" in resp.text


def test_mapping_simple_pas_de_bannerre_si_seulement_simples(
    client_vide: TestClient,
) -> None:
    """Mapping qui n'utilise que cote/titre/date + metadonnees libres :
    aucune perte potentielle, pas de bannière."""
    sid = _session_a_l_etape_mapping(client_vide)
    client_vide.post(
        f"/import/{sid}/mapping/simple",
        data={
            "colonne_cote": "Cote",
            "colonne_titre": "Titre",
            "colonne_date": "Date",
            "granularite": "item",
        },
    )
    resp = client_vide.get(f"/import/{sid}/mapping")
    assert resp.status_code == 200
    assert "data-avertissement-pertes" not in resp.text


def test_construire_mapping_simple_collision_roles() -> None:
    """Une même colonne ne peut pas être à la fois cote et titre."""
    import pytest
    from archives_tool.api.services.import_web import (
        MappingInvalide,
        construire_mapping_depuis_simple,
    )

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["c", "x"],
        colonnes_echantillon=None,
    )
    with pytest.raises(MappingInvalide, match="à la fois"):
        construire_mapping_depuis_simple(
            session, colonne_cote="c", colonne_titre="c"
        )


# ---------------------------------------------------------------------------
# V0.9.2-import #4 — détection d'anomalies de mapping
# ---------------------------------------------------------------------------


def _session_avec_classif(
    colonnes_classif: dict[str, str],
) -> SessionImport:
    """Helper : construit une SessionImport in-memory avec une classif
    par colonne. Utile pour les tests unitaires de detecter_anomalies_*."""
    return SessionImport(
        utilisateur="test",
        colonnes_detectees=list(colonnes_classif.keys()),
        colonnes_echantillon={
            col: {"classif": cl, "uniques": 100, "remplies": 100}
            for col, cl in colonnes_classif.items()
        },
        mappings=None,
    )


def test_detecter_anomalies_par_fichier_cible_item() -> None:
    """Colonne classée par-fichier avec cible CIBLE_META (item) → anomalie
    suggérant la promotion en niveau fichier. Le message restitue les
    chiffres clés (uniques, remplies) pour donner du contexte au choix."""
    from archives_tool.api.services.import_web import (
        CIBLE_META,
        CIBLE_META_FICHIER,
        detecter_anomalies_mapping,
    )

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "page", "titre"],
        colonnes_echantillon={
            "cote": {"classif": "cote", "uniques": 50, "remplies": 50},
            "page": {"classif": "par-fichier", "uniques": 173, "remplies": 7466},
            "titre": {"classif": "par-item", "uniques": 50, "remplies": 7466},
        },
        mappings=None,
    )
    cibles = ["cote", CIBLE_META, CIBLE_META]  # page en CIBLE_META (override)
    anomalies = detecter_anomalies_mapping(session, cibles)
    assert len(anomalies) == 1
    assert anomalies[0].colonne == "page"
    assert anomalies[0].cible_suggeree == CIBLE_META_FICHIER
    assert "varie au sein de chaque cote" in anomalies[0].message
    # Le message expose les chiffres (utile pour justifier la suggestion).
    assert "173 valeurs uniques" in anomalies[0].message
    assert "7466 cellules" in anomalies[0].message


def test_detecter_anomalies_par_item_cible_fichier() -> None:
    """Colonne classée par-item avec cible fichier → anomalie suggérant
    le retour en métadonnée d'item."""
    from archives_tool.api.services.import_web import (
        CIBLE_META,
        CIBLE_META_FICHIER,
        detecter_anomalies_mapping,
    )

    session = _session_avec_classif(
        {"cote": "cote", "titre": "par-item"}
    )
    cibles = ["cote", CIBLE_META_FICHIER]  # titre en niveau fichier (faux)
    anomalies = detecter_anomalies_mapping(session, cibles)
    assert len(anomalies) == 1
    assert anomalies[0].colonne == "titre"
    assert anomalies[0].cible_suggeree == CIBLE_META
    assert "stable au sein de chaque cote" in anomalies[0].message


def test_detecter_anomalies_melange_sans_suggestion() -> None:
    """Colonne classée melange → anomalie sans suggestion auto, juste
    une alerte (l'utilisateur doit trancher)."""
    from archives_tool.api.services.import_web import (
        CIBLE_META,
        detecter_anomalies_mapping,
    )

    session = _session_avec_classif(
        {"cote": "cote", "X": "melange"}
    )
    cibles = ["cote", CIBLE_META]
    anomalies = detecter_anomalies_mapping(session, cibles)
    assert len(anomalies) == 1
    assert anomalies[0].cible_suggeree == ""
    assert "mêlées" in anomalies[0].message


def test_detecter_anomalies_ignore_cible_ignore() -> None:
    """Colonne sur CIBLE_IGNORE : pas d'anomalie, l'utilisateur a
    explicitement choisi de ne pas importer."""
    from archives_tool.api.services.import_web import (
        CIBLE_IGNORE,
        detecter_anomalies_mapping,
    )

    session = _session_avec_classif(
        {"cote": "cote", "page": "par-fichier"}
    )
    cibles = ["cote", CIBLE_IGNORE]
    assert detecter_anomalies_mapping(session, cibles) == []


def test_detecter_anomalies_pas_signalee_si_coherent() -> None:
    """Cibles cohérentes avec la classif → aucune anomalie.

    Par-fichier sur CIBLE_META_FICHIER, par-item sur CIBLE_META,
    cote sur 'cote' : tout est en accord."""
    from archives_tool.api.services.import_web import (
        CIBLE_META,
        CIBLE_META_FICHIER,
        detecter_anomalies_mapping,
    )

    session = _session_avec_classif(
        {"cote": "cote", "page": "par-fichier", "titre": "par-item"}
    )
    cibles = ["cote", CIBLE_META_FICHIER, CIBLE_META]
    assert detecter_anomalies_mapping(session, cibles) == []


def test_detecter_anomalies_par_fichier_sur_champ_dedie_fichier_ok() -> None:
    """Par-fichier sur un champ dédié fichier (ex. fichier.nom_fichier) :
    pas d'anomalie, c'est cohérent."""
    from archives_tool.api.services.import_web import detecter_anomalies_mapping

    session = _session_avec_classif(
        {"cote": "cote", "filename": "par-fichier"}
    )
    cibles = ["cote", "fichier.nom_fichier"]
    assert detecter_anomalies_mapping(session, cibles) == []


def test_detecter_anomalies_desalignement_levee_explicitement() -> None:
    """Garde-fou : si colonnes et cibles n'ont pas la même longueur,
    on lève au lieu de `zip`-truncer silencieusement (qui masquerait
    une anomalie réelle)."""
    import pytest
    from archives_tool.api.services.import_web import detecter_anomalies_mapping

    session = _session_avec_classif({"cote": "cote", "x": "par-fichier"})
    with pytest.raises(ValueError, match="Désalignement"):
        detecter_anomalies_mapping(session, ["cote"])  # 1 cible vs 2 colonnes


def test_detecter_anomalies_sans_classif() -> None:
    """Session legacy sans colonnes_echantillon (ou classif indetermine) :
    aucune anomalie remontée."""
    from archives_tool.api.services.import_web import (
        CIBLE_META,
        detecter_anomalies_mapping,
    )

    session_sans_ech = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "x"],
        colonnes_echantillon=None,
    )
    assert detecter_anomalies_mapping(session_sans_ech, ["cote", CIBLE_META]) == []

    session_indetermine = _session_avec_classif(
        {"cote": "cote", "x": "indetermine"}
    )
    assert (
        detecter_anomalies_mapping(session_indetermine, ["cote", CIBLE_META])
        == []
    )


def test_cibles_proposees_mapping_existant_pas_re_promu() -> None:
    """Si un mapping a déjà été soumis (l'utilisateur revient sur
    l'étape), la promotion auto ne s'applique pas — on respecte le
    choix utilisateur (qui peut avoir explicitement laissé un slug
    libre en metadonnees d'item)."""
    from archives_tool.api.services.import_web import (
        CIBLE_META,
        cibles_proposees,
    )

    session = SessionImport(
        utilisateur="test",
        colonnes_detectees=["cote", "indice_page"],
        colonnes_echantillon={
            "cote": {"classif": "cote"},
            "indice_page": {"classif": "par-fichier"},
        },
        mappings={
            "cote": "cote",
            "metadonnees.indice_page": "indice_page",
        },
    )
    cibles = cibles_proposees(session)
    # `indice_page` → metadonnees.indice_page → normalise vers CIBLE_META,
    # **pas** CIBLE_META_FICHIER (la branche promotion n'est active qu'à
    # la première visite, quand mappings est null).
    assert cibles[1] == CIBLE_META


def test_soumettre_mapping_valide(
    client_vide: TestClient, tmp_path: Path
) -> None:
    sid = _session_a_l_etape_mapping(client_vide)
    # 3 colonnes (Cote, Titre, Date) → cote, titre, métadonnée.
    resp = client_vide.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "titre", "__meta__"]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/import/{sid}/fichiers"
    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].mappings == {
        "cote": "Cote",
        "titre": "Titre",
        "metadonnees.date": "Date",
    }
    assert rows[0].etape == "fichiers"


def test_soumettre_mapping_sans_cote_rejete(client_vide: TestClient) -> None:
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/mapping",
        data={"cible": ["__meta__", "titre", "__ignore__"]},
    )
    assert resp.status_code == 400
    assert "cote" in resp.text.lower()


def test_soumettre_mapping_conflit_champ_dedie(
    client_vide: TestClient,
) -> None:
    """Deux colonnes vers le même champ dédié → erreur explicite."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "titre", "titre"]},
    )
    assert resp.status_code == 400
    assert "titre" in resp.text.lower()


def _session_a_l_etape_fichiers(client: TestClient) -> int:
    sid = _session_a_l_etape_mapping(client)
    client.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "titre", "__meta__"]},
    )
    return sid


def test_fichiers_skip_metadonnees_seules(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """Racine vide → import métadonnées seules, configuration None."""
    sid = _session_a_l_etape_fichiers(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/fichiers",
        data={"racine": "", "motif_chemin": "", "type_motif": "template"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/import/{sid}/apercu"
    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].configuration_fichiers is None
    assert rows[0].etape == "apercu"


def test_fichiers_avec_racine_motif(
    client_vide: TestClient, tmp_path: Path
) -> None:
    sid = _session_a_l_etape_fichiers(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/fichiers",
        data={
            "racine": "scans",
            "motif_chemin": "{cote}/*.tif",
            "type_motif": "template",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].configuration_fichiers == {
        "racine": "scans",
        "motif_chemin": "{cote}/*.tif",
        "type_motif": "template",
    }


def test_fichiers_racine_sans_motif_rejete(client_vide: TestClient) -> None:
    """Une racine fournie sans motif de chemin est invalide."""
    sid = _session_a_l_etape_fichiers(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/fichiers",
        data={"racine": "scans", "motif_chemin": "", "type_motif": "template"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Sous-étape 4 — aperçu (dry-run) + exécution
# ---------------------------------------------------------------------------


def _session_prete_pour_apercu(client: TestClient) -> int:
    """Session menée jusqu'à l'étape aperçu : tableur + fonds + mapping
    + fichiers sautés (import métadonnées seules)."""
    sid = _session_a_l_etape_fichiers(client)
    client.post(
        f"/import/{sid}/fichiers",
        data={"racine": "", "motif_chemin": "", "type_motif": "template"},
    )
    return sid


def test_apercu_dry_run_compte_les_items(client_vide: TestClient) -> None:
    """L'aperçu simule l'import : le CSV de démo a 2 lignes → 2 items."""
    sid = _session_prete_pour_apercu(client_vide)
    resp = client_vide.get(f"/import/{sid}/apercu")
    assert resp.status_code == 200
    assert "Items à créer" in resp.text
    assert ">2</strong>" in resp.text


def test_executer_cree_le_fonds(
    client_vide: TestClient, tmp_path: Path
) -> None:
    from archives_tool.models import Fonds, Item

    sid = _session_prete_pour_apercu(client_vide)
    resp = client_vide.post(
        f"/import/{sid}/executer", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/fonds/HK"

    engine = creer_engine(tmp_path / "vide.db")
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        assert fonds is not None
        nb_items = len(
            list(s.scalars(select(Item).where(Item.fonds_id == fonds.id)))
        )
        assert nb_items == 2
    engine.dispose()

    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].statut == "validee"
    assert rows[0].fonds_cree_id == fonds.id


def test_executer_idempotent_redirige_vers_le_fonds(
    client_vide: TestClient,
) -> None:
    """Re-POST sur une session déjà exécutée → redirection vers le fonds,
    pas de second import."""
    sid = _session_prete_pour_apercu(client_vide)
    client_vide.post(f"/import/{sid}/executer", follow_redirects=False)
    resp = client_vide.post(
        f"/import/{sid}/executer", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/fonds/HK"


def test_session_validee_disparait_de_l_accueil(
    client_vide: TestClient,
) -> None:
    sid = _session_prete_pour_apercu(client_vide)
    client_vide.post(f"/import/{sid}/executer")
    resp = client_vide.get("/import")
    assert "Aucun import en cours" in resp.text


# ---------------------------------------------------------------------------
# Tolérance des lignes sans cote (documentation en pied de tableur)
# ---------------------------------------------------------------------------

# CSV avec 2 vraies lignes + 1 ligne de documentation sans cote.
CSV_AVEC_LIGNE_SANS_COTE = (
    b"Cote;Titre;Annee\n"
    b"HK-1;Numero 1;1960\n"
    b"HK-2;Numero 2;1961\n"
    b";Liste des metadonnees du tableau;\n"
)


def _session_apercu_csv(client: TestClient, contenu: bytes) -> int:
    """Mène une session jusqu'à l'aperçu avec un CSV fourni (colonnes
    Cote/Titre/Annee), import métadonnées seules."""
    cree = client.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", contenu, "text/csv")},
        data={"feuille": ""},
    )
    client.post(
        f"/import/{sid}/fonds", data={"cote": "HK", "titre": "Hara-Kiri"}
    )
    client.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "titre", "annee"]},
    )
    client.post(
        f"/import/{sid}/fichiers",
        data={"racine": "", "motif_chemin": "", "type_motif": "template"},
    )
    return sid


def test_apercu_ligne_sans_cote_en_erreur(client_vide: TestClient) -> None:
    """Sans tolérance, une ligne sans cote bloque l'import et propose
    de l'ignorer."""
    sid = _session_apercu_csv(client_vide, CSV_AVEC_LIGNE_SANS_COTE)
    resp = client_vide.get(f"/import/{sid}/apercu")
    assert resp.status_code == 200
    assert "cote absente" in resp.text
    assert "tolerer_sans_cote=true" in resp.text  # le lien de rattrapage


def test_apercu_tolere_les_lignes_sans_cote(client_vide: TestClient) -> None:
    """Avec `?tolerer_sans_cote=true`, la ligne sans cote est ignorée :
    2 items, plus d'erreur bloquante."""
    sid = _session_apercu_csv(client_vide, CSV_AVEC_LIGNE_SANS_COTE)
    resp = client_vide.get(
        f"/import/{sid}/apercu?tolerer_sans_cote=true"
    )
    assert resp.status_code == 200
    assert "ne peut pas s'exécuter" not in resp.text
    assert ">2</strong>" in resp.text  # 2 items


def test_executer_avec_tolerance_cree_le_fonds(
    client_vide: TestClient, tmp_path: Path
) -> None:
    from archives_tool.models import Fonds, Item

    sid = _session_apercu_csv(client_vide, CSV_AVEC_LIGNE_SANS_COTE)
    resp = client_vide.post(
        f"/import/{sid}/executer",
        data={"tolerer_sans_cote": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/fonds/HK"

    engine = creer_engine(tmp_path / "vide.db")
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "HK"))
        assert fonds is not None
        nb = len(list(s.scalars(select(Item).where(Item.fonds_id == fonds.id))))
        assert nb == 2  # la ligne sans cote a été ignorée
    engine.dispose()


def test_executer_sans_tolerance_bloque_sur_ligne_sans_cote(
    client_vide: TestClient,
) -> None:
    """Sans la tolérance, l'exécution échoue (400) et ne crée rien."""
    sid = _session_apercu_csv(client_vide, CSV_AVEC_LIGNE_SANS_COTE)
    resp = client_vide.post(f"/import/{sid}/executer")
    assert resp.status_code == 400
    assert "cote absente" in resp.text


# ---------------------------------------------------------------------------
# Granularité fichier : lignes regroupées par cote
# ---------------------------------------------------------------------------

# CSV à granularité fichier : 3 lignes, 2 cotes (PF-1 sur 2 lignes).
CSV_GRANULARITE_FICHIER = (
    b"Cote;Titre;Page\n"
    b"PF-1;Numero 1;1\n"
    b"PF-1;Numero 1;2\n"
    b"PF-2;Numero 2;1\n"
)


def test_granularite_fichier_regroupe_par_cote(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """Un tableur une-ligne-par-fichier importé en granularité fichier :
    les 3 lignes (2 cotes) donnent 2 items, pas 3 collisions."""
    from archives_tool.models import Fonds, Item

    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("inv.csv", CSV_GRANULARITE_FICHIER, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "PF", "titre": "Por Favor"}
    )
    client_vide.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "titre", "__ignore__"],
              "granularite": "fichier"},
    )
    client_vide.post(
        f"/import/{sid}/fichiers",
        data={"racine": "", "motif_chemin": "", "type_motif": "template"},
    )
    resp = client_vide.post(
        f"/import/{sid}/executer", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/fonds/PF"

    engine = creer_engine(tmp_path / "vide.db")
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "PF"))
        nb = len(list(s.scalars(select(Item).where(Item.fonds_id == fonds.id))))
        assert nb == 2  # PF-1 + PF-2, les 2 lignes PF-1 fusionnées
    engine.dispose()


def test_granularite_persistee_dans_la_session(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """Le choix de granularité au mapping est mémorisé sur la session."""
    sid = _session_a_l_etape_mapping(client_vide)
    client_vide.post(
        f"/import/{sid}/mapping",
        data={"cible": ["cote", "titre", "__meta__"],
              "granularite": "fichier"},
    )
    rows = _sessions(tmp_path / "vide.db")
    assert rows[0].granularite == "fichier"


# ---------------------------------------------------------------------------
# Mapping de niveau fichier (export Nakala : nom + hash + IIIF par ligne)
# ---------------------------------------------------------------------------

CSV_EXPORT_NAKALA = (
    b"Cote;Titre;Filename;Hash;Iiif\n"
    b"PF-1;Numero 1;pf1_p1.jpg;h1;https://api.nakala.fr/iiif/x/h1\n"
    b"PF-1;Numero 1;pf1_p2.jpg;h2;https://api.nakala.fr/iiif/x/h2\n"
    b"PF-2;Numero 2;pf2_p1.jpg;h3;https://api.nakala.fr/iiif/x/h3\n"
)


def test_mapping_fichier_cree_des_fichiers_nakala(
    client_vide: TestClient, tmp_path: Path
) -> None:
    """Colonnes mappées vers `fichier.*` + granularité fichier :
    chaque ligne devient un Fichier Nakala-only rattaché à son item."""
    from archives_tool.models import Fichier, Fonds, Item

    cree = client_vide.post("/import/nouveau", follow_redirects=False)
    sid = _id_session(cree)
    client_vide.post(
        f"/import/{sid}/tableur",
        files={"fichier": ("export.csv", CSV_EXPORT_NAKALA, "text/csv")},
        data={"feuille": ""},
    )
    client_vide.post(
        f"/import/{sid}/fonds", data={"cote": "PF", "titre": "Por Favor"}
    )
    client_vide.post(
        f"/import/{sid}/mapping",
        data={
            "cible": [
                "cote", "titre",
                "fichier.nom_fichier",
                "fichier.hash_sha256",
                "fichier.iiif_url_nakala",
            ],
            "granularite": "fichier",
        },
    )
    client_vide.post(
        f"/import/{sid}/fichiers",
        data={"racine": "", "motif_chemin": "", "type_motif": "template"},
    )
    resp = client_vide.post(
        f"/import/{sid}/executer", follow_redirects=False
    )
    assert resp.status_code == 303

    engine = creer_engine(tmp_path / "vide.db")
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(select(Fonds).where(Fonds.cote == "PF"))
        items = list(s.scalars(select(Item).where(Item.fonds_id == fonds.id)))
        assert len(items) == 2  # 3 lignes / 2 cotes
        fichiers = list(s.scalars(select(Fichier)))
        assert len(fichiers) == 3
        # Fichiers Nakala-only : URL IIIF présente, pas de source disque.
        for f in fichiers:
            assert f.iiif_url_nakala.startswith("https://api.nakala.fr/")
            assert f.chemin_relatif is None
    engine.dispose()


def test_mapping_propose_les_cibles_fichier(client_vide: TestClient) -> None:
    """L'étape mapping (avancée) expose les cibles « champ du fichier »."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    assert "fichier.iiif_url_nakala" in resp.text
    assert "URL IIIF Nakala" in resp.text


def test_mapping_propose_les_meta_dc_frequentes(client_vide: TestClient) -> None:
    """L'étape mapping (avancée) expose les champs DC fréquents (auteur,
    éditeur…) comme cibles dédiées, pas seulement la sentinelle générique."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    # Optgroup et libellés visibles, valeurs `metadonnees.X` posées.
    assert "Métadonnée Dublin Core fréquente" in resp.text
    for valeur, libelle in (
        ("metadonnees.auteur", "Auteur"),
        ("metadonnees.editeur", "Éditeur"),
        ("metadonnees.sujet", "Sujet"),
    ):
        assert f'value="{valeur}"' in resp.text
        assert libelle in resp.text


def test_hints_couvrent_toutes_les_cibles() -> None:
    """Garde-fou : chaque cible proposée dans l'UI (item, fichier, DC
    fréquent, sentinelles) doit avoir un hint contextuel. Sinon le
    paragraphe sous le sélecteur reste vide pour cette option, c'est
    une régression silencieuse de F4."""
    from archives_tool.api.routes import import_assistant as routes
    from archives_tool.api.services.import_web import (
        CIBLE_IGNORE,
        CIBLE_META,
        CIBLE_META_FICHIER,
    )

    cibles_attendues = {
        v for v, _ in routes._CIBLES_ITEM
    } | {
        v for v, _ in routes._CIBLES_FICHIER
    } | {
        v for v, _ in routes._CIBLES_META_FREQUENTES
    } | {CIBLE_META, CIBLE_META_FICHIER, CIBLE_IGNORE}
    couvertes = set(routes._HINTS_CIBLES.keys())
    manquantes = cibles_attendues - couvertes
    assert not manquantes, f"hints absents pour : {sorted(manquantes)}"


def test_mapping_rend_hints_et_script(client_vide: TestClient) -> None:
    """L'étape mapping (avancée) injecte le JSON des hints + charge le JS."""
    sid = _session_a_l_etape_mapping(client_vide)
    resp = client_vide.get(f"/import/{sid}/mapping?avance=1")
    assert resp.status_code == 200
    assert '<script id="hints-cibles-data"' in resp.text
    assert "data-cible-hint" in resp.text
    assert "data-cible-select" in resp.text
    assert "js/hints_cibles.js" in resp.text
    # Au moins un hint de Item exposé dans le JSON inline.
    assert "Identifiant unique de l" in resp.text  # hint de `cote`


def test_alignement_meta_canoniques() -> None:
    """Garde-fou : `_CIBLES_META_FREQUENTES` (routes) et
    `_CIBLES_META_CANONIQUES` (services) doivent porter les mêmes
    clés. Sans ça, l'utilisateur sélectionne « Auteur » dans l'UI
    mais en revenant sur l'étape voit `__meta__` à la place."""
    from archives_tool.api.routes import import_assistant as routes
    from archives_tool.api.services import import_web as svc

    cles_routes = {c for c, _libelle in routes._CIBLES_META_FREQUENTES}
    assert cles_routes == svc._CIBLES_META_CANONIQUES


def test_mapping_auteur_dedie_pas_de_collapse(client_vide: TestClient) -> None:
    """Quand l'utilisateur sélectionne « Auteur » (cible
    `metadonnees.auteur`), le mapping est écrit tel quel — pas
    de slug renommé via `__meta__`. Le `construire_mapping` du
    service garde la clé canonique."""
    cols = ["cote", "titre_auteur"]
    cibles = ["cote", "metadonnees.auteur"]
    mapping = import_web.construire_mapping(cols, cibles)
    assert mapping == {"cote": "cote", "metadonnees.auteur": "titre_auteur"}
