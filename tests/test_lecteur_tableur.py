"""Tests du lecteur de tableur."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from archives_tool.importers.lecteur_tableur import (
    LectureTableurErreur,
    analyser_colonnes_tableur,
    lire_entetes_tableur,
    lire_tableur,
)
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"


def _charger(cas: str):
    chemin = FIXTURES / cas / "profil.yaml"
    return charger_profil(chemin), chemin


def test_lecture_cas_item_simple() -> None:
    profil, chemin = _charger("cas_item_simple")
    lignes = lire_tableur(profil, chemin)
    assert len(lignes) == 5
    assert lignes[0]["Cote"] == "HK-1960-01"
    assert lignes[0]["Numero"] == "1"
    # Valeur "none" de la liste valeurs_nulles → None.
    assert lignes[1]["Notes"] is None
    # Valeur "n/a" aussi.
    assert lignes[2]["Notes"] is None
    # Cellule vide (CSV sans valeur) → None.
    assert lignes[0]["Notes"] is None


def test_lecture_cas_fichier_groupe() -> None:
    profil, chemin = _charger("cas_fichier_groupe")
    lignes = lire_tableur(profil, chemin)
    assert len(lignes) == 3
    assert lignes[0]["cote_item"] == "PF-001"
    assert lignes[0]["doi_item"].startswith("10.34847/nkl")


def test_lecture_cas_hierarchie_cote() -> None:
    profil, chemin = _charger("cas_hierarchie_cote")
    lignes = lire_tableur(profil, chemin)
    assert len(lignes) == 4
    # Date incertaine préservée en l'état (pas d'inférence).
    assert lignes[2]["Date"] == "vers 1924"


def test_lecture_cas_uri_dc() -> None:
    profil, chemin = _charger("cas_uri_dc")
    lignes = lire_tableur(profil, chemin)
    assert len(lignes) == 2
    # Colonnes nommées par URI, accessibles tels quels.
    assert lignes[0]["http://purl.org/dc/terms/title"] == "Étude café"
    # Cellule vide ("" est dans valeurs_nulles) → None.
    assert lignes[1]["sujet 2_fr"] is None
    assert lignes[1]["creator_2"] is None


def test_accents_nfc(tmp_path: Path) -> None:
    # On écrit un CSV avec un titre en NFD et on vérifie que la
    # lecture renvoie du NFC.
    nfd = unicodedata.normalize("NFD", "café")
    csv = tmp_path / "t.csv"
    csv.write_text(f"Cote;Titre\nX1;{nfd}\n", encoding="utf-8")
    yml = tmp_path / "p.yaml"
    yml.write_text(
        """
version_profil: 2
fonds:
  cote: "X"
  titre: "Test NFC"
tableur:
  chemin: "t.csv"
  separateur_csv: ";"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    lignes = lire_tableur(profil, yml)
    assert lignes[0]["Titre"] == "café"
    assert unicodedata.is_normalized("NFC", lignes[0]["Titre"])


def test_fichier_inexistant(tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    yml.write_text(
        """
version_profil: 2
fonds:
  cote: "X"
  titre: "Fichier absent"
tableur:
  chemin: "n_existe_pas.csv"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    with pytest.raises(LectureTableurErreur, match="introuvable"):
        lire_tableur(profil, yml)


def test_extension_non_supportee(tmp_path: Path) -> None:
    txt = tmp_path / "t.txt"
    txt.write_text("x", encoding="utf-8")
    yml = tmp_path / "p.yaml"
    yml.write_text(
        """
version_profil: 2
fonds:
  cote: "X"
  titre: "Mauvais format"
tableur:
  chemin: "t.txt"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    profil = charger_profil(yml)
    with pytest.raises(LectureTableurErreur, match="Extension"):
        lire_tableur(profil, yml)


# ---------------------------------------------------------------------------
# lire_entetes_tableur — lecture des seules colonnes (assistant import web)
# ---------------------------------------------------------------------------


def test_entetes_csv(tmp_path: Path) -> None:
    csv = tmp_path / "inv.csv"
    csv.write_text("Cote;Titre;Date\nHK-1;Numero 1;1960\n", encoding="utf-8")
    assert lire_entetes_tableur(csv) == ["Cote", "Titre", "Date"]


def test_entetes_strip_les_espaces(tmp_path: Path) -> None:
    """Les espaces parasites en bordure d'en-tête sont retirés."""
    csv = tmp_path / "inv.csv"
    csv.write_text(" Cote ;  Titre\nx;y\n", encoding="utf-8")
    assert lire_entetes_tableur(csv) == ["Cote", "Titre"]


def test_entetes_csv_cp1252_fallback(tmp_path: Path) -> None:
    """Un CSV encodé CP1252 (tableur ancien) est lu malgré l'échec UTF-8."""
    csv = tmp_path / "vieux.csv"
    csv.write_bytes("Côte;Éditeur\nx;y\n".encode("cp1252"))
    assert lire_entetes_tableur(csv) == ["Côte", "Éditeur"]


def test_entetes_extension_inconnue(tmp_path: Path) -> None:
    fichier = tmp_path / "notes.txt"
    fichier.write_text("rien", encoding="utf-8")
    with pytest.raises(LectureTableurErreur, match="Extension"):
        lire_entetes_tableur(fichier)


def test_entetes_fichier_absent(tmp_path: Path) -> None:
    with pytest.raises(LectureTableurErreur, match="introuvable"):
        lire_entetes_tableur(tmp_path / "n_existe_pas.csv")


# ---------------------------------------------------------------------------
# analyser_colonnes_tableur — statistiques d'échantillonnage (V0.9.2-import #2)
# ---------------------------------------------------------------------------


def test_analyse_colonnes_stats_de_base(tmp_path: Path) -> None:
    csv = tmp_path / "t.csv"
    csv.write_text(
        "Cote;Numero;Titre\n"
        "HK-1;1;Premier\n"
        "HK-2;2;Deuxieme\n"
        "HK-3;3;Troisieme\n"
        "HK-4;1;Quatrieme\n",
        encoding="utf-8",
    )
    stats = analyser_colonnes_tableur(csv)
    assert set(stats.keys()) == {"Cote", "Numero", "Titre"}
    assert stats["Cote"]["total"] == 4
    assert stats["Cote"]["remplies"] == 4
    assert stats["Cote"]["uniques"] == 4
    assert stats["Cote"]["exemples"] == ["HK-1", "HK-2", "HK-3"]
    # Numero : "1" apparaît 2 fois, c'est la valeur la plus fréquente.
    assert stats["Numero"]["valeur_frequente"] == "1"
    assert stats["Numero"]["uniques"] == 3


def test_analyse_colonnes_sentinelles_nulles_ignorees(tmp_path: Path) -> None:
    csv = tmp_path / "t.csv"
    csv.write_text(
        "Cote;Notes\n"
        "HK-1;none\n"
        "HK-2;n/a\n"
        "HK-3;\n"
        "HK-4;NaN\n"
        "HK-5;reel\n",
        encoding="utf-8",
    )
    stats = analyser_colonnes_tableur(csv)
    # "none", "n/a", cellule vide, "NaN" → tous nulls, seule "reel" reste.
    assert stats["Notes"]["remplies"] == 1
    assert stats["Notes"]["exemples"] == ["reel"]
    assert stats["Notes"]["valeur_frequente"] == "reel"


def test_analyse_colonnes_exemples_distincts_premiers(tmp_path: Path) -> None:
    """Les exemples sont les 3 premières valeurs distinctes — pas les
    3 premières lignes (les doublons consécutifs sont sautés)."""
    csv = tmp_path / "t.csv"
    csv.write_text(
        "Cote;Type\n"
        "HK-1;article\n"
        "HK-2;article\n"
        "HK-3;dessin\n"
        "HK-4;article\n"
        "HK-5;photo\n"
        "HK-6;couv\n",
        encoding="utf-8",
    )
    stats = analyser_colonnes_tableur(csv)
    assert stats["Type"]["exemples"] == ["article", "dessin", "photo"]


def test_analyse_colonnes_colonne_vide_filtree(tmp_path: Path) -> None:
    """#2 V0.9.2-import : une colonne 100 % vide (0 cellules remplies)
    est filtrée du résultat. Sans ce filtre, mode simple la promouvait
    en `metadonnees.<slug>` libre et la page item affichait
    « Unnamed 15: non renseigné » — bruit visuel pour 0 valeur utile.

    La colonne `Cote` reste, et seules les colonnes ayant au moins
    une valeur non-nulle apparaissent."""
    csv = tmp_path / "t.csv"
    csv.write_text(
        "Cote;Vide;Une\nHK-1;;X\nHK-2;;\n", encoding="utf-8"
    )
    stats = analyser_colonnes_tableur(csv)
    assert "Vide" not in stats
    assert "Cote" in stats
    assert "Une" in stats
    assert stats["Une"]["remplies"] == 1


def test_analyse_colonnes_normalisation_nfc(tmp_path: Path) -> None:
    """Les valeurs sont normalisées NFC avant calcul des stats : un même
    mot écrit en NFD et NFC doit compter pour une seule valeur unique."""
    nfd = unicodedata.normalize("NFD", "café")
    nfc = unicodedata.normalize("NFC", "café")
    csv = tmp_path / "t.csv"
    csv.write_text(
        f"Cote;Titre\nHK-1;{nfd}\nHK-2;{nfc}\n", encoding="utf-8"
    )
    stats = analyser_colonnes_tableur(csv)
    assert stats["Titre"]["uniques"] == 1


def test_analyse_colonnes_extension_inconnue(tmp_path: Path) -> None:
    fichier = tmp_path / "x.txt"
    fichier.write_text("rien", encoding="utf-8")
    with pytest.raises(LectureTableurErreur, match="Extension"):
        analyser_colonnes_tableur(fichier)


def test_analyse_colonnes_fichier_absent(tmp_path: Path) -> None:
    with pytest.raises(LectureTableurErreur, match="introuvable"):
        analyser_colonnes_tableur(tmp_path / "n_existe_pas.csv")


# ---------------------------------------------------------------------------
# Classification par-item / par-fichier (V0.9.2-import #1)
# ---------------------------------------------------------------------------


def test_classif_cote_identifiee_par_nom(tmp_path: Path) -> None:
    csv = tmp_path / "t.csv"
    csv.write_text(
        "Cote;Titre\nHK-1;A\nHK-2;B\n", encoding="utf-8"
    )
    stats = analyser_colonnes_tableur(csv)
    assert stats["Cote"]["classif"] == "cote"


def test_classif_cote_fallback_unicite(tmp_path: Path) -> None:
    """Aucune colonne nommée 'cote' — fallback : la première colonne
    100% unique est désignée cote."""
    csv = tmp_path / "t.csv"
    csv.write_text(
        "identifiant;titre\nHK-1;A\nHK-2;B\nHK-3;C\n",
        encoding="utf-8",
    )
    stats = analyser_colonnes_tableur(csv)
    assert stats["identifiant"]["classif"] == "cote"
    # `titre` non unique au global mais 1 valeur par cote → par-item.
    assert stats["titre"]["classif"] == "par-item"


def test_classif_par_item_majorite_stable(tmp_path: Path) -> None:
    """≥90% des cotes ont une seule valeur dans la colonne → par-item.
    Ici : 5 cotes × 3 fichiers ; titre identique par cote."""
    lignes = ["Cote;Titre"]
    for i in range(1, 6):
        for _ in range(3):
            lignes.append(f"HK-{i};Numero {i}")
    csv = tmp_path / "t.csv"
    csv.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    stats = analyser_colonnes_tableur(csv)
    assert stats["Titre"]["classif"] == "par-item"


def test_classif_par_fichier_majorite_varie(tmp_path: Path) -> None:
    """>50% des cotes ont plusieurs valeurs distinctes → par-fichier.
    Ici : numéro de page varie au sein de chaque cote."""
    lignes = ["Cote;Page"]
    for i in range(1, 6):
        for p in range(1, 4):
            lignes.append(f"HK-{i};{p}")
    csv = tmp_path / "t.csv"
    csv.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    stats = analyser_colonnes_tableur(csv)
    assert stats["Page"]["classif"] == "par-fichier"


def test_classif_indetermine_si_pas_de_cote(tmp_path: Path) -> None:
    """Aucune colonne nommée cote ET aucune colonne 100% unique —
    impossible de classer les autres colonnes."""
    csv = tmp_path / "t.csv"
    csv.write_text(
        "a;b\nx;1\nx;1\nx;2\n", encoding="utf-8"
    )
    stats = analyser_colonnes_tableur(csv)
    # `a` n'est pas 100% unique (x,x,x), `b` non plus (1,1,2). Pas de cote.
    assert stats["a"]["classif"] == "indetermine"
    assert stats["b"]["classif"] == "indetermine"


def test_classif_indetermine_si_colonne_vide(tmp_path: Path) -> None:
    """Une colonne entièrement vide est filtrée du résultat
    (#2 V0.9.2-import) — pas besoin de la classifier. La colonne
    Cote reste."""
    csv = tmp_path / "t.csv"
    csv.write_text(
        "Cote;Vide\nHK-1;\nHK-2;\nHK-3;\n", encoding="utf-8"
    )
    stats = analyser_colonnes_tableur(csv)
    assert stats["Cote"]["classif"] == "cote"
    assert "Vide" not in stats


def test_classif_melange_si_partage(tmp_path: Path) -> None:
    """Mélange : la moitié des cotes a 1 valeur, l'autre moitié a 2
    valeurs — ni au-dessus du seuil par-item ni au-dessus du
    par-fichier."""
    # 4 cotes : 2 à valeur unique, 2 à valeurs multiples → 50% / 50%.
    lignes = [
        "Cote;X",
        "HK-1;a",
        "HK-1;a",
        "HK-2;b",
        "HK-2;b",
        "HK-3;c",
        "HK-3;d",
        "HK-4;e",
        "HK-4;f",
    ]
    csv = tmp_path / "t.csv"
    csv.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    stats = analyser_colonnes_tableur(csv)
    # 50% à 1 valeur, 50% à plusieurs : ni >=90% par-item, ni >50% par-fichier.
    assert stats["X"]["classif"] == "melange"


def test_classif_seuil_par_item_strict(tmp_path: Path) -> None:
    """Le seuil par-item est `>=90%`. À 9/10 cotes stables, on classe
    bien par-item (et non melange)."""
    lignes = ["Cote;Titre"]
    # 9 cotes avec 1 seule valeur, 1 cote avec 2 valeurs distinctes.
    for i in range(1, 10):
        lignes.append(f"HK-{i};Numero {i}")
        lignes.append(f"HK-{i};Numero {i}")
    lignes.append("HK-10;Numero 10")
    lignes.append("HK-10;Variante 10")
    csv = tmp_path / "t.csv"
    csv.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    stats = analyser_colonnes_tableur(csv)
    assert stats["Titre"]["classif"] == "par-item"


def test_classif_fallback_cote_ignore_urls_nakala(tmp_path: Path) -> None:
    """Test d'usage PF (2026-05-23) — `data_url` est 100 % unique sur un
    export Nakala (1 URL par scan), placée APRÈS la vraie cote dans le
    tableur. Sans cette exclusion, le fallback prenait `data_url` pour
    cote (vraie cote dupliquée sur tous les scans, donc pas 100 % unique
    au global) → toutes les classifs faussement par-item → mode simple
    ne promouvait rien."""
    lignes = ["cote_item;titre;data_url;preview_url;thumb"]
    for i in range(1, 4):
        for s in range(1, 4):
            lignes.append(
                f"PF-{i};Num {i};"
                f"https://api.nakala.fr/data/x/{i}_{s};"
                f"https://api.nakala.fr/embed/x/{i}_{s};"
                f"https://api.nakala.fr/iiif/x/{i}_{s}"
            )
    csv = tmp_path / "t.csv"
    csv.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    stats = analyser_colonnes_tableur(csv)
    # `cote_item` matche le pattern strict — c'est lui la cote.
    assert stats["cote_item"]["classif"] == "cote"
    # Les URLs Nakala sont par-fichier (varient au sein de chaque cote).
    assert stats["data_url"]["classif"] == "par-fichier"
    assert stats["preview_url"]["classif"] == "par-fichier"
    assert stats["thumb"]["classif"] == "par-fichier"


def test_classif_fallback_cote_ignore_filename(tmp_path: Path) -> None:
    """Si `filename` (typiquement 100 % unique) précède la vraie cote
    et qu'aucune colonne ne porte un nom canonique de cote, le fallback
    doit sauter `filename` plutôt que de le prendre pour cote — sinon
    une mauvaise colonne cote casse toutes les classifs en aval."""
    csv = tmp_path / "t.csv"
    csv.write_text(
        "filename;identifiant;titre\n"
        "scan_001.tif;HK-1;Numero 1\n"
        "scan_002.tif;HK-2;Numero 2\n"
        "scan_003.tif;HK-3;Numero 3\n",
        encoding="utf-8",
    )
    stats = analyser_colonnes_tableur(csv)
    # `identifiant` doit gagner comme cote (filename est exclu du fallback).
    assert stats["identifiant"]["classif"] == "cote"
    # `filename` reste classé, mais pas en tant que cote.
    assert stats["filename"]["classif"] != "cote"


def test_classif_sentinelles_ignorees_dans_groupby(tmp_path: Path) -> None:
    """Les sentinelles (`none`, `n/a`, NaN, ...) ne doivent pas compter
    comme valeurs distinctes au sein d'une cote : sinon une colonne
    par-item avec des trous serait classée par-fichier."""
    csv = tmp_path / "t.csv"
    csv.write_text(
        "Cote;Titre\n"
        "HK-1;Numero 1\n"
        "HK-1;none\n"
        "HK-1;Numero 1\n"
        "HK-2;Numero 2\n"
        "HK-2;n/a\n"
        "HK-2;Numero 2\n",
        encoding="utf-8",
    )
    stats = analyser_colonnes_tableur(csv)
    # Chaque cote a une seule valeur réelle ("Numero N"), les sentinelles
    # sont normalisées en null avant le groupby → classif par-item.
    assert stats["Titre"]["classif"] == "par-item"
