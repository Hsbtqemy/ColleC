"""V0.9.0-alpha — refonte du modèle Fonds / Collection / Item.

Migration structurelle : pas de données utiles à préserver. La base
demo actuelle est supprimée à la main avant `alembic upgrade head`.

Tables introduites :
- fonds (corpus brut)
- item_collection (liaison N-N item ↔ collection)
- collaborateur_fonds (analogue de collaborateur_collection)

Tables refondues :
- collection : drop parent_id, drop unique cote_collection, rename
  cote_collection → cote, ajout fonds_id + type_collection +
  description_publique + doi_collection_nakala_parent + champs
  périodique. CHECK constraint sur miroir↔fonds.
- item : drop collection_id, ajout fonds_id obligatoire, cote unique
  par fonds.

Stratégie SQLite : drop des tables impactées + recréation via les
metadata SQLAlchemy. Plus simple et plus sûr que des batch_alter
multiples vu l'ampleur de la refonte.

Revision ID: g7l8m9n0o1p2
Revises: f6k7l8m9n0o1
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op

revision: str = "g7l8m9n0o1p2"
down_revision: str | None = "f6k7l8m9n0o1"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# Tables à supprimer puis recréer depuis les nouvelles metadata.
# L'ordre respecte les dépendances FK descendantes.
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

# Tables à créer (ordre amont→aval pour les FK).
_TABLES_A_CREER = (
    "fonds",
    "collection",
    "item",
    "item_collection",
    "fichier",
    "champ_personnalise",
    "collaborateur_collection",
    "collaborateur_fonds",
    "modification_item",
    "operation_fichier",
    "operation_import",
    "lien_externe_item",
    "preferences_affichage",
    "session_import",
)


def _metadata_target():
    """Charge les metadata SQLAlchemy au runtime (évite l'import au
    chargement du module Alembic, qui prive la migration d'un état
    Python sain en cas de problème d'import)."""
    from archives_tool.models import Base

    return Base.metadata


def upgrade() -> None:
    bind = op.get_bind()
    metadata = _metadata_target()

    for nom in _TABLES_A_DROPPER:
        op.execute(f"DROP TABLE IF EXISTS {nom}")

    for nom in _TABLES_A_CREER:
        table = metadata.tables.get(nom)
        if table is None:
            raise RuntimeError(
                f"Table {nom!r} introuvable dans Base.metadata — "
                "vérifier l'enregistrement du modèle."
            )
        table.create(bind=bind, checkfirst=False)


def downgrade() -> None:
    """Pas de descente possible : la refonte ne préserve pas les
    données. Restaurer depuis une sauvegarde si besoin."""
    raise NotImplementedError(
        "Downgrade non supporté pour la refonte V0.9.0-alpha. "
        "Restaurer depuis sauvegarde."
    )
