"""Step 3 — Media collection.

Pull / enhance the image set we'll show on Shopify and use as ad
creatives. Strategy:

  1. Use ``source.gallery_urls`` first (already free, supplier-provided)
  2. Fallback to Pexels / Pixabay if gallery is missing or weak
  3. (Optional) AI enhance via Replicate background removal
  4. (Optional) Upload to Cloudinary for stable CDN URLs

For today, simply forward what the source produced.
"""
from __future__ import annotations

from typing import Any

from ..context import LaunchContext
from ._base import Step, StepSkip


class MediaStep(Step):
    name = "media"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        urls = context.source.get("gallery_urls") or []
        if not urls:
            raise StepSkip("no gallery URLs from source — cannot list product")

        # TODO(brain): background-remove via core/adapters/image/replicate
        # TODO(brain): re-host on Cloudinary CDN for stable Shopify CDN refs
        return {
            "primary_image": urls[0],
            "gallery": urls[:8],
            "enhanced": False,
            "cdn_uploaded": False,
        }
