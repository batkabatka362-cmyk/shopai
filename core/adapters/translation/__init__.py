"""Translation adapter family.

Concrete adapters live here (DeepL today; Google Translate,
Lokalise, LibreTranslate later). They share the
:class:`TranslationBaseAdapter` skeleton and wire into the
router through
:func:`core.adapters.translation.bootstrap.register_all`.
"""
from __future__ import annotations

from ._base import TranslationBaseAdapter
from .deepl import DeepLAdapter

__all__ = [
    "TranslationBaseAdapter",
    "DeepLAdapter",
]
