"""Image CDN adapter family.

Concrete adapters live here (ImageKit today; Cloudinary,
imgix, Bunny Optimizer later). They share the
:class:`ImageCdnBaseAdapter` skeleton and wire into the
router through
:func:`core.adapters.image_cdn.bootstrap.register_all`.

Not to be confused with ``core/adapters/image/`` which covers
image *generation* (DALL-E 3, Stable Diffusion, …). The CDN
family accepts an existing image source and returns an
optimised, CDN-hosted variant.
"""
from __future__ import annotations

from ._base import ImageCdnBaseAdapter
from .imagekit import ImageKitAdapter

__all__ = [
    "ImageCdnBaseAdapter",
    "ImageKitAdapter",
]
