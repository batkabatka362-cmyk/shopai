"""Image-generation adapter family.

Concrete adapters live here (DALL-E 3 today; Stability AI,
Replicate, and the free tiers of Pollinations / Hugging Face
later). They all share the :class:`ImageBaseAdapter` skeleton
and wire into the router through
:func:`core.adapters.image.bootstrap.register_all`.
"""
from __future__ import annotations

from ._base import ImageBaseAdapter
from .dalle3 import DallE3Adapter

__all__ = [
    "ImageBaseAdapter",
    "DallE3Adapter",
]
