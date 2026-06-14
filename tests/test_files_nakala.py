"""Tests des helpers Nakala (`files/nakala.py`)."""

from __future__ import annotations

from archives_tool.files.nakala import vers_data, vers_iiif_info_json

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DOI = "10.34847/nkl.abc"


def test_vers_iiif_info_json_depuis_data() -> None:
    src = f"https://api.nakala.fr/data/{DOI}/{SHA}"
    assert vers_iiif_info_json(src) == (
        f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    )


def test_vers_iiif_info_json_depuis_thumb() -> None:
    """Pattern `thumb` = `/iiif/<doi>/<sha>/full/!200,200/0/default.jpg`
    — on extrait juste la base et reconstruit info.json."""
    src = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/full/!200,200/0/default.jpg"
    assert vers_iiif_info_json(src) == (
        f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    )


def test_vers_iiif_info_json_hostname_preserve() -> None:
    src = f"https://api-test.nakala.fr/data/{DOI}/{SHA}"
    assert vers_iiif_info_json(src) == (
        f"https://api-test.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    )


def test_vers_iiif_info_json_non_nakala_inchangee() -> None:
    for url in (
        "https://example.com/image.jpg",
        f"https://evil-nakala.fr/data/{DOI}/{SHA}",  # faux positif domain
        f"https://nakala.fr.attacker.com/data/{DOI}/{SHA}",
    ):
        assert vers_iiif_info_json(url) == url


def test_vers_data_depuis_iiif_info_json() -> None:
    """Inverse de vers_iiif_info_json — récupère l'URL data binaire
    depuis l'URL IIIF info.json. Sert au bouton « Télécharger » de
    la visionneuse pour les Fichier Nakala-only (sinon la route
    locale `/item/.../fichiers/<id>` retournerait 404)."""
    src = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    assert vers_data(src) == f"https://api.nakala.fr/data/{DOI}/{SHA}"


def test_vers_data_depuis_iiif_image_full() -> None:
    """Une URL IIIF image (full/...) est aussi convertible — on
    extrait `(doi, sha)` et on reconstruit `/data/`."""
    src = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/full/!200,200/0/default.jpg"
    assert vers_data(src) == f"https://api.nakala.fr/data/{DOI}/{SHA}"


def test_vers_data_depuis_data_url_inchangee() -> None:
    """Si déjà une URL data, on l'extrait et la reconstruit
    identique."""
    src = f"https://api.nakala.fr/data/{DOI}/{SHA}"
    assert vers_data(src) == src


def test_vers_data_hostname_preserve() -> None:
    src = f"https://api-test.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    assert vers_data(src) == f"https://api-test.nakala.fr/data/{DOI}/{SHA}"


def test_vers_data_non_nakala_retourne_none() -> None:
    """Si pas une URL Nakala reconnue, retourne `None` — le caller
    doit fallback (route locale, message…)."""
    for url in (
        "https://example.com/image.jpg",
        f"https://evil-nakala.fr/iiif/{DOI}/{SHA}/info.json",
        "",
    ):
        assert vers_data(url) is None


# vers_thumb


def test_vers_thumb_depuis_data() -> None:
    """L'URL data est convertie en thumb IIIF carrée (200x200 par
    défaut, conserve le ratio via `!`)."""
    from archives_tool.files.nakala import vers_thumb

    src = f"https://api.nakala.fr/data/{DOI}/{SHA}"
    assert vers_thumb(src) == (
        f"https://api.nakala.fr/iiif/{DOI}/{SHA}/full/!200,200/0/default.jpg"
    )


def test_vers_thumb_depuis_iiif_info_json() -> None:
    """Une URL IIIF info.json (cas typique : ce qu'on stocke dans
    `Fichier.iiif_url_nakala` après la normalisation V0.9.2-import)
    est aussi convertible en thumb — on extrait `(doi, sha)` et on
    reconstruit le pattern `full/!W,H/0/default.jpg`."""
    from archives_tool.files.nakala import vers_thumb

    src = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    assert vers_thumb(src) == (
        f"https://api.nakala.fr/iiif/{DOI}/{SHA}/full/!200,200/0/default.jpg"
    )


def test_vers_thumb_taille_custom() -> None:
    from archives_tool.files.nakala import vers_thumb

    src = f"https://api.nakala.fr/data/{DOI}/{SHA}"
    assert vers_thumb(src, taille_max=100) == (
        f"https://api.nakala.fr/iiif/{DOI}/{SHA}/full/!100,100/0/default.jpg"
    )


def test_vers_thumb_hostname_preserve() -> None:
    from archives_tool.files.nakala import vers_thumb

    src = f"https://api-test.nakala.fr/data/{DOI}/{SHA}"
    assert vers_thumb(src) == (
        f"https://api-test.nakala.fr/iiif/{DOI}/{SHA}/full/!200,200/0/default.jpg"
    )


def test_vers_thumb_non_nakala_retourne_none() -> None:
    from archives_tool.files.nakala import vers_thumb

    for url in (
        "https://example.com/image.jpg",
        f"https://evil-nakala.fr/data/{DOI}/{SHA}",
        "",
    ):
        assert vers_thumb(url) is None


def test_construire_source_image_donne_info_json() -> None:
    from archives_tool.files.nakala import construire_source_fichier_nakala

    url = construire_source_fichier_nakala(
        "https://api.nakala.fr", DOI, SHA, nom_fichier="page.jpg"
    )
    assert url == f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"


def test_construire_source_non_image_donne_data() -> None:
    from archives_tool.files.nakala import construire_source_fichier_nakala

    url = construire_source_fichier_nakala(
        "https://api.nakala.fr/", DOI, SHA, nom_fichier="numero.pdf"
    )
    # base_url avec slash final toléré ; non-image → data binaire.
    assert url == f"https://api.nakala.fr/data/{DOI}/{SHA}"


# ---------------------------------------------------------------------------
# Trou V (passe 11 P3+c.2) — remplacer_sha sur URLs Nakala
# ---------------------------------------------------------------------------


def test_remplacer_sha_sur_url_iiif_info_json() -> None:
    """Cas typique : URL stockée par `comparer` après import → IIIF
    info.json. Apres push qui change le sha, on recalcule."""
    from archives_tool.files.nakala import remplacer_sha

    nouveau = "fedcba9876543210fedcba9876543210fedcba98"
    url = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    assert remplacer_sha(url, nouveau) == (
        f"https://api.nakala.fr/iiif/{DOI}/{nouveau}/info.json"
    )


def test_remplacer_sha_sur_url_data() -> None:
    """URL de telechargement binaire — sha aussi present, doit etre
    remplace (PDF, audio, video stockes en `data`)."""
    from archives_tool.files.nakala import remplacer_sha

    nouveau = "fedcba9876543210fedcba9876543210fedcba98"
    url = f"https://api.nakala.fr/data/{DOI}/{SHA}"
    assert remplacer_sha(url, nouveau) == (
        f"https://api.nakala.fr/data/{DOI}/{nouveau}"
    )


def test_remplacer_sha_sur_url_thumb() -> None:
    """Pattern thumb avec suffixe `/full/!200,200/0/default.jpg` — le
    suffixe doit etre preserve."""
    from archives_tool.files.nakala import remplacer_sha

    nouveau = "fedcba9876543210fedcba9876543210fedcba98"
    url = f"https://api.nakala.fr/iiif/{DOI}/{SHA}/full/!200,200/0/default.jpg"
    assert remplacer_sha(url, nouveau) == (
        f"https://api.nakala.fr/iiif/{DOI}/{nouveau}/full/!200,200/0/default.jpg"
    )


def test_remplacer_sha_preserve_hostname_test() -> None:
    """`api-test.nakala.fr` reste sur api-test (cohérent avec
    `vers_iiif_info_json`)."""
    from archives_tool.files.nakala import remplacer_sha

    nouveau = "fedcba9876543210fedcba9876543210fedcba98"
    url = f"https://api-test.nakala.fr/iiif/{DOI}/{SHA}/info.json"
    assert remplacer_sha(url, nouveau) == (
        f"https://api-test.nakala.fr/iiif/{DOI}/{nouveau}/info.json"
    )


def test_remplacer_sha_sur_url_non_nakala_retourne_inchangee() -> None:
    """Pattern non-Nakala (gallica, peri vues…) : retourne tel quel."""
    from archives_tool.files.nakala import remplacer_sha

    url = "https://gallica.bnf.fr/iiif/ark:/12148/bpt6k1234567/manifest.json"
    assert remplacer_sha(url, "abc") == url


def test_remplacer_sha_sur_url_malformee_retourne_inchangee() -> None:
    """URL Nakala-like mais hors pattern : pas modifiée."""
    from archives_tool.files.nakala import remplacer_sha

    url = "https://api.nakala.fr/foo/bar"
    assert remplacer_sha(url, "abc") == url
