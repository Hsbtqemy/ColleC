"""Garde-fou XSS sur le panneau de configuration des colonnes.

Trouve a l'audit transversal : `panneau_colonnes.js` reconstruisait
les `<li>` retire / ajoute via template literal dans `innerHTML` —
`${dataset.colLabel}` interpole directement, sans escape. Si un import
tableur cree une colonne `Item.metadonnees` avec une cle ou un libelle
contenant `<img src=x onerror=alert(1)>`, le clic sur retirer/ajouter
declenche l'XSS.

Le fix utilise `textContent` + DOM `createElement` pour les chaines
user-supplied. Les SVG (constants) restent en innerHTML.

Ce fichier ne teste pas le navigateur (Playwright not setup) mais
verifie que :
1. Le JS ne contient plus d'interpolation `${...}` de dataset dans
   un innerHTML.
2. Le rendu serveur des cles metadonnees malicieuses est bien
   autoescape (HTML attr safe).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from archives_tool.api.main import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Collection, Item, ItemCollection, TypeCollection


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_panneau_colonnes_js_n_a_pas_d_interpolation_dataset_dans_innerhtml() -> None:
    """Garde-fou source code : le JS ne doit jamais utiliser
    `${dataset.X}` dans une chaine `innerHTML` — pattern XSS classique
    quand la valeur vient d'un user-controlled data attribute."""
    chemin = Path("src/archives_tool/web/static/js/panneau_colonnes.js")
    contenu = chemin.read_text(encoding="utf-8")

    # Cherche les blocs `innerHTML = \`...\`` qui contiennent `${...}`
    # avec une reference dataset.
    import re

    # Pattern : `.innerHTML = \`...${...dataset...}...\`` (template literal)
    fragments_innerhtml = re.findall(r"\.innerHTML\s*=\s*`([^`]*)`", contenu, re.DOTALL)
    for frag in fragments_innerhtml:
        # Recherche $ {...dataset...}
        if re.search(r"\$\{[^}]*dataset[^}]*\}", frag):
            pytest.fail(
                "panneau_colonnes.js contient `innerHTML = ...${...dataset...}` "
                "→ XSS via valeur d'un data-attribute. Utiliser textContent + "
                "createElement pour les chaines user-supplied."
            )
        # Aussi $ {key} ou $ {label} sans isolation
        if re.search(r"\$\{\s*(key|label|cat|colLabel|colKey)\s*\}", frag):
            pytest.fail(
                "panneau_colonnes.js contient `innerHTML` avec interpolation "
                "directe de key/label/cat — XSS si l'import contient un "
                "caractere HTML dans la cle metadonnees. Utiliser textContent."
            )


def test_visionneuse_osd_js_fallback_n_a_pas_d_interpolation_user_data() -> None:
    """Garde-fou source code : la fonction `afficherFallback` de
    visionneuse_osd.js ne doit jamais interpoler `nom` ou `telecharger`
    dans une chaine `innerHTML`. Ces valeurs viennent de
    `data-source` JSON parsé qui contient `fichier.nom_fichier`
    (free text). Pattern XSS : un nom_fichier
    `<img src=x onerror=alert(1)>.jpg` → fallback rendu → exécution JS."""
    chemin = Path("src/archives_tool/web/static/js/visionneuse_osd.js")
    contenu = chemin.read_text(encoding="utf-8")

    import re

    fragments_innerhtml = re.findall(r"\.innerHTML\s*=\s*`([^`]*)`", contenu, re.DOTALL)
    for frag in fragments_innerhtml:
        # Variables clés du data.source qui pourraient venir d'user
        if re.search(
            r"\$\{\s*(nom|telecharger|data\.nom|data\.telecharger)\s*\}", frag
        ):
            pytest.fail(
                "visionneuse_osd.js contient `innerHTML` avec interpolation "
                "de nom/telecharger — XSS via nom_fichier malicieux. Utiliser "
                "createElement + textContent pour le label, set href via "
                "propriété pour l'URL."
            )


def test_aucun_js_app_n_a_de_template_literal_dans_innerhtml_avec_data_user() -> None:
    """Audit transversal : aucun fichier JS de l'application ne doit
    avoir un `innerHTML = \\`...${X}...\\`` où X référence un objet
    `data` ou `dataset` (les sources typiques de free text user).

    Ce garde-fou s'étend automatiquement à tout nouveau fichier JS
    de l'app."""
    import re

    racine = Path("src/archives_tool/web/static/js")
    for fjs in racine.glob("*.js"):
        # Exclure le vendor/
        if "vendor" in str(fjs):
            continue
        contenu = fjs.read_text(encoding="utf-8")
        fragments = re.findall(r"\.innerHTML\s*=\s*`([^`]*)`", contenu, re.DOTALL)
        for frag in fragments:
            # `${data.X}` ou `${dataset.X}` ou `${X}` où X est un nom
            # connu pour porter du user data (label, nom, titre…).
            suspects = re.findall(r"\$\{\s*([^}]+)\s*\}", frag)
            for s in suspects:
                # Constantes / appels surs : encodeURIComponent, ${i+1},
                # ${r.status}, ${id} (entier), CSS.escape…
                if (
                    "encodeURIComponent" in s
                    or "CSS.escape" in s
                    or re.match(r"^\s*\w+\.status\s*$", s)
                    or re.match(r"^\s*r\.\w+\s*$", s)
                ):
                    continue
                # Variables qui sentent le user data
                if re.search(
                    r"\b(nom|label|titre|description|libelle|colLabel|colKey)\b",
                    s,
                ):
                    pytest.fail(
                        f"{fjs.name} : innerHTML interpole `${{{s}}}` "
                        f"qui ressemble a du user data. Refactor via "
                        f"createElement + textContent."
                    )


def test_metadonnee_avec_cle_html_se_rend_safe_en_attribut(
    base_demo: Path,
) -> None:
    """Si un import dépose `<img src=x onerror=alert(1)>` comme clé
    metadonnees, la page rendue doit l'autoescape correctement dans les
    attributs (data-col-key, data-col-label). Jinja autoescape couvre ce
    cas — ce test verrouille qu'on ne contourne pas l'autoescape."""
    # Pose une cle malicieuse dans metadonnees d'un item de HK
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        miroir = s.scalar(
            select(Collection).where(
                Collection.cote == "HK",
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        item = s.scalar(
            select(Item)
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == miroir.id)
            .limit(1)
        )
        meta = dict(item.metadonnees or {})
        meta["<img src=x onerror=alert(1)>"] = "valeur"
        item.metadonnees = meta
        flag_modified(item, "metadonnees")
        s.commit()
        col_id = miroir.id
    engine.dispose()

    client = TestClient(app)
    # Le panneau colonnes est rendu via GET /preferences/colonnes/items/<id>
    r = client.get(f"/preferences/colonnes/items/{col_id}")
    assert r.status_code == 200
    # Jinja doit avoir autoescape les chevrons : `<img>` devient
    # `&lt;img&gt;` ou similar dans le HTML.
    # Verifie qu'on N'a PAS le tag brut <img src=x onerror=...>
    assert "<img src=x" not in r.text
    # En revanche on doit voir la forme echappee (signe que la cle est
    # bien rendue, juste safely)
    assert "&lt;img" in r.text or "&#60;img" in r.text
