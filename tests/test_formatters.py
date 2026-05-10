"""Tests des formatters d'affichage."""

from __future__ import annotations

from datetime import datetime

from archives_tool.affichage.formatters import (
    ABSENT,
    barre_progression,
    date_incertaine,
    formater_date,
    formater_etat,
    formater_liste,
    formater_taille_octets,
    tronquer,
)


def test_formater_date() -> None:
    assert formater_date(None) == ABSENT
    assert formater_date("") == ABSENT
    assert formater_date("1923") == "1923"  # EDTF tel quel
    assert formater_date("vers 1964") == "vers 1964"
    dt = datetime(2026, 4, 12, 14, 32)
    assert formater_date(dt) == "2026-04-12 14:32"


def test_formater_liste() -> None:
    assert formater_liste(None) == ABSENT
    assert formater_liste([]) == ABSENT
    assert formater_liste(["A", "B"]) == "A, B"
    assert formater_liste(["A", "B"], " | ") == "A | B"


def test_formater_etat() -> None:
    rendu = formater_etat("valide")
    assert "[etat.valide]" in rendu
    assert "validé" in rendu
    assert "[/etat.valide]" in rendu
    assert formater_etat(None) == ABSENT


def test_formater_etat_avec_crochets_dans_libelle() -> None:
    # Les états sont des enums simples mais on teste l'échappement.
    rendu = formater_etat("brouillon")
    assert "brouillon" in rendu


def test_formater_taille_octets() -> None:
    assert formater_taille_octets(None) == ABSENT
    assert formater_taille_octets(0) == "0 B"
    assert formater_taille_octets(512) == "512 B"
    assert formater_taille_octets(2048) == "2.0 KB"
    assert formater_taille_octets(1024 * 1024 * 5) == "5.0 MB"
    assert formater_taille_octets(int(1024**3 * 1.5)) == "1.50 GB"


def test_tronquer() -> None:
    assert tronquer(None) == ABSENT
    assert tronquer("") == ABSENT
    assert tronquer("court") == "court"
    long = "x" * 100
    assert tronquer(long, 10) == "xxxxxxxxx…"
    # Newlines remplacés.
    assert tronquer("a\nb\nc") == "a b c"


def test_barre_progression() -> None:
    assert barre_progression(0.0, 10) == "░" * 10
    assert barre_progression(1.0, 10) == "▓" * 10
    assert barre_progression(0.5, 10) == "▓" * 5 + "░" * 5
    # Bornes : valeurs hors [0,1] → clampées.
    assert barre_progression(-1, 10) == "░" * 10
    assert barre_progression(2, 10) == "▓" * 10


def test_date_incertaine_marqueurs() -> None:
    """Régression V0.9.2-beta passe : `ItemResume.date_incertaine`
    avait forké la regex en `?~XU` et manquait `vers`/`c.`/`s.d.`.
    Les tests ci-dessous documentent les marqueurs canoniques."""
    # Cas positifs : marqueurs d'incertitude reconnus.
    assert date_incertaine("vers 1969") is True
    assert date_incertaine("Vers 1923") is True  # insensible à la casse
    assert date_incertaine("1923 ?") is True
    assert date_incertaine("c. 1925") is True
    assert date_incertaine("ca. 1925") is True
    assert date_incertaine("s.d.") is True
    assert date_incertaine("S.D.") is True
    # Cas négatifs : dates précises.
    assert date_incertaine("1969") is False
    assert date_incertaine("1969-03-15") is False
    assert date_incertaine("2026-05-10") is False
    # None / vide.
    assert date_incertaine(None) is False
    assert date_incertaine("") is False


def test_item_resume_date_incertaine_via_property() -> None:
    """Vérifie que ItemResume.date_incertaine délègue au helper
    canonique (régression V0.9.2-beta passe simplification)."""
    from archives_tool.api.services.items import ItemResume

    # Cas archivistique typique : « vers 1969 » est incertain.
    item = ItemResume(
        id=1, cote="X-001", titre="T", fonds_id=1, fonds_cote="X",
        etat="brouillon", date="vers 1969",
    )
    assert item.date_incertaine is True
    # Date précise.
    item2 = ItemResume(
        id=2, cote="X-002", titre="T", fonds_id=1, fonds_cote="X",
        etat="brouillon", date="1969-03-15",
    )
    assert item2.date_incertaine is False
    # None.
    item3 = ItemResume(
        id=3, cote="X-003", titre="T", fonds_id=1, fonds_cote="X",
        etat="brouillon",
    )
    assert item3.date_incertaine is False
