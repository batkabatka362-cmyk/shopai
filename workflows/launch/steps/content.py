"""Step 4 — AI content generation.

This is the *one* place LLMs are unconditionally needed (per CLAUDE.md
§4b.A — 95/5 rule). Produce:

  • title  — short, benefit-led, SEO friendly
  • description — HTML body with bullets, hook, social proof
  • bullets — 5 short benefits
  • seo_title, seo_description, tags

Calls the configured Model 2 (Gemini 1.5 Flash) by preference because
it handles long-context multimodal content well. Falls back through the
adapter router so a missing GOOGLE_API_KEY doesn't break the launch.
"""
from __future__ import annotations

from typing import Any

from ..context import LaunchContext
from ._base import Step, StepSkip


class ContentStep(Step):
    name = "content"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        title = context.source.get("title") or ""
        if not title:
            raise StepSkip("source has no title — cannot draft content")

        tone = context.goal.copy_tone
        niche = context.goal.niche
        attrs = context.source.get("attributes", {})

        prompt = (
            "You are a conversion-focused e-commerce copywriter. "
            f"Write product copy for a dropshipping Shopify listing in a {tone} tone. "
            f"Niche: {niche or 'general'}. "
            f"Product title (raw): \"{title}\". "
            f"Known attributes: {attrs}. "
            "\n\nRespond ONLY with a compact JSON object with these keys:"
            "\n  title: short catchy title (<=80 chars)"
            "\n  description_html: HTML body with <p> and <ul><li> only"
            "\n  bullets: JSON array of 5 one-line benefit strings"
            "\n  seo_title: <=70 chars"
            "\n  seo_description: <=160 chars"
            "\n  tags: JSON array of 3-6 single-word tags"
            "\nNo commentary, no markdown fences — JSON only."
        )

        fallback = self._deterministic_fallback(title, niche)

        try:
            from core.adapters import get_router
            from core.adapters.base import Capability
        except Exception as exc:  # adapter layer not initialised
            fallback["_llm_used"] = False
            fallback["_llm_error"] = f"adapters unavailable: {exc}"
            return fallback

        try:
            router = get_router()
            result = router.execute(
                capability=Capability.CHAT_COMPLETE,
                params={
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 600,
                    "temperature": 0.7,
                },
            )
        except Exception as exc:  # router raised NoAdapterAvailable / etc.
            fallback["_llm_used"] = False
            fallback["_llm_error"] = f"{type(exc).__name__}: {exc}"
            return fallback

        if not result.ok or not result.data:
            fallback["_llm_used"] = False
            fallback["_llm_error"] = (
                f"adapter={result.adapter}, error={result.error}"
            )
            return fallback

        parsed = self._parse_llm_response(result.data.get("text", ""))
        if not parsed:
            fallback["_llm_used"] = False
            fallback["_llm_error"] = "LLM response was not parseable JSON"
            fallback["_llm_adapter"] = result.adapter
            return fallback

        return {
            "title": parsed.get("title") or title[:120],
            "description": parsed.get("description_html") or fallback["description"],
            "bullets": parsed.get("bullets") or fallback["bullets"],
            "seo_title": parsed.get("seo_title") or title[:70],
            "seo_description": parsed.get("seo_description") or fallback["seo_description"],
            "tags": parsed.get("tags") or fallback["tags"],
            "_llm_used": True,
            "_llm_adapter": result.adapter,
            "_llm_model": result.model,
            "_llm_latency_ms": round(result.latency_ms, 1),
        }

    @staticmethod
    def _deterministic_fallback(title: str, niche: str) -> dict[str, Any]:
        bullets = [
            "Premium quality, ready to ship",
            "Fast delivery from our trusted suppliers",
            "30-day money-back guarantee",
            "Loved by thousands of customers",
            "Limited stock — order today",
        ]
        tags = [t.strip() for t in (niche or "").split(",") if t.strip()]
        return {
            "title": title[:120],
            "description": (
                f"<p><strong>{title}</strong></p>"
                "<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
            ),
            "bullets": bullets,
            "seo_title": title[:70],
            "seo_description": (title + " — fast shipping, money-back guarantee")[:160],
            "tags": tags,
        }

    @staticmethod
    def _parse_llm_response(text: str) -> dict[str, Any] | None:
        """Pull the first JSON object out of the LLM text. Models
        occasionally wrap the payload in ```json fences — strip those
        before parsing."""
        import json
        import re
        if not text:
            return None
        # Strip markdown fences
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        return data
