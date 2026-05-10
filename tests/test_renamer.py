"""Tests du module renamer (V0.9.0-gamma.4.2).

Quatre familles de tests :
- `template.py` : variables disponibles, validation, format spec.
- `plan.py` : sélection par fonds / collection / item / ids,
  détection des conflits intra-batch et externes.
- `execution.py` : application transactionnelle, rollback compensateur
  si rename FS échoue, journalisation `OperationFichier`.
- `annulation.py` : retour en arrière d'un batch via `batch_id`.

Les fixtures créent de vrais fichiers physiques sur `tmp_path` —
le moteur teste à la fois la base et le filesystem, donc pas de mock.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services.collections import (
    FormulaireCollection,
    creer_collection_libre,
    lire_collection_par_cote,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    creer_item,
)
from archives_tool.models import (
    Fichier,
    ItemCollection,
    OperationFichier,
)
from archives_tool.renamer import (
    EchecTemplate,
    annuler_batch,
    construire_plan,
    evaluer_template,
    executer_plan,
)
from archives_tool.renamer.rapport import CodeConflit, StatutPlan


# ---------------------------------------------------------------------------
# Fixtures : base avec fichiers réels sur disque
# ---------------------------------------------------------------------------


@pytest.fixture
def racine_scans(tmp_path: Path) -> Path:
    """Dossier racine où les fichiers physiques sont créés."""
    base = tmp_path / "scans"
    base.mkdir()
    return base


@pytest.fixture
def session_avec_fichiers(
    session: Session, racine_scans: Path
) -> Session:
    """1 fonds HK + 2 items + 5 fichiers physiques + 1 libre rattachée.

    HK-001 : 3 fichiers (HK-001-001.tif à HK-001-003.tif).
    HK-002 : 2 fichiers (HK-002-001.tif à HK-002-002.tif).
    Tous physiquement créés sous `racine_scans`. La libre HK-FAVORIS
    contient HK-001 (utilisée pour tester la sélection par collection).
    """
    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    fonds = lire_fonds_par_cote(session, "HK")
    item_001 = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id),
    )
    item_002 = creer_item(
        session,
        FormulaireItem(cote="HK-002", titre="N°2", fonds_id=fonds.id),
    )

    creer_collection_libre(
        session,
        FormulaireCollection(
            cote="HK-FAVORIS", titre="Favoris", fonds_id=fonds.id
        ),
    )
    fav = lire_collection_par_cote(session, "HK-FAVORIS", fonds_id=fonds.id)
    session.add(ItemCollection(item_id=item_001.id, collection_id=fav.id))

    for item, nb in ((item_001, 3), (item_002, 2)):
        for ordre in range(1, nb + 1):
            nom = f"{item.cote}-{ordre:03d}.tif"
            chemin_rel = nom
            (racine_scans / chemin_rel).write_bytes(b"data")
            session.add(
                Fichier(
                    item_id=item.id,
                    racine="scans",
                    chemin_relatif=chemin_rel,
                    nom_fichier=nom,
                    ordre=ordre,
                    format="tif",
                    type_page="page",
                )
            )
    session.commit()
    return session


def _racines(scans: Path) -> dict[str, Path]:
    return {"scans": scans}


# ---------------------------------------------------------------------------
# Famille 1 — template
# ---------------------------------------------------------------------------


def test_template_variables_de_base(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    """Les variables item + fonds sont exposées par défaut."""
    fichier = session_avec_fichiers.scalar(
        select(Fichier).order_by(Fichier.id).limit(1)
    )
    cible = evaluer_template(
        "{cote_fonds}/{cote}/{cote}-{ordre:03d}.{ext}",
        fichier,
        fichier.item,
    )
    assert cible == "HK/HK-001/HK-001-001.tif"


def test_template_format_spec_padding(
    session_avec_fichiers: Session,
) -> None:
    """`:03d` produit un padding zéro à 3 chiffres."""
    fichier = session_avec_fichiers.scalar(
        select(Fichier).where(Fichier.ordre == 1).limit(1)
    )
    cible = evaluer_template("p{ordre:03d}.{ext}", fichier, fichier.item)
    assert cible == "p001.tif"


def test_template_variable_inconnue_leve(
    session_avec_fichiers: Session,
) -> None:
    fichier = session_avec_fichiers.scalar(select(Fichier).limit(1))
    with pytest.raises(EchecTemplate, match="inconnue"):
        evaluer_template("{xxx}.tif", fichier, fichier.item)


def test_template_vide_leve(session_avec_fichiers: Session) -> None:
    fichier = session_avec_fichiers.scalar(select(Fichier).limit(1))
    with pytest.raises(EchecTemplate, match="vide"):
        evaluer_template("   ", fichier, fichier.item)


# ---------------------------------------------------------------------------
# Famille 2 — plan / sélection / conflits
# ---------------------------------------------------------------------------


def test_plan_perimetre_fonds(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    plan = construire_plan(
        session_avec_fichiers,
        template="{cote_fonds}/{cote}-{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        fonds_cote="HK",
    )
    # 5 fichiers du fonds HK.
    assert len(plan.operations) == 5
    assert plan.applicable
    assert all(
        op.chemin_apres.startswith("HK/")
        for op in plan.operations
        if op.statut == StatutPlan.PRET
    )


def test_plan_perimetre_collection_libre(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    """La collection HK-FAVORIS contient seulement HK-001 (3 fichiers)."""
    plan = construire_plan(
        session_avec_fichiers,
        template="fav/{cote}-{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        collection_cote="HK-FAVORIS",
        collection_fonds_cote="HK",
    )
    assert len(plan.operations) == 3


def test_plan_perimetre_item(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    plan = construire_plan(
        session_avec_fichiers,
        template="{cote}/{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        item_cote="HK-001",
        item_fonds_cote="HK",
    )
    assert len(plan.operations) == 3


def test_plan_collision_intra_batch(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    """Pattern qui ne discrimine pas l'ordre → 2+ fichiers visent
    la même cible."""
    plan = construire_plan(
        session_avec_fichiers,
        template="{cote}.{ext}",
        racines=_racines(racine_scans),
        fonds_cote="HK",
    )
    assert not plan.applicable
    codes = {c.code for c in plan.conflits}
    assert CodeConflit.COLLISION_INTRA_BATCH in codes


def test_plan_no_op_si_template_identique(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    """Si le template reproduit le chemin actuel, c'est NO_OP (pas un
    conflit)."""
    plan = construire_plan(
        session_avec_fichiers,
        template="{cote}-{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        fonds_cote="HK",
    )
    no_op = [o for o in plan.operations if o.statut == StatutPlan.NO_OP]
    assert len(no_op) == 5
    assert plan.nb_renommages == 0


# ---------------------------------------------------------------------------
# Famille 3 — exécution transactionnelle
# ---------------------------------------------------------------------------


def test_execution_dry_run_ne_modifie_rien(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    plan = construire_plan(
        session_avec_fichiers,
        template="renomme/{cote}-{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        fonds_cote="HK",
    )
    rap = executer_plan(
        session_avec_fichiers, plan, racines=_racines(racine_scans), dry_run=True
    )
    assert rap.dry_run is True
    # Aucun fichier déplacé sur disque.
    assert (racine_scans / "HK-001-001.tif").exists()
    assert not (racine_scans / "renomme").exists()


def test_execution_appliquee_modifie_db_et_disque(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    plan = construire_plan(
        session_avec_fichiers,
        template="renomme/{cote}-{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        fonds_cote="HK",
    )
    rap = executer_plan(
        session_avec_fichiers, plan, racines=_racines(racine_scans), dry_run=False
    )
    assert rap.dry_run is False
    assert not rap.erreurs
    assert rap.batch_id is not None

    # Disque : nouveau chemin existe, ancien plus.
    assert (racine_scans / "renomme" / "HK-001-001.tif").exists()
    assert not (racine_scans / "HK-001-001.tif").exists()

    # Base : `chemin_relatif` à jour.
    f = session_avec_fichiers.scalar(
        select(Fichier).where(Fichier.nom_fichier == "HK-001-001.tif")
    )
    assert f.chemin_relatif == "renomme/HK-001-001.tif"

    # Journal : 5 OperationFichier avec ce batch_id.
    ops = list(
        session_avec_fichiers.scalars(
            select(OperationFichier).where(
                OperationFichier.batch_id == rap.batch_id
            )
        )
    )
    assert len(ops) == 5


# ---------------------------------------------------------------------------
# Famille 4 — annulation
# ---------------------------------------------------------------------------


def test_annulation_remet_chemins_initiaux(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    """Après applique + annule, les chemins reviennent à leur état
    initial (DB + disque), avec un batch_id distinct journalé."""
    plan = construire_plan(
        session_avec_fichiers,
        template="renomme/{cote}-{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        fonds_cote="HK",
    )
    rap = executer_plan(
        session_avec_fichiers,
        plan,
        racines=_racines(racine_scans),
        dry_run=False,
    )
    batch_orig = rap.batch_id
    assert batch_orig is not None

    rap_annul = annuler_batch(
        session_avec_fichiers,
        batch_orig,
        racines=_racines(racine_scans),
        dry_run=False,
    )
    assert not rap_annul.erreurs

    # Disque : ancien chemin restauré. Le répertoire `renomme/` peut
    # subsister vide (le moteur ne supprime pas les répertoires créés
    # — c'est conservateur, à l'utilisateur de faire le ménage).
    assert (racine_scans / "HK-001-001.tif").exists()
    assert not any((racine_scans / "renomme").glob("*"))

    # Base : chemin_relatif d'origine.
    f = session_avec_fichiers.scalar(
        select(Fichier).where(Fichier.nom_fichier == "HK-001-001.tif")
    )
    assert f.chemin_relatif == "HK-001-001.tif"
