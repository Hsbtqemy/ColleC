"""Isolation per-owner des états serveur en mémoire (dé-risquage multi-user).

Vérifie que les trois états module-globaux — identifiants ShareDocs en RAM,
gardes mono-job du dépôt Nakala et de l'import ShareDocs — sont bien **keyés
par owner** : deux owners distincts ne se voient pas. En mode local
mono-utilisateur, un seul owner (``OWNER_DEFAUT``) existe ; ces tests
exercent la couture qui permettra l'injection d'un id de session/utilisateur
au Chantier 3 sans retoucher les services.
"""

from __future__ import annotations

import pytest

from archives_tool.api import deps
from archives_tool.api.services import (
    nakala_depot_jobs,
    sharedocs_jobs,
    sharedocs_session,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    sharedocs_session._reset_pour_tests()
    nakala_depot_jobs._reset_pour_tests()
    sharedocs_jobs._reset_pour_tests()
    yield
    sharedocs_session._reset_pour_tests()
    nakala_depot_jobs._reset_pour_tests()
    sharedocs_jobs._reset_pour_tests()


# ---------------------------------------------------------------------------
# Couture
# ---------------------------------------------------------------------------


def test_get_owner_key_renvoie_le_defaut_local() -> None:
    """En mode local, la couture renvoie la constante — un seul owner."""
    assert deps.get_owner_key() == deps.OWNER_DEFAUT == "local"


# ---------------------------------------------------------------------------
# sharedocs_session — identifiants en RAM (fuite de confidentialité évitée)
# ---------------------------------------------------------------------------


def test_creds_sharedocs_isoles_par_owner() -> None:
    """Les identifiants de l'owner A ne fuitent pas vers l'owner B."""
    sharedocs_session.connecter("https://a.example", "userA", "pwA", owner="alice")
    # B n'a rien.
    assert sharedocs_session.est_connecte(owner="bob") is False
    assert sharedocs_session.identifiants(owner="bob") is None
    assert sharedocs_session.etat_public(owner="bob")["connecte"] is False
    # A voit ses propres creds (mot de passe inclus côté usage interne).
    assert sharedocs_session.identifiants(owner="alice") == (
        "https://a.example",
        "userA",
        "pwA",
    )
    # L'état public de A n'expose jamais le mot de passe.
    pub = sharedocs_session.etat_public(owner="alice")
    assert pub["connecte"] is True
    assert pub["user"] == "userA"
    assert "pwA" not in pub.values()


def test_deconnecter_un_owner_nepasse_pas_lautre() -> None:
    sharedocs_session.connecter("https://a", "uA", "pA", owner="alice")
    sharedocs_session.connecter("https://b", "uB", "pB", owner="bob")
    sharedocs_session.deconnecter(owner="alice")
    assert sharedocs_session.est_connecte(owner="alice") is False
    assert sharedocs_session.est_connecte(owner="bob") is True


# ---------------------------------------------------------------------------
# nakala_depot_jobs — garde mono-job per-owner (disponibilité)
# ---------------------------------------------------------------------------


def test_garde_depot_nakala_per_owner() -> None:
    """Un dépôt de l'owner A ne bloque pas l'owner B (garde per-owner)."""
    job_a = nakala_depot_jobs.reserver_job(
        fonds_cote="X", collection_cote="X", total=1, owner="alice"
    )
    assert nakala_depot_jobs.est_job_actif(owner="alice") is True
    assert nakala_depot_jobs.est_job_actif(owner="bob") is False
    # B peut réserver malgré le job actif de A.
    job_b = nakala_depot_jobs.reserver_job(
        fonds_cote="Y", collection_cote="Y", total=1, owner="bob"
    )
    assert job_b != job_a
    assert nakala_depot_jobs.est_job_actif(owner="bob") is True


def test_garde_depot_nakala_refuse_2e_job_meme_owner() -> None:
    """Deux dépôts du même owner restent mutuellement exclusifs."""
    nakala_depot_jobs.reserver_job(
        fonds_cote="X", collection_cote="X", total=1, owner="alice"
    )
    with pytest.raises(nakala_depot_jobs.JobConcurrent):
        nakala_depot_jobs.reserver_job(
            fonds_cote="X2", collection_cote="X2", total=1, owner="alice"
        )


# ---------------------------------------------------------------------------
# sharedocs_jobs — garde mono-job per-owner
# ---------------------------------------------------------------------------


def test_garde_import_sharedocs_per_owner() -> None:
    job_a = sharedocs_jobs.reserver_job(
        item_cote="IT-A",
        fonds_cote="A",
        racine="scans",
        chemin_retour="/",
        chemins_distants=["/a.tif"],
        owner="alice",
    )
    assert sharedocs_jobs.est_job_actif(owner="alice") is True
    assert sharedocs_jobs.est_job_actif(owner="bob") is False
    job_b = sharedocs_jobs.reserver_job(
        item_cote="IT-B",
        fonds_cote="B",
        racine="scans",
        chemin_retour="/",
        chemins_distants=["/b.tif"],
        owner="bob",
    )
    assert job_b != job_a


def test_garde_import_sharedocs_refuse_2e_job_meme_owner() -> None:
    sharedocs_jobs.reserver_job(
        item_cote="IT-A",
        fonds_cote="A",
        racine="scans",
        chemin_retour="/",
        chemins_distants=["/a.tif"],
        owner="alice",
    )
    with pytest.raises(sharedocs_jobs.JobConcurrent):
        sharedocs_jobs.reserver_job(
            item_cote="IT-A2",
            fonds_cote="A",
            racine="scans",
            chemin_retour="/",
            chemins_distants=["/a2.tif"],
            owner="alice",
        )


def test_defaut_local_partage_entre_appels_sans_owner() -> None:
    """Sans owner explicite (chemin actuel en local), tout retombe sur le
    même owner ``OWNER_DEFAUT`` — comportement mono-utilisateur inchangé."""
    sharedocs_session.connecter("https://a", "u", "p")  # owner défaut
    assert sharedocs_session.est_connecte() is True
    assert sharedocs_session.est_connecte(owner=deps.OWNER_DEFAUT) is True
    nakala_depot_jobs.reserver_job(fonds_cote="X", collection_cote="X", total=0)
    assert nakala_depot_jobs.est_job_actif() is True


# ---------------------------------------------------------------------------
# IDOR — contrôle d'accès cross-owner sur les jobs (lecture / annulation)
#
# `_JOBS` est keyé par UUID (non devinable) ; le job_id n'est PAS une
# autorisation (il transite en clair dans URLs/logs). Le filtre `owner` des
# accesseurs est le vrai contrôle d'accès. Sans lui, un owner pouvait lire
# l'état (arborescence privée) ou annuler le job d'un autre owner.
# ---------------------------------------------------------------------------


def _job_sharedocs(owner: str) -> str:
    return sharedocs_jobs.reserver_job(
        item_cote="IT",
        fonds_cote="F",
        racine="scans",
        chemin_retour="/",
        chemins_distants=["/a.tif"],
        owner=owner,
    )


def test_lire_etat_job_sharedocs_filtre_par_owner() -> None:
    job_a = _job_sharedocs("alice")
    # Bob, en devinant le job_id de A, ne voit RIEN (indiscernable d'inconnu).
    assert sharedocs_jobs.lire_etat_job(job_a, owner="bob") is None
    # A voit son job ; l'accès sans owner (tests/CLI) reste permis.
    assert sharedocs_jobs.lire_etat_job(job_a, owner="alice") is not None
    assert sharedocs_jobs.lire_etat_job(job_a) is not None


def test_annuler_job_sharedocs_refuse_autre_owner() -> None:
    job_a = _job_sharedocs("alice")
    # Bob ne peut pas saboter l'import de A.
    assert sharedocs_jobs.demander_annulation(job_a, owner="bob") is False
    assert sharedocs_jobs.lire_etat_job(job_a, owner="alice").annule is False
    # A peut annuler le sien.
    assert sharedocs_jobs.demander_annulation(job_a, owner="alice") is True
    assert sharedocs_jobs.lire_etat_job(job_a, owner="alice").annule is True


def test_lire_etat_job_nakala_filtre_par_owner() -> None:
    job_a = nakala_depot_jobs.reserver_job(
        fonds_cote="X", collection_cote="X", total=1, owner="alice"
    )
    assert nakala_depot_jobs.lire_etat_job(job_a, owner="bob") is None
    assert nakala_depot_jobs.lire_etat_job(job_a, owner="alice") is not None
    assert nakala_depot_jobs.lire_etat_job(job_a) is not None
