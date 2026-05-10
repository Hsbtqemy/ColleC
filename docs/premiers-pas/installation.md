# Installation

ColleC est un projet Python. L'installation se fait avec [uv](https://docs.astral.sh/uv/),
le gestionnaire de paquets rapide d'Astral, qui gère à la fois
l'environnement virtuel et les dépendances.

## Prérequis système

| Composant | Version | Pourquoi                                                                |
| --------- | ------- | ----------------------------------------------------------------------- |
| Python    | 3.11+   | Type hints modernes, `match`, syntaxe `int \| None`.                    |
| uv        | récent  | Installation des dépendances et lancement des commandes.                |
| Node.js   | 20+     | Compilation Tailwind CSS (uniquement si vous lancez l'interface web).   |
| Git       | -       | Clonage du dépôt.                                                       |

### Installer uv

=== "macOS / Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

Vérifier :

```bash
uv --version
```

### Dépendances système

ColleC utilise [Pillow](https://pillow.readthedocs.io/) pour le
traitement raster et [PyMuPDF](https://pymupdf.readthedocs.io/)
pour la rasterisation des PDF. Sur la plupart des systèmes, les
wheels précompilés suffisent — pas de dépendance C à installer.

Si l'installation échoue avec un message évoquant `libjpeg`,
`libpng`, `zlib` ou `mupdf`, installer les paquets de
développement correspondants :

=== "Debian / Ubuntu"

    ```bash
    sudo apt install libjpeg-dev libpng-dev zlib1g-dev
    ```

=== "macOS (Homebrew)"

    ```bash
    brew install libjpeg libpng zlib
    ```

=== "Windows"

    Les wheels sont fournis ; pas d'installation système requise
    en pratique.

## Cloner et installer

```bash
git clone https://github.com/Hsbtqemy/ColleC.git
cd ColleC
uv sync
```

`uv sync` crée un `.venv/` à la racine du projet et installe
toutes les dépendances. La commande prend ~30 secondes au premier
lancement, quelques secondes ensuite (cache).

## Vérifier l'installation

La CLI doit répondre :

```bash
uv run archives-tool --help
```

Vous devez voir la liste des sous-commandes : `importer`,
`exporter`, `controler`, `montrer`, `renommer`, `deriver`, etc.

## Initialiser une base de démonstration

Pour explorer l'outil sans toucher à votre vraie base :

```bash
uv run archives-tool demo init
```

Cela crée `data/demo.db` avec **5 fonds, ~333 items, ~1300
fichiers, 1 collection transversale**, des collaborateurs, et
quelques DOI Nakala fictifs.

Vérifier :

```bash
uv run archives-tool montrer fonds
```

Vous devez voir 5 fonds (HK, FA, etc.) listés.

## Lancer l'interface web (facultatif)

L'interface web utilise Tailwind CSS compilé via npm. Première
installation :

```bash
npm install
npm run build:css
```

Puis lancer le serveur en pointant la base demo :

=== "macOS / Linux"

    ```bash
    ARCHIVES_DB=data/demo.db uv run uvicorn archives_tool.api.main:app --reload --port 8000
    ```

=== "Windows (PowerShell)"

    ```powershell
    $env:ARCHIVES_DB = "data/demo.db"
    uv run uvicorn archives_tool.api.main:app --reload --port 8000
    ```

Ouvrir <http://localhost:8000>.

En développement, lancer `npm run watch:css` dans un autre
terminal pour recompiler le CSS à chaque modification.

## Et ensuite ?

[Configuration](configuration.md) : créer un `config_local.yaml`
qui décrit où vivent vos vrais scans.
