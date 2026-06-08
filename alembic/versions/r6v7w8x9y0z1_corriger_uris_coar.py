"""Corrige les URIs COAR erronées des items existants (V0.9.10).

Les `TYPES_COAR_OPTIONS` de ColleC pointaient vers des URIs COAR fausses
ou mal étiquetées (cf. `docs/developpeurs/nakala-depot-future.md`). Les
items déjà catalogués portent donc des `type_coar` invalides — non
résolvables en `dc:type`, rejetés au dépôt Nakala. Cette migration les
remappe vers les URIs corrigées.

Remap = ancienne URI ColleC (selon le LABEL qu'elle portait dans le
dropdown) → URI corrigée. Sûr car ces anciennes URIs étaient
internes à ColleC (seul ColleC les écrivait, avec ses propres libellés).

Idempotente : ne touche que les valeurs exactes de l'ancien jeu ; rejouer
ne change rien (les nouvelles URIs ne sont pas des clés du remap).

Revision ID: r6v7w8x9y0z1
Revises: q5u6v7w8x9y0
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision: str = "r6v7w8x9y0z1"
down_revision: str | None = "q5u6v7w8x9y0"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_C = "http://purl.org/coar/resource_type"

# ancienne URI ColleC (intention selon le label) → URI corrigée
_REMAP: dict[str, str] = {
    f"{_C}/c_3e5a": f"{_C}/c_2fe3",      # Périodique → journal (Nakala)
    f"{_C}/c_0640": f"{_C}/c_2fe3",      # Numéro de périodique → Périodique
    f"{_C}/c_18co": f"{_C}/YC9F-HGCF",   # Document d'archives
    f"{_C}/c_ecc8": f"{_C}/c_12cd",      # Carte (c_ecc8 = image fixe → c_12cd map)
    f"{_C}/c_8a7e": f"{_C}/c_0040",      # Manuscrit
    f"{_C}/c_18cd": f"{_C}/c_ecc8",      # Photographie → still image
    f"{_C}/c_12cd": f"{_C}/c_12ce",      # Vidéo (c_12cd = carte → c_12ce video)
}

# Ordre critique — chaîne de réaffectations qui se recouvrent :
#   c_12cd : ANCIEN Vidéo → c_12ce  ET  NOUVEAU Carte (← c_ecc8)
#   c_ecc8 : ANCIEN Carte → c_12cd  ET  NOUVEAU Photographie (← c_18cd)
# Il faut donc consommer chaque ancienne valeur avant de la réutiliser
# comme cible : Vidéo (c_12cd→c_12ce), PUIS Carte (c_ecc8→c_12cd), PUIS
# Photographie (c_18cd→c_ecc8). Toute autre permutation re-capture une
# valeur déjà migrée (p.ex. photo→c_ecc8 avant carte→c_12cd ferait
# d'une photo une carte).
_ORDRE = [
    f"{_C}/c_12cd",  # Vidéo → c_12ce
    f"{_C}/c_ecc8",  # Carte → c_12cd
    f"{_C}/c_18cd",  # Photographie → c_ecc8
    f"{_C}/c_3e5a",  # Périodique (indépendant)
    f"{_C}/c_0640",  # Numéro → Périodique (indépendant)
    f"{_C}/c_18co",  # Document d'archives (indépendant)
    f"{_C}/c_8a7e",  # Manuscrit (indépendant)
]


def appliquer_remap(conn) -> None:
    """Applique le remap séquentiel sur `item.type_coar`. Extrait pour
    être testable avec une connexion SQLAlchemy hors contexte Alembic."""
    for ancienne in _ORDRE:
        conn.exec_driver_sql(
            "UPDATE item SET type_coar = ? WHERE type_coar = ?",
            (_REMAP[ancienne], ancienne),
        )


def upgrade() -> None:
    appliquer_remap(op.get_bind())


def downgrade() -> None:
    # Pas de downgrade fiable : le remap n'est pas bijectif (c_0640 et
    # c_3e5a fusionnent vers c_2659). On laisse les données corrigées.
    pass
