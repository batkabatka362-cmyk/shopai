"""Step 3 — Media collection.

Strategy (preserves CLAUDE.md §4 research-first ordering):
  1. Use ``source.gallery_urls`` first — free, supplier-provided,
     match-the-product guarantees
  2. Fall back to Pexels stock photos when supplier gallery is empty
     (PEXELS_API_KEY required; 200 req/hr free tier)
  3. (Optional) Replicate background-remove for cleaner creatives
  4. (Optional) Cloudinary re-host for stable CDN URLs

Keeps the step idempotent — same (title, niche) query returns the same
Pexels result pool because Pexels orders by relevance + popularity.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..context import LaunchContext
from ._base import Step, StepSkip


logger = get_logger("workflows.launch.media")


class MediaStep(Step):
    name = "media"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        gallery = list(context.source.get("gallery_urls") or [])
        supplier_count = len(gallery)
        pexels_added: list[dict[str, Any]] = []

        if len(gallery) < 3:
            pexels_added = self._fetch_pexels(context)
            gallery.extend(p["url"] for p in pexels_added)

        if not gallery:
            raise StepSkip(
                "no supplier gallery and Pexels returned no images — "
                "cannot list product without imagery"
            )

        quality = self._score_primary(gallery[0])

        return {
            "primary_image": gallery[0],
            "gallery": gallery[:8],
            "supplier_count": supplier_count,
            "pexels_count": len(pexels_added),
            "pexels_credit": [
                f"Photo by {p['photographer']}" for p in pexels_added if p.get("photographer")
            ],
            "enhanced": False,
            "cdn_uploaded": False,
            "primary_quality_score": quality.get("quality", 0),
            "primary_hero_suitable": quality.get("hero_suitable", False),
            "primary_issues": quality.get("issues", []),
            "primary_description": quality.get("description", ""),
        }

    @staticmethod
    def _score_primary(url: str) -> dict[str, Any]:
        """Run the vision analyser on the primary image. Returns {} if
        Gemini is unconfigured so downstream keeps working."""
        try:
            from core.adapters.image import vision
            if not vision.is_configured():
                return {}
            return vision.analyze(url)
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _fetch_pexels(context: LaunchContext) -> list[dict[str, Any]]:
        from core.adapters.image import pexels
        if not pexels.is_configured():
            return []

        # Query by title first (closest semantic match); fall back to niche
        queries = []
        if context.source.get("title"):
            queries.append(context.source["title"])
        if context.goal.niche:
            queries.append(context.goal.niche)
        if not queries:
            return []

        for q in queries:
            results = pexels.search(q, per_page=5, orientation="landscape")
            if results:
                logger.info(
                    "Pexels: %d photos for %r", len(results), q,
                )
                return results
        logger.info("Pexels: 0 photos for %s", " | ".join(queries))
        return []
