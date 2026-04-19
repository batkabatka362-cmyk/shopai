"""Step 6 — Ad creative generation.

Produces 3 creative variants tuned for A/B testing on Meta Ads:
  v1_hook     — curiosity / pattern interrupt
  v2_benefits — direct benefit stack
  v3_proof    — social-proof / urgency angle

Each variant gets its own LLM-drafted primary_text so the ads auction
has real variance to optimise on; falls back to a rule-based template
if the router is unavailable. One LLM call, ~500 tokens — budget-safe.

Also attempts Pexels video search for B-roll so the ads have a video
primary when the supplier gallery is thin (free stock, no credits).
"""
from __future__ import annotations

import json
import re
from typing import Any

from utils.logger import get_logger

from ..context import LaunchContext
from ._base import Step, StepSkip


logger = get_logger("workflows.launch.creative")


class CreativeStep(Step):
    name = "creative"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        if not context.media.get("gallery"):
            raise StepSkip("no media to build creatives from")

        title = context.content.get("title", "Limited offer")
        primary = context.media.get("primary_image", "")
        bullets = context.content.get("bullets", [])
        tone = context.goal.copy_tone

        variants = self._llm_variants(title, bullets, tone, context.goal.niche)
        if not variants:
            variants = self._fallback_variants(title, bullets)

        video_url = self._fetch_pexels_video(title, context.goal.niche)

        return {
            "variants": [dict(v, image_url=primary) for v in variants],
            "video_url": video_url,
            "_video_source": "pexels" if video_url else None,
        }

    @staticmethod
    def _llm_variants(
        title: str, bullets: list[str], tone: str, niche: str,
    ) -> list[dict[str, Any]]:
        """Ask one LLM call for three angles. Parse loose JSON so a
        missing comma or stray ```json fence doesn't kill the call."""
        try:
            from core.adapters import get_router
            from core.adapters.base import Capability
        except Exception:
            return []

        prompt = (
            f"You write Meta Ads creatives. Niche: {niche or 'general'}. "
            f"Tone: {tone}. Product title: \"{title}\". "
            f"Key benefits: {bullets[:5]}.\n\n"
            "Return a JSON array of exactly 3 ad variants. Each has:\n"
            "  id:            one of v1_hook | v2_benefits | v3_proof\n"
            "  headline:      <=40 chars, no emoji\n"
            "  primary_text:  90-125 chars, single sentence, compelling\n"
            "  cta:           one of 'Shop Now' | 'Learn More' | 'Get Yours'\n"
            "Respond with JSON only, no commentary, no markdown fences."
        )

        try:
            router = get_router()
            result = router.execute(
                capability=Capability.CHAT_COMPLETE,
                params={
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.8,
                },
            )
        except Exception as exc:  # router + adapter failures
            logger.debug("creative LLM call failed: %s", exc)
            return []

        if not result.ok or not result.data:
            return []

        text = result.data.get("text", "")
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        variants: list[dict[str, Any]] = []
        for item in data[:3]:
            if not isinstance(item, dict):
                continue
            variants.append({
                "id": item.get("id") or f"v{len(variants) + 1}",
                "headline": str(item.get("headline", ""))[:60],
                "primary_text": str(item.get("primary_text", ""))[:200],
                "cta": item.get("cta") or "Shop Now",
            })
        return variants

    @staticmethod
    def _fallback_variants(title: str, bullets: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": "v1_hook",
                "headline": title[:40],
                "primary_text": f"You won't believe this. {title}",
                "cta": "Shop Now",
            },
            {
                "id": "v2_benefits",
                "headline": title[:40],
                "primary_text": "✓ " + " ✓ ".join(bullets[:3]) if bullets else title,
                "cta": "Learn More",
            },
            {
                "id": "v3_proof",
                "headline": "Loved by thousands",
                "primary_text": f"⭐⭐⭐⭐⭐ {title}",
                "cta": "Shop Now",
            },
        ]

    @staticmethod
    def _fetch_pexels_video(title: str, niche: str) -> str | None:
        """Pexels video search — optional. Returns first landscape
        HD clip URL or None. Free tier is generous; a missing key just
        returns None silently."""
        try:
            import os
            import urllib.error
            import urllib.parse
            import urllib.request
            api_key = os.environ.get("PEXELS_API_KEY", "")
            if not api_key:
                return None
            query = title or niche
            if not query:
                return None
            url = (
                "https://api.pexels.com/videos/search?"
                + urllib.parse.urlencode({
                    "query": query,
                    "per_page": 3,
                    "orientation": "landscape",
                    "size": "medium",
                })
            )
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": api_key,
                    "User-Agent": "ShopAI/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
            logger.debug("Pexels video search failed: %s", exc)
            return None

        for video in data.get("videos", []):
            files = video.get("video_files") or []
            for f in files:
                if f.get("quality") in ("hd", "sd") and f.get("link"):
                    return f["link"]
        return None
