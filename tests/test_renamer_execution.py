"""Tests de l'exécution transactionnelle du renommage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import Collection, Fichier, Item, OperationFichier
from archives_tool.renamer.execution import executer_plan
from archives_tool.renamer.plan import construire_plan


def _setup(
    session: Session, racine: Path, fichiers: list[tuple[str, int, str]]
) -> Collection:
    """fichiers : liste de (cote_item, ordre, nom_fichier)."""
    racine.mkdir(parents=True, exist_ok=True)
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    items_par_cote: dict[str, Item] = {}
    for cote, ordre, nom in fichiers:
        if cote not in items_par_cote:
            it = Item(collection_id=col.id, cote=cote)
            session.add(it)
            session.flush()
            items_par_cote[cote] = it
        chemin_disque = racine / nom
        chemin_disque.parent.mkdir(parents=True, exist_ok=True)
        chemin_disque.write_bytes(b"data")
        session.add(
            Fichier(
                item_id=items_par_cote[cote].id,
                racine="s",
                chemin_relatif=nom,
                nom_fichier=nom,
                ordre=ordre,
            )
        )
    session.commit()
    return col


def test_dry_run_ne_touche_a_rien(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "s"
    _setup(session, racine, [("ALPHA", 1, "a.png")])

    plan = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    rap = executer_plan(session, plan, racines={"s": racine}, dry_run=True)
    assert rap.dry_run is True
    assert rap.batch_id is None
    assert rap.operations_reussies == 1
    # Sur disque : a.png inchangé.
    assert (racine / "a.png").exists()
    assert not (racine / "ALPHA.png").exists()
    # En base : chemin inchangé.
    f = session.scalar(select(Fichier))
    assert f.chemin_relatif == "a.png"
    # Aucun journal.
    assert session.scalar(select(OperationFichier)) is None


def test_execution_reelle_renomme_disque_et_base(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "s"
    _setup(session, racine, [("ALPHA", 1, "a.png"), ("BETA", 1, "b.png")])

    plan = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    rap = executer_plan(
        session, plan, racines={"s": racine}, dry_run=False, execute_par="Marie"
    )
    assert rap.batch_id is not None
    assert rap.operations_reussies == 2
    assert rap.erreurs == []

    # Disque.
    assert not (racine / "a.png").exists()
    assert not (racine / "b.png").exists()
    assert (racine / "ALPHA.png").exists()
    assert (racine / "BETA.png").exists()

    # Base.
    fichiers = session.scalars(select(Fichier).order_by(Fichier.id)).all()
    assert {f.chemin_relatif for f in fichiers} == {"ALPHA.png", "BETA.png"}
    assert {f.nom_fichier for f in fichiers} == {"ALPHA.png", "BETA.png"}

    # Journal : 2 OperationFichier réussies, même batch_id.
    ops = session.scalars(select(OperationFichier)).all()
    assert len(ops) == 2
    assert {o.batch_id for o in ops} == {rap.batch_id}
    assert {o.statut for o in ops} == {"reussie"}
    assert {o.execute_par for o in ops} == {"Marie"}
    assert {o.type_operation for o in ops} == {"rename"}


def test_cycle_resolu_via_pivot(session: Session, tmp_path: Path) -> None:
    """Échange A↔B : avec template {cote}, les deux fichiers s'échangent."""
    racine = tmp_path / "s"
    racine.mkdir()
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    i_alpha = Item(collection_id=col.id, cote="ALPHA")
    i_beta = Item(collection_id=col.id, cote="BETA")
    session.add_all([i_alpha, i_beta])
    session.flush()
    (racine / "BETA.png").write_bytes(b"alpha-content")
    (racine / "ALPHA.png").write_bytes(b"beta-content")
    session.add_all(
        [
            Fichier(
                item_id=i_alpha.id,
                racine="s",
                chemin_relatif="BETA.png",
                nom_fichier="BETA.png",
                ordre=1,
            ),
            Fichier(
                item_id=i_beta.id,
                racine="s",
                chemin_relatif="ALPHA.png",
                nom_fichier="ALPHA.png",
                ordre=1,
            ),
        ]
    )
    session.commit()

    plan = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    rap = executer_plan(session, plan, racines={"s": racine}, dry_run=False)
    assert rap.erreurs == []
    assert rap.operations_reussies == 2

    # Le contenu attendu : ALPHA.png contient "alpha-content".
    assert (racine / "ALPHA.png").read_bytes() == b"alpha-content"
    assert (racine / "BETA.png").read_bytes() == b"beta-content"


def test_rollback_compensateur_si_echec_phase2(
    session: Session, tmp_path: Path
) -> None:
    """Si le déplacement final échoue mid-batch, l'état initial est restauré."""
    racine = tmp_path / "s"
    _setup(session, racine, [("ALPHA", 1, "a.png"), ("BETA", 1, "b.png")])

    plan = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )

    appels = {"phase2": 0}
    original_rename = Path.rename

    def rename_qui_echoue_au_2eme_phase2(self: Path, target):
        # Phase 1 utilise des noms .tmp_rename_… — on les laisse passer.
        # Phase 2 : la cible n'est PAS un .tmp_… → on échoue au 2e appel.
        if ".tmp_rename_" in self.name:
            appels["phase2"] += 1
            if appels["phase2"] == 2:
                raise OSError("disque plein simulé")
        return original_rename(self, target)

    with patch.object(Path, "rename", rename_qui_echoue_au_2eme_phase2):
        rap = executer_plan(session, plan, racines={"s": racine}, dry_run=False)

    assert rap.erreurs
    assert "disque plein" in rap.erreurs[0]
    assert rap.operations_reussies == 0
    assert rap.operations_compensees > 0

    # Disque restauré : a.png et b.png présents, ALPHA/BETA absents.
    assert (racine / "a.png").exists()
    assert (racine / "b.png").exists()
    assert not (racine / "ALPHA.png").exists()
    # Aucun fichier .tmp_… ne doit traîner.
    tmps = list(racine.glob(".tmp_rename_*"))
    assert tmps == []

    # Base inchangée.
    fichiers = session.scalars(select(Fichier)).all()
    assert {f.chemin_relatif for f in fichiers} == {"a.png", "b.png"}

    # Aucun journal n'a été commit.
    assert session.scalar(select(OperationFichier)) is None


def test_plan_non_applicable_refuse_execution(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "s"
    _setup(session, racine, [("ALPHA", 1, "a.png"), ("ALPHA", 2, "b.png")])

    plan = construire_plan(
        session,
        template="{cote}.{ext}",  # collision intra-batch
        racines={"s": racine},
        collection_cote="C",
    )
    rap = executer_plan(session, plan, racines={"s": racine}, dry_run=False)
    assert rap.batch_id is None
    assert rap.erreurs
    assert "applicable" in rap.erreurs[0].lower() or "conflit" in rap.erreurs[0].lower()


def test_execution_ignore_no_op(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "s"
    _setup(session, racine, [("ALPHA", 1, "ALPHA.png")])

    plan = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    rap = executer_plan(session, plan, racines={"s": racine}, dry_run=False)
    # Aucun rename, aucun journal.
    assert rap.batch_id is None
    assert rap.operations_reussies == 0
    assert session.scalar(select(OperationFichier)) is None
