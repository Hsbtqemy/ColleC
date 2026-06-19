"""Tests du module renamer.

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
    Perimetre,
    annuler_batch,
    construire_plan,
    evaluer_template,
    executer_plan,
)
from archives_tool.renamer.plan import _detecter_cycles
from archives_tool.renamer.rapport import (
    CodeConflit,
    OperationRenommage,
    RapportPlan,
    StatutPlan,
)


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
def session_avec_fichiers(session: Session, racine_scans: Path) -> Session:
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
        FormulaireCollection(cote="HK-FAVORIS", titre="Favoris", fonds_id=fonds.id),
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
        fichier.item.fonds,
    )
    assert cible == "HK/HK-001/HK-001-001.tif"


def test_template_format_spec_padding(
    session_avec_fichiers: Session,
) -> None:
    """`:03d` produit un padding zéro à 3 chiffres."""
    fichier = session_avec_fichiers.scalar(
        select(Fichier).where(Fichier.ordre == 1).limit(1)
    )
    cible = evaluer_template(
        "p{ordre:03d}.{ext}", fichier, fichier.item, fichier.item.fonds
    )
    assert cible == "p001.tif"


def test_template_variable_inconnue_leve(
    session_avec_fichiers: Session,
) -> None:
    fichier = session_avec_fichiers.scalar(select(Fichier).limit(1))
    with pytest.raises(EchecTemplate, match="inconnue"):
        evaluer_template("{xxx}.tif", fichier, fichier.item, fichier.item.fonds)


def test_template_vide_leve(session_avec_fichiers: Session) -> None:
    fichier = session_avec_fichiers.scalar(select(Fichier).limit(1))
    with pytest.raises(EchecTemplate, match="vide"):
        evaluer_template("   ", fichier, fichier.item, fichier.item.fonds)


# ---------------------------------------------------------------------------
# Famille 2 — plan / sélection / conflits
# ---------------------------------------------------------------------------


def test_perimetre_aucun_mode_leve() -> None:
    """`Perimetre()` sans aucun sélecteur est rejeté à la construction."""
    with pytest.raises(ValueError, match="exactement un"):
        Perimetre()


def test_plan_perimetre_fonds(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    plan = construire_plan(
        session_avec_fichiers,
        template="{cote_fonds}/{cote}-{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        perimetre=Perimetre(fonds_cote="HK"),
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
        perimetre=Perimetre(collection_cote="HK-FAVORIS", collection_fonds_cote="HK"),
    )
    assert len(plan.operations) == 3


def test_plan_perimetre_item(
    session_avec_fichiers: Session, racine_scans: Path
) -> None:
    plan = construire_plan(
        session_avec_fichiers,
        template="{cote}/{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        perimetre=Perimetre(item_cote="HK-001", item_fonds_cote="HK"),
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
        perimetre=Perimetre(fonds_cote="HK"),
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
        perimetre=Perimetre(fonds_cote="HK"),
    )
    no_op = [o for o in plan.operations if o.statut == StatutPlan.NO_OP]
    assert len(no_op) == 5
    assert plan.nb_renommages == 0


def test_plan_collision_externe_en_base_binaire_absent(
    session: Session, racine_scans: Path
) -> None:
    """R3 : une cible correspondant au `chemin_relatif` d'un Fichier HORS-lot
    dont le binaire est ABSENT du disque (cas import Nakala) est bloquée au
    PLAN — sinon `uq_fichier_chemin` lèverait tardivement en phase 2."""
    creer_fonds(session, FormulaireFonds(cote="Z", titre="Z"))
    fonds = lire_fonds_par_cote(session, "Z")
    item1 = creer_item(
        session, FormulaireItem(cote="Z-1", titre="N", fonds_id=fonds.id)
    )
    item2 = creer_item(
        session, FormulaireItem(cote="Z-2", titre="M", fonds_id=fonds.id)
    )
    # f1 : dans le lot (item Z-1), binaire présent.
    (racine_scans / "src.tif").write_bytes(b"X")
    session.add(
        Fichier(
            item_id=item1.id,
            racine="scans",
            chemin_relatif="src.tif",
            nom_fichier="src.tif",
            ordre=1,
            format="tif",
            type_page="page",
        )
    )
    # f2 : HORS lot (item Z-2), occupe "occupe.tif" en base mais SANS binaire.
    session.add(
        Fichier(
            item_id=item2.id,
            racine="scans",
            chemin_relatif="occupe.tif",
            nom_fichier="occupe.tif",
            ordre=1,
            format="tif",
            type_page="page",
        )
    )
    session.commit()

    plan = construire_plan(
        session,
        template="occupe.{ext}",  # f1 → "occupe.tif" = chemin de f2 (hors lot)
        racines=_racines(racine_scans),
        perimetre=Perimetre(item_cote="Z-1", item_fonds_cote="Z"),
    )
    assert not plan.applicable
    assert CodeConflit.COLLISION_EXTERNE in {c.code for c in plan.conflits}
    op = next(o for o in plan.operations if o.chemin_avant == "src.tif")
    assert op.statut == StatutPlan.BLOQUE
    assert op.raison == "collision externe en base"


def test_plan_collision_en_base_avec_no_op_occupant(
    session: Session, racine_scans: Path
) -> None:
    """R3 : un fichier du périmètre qui RESTE en place (NO_OP, binaire absent)
    est un occupant légitime. Une autre op qui vise son chemin est bloquée par
    la garde BASE — pas par l'intra-batch (qui ignore les NO_OP) ni par le
    disque (binaire absent). Verrouille l'affirmation fragile du fix R3."""
    creer_fonds(session, FormulaireFonds(cote="W", titre="W"))
    fonds = lire_fonds_par_cote(session, "W")
    item = creer_item(session, FormulaireItem(cote="W-1", titre="N", fonds_id=fonds.id))
    # f_keep : reste en place (template = son chemin → NO_OP), binaire ABSENT.
    session.add(
        Fichier(
            item_id=item.id,
            racine="scans",
            chemin_relatif="keep.tif",
            nom_fichier="keep.tif",
            ordre=1,
            format="tif",
            type_page="page",
        )
    )
    # f_move : binaire présent, vise "keep.tif".
    (racine_scans / "move.tif").write_bytes(b"X")
    session.add(
        Fichier(
            item_id=item.id,
            racine="scans",
            chemin_relatif="move.tif",
            nom_fichier="move.tif",
            ordre=2,
            format="tif",
            type_page="page",
        )
    )
    session.commit()

    plan = construire_plan(
        session,
        template="keep.{ext}",  # f_keep → NO_OP ; f_move → "keep.tif"
        racines=_racines(racine_scans),
        perimetre=Perimetre(item_cote="W-1", item_fonds_cote="W"),
    )
    assert not plan.applicable
    op_keep = next(o for o in plan.operations if o.chemin_avant == "keep.tif")
    op_move = next(o for o in plan.operations if o.chemin_avant == "move.tif")
    assert op_keep.statut == StatutPlan.NO_OP  # l'occupant reste en place
    assert op_move.statut == StatutPlan.BLOQUE
    assert op_move.raison == "collision externe en base"


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
        perimetre=Perimetre(fonds_cote="HK"),
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
        perimetre=Perimetre(fonds_cote="HK"),
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
            select(OperationFichier).where(OperationFichier.batch_id == rap.batch_id)
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
        perimetre=Perimetre(fonds_cote="HK"),
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


# ---------------------------------------------------------------------------
# Famille 5 — cycles + compensation (R1, durcissement zone destructive)
# ---------------------------------------------------------------------------


@pytest.fixture
def deux_fichiers(session: Session, racine_scans: Path) -> Session:
    """Fonds X + item X-1 + 2 fichiers physiques distincts : a.tif (AAA),
    b.tif (BBB). Contenus distincts pour vérifier un échange par leur
    contenu, et petit lot pour piloter finement les pannes de rename."""
    creer_fonds(session, FormulaireFonds(cote="X", titre="X"))
    fonds = lire_fonds_par_cote(session, "X")
    item = creer_item(session, FormulaireItem(cote="X-1", titre="N", fonds_id=fonds.id))
    for nom, contenu, ordre in (("a.tif", b"AAA", 1), ("b.tif", b"BBB", 2)):
        (racine_scans / nom).write_bytes(contenu)
        session.add(
            Fichier(
                item_id=item.id,
                racine="scans",
                chemin_relatif=nom,
                nom_fichier=nom,
                ordre=ordre,
                format="tif",
                type_page="page",
            )
        )
    session.commit()
    return session


def _patch_rename(monkeypatch: pytest.MonkeyPatch, fail_on: set[int]) -> dict:
    """Patche `Path.rename` pour lever une OSError aux N-ièmes appels listés
    dans `fail_on` (1-indexé). Renvoie l'état du compteur (clé `n`)."""
    import pathlib

    orig = pathlib.Path.rename
    etat = {"n": 0}

    def fake(self: Path, target):  # noqa: ANN001
        etat["n"] += 1
        if etat["n"] in fail_on:
            raise OSError(f"panne injectée au rename #{etat['n']}")
        return orig(self, target)

    monkeypatch.setattr(pathlib.Path, "rename", fake)
    return etat


# --- détection de cycles (fonction pure) ---


def _op(avant: str, apres: str) -> OperationRenommage:
    return OperationRenommage(
        fichier_id=0,
        racine="scans",
        chemin_avant=avant,
        chemin_apres=apres,
        statut=StatutPlan.PRET,
    )


def test_detecter_cycle_swap() -> None:
    ops = [_op("a.tif", "b.tif"), _op("b.tif", "a.tif")]
    assert _detecter_cycles(ops) == {0, 1}


def test_detecter_cycle_triple() -> None:
    ops = [_op("a", "b"), _op("b", "c"), _op("c", "a")]
    assert _detecter_cycles(ops) == {0, 1, 2}


def test_detecter_pas_de_cycle_chaine_ouverte() -> None:
    # a→b, b→c : chaîne ouverte (c n'est source de personne) → pas de cycle.
    ops = [_op("a", "b"), _op("b", "c")]
    assert _detecter_cycles(ops) == set()


# --- exécution d'un cycle (swap réel sur disque + base) ---


def test_execution_cycle_swap_echange_fichiers(
    deux_fichiers: Session, racine_scans: Path
) -> None:
    """Un cycle A↔B est résolu par le pivot temporaire : les fichiers sont
    réellement échangés (contenu + base), via 2 OperationFichier journalées."""
    fa = deux_fichiers.scalar(select(Fichier).where(Fichier.nom_fichier == "a.tif"))
    fb = deux_fichiers.scalar(select(Fichier).where(Fichier.nom_fichier == "b.tif"))
    plan = RapportPlan(
        operations=[
            OperationRenommage(fa.id, "scans", "a.tif", "b.tif", StatutPlan.EN_CYCLE),
            OperationRenommage(fb.id, "scans", "b.tif", "a.tif", StatutPlan.EN_CYCLE),
        ]
    )
    assert plan.applicable
    rap = executer_plan(
        deux_fichiers, plan, racines=_racines(racine_scans), dry_run=False
    )
    assert not rap.erreurs
    assert rap.operations_reussies == 2
    # Disque : contenus échangés (le fichier suit son binaire).
    assert (racine_scans / "a.tif").read_bytes() == b"BBB"
    assert (racine_scans / "b.tif").read_bytes() == b"AAA"
    # Base : chemins échangés.
    deux_fichiers.refresh(fa)
    deux_fichiers.refresh(fb)
    assert fa.chemin_relatif == "b.tif"
    assert fb.chemin_relatif == "a.tif"
    # Journal : 2 ops sur le batch.
    ops = list(
        deux_fichiers.scalars(
            select(OperationFichier).where(OperationFichier.batch_id == rap.batch_id)
        )
    )
    assert len(ops) == 2


# --- compensation : pannes de rename ---


def _plan_deux(session: Session, racine_scans: Path) -> RapportPlan:
    return construire_plan(
        session,
        template="renomme/p{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        perimetre=Perimetre(fonds_cote="X"),
    )


def _etat_disque(racine: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in racine.rglob("*.tif")}


def test_compensation_echec_phase1_restaure_tout(
    deux_fichiers: Session, racine_scans: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Panne au 2e rename de phase 1 → compensation : tout revient à l'état
    initial (disque + base), l'échec est signalé."""
    plan = _plan_deux(deux_fichiers, racine_scans)
    etat = _patch_rename(monkeypatch, fail_on={2})  # 2e src→tmp
    rap = executer_plan(
        deux_fichiers, plan, racines=_racines(racine_scans), dry_run=False
    )
    assert rap.erreurs and "phase 1" in rap.erreurs[0]
    assert rap.batch_id is None
    # Compte de renames verrouillé : 2 phase 1 (dont 1 échoue) + 1 compensation
    # du seul appliqué. Fige le couplage des indices `fail_on` (un rename
    # ajouté ailleurs ferait échouer cette assertion plutôt que glisser en
    # silence).
    assert etat["n"] == 3
    # Disque : a.tif/b.tif intacts à leur place + contenu d'origine.
    assert _etat_disque(racine_scans) == {"a.tif": b"AAA", "b.tif": b"BBB"}
    # Base : chemins d'origine (rollback).
    chemins = {
        f.nom_fichier: f.chemin_relatif for f in deux_fichiers.scalars(select(Fichier))
    }
    assert chemins == {"a.tif": "a.tif", "b.tif": "b.tif"}


def test_compensation_echec_phase2_restaure_tout(
    deux_fichiers: Session, racine_scans: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Panne au 2e rename de phase 2 → compensation complète : les FICHIERS
    reviennent à l'origine (disque + base), aucun binaire perdu."""
    plan = _plan_deux(deux_fichiers, racine_scans)
    etat = _patch_rename(monkeypatch, fail_on={4})  # 2e tmp→dst
    rap = executer_plan(
        deux_fichiers, plan, racines=_racines(racine_scans), dry_run=False
    )
    assert rap.erreurs and "phase 2" in rap.erreurs[0]
    assert rap.operations_compensees == 3  # 1 (undo phase2) + 2 (undo phase1)
    # Compte verrouillé : 2 (phase1) + 2 (phase2, 1 échoue) + 3 (compensation).
    assert etat["n"] == 7
    # Disque : les .tif reviennent intégralement à l'origine (tmp résorbés).
    assert _etat_disque(racine_scans) == {"a.tif": b"AAA", "b.tif": b"BBB"}
    # R4 (dette connue) : le dossier `renomme/` créé en phase 2 subsiste
    # vide — le moteur ne nettoie pas les répertoires créés. Verrouillé ici
    # pour documenter le comportement (cf. backlog-revue-generale R4).
    assert (racine_scans / "renomme").is_dir()
    chemins = {
        f.nom_fichier: f.chemin_relatif for f in deux_fichiers.scalars(select(Fichier))
    }
    assert chemins == {"a.tif": "a.tif", "b.tif": "b.tif"}


def test_compensation_double_panne_signale_l_echec(
    deux_fichiers: Session, racine_scans: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Double panne (rename phase 2 ET une compensation) : le FS n'étant pas
    transactionnel, une désync résiduelle est possible — le contrat est que
    l'opération la SIGNALE bruyamment (plusieurs erreurs, dont une
    « Compensation impossible »), pour que l'utilisateur intervienne."""
    plan = _plan_deux(deux_fichiers, racine_scans)
    _patch_rename(monkeypatch, fail_on={4, 5})  # phase2 #2 + 1re compensation
    rap = executer_plan(
        deux_fichiers, plan, racines=_racines(racine_scans), dry_run=False
    )
    assert rap.batch_id is None  # pas de succès
    assert len(rap.erreurs) >= 2
    assert any("Compensation impossible" in e for e in rap.erreurs)
    # Base rollback-ée à l'origine ; mais la désync disque est réelle et
    # signalée — on vérifie qu'au moins un binaire d'origine manque de sa
    # place (preuve que l'échec n'est pas silencieux).
    sur_disque = _etat_disque(racine_scans)
    assert sur_disque.get("a.tif") != b"AAA" or sur_disque.get("b.tif") != b"BBB"


# --- bout-en-bout : construire_plan (cycle + normal mélangés) → exécution ---


def test_plan_mixte_cycle_et_normal_bout_en_bout(
    session: Session, racine_scans: Path
) -> None:
    """Un même `construire_plan` produit un cycle (swap) ET un renommage
    normal, puis l'exécute. Exerce le pont détection→tag→exécution complet
    + le remapping d'indices `pret_indices → globaux` (plan.py), non couvert
    par le test de swap qui fabrique le plan à la main.

    Setup : fichiers nommés à l'envers de leur ordre pour forcer un swap via
    template `{cote}-{ordre:03d}.{ext}` (cote item = `Y`) :
    - f1 ordre 1, chemin `Y-002.tif` → cible `Y-001.tif`  ┐ swap (EN_CYCLE)
    - f2 ordre 2, chemin `Y-001.tif` → cible `Y-002.tif`  ┘
    - f3 ordre 3, chemin `autre.tif` → cible `Y-003.tif`    (PRET normal)
    """
    creer_fonds(session, FormulaireFonds(cote="Y", titre="Y"))
    fonds = lire_fonds_par_cote(session, "Y")
    item = creer_item(session, FormulaireItem(cote="Y", titre="N", fonds_id=fonds.id))
    for nom, contenu, ordre in (
        ("Y-002.tif", b"UN", 1),
        ("Y-001.tif", b"DEUX", 2),
        ("autre.tif", b"TROIS", 3),
    ):
        (racine_scans / nom).write_bytes(contenu)
        session.add(
            Fichier(
                item_id=item.id,
                racine="scans",
                chemin_relatif=nom,
                nom_fichier=nom,
                ordre=ordre,
                format="tif",
                type_page="page",
            )
        )
    session.commit()

    plan = construire_plan(
        session,
        template="{cote}-{ordre:03d}.{ext}",
        racines=_racines(racine_scans),
        perimetre=Perimetre(fonds_cote="Y"),
    )
    assert plan.applicable
    statuts = {op.chemin_avant: op.statut for op in plan.operations}
    assert statuts["Y-002.tif"] == StatutPlan.EN_CYCLE  # swap
    assert statuts["Y-001.tif"] == StatutPlan.EN_CYCLE  # swap
    assert statuts["autre.tif"] == StatutPlan.PRET  # normal

    rap = executer_plan(session, plan, racines=_racines(racine_scans), dry_run=False)
    assert not rap.erreurs
    assert rap.operations_reussies == 3
    # Le swap a échangé les binaires ; le normal a renommé autre→Y-003.
    assert (racine_scans / "Y-001.tif").read_bytes() == b"UN"  # f1 (était Y-002)
    assert (racine_scans / "Y-002.tif").read_bytes() == b"DEUX"  # f2 (était Y-001)
    assert (racine_scans / "Y-003.tif").read_bytes() == b"TROIS"  # f3
    assert not (racine_scans / "autre.tif").exists()
