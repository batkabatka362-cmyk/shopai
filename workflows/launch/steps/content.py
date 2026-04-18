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

        # TODO(brain): call core.adapters.get_router().route(
        #     capability="text.write_long",
        #     prompt=_build_prompt(context),
        #     prefer=("gemini", "groq", "deepseek"),
        # )
        # Stub: deterministic template so downstream steps work without LLM.
        bullets = [
            "Premium quality, ready to ship",
            "Fast delivery from our trusted suppliers",
            "30-day money-back guarantee",
            "Loved by thousands of customers",
            "Limited stock — order today",
        ]
        return {
            "title": title[:120],
            "description": (
                f"<p><strong>{title}</strong></p>"
                "<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
            ),
            "bullets": bullets,
            "seo_title": title[:70],
            "seo_description": (title + " — fast shipping, money-back guarantee")[:160],
            "tags": [t.strip() for t in (context.goal.niche or "").split(",") if t.strip()],
            "_llm_used": False,  # toggle when router is wired
        }
