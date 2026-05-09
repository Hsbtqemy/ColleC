"""V0.9.0-alpha — refonte du modèle Fonds / Collection / Item.

Migration structurelle : pas de données utiles à préserver. La base
demo actuelle est supprimée à la main avant `alembic upgrade head`.

Tables introduites : `fonds`, `item_collection`, `collaborateur_fonds`.
Tables refondues : `collection` (drop parent_id, rename
cote_collection→cote, ajout fonds_id + type_collection + CHECK
miroir↔fonds), `item` (drop collection_id, ajout fonds_id
obligatoire, cote unique par fonds).

Stratégie SQLite : drop des tables impactées dans l'ordre FK
descendant, puis `metadata.create_all` recrée tout ce qui manque.
Plus simple que des batch_alter multiples vu l'ampleur de la refonte.

Revision ID: g7l8m9n0o1p2
Revises: f6k7l8m9n0o1
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op

from archives_tool.models import Base

revision: str = "g7l8m9n0o1p2"
down_revision: str | None = "f6k7l8m9n0o1"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# Ordre FK descendant : enfants d'abord pour pouvoir DROP les parents.
_TABLES_A_DROPPER = (
    "lien_externe_item",
    "modification_item",
    "operation_fichier",
    "operation_import",
    "fichier",
    "champ_personnalise",
    "collaborateur_collection",
    "preferences_affichage",
    "session_import",
    "item",
    "collection",
)


def upgrade() -> None:
    bind = op.get_bind()
    for nom in _TABLES_A_DROPPER:
        op.execute(f"DROP TABLE IF EXISTS {nom}")
    # Recrée toutes les tables manquantes depuis les metadata du modèle.
    # Ordre topologique géré par SQLAlchemy ; les tables intactes
    # (profil_import, vocabulaire, etc.) sont laissées telles quelles
    # grâce à `checkfirst=True`.
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Pas de descente possible : la refonte ne préserve pas les
    données. Restaurer depuis une sauvegarde si besoin."""
    raise NotImplementedError(
        "Downgrade non supporté pour la refonte V0.9.0-alpha. "
        "Restaurer depuis sauvegarde."
    )
