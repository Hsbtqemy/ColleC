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
