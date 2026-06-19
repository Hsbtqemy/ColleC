"""Tests du chargement de `config_local.yaml`."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from archives_tool.config import ConfigLocale, NakalaConfig, charger_config


def _ecrire_yaml(chemin: Path, contenu: str) -> Path:
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_config_valide(tmp_path: Path) -> None:
    racine_scans = tmp_path / "scans"
    racine_scans.mkdir()
    cfg_path = _ecrire_yaml(
        tmp_path / "config.yaml",
        f"""
utilisateur: "Marie Dupont"
racines:
  scans: {racine_scans}
""",
    )
    cfg = charger_config(cfg_path)
    assert isinstance(cfg, ConfigLocale)
    assert cfg.utilisateur == "Marie Dupont"
    assert cfg.racines["scans"] == racine_scans


def test_racine_inexistante_rejetee(tmp_path: Path) -> None:
    cfg_path = _ecrire_yaml(
        tmp_path / "config.yaml",
        f"""
utilisateur: "Marie"
racines:
  scans: {tmp_path / "n_existe_pas"}
""",
    )
    with pytest.raises(ValidationError):
        charger_config(cfg_path)


def test_racine_pointant_sur_fichier_rejetee(tmp_path: Path) -> None:
    faux = tmp_path / "faux.txt"
    faux.write_text("x", encoding="utf-8")
    cfg_path = _ecrire_yaml(
        tmp_path / "config.yaml",
        f"""
utilisateur: "Marie"
racines:
  scans: {faux}
""",
    )
    with pytest.raises(ValidationError):
        charger_config(cfg_path)


def test_utilisateur_vide_rejete(tmp_path: Path) -> None:
    cfg_path = _ecrire_yaml(
        tmp_path / "config.yaml",
        """
utilisateur: ""
racines: {}
""",
    )
    with pytest.raises(ValidationError):
        charger_config(cfg_path)


def test_yaml_non_mapping_rejete(tmp_path: Path) -> None:
    cfg_path = _ecrire_yaml(tmp_path / "config.yaml", "- une\n- liste\n")
    with pytest.raises(ValueError):
        charger_config(cfg_path)


def test_config_sans_racines_ok(tmp_path: Path) -> None:
    cfg_path = _ecrire_yaml(tmp_path / "config.yaml", 'utilisateur: "Jean"\n')
    cfg = charger_config(cfg_path)
    assert cfg.racines == {}


# --- Anti-SSRF de NakalaConfig.base_url (Lot 3, revue générale) ---


def test_nakala_hotes_par_defaut_acceptes() -> None:
    for url in ("https://api.nakala.fr", "https://apitest.nakala.fr"):
        assert NakalaConfig(base_url=url).base_url == url


def test_nakala_base_url_normalisee() -> None:
    assert NakalaConfig(base_url="https://api.nakala.fr/").base_url == (
        "https://api.nakala.fr"
    )


@pytest.mark.parametrize(
    "url", ["http://api.nakala.fr", "ftp://api.nakala.fr", "apitest.nakala.fr"]
)
def test_nakala_base_url_non_https_rejete(url: str) -> None:
    # http://, ftp://, et hôte nu sans schéma (urlsplit → scheme='') → tous
    # rejetés sur l'exigence HTTPS.
    with pytest.raises(ValidationError, match="HTTPS"):
        NakalaConfig(base_url=url)


def test_nakala_hote_vide_rejete() -> None:
    with pytest.raises(ValidationError, match="manquant"):
        NakalaConfig(base_url="https:///datas")


def test_nakala_allowlist_vide_rejette_tout() -> None:
    # Verrou : une allowlist vide rejette TOUT (et non « autorise tout »).
    with pytest.raises(ValidationError, match="non autoris"):
        NakalaConfig(base_url="https://api.nakala.fr", hotes_autorises=[])


def test_nakala_base_url_hote_non_autorise_rejete() -> None:
    with pytest.raises(ValidationError, match="non autoris"):
        NakalaConfig(base_url="https://evil.example.com")


def test_nakala_base_url_userinfo_rejete() -> None:
    with pytest.raises(ValidationError, match="identifiants"):
        NakalaConfig(base_url="https://user:pass@apitest.nakala.fr")


def test_nakala_base_url_ip_interne_rejetee() -> None:
    # IP ajoutée à l'allowlist : prouve que la garde IP interne mord même
    # si l'hôte est explicitement autorisé (défense en profondeur).
    with pytest.raises(ValidationError, match="interne"):
        NakalaConfig(base_url="https://127.0.0.1", hotes_autorises=["127.0.0.1"])


def test_nakala_hotes_autorises_surchargeable() -> None:
    cfg = NakalaConfig(
        base_url="https://nakala.mon-instance.fr",
        hotes_autorises=["nakala.mon-instance.fr"],
    )
    assert cfg.base_url == "https://nakala.mon-instance.fr"


# --- R2 : une section distante invalide ne fait pas tomber TOUTE la config ---


def test_nakala_invalide_ne_fait_pas_tomber_la_config(tmp_path: Path) -> None:
    """Un `nakala.base_url` invalide désactive la SECTION nakala (→ None)
    sans perdre `lecture_seule` / `racines` / l'identité (backlog R2)."""
    racine = tmp_path / "scans"
    racine.mkdir()
    cfg = charger_config(
        _ecrire_yaml(
            tmp_path / "c.yaml",
            f"""
utilisateur: "Marie"
lecture_seule: true
racines:
  scans: {racine}
nakala:
  base_url: http://api.nakala.fr
""",
        )
    )
    assert cfg.nakala is None  # section désactivée
    assert cfg.lecture_seule is True  # ★ mode sûreté préservé
    assert cfg.utilisateur == "Marie"
    assert "scans" in cfg.racines


def test_sharedocs_invalide_ne_fait_pas_tomber_la_config(tmp_path: Path) -> None:
    racine = tmp_path / "scans"
    racine.mkdir()
    cfg = charger_config(
        _ecrire_yaml(
            tmp_path / "c.yaml",
            f"""
utilisateur: "Marie"
lecture_seule: true
racines:
  scans: {racine}
sharedocs:
  base_url: http://sharedocs.huma-num.fr/dav
""",
        )
    )
    assert cfg.sharedocs is None
    assert cfg.lecture_seule is True
    assert "scans" in cfg.racines


def test_nakala_valide_reste_construit(tmp_path: Path) -> None:
    """La tolérance ne casse pas une section valide."""
    cfg = charger_config(
        _ecrire_yaml(
            tmp_path / "c.yaml",
            """
utilisateur: "Marie"
nakala:
  base_url: https://apitest.nakala.fr
  api_key: k
""",
        )
    )
    assert cfg.nakala is not None
    assert cfg.nakala.base_url == "https://apitest.nakala.fr"
    assert cfg.nakala.api_key == "k"


def test_section_invalide_warning_sans_fuite_de_cle(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Une section nakala invalide émet un warning ciblé MAIS ne fait
    jamais fuiter l'api_key dans les logs (doctrine secrets, R2 revue)."""
    secret = "SECRET-LEAK-0123456789abcdef-cafe"
    cfg_path = _ecrire_yaml(
        tmp_path / "c.yaml",
        f"""
utilisateur: "M"
nakala:
  base_url: http://api.nakala.fr
  api_key: {secret}
""",
    )
    with caplog.at_level(logging.WARNING, logger="archives_tool.config"):
        cfg = charger_config(cfg_path)
    assert cfg.nakala is None
    assert any(
        "nakala" in r.message and "invalide" in r.message for r in caplog.records
    )
    assert secret not in caplog.text  # ★ pas de fuite de la clé
    # repr=False : une clé valide n'apparaît jamais dans le repr du modèle.
    assert secret not in repr(NakalaConfig(api_key=secret))


def test_nakala_et_sharedocs_tous_deux_invalides(tmp_path: Path) -> None:
    """Deux sections distantes invalides → les deux désactivées, le reste
    de la config (sûreté + racines) intact."""
    racine = tmp_path / "scans"
    racine.mkdir()
    cfg = charger_config(
        _ecrire_yaml(
            tmp_path / "c.yaml",
            f"""
utilisateur: "M"
lecture_seule: true
racines:
  scans: {racine}
nakala:
  base_url: http://api.nakala.fr
sharedocs:
  base_url: http://sharedocs.huma-num.fr/dav
""",
        )
    )
    assert cfg.nakala is None
    assert cfg.sharedocs is None
    assert cfg.lecture_seule is True
    assert "scans" in cfg.racines


def test_section_non_dict_toleree(tmp_path: Path) -> None:
    """Une section scalaire/liste mal tapée (pas un mapping) est aussi
    tolérée (désactivée), sans ré-effondrer la config (blast-radius fermé)."""
    racine = tmp_path / "scans"
    racine.mkdir()
    cfg = charger_config(
        _ecrire_yaml(
            tmp_path / "c.yaml",
            f"""
utilisateur: "M"
lecture_seule: true
racines:
  scans: {racine}
nakala: "pas un mapping"
""",
        )
    )
    assert cfg.nakala is None
    assert cfg.lecture_seule is True
    assert "scans" in cfg.racines
