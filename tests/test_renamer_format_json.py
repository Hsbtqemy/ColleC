"""Tests des formateurs JSON du module renamer.

Couvre les trois sorties : plan, exécution, annulation, historique.
"""

from __future__ import annotations

import json
from datetime import datetime

from archives_tool.renamer import (
    Conflit,
    OperationRenommage,
    RapportAnnulation,
    RapportExecution,
    RapportPlan,
    StatutPlan,
    formatter_annulation_json,
    formatter_execution_json,
    formatter_historique_json,
    formatter_plan_json,
)
from archives_tool.renamer.historique import EntreeHistorique


def test_plan_json_structure() -> None:
    rapport = RapportPlan()
    rapport.operations = [
        OperationRenommage(
            fichier_id=42,
            racine="scans",
            chemin_avant="a.png",
            chemin_apres="b.png",
            statut=StatutPlan.PRET,
        )
    ]
    rapport.conflits = []

    payload = json.loads(formatter_plan_json(rapport))
    assert payload["bilan"]["nb_renommages"] == 1
    assert payload["bilan"]["applicable"] is True
    assert payload["operations"][0]["chemin_avant"] == "a.png"


def test_plan_json_conflit_serialise() -> None:
    rapport = RapportPlan()
    rapport.operations = [
        OperationRenommage(
            fichier_id=1,
            racine="s",
            chemin_avant="x",
            chemin_apres="x",
            statut=StatutPlan.BLOQUE,
        )
    ]
    rapport.conflits = [
        Conflit(code="template_invalide", message="vide", fichier_ids=[1])
    ]

    payload = json.loads(formatter_plan_json(rapport))
    assert payload["bilan"]["applicable"] is False
    assert payload["conflits"][0]["code"] == "template_invalide"


def test_execution_json() -> None:
    rapport = RapportExecution(
        dry_run=False,
        batch_id="abc-123",
        operations_reussies=5,
    )
    payload = json.loads(formatter_execution_json(rapport))
    assert payload["dry_run"] is False
    assert payload["batch_id"] == "abc-123"
    assert payload["operations_reussies"] == 5


def test_annulation_json() -> None:
    rapport = RapportAnnulation(
        dry_run=True,
        batch_id_original="orig-1",
        operations_inversees=3,
    )
    payload = json.loads(formatter_annulation_json(rapport))
    assert payload["batch_id_original"] == "orig-1"
    assert payload["operations_inversees"] == 3
    assert payload["dry_run"] is True


def test_historique_json_serialise_datetime() -> None:
    e = EntreeHistorique(
        batch_id="b1",
        nb_operations=4,
        types_operations=["rename"],
        execute_le_premier=datetime(2026, 1, 15, 14, 30),
        execute_par="Marie",
    )
    payload = json.loads(formatter_historique_json([e]))
    assert payload["batchs"][0]["batch_id"] == "b1"
    # `datetime` → ISO 8601.
    assert payload["batchs"][0]["execute_le_premier"].startswith("2026-01-15T14:30")


def test_historique_json_vide() -> None:
    payload = json.loads(formatter_historique_json([]))
    assert payload == {"batchs": []}
