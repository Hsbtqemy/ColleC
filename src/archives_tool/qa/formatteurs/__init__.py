"""Formatteurs de `RapportQa` : text (Rich) et JSON."""

from .json import formatter_rapport_json
from .text import formatter_rapport_text

__all__ = ["formatter_rapport_json", "formatter_rapport_text"]
