"""Smoke d'intégration **réel** du palier P3+b — comparer fichiers vs
apitest. Confirme que le pipeline complet marche :

    déposer (palier a : capture sha1 dans Fichier.sha1_nakala) →
    comparer (palier b : recalcule sha1 local + pull distant) → inchangé →
    modifier le binaire local → comparer → modifié.

Exclus par défaut (`-m "not integration"`). Compte de test public
Huma-Num apitest (non secret) en défaut. Lancer :

    uv run pytest -m integration tests/test_nakala_fichiers_integration.py
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala_depot import deposer_item
from archives_tool.api.services.nakala_fichiers import (
    comparer_fichiers_item,
    pousser_fichiers_item,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Base, Fichier, Item

pytestmark = pytest.mark.integration

CLE = os.environ.get("NAKALA_API_KEY", "01234567-89ab-cdef-0123-456789abcdef")
HOTE = os.environ.get("NAKALA_HOST", "https://apitest.nakala.fr")
_TYPE_LIVRE = "http://purl.org/coar/resource_type/c_2f33"


def _amorcer_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _session(db: Path):
    return creer_session_factory(creer_engine(db))()


def _sha1(data: bytes) -> str:
    h = hashlib.sha1(usedforsecurity=False)  # noqa: S324
    h.update(data)
    return h.hexdigest()


def _seed(db: Path, scans: Path, contenu_initial: bytes) -> None:
    scans.mkdir(exist_ok=True)
    (scans / "as001.jpg").write_bytes(contenu_initial)
    with _session(db) as s:
        f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS smoke b"))
        item = creer_item(s, FormulaireItem(
            cote="AS-001", titre="X", fonds_id=f.id, date="1984", langue="spa",
            description="Roman", type_coar=_TYPE_LIVRE,
            metadonnees={"createurs": ["Somers, A."], "sujets": ["Lit"]},
        ))
        s.add(Fichier(
            item_id=item.id, nom_fichier="as001.jpg", racine="scans",
            chemin_relatif="as001.jpg", ordre=1,
        ))
        s.commit()


def test_comparer_fichiers_live(tmp_path: Path) -> None:
    """Cycle complet sur apitest : dépôt → comparer (inchangé) → modif →
    comparer (modifié) → cleanup."""
    db = _amorcer_db(tmp_path)
    scans = tmp_path / "scans"
    contenu_initial = b"\xff\xd8\xff smoke initial"
    sha1_initial = _sha1(contenu_initial)
    _seed(db, scans, contenu_initial)

    racines = {"scans": scans}
    ecriture = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
    lecture = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
    doi: str | None = None
    try:
        # 1. Dépôt + capture sha1 (palier a).
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            rapport_depot = deposer_item(
                s, ecriture, item, racines=racines,
                dry_run=False, cree_par="smoke",
            )
        doi = rapport_depot.doi
        assert doi

        # Verif persistance palier a : sha1_nakala posé en base.
        with _session(db) as s:
            fichier = s.scalar(
                select(Fichier).join(Item).where(Item.cote == "AS-001")
            )
            assert fichier.sha1_nakala == sha1_initial

        # 2. Comparer : tout inchangé (sha1 local match distant).
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            rapport = comparer_fichiers_item(
                s, lecture, item, racines=racines,
            )
        assert rapport.aucun_changement, (
            f"Attendu aucun_changement après dépôt initial, vu : "
            f"nouveaux={len(rapport.nouveaux)}, "
            f"modifies={len(rapport.modifies)}, "
            f"orphelins={len(rapport.orphelins_distants)}"
        )
        assert len(rapport.inchanges) == 1
        assert rapport.inchanges[0].sha1_local == sha1_initial

        # 3. Modifier le binaire local — sha1 change.
        contenu_modifie = b"\xff\xd8\xff smoke MODIFIE"
        sha1_modifie = _sha1(contenu_modifie)
        assert sha1_modifie != sha1_initial
        (scans / "as001.jpg").write_bytes(contenu_modifie)

        # 4. Comparer : doit signaler modifié.
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            rapport2 = comparer_fichiers_item(
                s, lecture, item, racines=racines,
            )
        assert not rapport2.aucun_changement
        assert len(rapport2.modifies) == 1
        fc = rapport2.modifies[0]
        assert fc.sha1_local == sha1_modifie
        assert fc.sha1_distant == sha1_initial  # snapshot ColleC = avant
        assert rapport2.inchanges == []
        assert rapport2.orphelins_distants == []
    finally:
        # Cleanup pending dépôt.
        if doi:
            try:
                ecriture.supprimer_depot(doi)
            except Exception:  # noqa: BLE001
                pass
        ecriture.fermer()
        lecture.fermer()


def test_pousser_fichiers_live_avec_retirer_orphelins(tmp_path: Path) -> None:
    """Smoke d'intégration P3+c — cas `--retirer-orphelins` réel.

    Cycle :
    1. Déposer item avec 2 fichiers (alpha + beta)
    2. Supprimer le Fichier ColleC beta (sans toucher au binaire)
    3. comparer → beta apparait en orphelin distant
    4. pousser_fichiers sans flag → OrphelinsDetectes
    5. pousser_fichiers avec retirer_orphelins=True → PUT, beta retire
    6. lire_depot distant → confirme 1 seul fichier restant (alpha)
    7. Cleanup

    Valide bout-en-bout H1 (retrait par exclusion de files[]) + la
    garde-fou `retirer_orphelins` requis."""
    from archives_tool.api.services.nakala_fichiers import OrphelinsDetectes
    from sqlalchemy import delete

    db = _amorcer_db(tmp_path)
    scans = tmp_path / "scans"
    scans.mkdir(exist_ok=True)
    (scans / "alpha.jpg").write_bytes(b"\xff\xd8\xff ALPHA smoke orph")
    (scans / "beta.jpg").write_bytes(b"\xff\xd8\xff BETA smoke orph")

    racines = {"scans": scans}
    ecriture = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
    lecture = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
    doi: str | None = None
    try:
        # 1. Setup item avec 2 fichiers locaux + dépôt
        with _session(db) as s:
            f = creer_fonds(s, FormulaireFonds(cote="AS", titre="AS smoke orph"))
            item = creer_item(s, FormulaireItem(
                cote="AS-001", titre="Orph smoke", fonds_id=f.id, date="1984",
                langue="spa", description="Smoke orph", type_coar=_TYPE_LIVRE,
                metadonnees={"createurs": ["Test, H."]},
            ))
            for i, nom in enumerate(["alpha.jpg", "beta.jpg"], start=1):
                s.add(Fichier(
                    item_id=item.id, nom_fichier=nom, racine="scans",
                    chemin_relatif=nom, ordre=i,
                ))
            s.commit()
            rapport_depot = deposer_item(
                s, ecriture, item, racines=racines,
                dry_run=False, cree_par="smoke-orph",
            )
        doi = rapport_depot.doi
        assert doi

        # 2. Supprimer le Fichier ColleC beta (sans toucher au binaire)
        with _session(db) as s:
            s.execute(
                delete(Fichier).where(
                    Fichier.item_id == s.scalar(
                        select(Item.id).where(Item.cote == "AS-001")
                    ),
                    Fichier.nom_fichier == "beta.jpg",
                )
            )
            s.commit()

        # 3. Comparer : beta apparait en orphelin distant
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            cmp_avant = comparer_fichiers_item(
                s, lecture, item, racines=racines,
            )
        assert len(cmp_avant.orphelins_distants) == 1
        assert cmp_avant.orphelins_distants[0].nom_fichier == "beta.jpg"

        # 4. Pousser sans flag → OrphelinsDetectes
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            with pytest.raises(OrphelinsDetectes):
                pousser_fichiers_item(
                    s, lecture, ecriture, item, racines=racines,
                    dry_run=False, retirer_orphelins=False,
                )

        # 5. Pousser avec retirer_orphelins=True → PUT, beta retire
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            rapport_push = pousser_fichiers_item(
                s, lecture, ecriture, item, racines=racines,
                dry_run=False, retirer_orphelins=True,
            )
        assert rapport_push.applique is True
        # 0 upload (alpha est inchange), beta sera retire au PUT
        assert rapport_push.sha1s_uploades == []
        # Le rapport documente le retrait
        assert len(rapport_push.sha1s_retires) == 1

        # 6. Lire_depot distant : 1 seul fichier restant (alpha)
        apres = lecture.lire_depot(doi)
        files_apres = apres.get("files") or []
        assert len(files_apres) == 1, files_apres
        assert files_apres[0].get("name") == "alpha.jpg"

    finally:
        if doi:
            try:
                ecriture.supprimer_depot(doi)
            except Exception:  # noqa: BLE001
                pass
        ecriture.fermer()
        lecture.fermer()


def test_pousser_fichiers_live(tmp_path: Path) -> None:
    """Smoke d'intégration P3+c — cycle complet pousser_fichiers_item :

        déposer → comparer (inchangé) → modifier binaire local →
        pousser_fichiers (no-dry-run) → upload + PUT → re-comparer →
        tout inchangé (sha1_nakala mis à jour, distant aligné).

    Valide bout-en-bout :
    - signature étendue ``modifier_depot(files=...)`` réelle
    - H1 : remplacement de files[] côté Nakala
    - H10 : ``lire_depot`` immédiat post-PUT reflète bien
    - ``Fichier.sha1_nakala`` mis à jour en base
    - cache ``RessourceExterne`` invalidé (consommateurs lisent à jour)
    """
    db = _amorcer_db(tmp_path)
    scans = tmp_path / "scans"
    contenu_initial = b"\xff\xd8\xff smoke push initial"
    sha1_initial = _sha1(contenu_initial)
    _seed(db, scans, contenu_initial)

    racines = {"scans": scans}
    ecriture = NakalaEcritureClient(HOTE, api_key=CLE, timeout=60)
    lecture = ClientLectureNakala(HOTE, api_key=CLE, timeout=60)
    doi: str | None = None
    try:
        # 1. Dépôt initial.
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            rapport_depot = deposer_item(
                s, ecriture, item, racines=racines,
                dry_run=False, cree_par="smoke-push",
            )
        doi = rapport_depot.doi
        assert doi

        # 2. Modifier le binaire local — sha1 change.
        contenu_modifie = b"\xff\xd8\xff smoke push MODIFIE"
        sha1_modifie = _sha1(contenu_modifie)
        assert sha1_modifie != sha1_initial
        (scans / "as001.jpg").write_bytes(contenu_modifie)

        # 3. Verif via comparer : 1 modifié détecté
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            cmp_avant = comparer_fichiers_item(
                s, lecture, item, racines=racines,
            )
        assert len(cmp_avant.modifies) == 1
        assert cmp_avant.modifies[0].sha1_local == sha1_modifie
        assert cmp_avant.modifies[0].sha1_distant == sha1_initial

        # 4. PUSH effectif : upload + PUT
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            rapport_push = pousser_fichiers_item(
                s, lecture, ecriture, item, racines=racines,
                dry_run=False, modifie_par="smoke-push",
            )
        assert rapport_push.applique is True
        assert len(rapport_push.sha1s_uploades) == 1

        # 5. Vérif base : Fichier.sha1_nakala mis à jour
        with _session(db) as s:
            fichier = s.scalar(
                select(Fichier).join(Item).where(Item.cote == "AS-001")
            )
            assert fichier.sha1_nakala == sha1_modifie
            assert fichier.modifie_le is not None

        # 6. Re-comparer : tout inchangé (distant aligné, base à jour)
        with _session(db) as s:
            item = s.scalar(select(Item).where(Item.cote == "AS-001"))
            cmp_apres = comparer_fichiers_item(
                s, lecture, item, racines=racines,
            )
        assert cmp_apres.aucun_changement, (
            f"Attendu aucun_changement après push, vu : "
            f"nouveaux={len(cmp_apres.nouveaux)}, "
            f"modifies={len(cmp_apres.modifies)}, "
            f"orphelins={len(cmp_apres.orphelins_distants)}"
        )
        assert len(cmp_apres.inchanges) == 1
        assert cmp_apres.inchanges[0].sha1_local == sha1_modifie
    finally:
        if doi:
            try:
                ecriture.supprimer_depot(doi)
            except Exception:  # noqa: BLE001
                pass
        ecriture.fermer()
        lecture.fermer()
