"""Step 6 — Ad creative generation.

Build 3 creative variants for A/B testing on Meta Ads:
  variant_1: hook-driven copy + primary image
  variant_2: benefit list + product video (if available)
  variant_3: social-proof angle + carousel

Today's stub returns plausible placeholders so the next step's adapter
contract can be tested. Real generation will use:
  • Replicate / Higgsfield for AI video
  • Pexels for stock B-roll
  • Groq for ad copy variants
"""
from __future__ import annotations

from typing import Any

from ..context import LaunchContext
from ._base import Step, StepSkip


class CreativeStep(Step):
    name = "creative"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        if not context.media.get("gallery"):
            raise StepSkip("no media to build creatives from")

        title = context.content.get("title", "Limited offer")
        primary = context.media.get("primary_image", "")
        bullets = context.content.get("bullets", [])

        return {
            "variants": [
                {
                    "id": "v1_hook",
                    "headline": title[:40],
                    "primary_text": f"You won't believe this. {title}",
                    "image_url": primary,
                    "cta": "Shop Now",
                },
                {
                    "id": "v2_benefits",
                    "headline": title[:40],
                    "primary_text": "✓ " + " ✓ ".join(bullets[:3]),
                    "image_url": primary,
                    "cta": "Learn More",
                },
                {
                    "id": "v3_proof",
                    "headline": "Loved by thousands",
                    "primary_text": f"⭐⭐⭐⭐⭐ {title}",
                    "image_url": primary,
                    "cta": "Shop Now",
                },
            ],
            "_video_generated": False,
        }
