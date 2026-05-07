"""Tests de l'annulation d'un batch de renommage."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.models import Collection, Fichier, Item, OperationFichier
from archives_tool.renamer.annulation import annuler_batch
from archives_tool.renamer.execution import executer_plan
from archives_tool.renamer.plan import construire_plan


def _setup_et_renommer(session: Session, racine: Path) -> str:
    racine.mkdir(parents=True, exist_ok=True)
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    item = Item(collection_id=col.id, cote="ALPHA")
    session.add(item)
    session.flush()
    (racine / "a.png").write_bytes(b"alpha")
    session.add(
        Fichier(
            item_id=item.id,
            racine="s",
            chemin_relatif="a.png",
            nom_fichier="a.png",
            ordre=1,
        )
    )
    session.commit()

    plan = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    rap = executer_plan(session, plan, racines={"s": racine}, dry_run=False)
    assert rap.batch_id is not None
    return rap.batch_id


def test_annulation_retablit_etat_initial(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "s"
    batch = _setup_et_renommer(session, racine)
    assert (racine / "ALPHA.png").exists()

    rap = annuler_batch(
        session, batch, racines={"s": racine}, dry_run=False, execute_par="Marie"
    )
    assert rap.erreurs == []
    assert rap.operations_inversees == 1
    assert rap.batch_id_annulation is not None and rap.batch_id_annulation != batch

    # Disque restauré.
    assert (racine / "a.png").exists()
    assert not (racine / "ALPHA.png").exists()
    # Base : chemin_relatif redevient a.png.
    f = session.scalar(select(Fichier))
    assert f.chemin_relatif == "a.png"

    # Journal :
    # - 1 op originale (statut=reussie) marquée annule_par_batch_id=nouveau batch
    # - 1 op nouvelle (statut=reussie, type=restore) avec batch_id=nouveau batch
    ops = session.scalars(select(OperationFichier).order_by(OperationFichier.id)).all()
    assert len(ops) == 2
    assert ops[0].batch_id == batch
    assert ops[0].annule_par_batch_id == rap.batch_id_annulation
    assert ops[1].batch_id == rap.batch_id_annulation
    assert ops[1].type_operation == "restore"
    assert ops[1].execute_par == "Marie"


def test_annulation_dry_run(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "s"
    batch = _setup_et_renommer(session, racine)

    rap = annuler_batch(session, batch, racines={"s": racine}, dry_run=True)
    assert rap.dry_run is True
    assert rap.batch_id_annulation is None
    assert rap.operations_inversees == 1
    # Disque inchangé.
    assert (racine / "ALPHA.png").exists()
    assert not (racine / "a.png").exists()
    # Pas d'op supplémentaire.
    ops = session.scalars(select(OperationFichier)).all()
    assert len(ops) == 1


def test_annulation_idempotente_refuse_2eme_passage(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "s"
    batch = _setup_et_renommer(session, racine)

    annuler_batch(session, batch, racines={"s": racine}, dry_run=False)
    rap2 = annuler_batch(session, batch, racines={"s": racine}, dry_run=False)
    assert rap2.operations_inversees == 0
    assert any("annul" in e.lower() or "aucune" in e.lower() for e in rap2.erreurs)


def test_annulation_batch_inconnu(session: Session, tmp_path: Path) -> None:
    rap = annuler_batch(
        session,
        "00000000-0000-0000-0000-000000000000",
        racines={},
        dry_run=True,
    )
    assert rap.operations_inversees == 0
    assert rap.erreurs


def test_annulation_etat_diverge(session: Session, tmp_path: Path) -> None:
    """Si un fichier a été re-renommé entre-temps, l'annulation refuse."""
    racine = tmp_path / "s"
    batch = _setup_et_renommer(session, racine)
    # Quelqu'un déplace ALPHA.png ailleurs sans passer par l'outil.
    (racine / "ALPHA.png").rename(racine / "z.png")

    rap = annuler_batch(session, batch, racines={"s": racine}, dry_run=False)
    assert rap.operations_inversees == 0
    assert rap.erreurs
    assert any("introuvable" in e.lower() or "absent" in e.lower() for e in rap.erreurs)
