"""Test du remap des URIs COAR erronées (migration r6v7w8x9y0z1).

Vérifie surtout la **chaîne de réaffectations qui se recouvrent**
(Vidéo c_12cd→c_12ce, Carte c_ecc8→c_12cd, Photographie c_18cd→c_ecc8) :
l'ordre doit garantir qu'aucun item n'est re-capturé par une étape
ultérieure.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.models import Fonds, Item

_C = "http://purl.org/coar/resource_type"

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "r6v7w8x9y0z1_corriger_uris_coar.py"
)


def _charger_migration():
    spec = importlib.util.spec_from_file_location("_mig_remap_coar", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remap_uris_coar_y_compris_chaine_recouvrante(
    session: Session, fonds_hk: Fonds
) -> None:
    mig = _charger_migration()

    # Items avec les anciennes URIs (selon leur intention de label).
    cas = {
        "HK-VID": f"{_C}/c_12cd",  # Vidéo  → attendu c_12ce
        "HK-CAR": f"{_C}/c_ecc8",  # Carte  → attendu c_12cd
        "HK-PHO": f"{_C}/c_18cd",  # Photo  → attendu c_ecc8
        "HK-PER": f"{_C}/c_3e5a",  # Périodique → c_2fe3
        "HK-NUM": f"{_C}/c_0640",  # Numéro → c_2fe3
        "HK-ARC": f"{_C}/c_18co",  # Archives → YC9F-HGCF
        "HK-MAN": f"{_C}/c_8a7e",  # Manuscrit → c_0040
        "HK-OK": f"{_C}/c_18cf",  # Texte (déjà bon) → inchangé
    }
    for cote, uri in cas.items():
        creer_item(
            session,
            FormulaireItem(cote=cote, titre=cote, fonds_id=fonds_hk.id, type_coar=uri),
        )
    session.commit()

    mig.appliquer_remap(session.connection())
    session.commit()
    session.expire_all()

    def lire(cote: str) -> str | None:
        return session.scalar(select(Item.type_coar).where(Item.cote == cote))

    assert lire("HK-VID") == f"{_C}/c_12ce"  # PAS c_12cd (carte)
    assert lire("HK-CAR") == f"{_C}/c_12cd"  # PAS c_12ce ni c_ecc8
    assert lire("HK-PHO") == f"{_C}/c_ecc8"  # PAS c_12cd (re-capture évitée)
    assert lire("HK-PER") == f"{_C}/c_2fe3"
    assert lire("HK-NUM") == f"{_C}/c_2fe3"
    assert lire("HK-ARC") == f"{_C}/YC9F-HGCF"
    assert lire("HK-MAN") == f"{_C}/c_0040"
    assert lire("HK-OK") == f"{_C}/c_18cf"


def test_remap_idempotent(session: Session, fonds_hk: Fonds) -> None:
    """Rejouer ne change rien : les nouvelles URIs ne sont pas des clés
    du remap."""
    mig = _charger_migration()
    creer_item(
        session,
        FormulaireItem(
            cote="HK-1", titre="x", fonds_id=fonds_hk.id, type_coar=f"{_C}/c_3e5a"
        ),
    )
    session.commit()
    mig.appliquer_remap(session.connection())
    session.commit()
    mig.appliquer_remap(session.connection())  # 2e passe
    session.commit()
    session.expire_all()
    assert (
        session.scalar(select(Item.type_coar).where(Item.cote == "HK-1"))
        == f"{_C}/c_2fe3"
    )
