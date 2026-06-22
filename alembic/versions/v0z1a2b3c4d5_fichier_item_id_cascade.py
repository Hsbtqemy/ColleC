"""Ajoute ON DELETE CASCADE à Fichier.item_id (parité FK, R5 revue générale).

La FK `fichier.item_id` n'avait pas d'`ON DELETE CASCADE`, contrairement à ses
sœurs (`item.fonds_id`, `item_collection.*`, `annotation_region.fichier_id`,
toutes en cascade). La suppression des fichiers d'un item reposait donc
**uniquement** sur la cascade ORM `Item.fichiers` (`cascade="all,
delete-orphan"`). Aucun bug aujourd'hui (tous les chemins passent par
`db.delete(item)` ORM) ; ce ticket pose la cascade au niveau SQL en
**défense en profondeur** — un futur `delete()` Core/bulk sur `item`
n'orphelinera plus les `fichier` (ni transitivement leurs `annotation_region`).

La FK initiale est **anonyme** (`sa.ForeignKeyConstraint(["item_id"],
["item.id"])` dans `380e05cd7254`, sans `name=`). On la recrée en
`batch_alter_table` avec une `naming_convention` pour que la FK reflétée
reçoive le nom canonique SQLAlchemy (`fk_fichier_item_id_item`) et puisse être
droppée. `fichier` ne porte aucun trigger FTS (FTS = item/fonds/collection
seulement), donc pas de dance trigger ici.

Idempotente : skip si la FK porte déjà `ondelete=CASCADE` (cas d'une base
recréée via `Base.metadata.create_all` en parallèle des migrations — la
colonne FK du modèle a désormais la cascade). downgrade fonctionnelle
(post-refonte V0.9.0, cf. règle `contribuer.md`) : recrée la FK sans cascade.

Revision ID: v0z1a2b3c4d5
Revises: u9y0z1a2b3c4
Create Date: 2026-06-22
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision: str = "v0z1a2b3c4d5"
down_revision: str | None = "u9y0z1a2b3c4"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

#: Convention de nommage SQLAlchemy par défaut pour les FK : permet de nommer
#: la contrainte anonyme reflétée afin de la dropper en batch mode.
_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
_FK = "fk_fichier_item_id_item"


def _item_fk_ondelete(bind) -> str | None:
    """Retourne l'action `ON DELETE` de la FK `fichier.item_id` (None si FK
    absente ou sans action). Sert au guard d'idempotence."""
    for fk in inspect(bind).get_foreign_keys("fichier"):
        if fk["constrained_columns"] == ["item_id"]:
            return (fk.get("options") or {}).get("ondelete")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    if (_item_fk_ondelete(bind) or "").upper() == "CASCADE":
        return  # déjà en cascade (base create_all) → rien à faire
    with op.batch_alter_table("fichier", schema=None, naming_convention=_NAMING) as b:
        b.drop_constraint(_FK, type_="foreignkey")
        b.create_foreign_key(_FK, "item", ["item_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    bind = op.get_bind()
    if (_item_fk_ondelete(bind) or "").upper() != "CASCADE":
        return  # déjà sans cascade → rien à faire
    with op.batch_alter_table("fichier", schema=None, naming_convention=_NAMING) as b:
        b.drop_constraint(_FK, type_="foreignkey")
        b.create_foreign_key(_FK, "item", ["item_id"], ["id"])
