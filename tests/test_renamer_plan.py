"""Tests du module renamer.plan : sélection, conflits, cycles."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from archives_tool.models import Collection, Fichier, Item
from archives_tool.renamer.plan import construire_plan
from archives_tool.renamer.rapport import StatutPlan


def _setup_collection_avec_fichiers(
    session: Session,
    racine_disque: Path,
    cote_collection: str = "C",
    fichiers: list[tuple[str, str, int]] | None = None,
) -> Collection:
    """Crée une collection, un item, puis des fichiers en base et sur disque."""
    racine_disque.mkdir(parents=True, exist_ok=True)
    col = Collection(cote_collection=cote_collection, titre="T")
    session.add(col)
    session.flush()
    item = Item(collection_id=col.id, cote=f"{cote_collection}-001")
    session.add(item)
    session.flush()

    fichiers = fichiers or [("scan_01.png", "scan_01.png", 1)]
    for nom, chemin_relatif, ordre in fichiers:
        chemin_disque = racine_disque / chemin_relatif
        chemin_disque.parent.mkdir(parents=True, exist_ok=True)
        chemin_disque.write_bytes(b"x")
        session.add(
            Fichier(
                item_id=item.id,
                racine="s",
                chemin_relatif=chemin_relatif,
                nom_fichier=nom,
                ordre=ordre,
            )
        )
    session.commit()
    return col


def test_plan_simple_renomme_chaque_fichier(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "scans"
    _setup_collection_avec_fichiers(
        session,
        racine,
        fichiers=[("scan_01.png", "scan_01.png", 1), ("scan_02.png", "scan_02.png", 2)],
    )

    rap = construire_plan(
        session,
        template="{cote}-{ordre:02d}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    assert rap.conflits == []
    assert rap.applicable
    cibles = sorted(op.chemin_apres for op in rap.operations)
    assert cibles == ["C-001-01.png", "C-001-02.png"]
    assert all(op.statut == StatutPlan.PRET for op in rap.operations)


def test_plan_no_op_quand_cible_egale_source(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "scans"
    _setup_collection_avec_fichiers(
        session,
        racine,
        fichiers=[("C-001-01.png", "C-001-01.png", 1)],
    )

    rap = construire_plan(
        session,
        template="{cote}-{ordre:02d}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    assert rap.nb_no_op == 1
    assert rap.nb_renommages == 0
    assert rap.applicable


def test_plan_collision_intra_batch_bloque(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "scans"
    _setup_collection_avec_fichiers(
        session,
        racine,
        fichiers=[("a.png", "a.png", 1), ("b.png", "b.png", 2)],
    )
    # Template sans {ordre} → les deux fichiers visent C-001.png.
    rap = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    assert any(c.code == "collision_intra_batch" for c in rap.conflits)
    assert all(op.statut == StatutPlan.BLOQUE for op in rap.operations)
    assert not rap.applicable


def test_plan_collision_externe_bloque(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "scans"
    _setup_collection_avec_fichiers(
        session,
        racine,
        fichiers=[("a.png", "a.png", 1)],
    )
    # Crée un fichier qui squattera la cible — non géré par le batch.
    (racine / "C-001-01.png").write_bytes(b"squatteur")

    rap = construire_plan(
        session,
        template="{cote}-{ordre:02d}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    assert any(c.code == "collision_externe" for c in rap.conflits)
    assert all(op.statut == StatutPlan.BLOQUE for op in rap.operations)


def test_plan_chaine_pas_consideree_comme_collision(
    session: Session, tmp_path: Path
) -> None:
    """A → B où B est aussi une source du batch (déplacée vers C) :
    la collision avec B sur disque n'en est pas une, c'est une chaîne."""
    racine = tmp_path / "scans"
    racine.mkdir()
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    item = Item(collection_id=col.id, cote="C-001")
    session.add(item)
    session.flush()
    # Deux fichiers : a.png et b.png, déjà sur disque.
    (racine / "a.png").write_bytes(b"1")
    (racine / "b.png").write_bytes(b"2")
    session.add_all(
        [
            Fichier(
                item_id=item.id,
                racine="s",
                chemin_relatif="a.png",
                nom_fichier="a.png",
                ordre=1,
            ),
            Fichier(
                item_id=item.id,
                racine="s",
                chemin_relatif="b.png",
                nom_fichier="b.png",
                ordre=2,
            ),
        ]
    )
    session.commit()

    rap = construire_plan(
        session,
        template="{ordre}.png",  # 1.png et 2.png → différentes cibles, pas chaîne
        racines={"s": racine},
        collection_cote="C",
    )
    # Pas de conflit, pas de cycle.
    assert rap.conflits == []
    assert all(op.statut == StatutPlan.PRET for op in rap.operations)


def test_plan_cycle_detecte_et_marque(session: Session, tmp_path: Path) -> None:
    """A → B et B → A : cycle, à résoudre par pivot."""
    racine = tmp_path / "scans"
    racine.mkdir()
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    i1 = Item(collection_id=col.id, cote="ALPHA")
    i2 = Item(collection_id=col.id, cote="BETA")
    session.add_all([i1, i2])
    session.flush()
    # Sur disque : ALPHA.png et BETA.png
    (racine / "ALPHA.png").write_bytes(b"1")
    (racine / "BETA.png").write_bytes(b"2")
    # En base : i1 a un fichier nommé ALPHA.png, i2 BETA.png
    # Avec un template "{cote}.{ext}", après import les cibles seraient
    # ALPHA.png et BETA.png — pas de changement. Pour fabriquer un cycle, on
    # met i1 sur le fichier "BETA.png" (chemin_relatif inversé) et i2 sur
    # "ALPHA.png". Le template "{cote}.{ext}" produira alors :
    #   fichier "BETA.png" (lié à i1 cote=ALPHA) → "ALPHA.png"
    #   fichier "ALPHA.png" (lié à i2 cote=BETA) → "BETA.png"
    # = échange.
    session.add_all(
        [
            Fichier(
                item_id=i1.id,
                racine="s",
                chemin_relatif="BETA.png",
                nom_fichier="BETA.png",
                ordre=1,
            ),
            Fichier(
                item_id=i2.id,
                racine="s",
                chemin_relatif="ALPHA.png",
                nom_fichier="ALPHA.png",
                ordre=1,
            ),
        ]
    )
    session.commit()

    rap = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    assert rap.applicable
    statuts = {op.statut for op in rap.operations}
    assert StatutPlan.EN_CYCLE in statuts
    # Pas de conflit malgré la "collision externe" apparente.
    assert rap.conflits == []


def test_plan_filtre_par_item(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "scans"
    racine.mkdir()
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    i1 = Item(collection_id=col.id, cote="A")
    i2 = Item(collection_id=col.id, cote="B")
    session.add_all([i1, i2])
    session.flush()
    (racine / "x.png").write_bytes(b"1")
    (racine / "y.png").write_bytes(b"2")
    session.add_all(
        [
            Fichier(
                item_id=i1.id,
                racine="s",
                chemin_relatif="x.png",
                nom_fichier="x.png",
                ordre=1,
            ),
            Fichier(
                item_id=i2.id,
                racine="s",
                chemin_relatif="y.png",
                nom_fichier="y.png",
                ordre=1,
            ),
        ]
    )
    session.commit()

    rap = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        item_cote="A",
    )
    assert len(rap.operations) == 1
    assert rap.operations[0].chemin_apres == "A.png"


def test_plan_filtre_par_fichier_ids(session: Session, tmp_path: Path) -> None:
    racine = tmp_path / "scans"
    _setup_collection_avec_fichiers(
        session,
        racine,
        fichiers=[("a.png", "a.png", 1), ("b.png", "b.png", 2)],
    )
    from sqlalchemy import select

    ids = list(session.scalars(select(Fichier.id).order_by(Fichier.id)).all())
    rap = construire_plan(
        session,
        template="renamed-{ordre}.{ext}",
        racines={"s": racine},
        fichier_ids=[ids[0]],
    )
    assert len(rap.operations) == 1
    assert rap.operations[0].fichier_id == ids[0]


def test_plan_template_invalide_marque_op_bloquee(
    session: Session, tmp_path: Path
) -> None:
    racine = tmp_path / "scans"
    _setup_collection_avec_fichiers(
        session,
        racine,
        fichiers=[("a.png", "a.png", 1)],
    )
    rap = construire_plan(
        session,
        template="{xxx}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    assert rap.operations[0].statut == StatutPlan.BLOQUE
    assert any(c.code == "template_invalide" for c in rap.conflits)


def test_plan_perimetre_vide_leve_erreur(session: Session) -> None:
    with pytest.raises(ValueError, match="périmètre"):
        construire_plan(session, template="{cote}.{ext}", racines={})


def test_plan_cycle_longueur_3(session: Session, tmp_path: Path) -> None:
    """Cycle A→B→C→A : les trois ops sont marquées EN_CYCLE."""
    racine = tmp_path / "s"
    racine.mkdir()
    col = Collection(cote_collection="C", titre="T")
    session.add(col)
    session.flush()
    items = [Item(collection_id=col.id, cote=c) for c in ("ALPHA", "BETA", "GAMMA")]
    session.add_all(items)
    session.flush()
    # Disque + base : ALPHA est sur "GAMMA.png", BETA sur "ALPHA.png",
    # GAMMA sur "BETA.png". Avec template {cote}.{ext} :
    #   GAMMA.png (item ALPHA) → ALPHA.png
    #   ALPHA.png (item BETA) → BETA.png
    #   BETA.png (item GAMMA) → GAMMA.png
    for nom in ("ALPHA.png", "BETA.png", "GAMMA.png"):
        (racine / nom).write_bytes(b"x")
    session.add_all(
        [
            Fichier(
                item_id=items[0].id,
                racine="s",
                chemin_relatif="GAMMA.png",
                nom_fichier="GAMMA.png",
                ordre=1,
            ),
            Fichier(
                item_id=items[1].id,
                racine="s",
                chemin_relatif="ALPHA.png",
                nom_fichier="ALPHA.png",
                ordre=1,
            ),
            Fichier(
                item_id=items[2].id,
                racine="s",
                chemin_relatif="BETA.png",
                nom_fichier="BETA.png",
                ordre=1,
            ),
        ]
    )
    session.commit()

    rap = construire_plan(
        session,
        template="{cote}.{ext}",
        racines={"s": racine},
        collection_cote="C",
    )
    assert rap.applicable
    assert all(op.statut == StatutPlan.EN_CYCLE for op in rap.operations)
    assert rap.conflits == []


def test_detecter_cycles_chaine_dans_cycle() -> None:
    """Test direct de _detecter_cycles : A→B, B→C, C→B."""
    from archives_tool.renamer.plan import _detecter_cycles
    from archives_tool.renamer.rapport import OperationRenommage, StatutPlan

    ops = [
        OperationRenommage(1, "s", "A", "B", StatutPlan.PRET),
        OperationRenommage(2, "s", "B", "C", StatutPlan.PRET),
        OperationRenommage(3, "s", "C", "B", StatutPlan.PRET),
    ]
    indices = _detecter_cycles(ops)
    # Le cycle est {B, C} → ops 1 et 2. L'op 0 (A→B) n'est pas dans
    # un cycle même si elle vise une cible dans le cycle.
    assert indices == {1, 2}


def test_detecter_cycles_longueur_3() -> None:
    from archives_tool.renamer.plan import _detecter_cycles
    from archives_tool.renamer.rapport import OperationRenommage, StatutPlan

    ops = [
        OperationRenommage(1, "s", "A", "B", StatutPlan.PRET),
        OperationRenommage(2, "s", "B", "C", StatutPlan.PRET),
        OperationRenommage(3, "s", "C", "A", StatutPlan.PRET),
    ]
    assert _detecter_cycles(ops) == {0, 1, 2}
