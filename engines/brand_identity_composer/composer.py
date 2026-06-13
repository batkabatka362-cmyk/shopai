"""Brand identity composer.

Chains LLM (Claude / OpenAI) for palette + typography +
brief, image-gen adapter for logo concepts, Pexels for
hero candidates. Each stage defensive: missing adapter
degrades to a fallback (curated niche template) without
crashing the chain.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Per-niche curated fallback templates ──────────────────


_NICHE_TEMPLATES: dict[str, dict[str, Any]] = {
    "beauty": {
        "palette": {
            "primary": "#E8B4BC",
            "secondary": "#9B6B7A",
            "accent": "#F5C9C6",
            "text": "#2D1F22",
            "background": "#FAF7F5",
        },
        "fonts": {
            "heading": "Playfair Display",
            "body": "Lato",
        },
        "voice": "warm + aspirational + clean",
    },
    "tech": {
        "palette": {
            "primary": "#0F62FE",
            "secondary": "#161616",
            "accent": "#42BE65",
            "text": "#161616",
            "background": "#FFFFFF",
        },
        "fonts": {
            "heading": "IBM Plex Sans",
            "body": "IBM Plex Sans",
        },
        "voice": "precise + confident + minimal",
    },
    "fashion": {
        "palette": {
            "primary": "#1A1A1A",
            "secondary": "#C9A961",
            "accent": "#FFFFFF",
            "text": "#1A1A1A",
            "background": "#F5F2EC",
        },
        "fonts": {
            "heading": "Bodoni Moda",
            "body": "Inter",
        },
        "voice": "editorial + bold + curated",
    },
    "home": {
        "palette": {
            "primary": "#7C9885",
            "secondary": "#D4A574",
            "accent": "#F0EAD6",
            "text": "#3A3A3A",
            "background": "#FBFAF7",
        },
        "fonts": {
            "heading": "Cormorant Garamond",
            "body": "Source Sans 3",
        },
        "voice": "calm + cozy + practical",
    },
    "food": {
        "palette": {
            "primary": "#D2691E",
            "secondary": "#8B4513",
            "accent": "#FFE4B5",
            "text": "#3E2723",
            "background": "#FFF8E1",
        },
        "fonts": {
            "heading": "Merriweather",
            "body": "Open Sans",
        },
        "voice": "warm + trustworthy + appetising",
    },
    # Fallback when niche is empty or unknown
    "general": {
        "palette": {
            "primary": "#2C3E50",
            "secondary": "#E67E22",
            "accent": "#ECF0F1",
            "text": "#2C3E50",
            "background": "#FFFFFF",
        },
        "fonts": {
            "heading": "Inter",
            "body": "Inter",
        },
        "voice": "clear + friendly + neutral",
    },
}


@dataclass
class ColorPalette:
    primary: str
    secondary: str
    accent: str
    text: str
    background: str


@dataclass
class Typography:
    heading: str
    body: str


@dataclass
class BrandBrief:
    """Composed brand identity brief."""
    store_id: str
    niche: str
    brand_name_suggestions: list[str] = field(
        default_factory=list,
    )
    tagline: str = ""
    voice: str = ""
    palette: ColorPalette | None = None
    typography: Typography | None = None
    logo_concepts: list[dict[str, str]] = field(
        default_factory=list,
    )
    hero_candidates: list[dict[str, str]] = field(
        default_factory=list,
    )
    notes: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return bool(
            self.palette
            and self.typography
            and (
                self.brand_name_suggestions
                or self.logo_concepts
            )
        )


def _normalise_niche(niche: str) -> str:
    n = (niche or "").strip().lower()
    if n in _NICHE_TEMPLATES:
        return n
    return "general"


def _apply_template(
    brief: BrandBrief,
) -> None:
    """Seed brief with niche template defaults so we
    always have a palette + typography even if LLM
    fails."""
    tmpl = _NICHE_TEMPLATES[
        _normalise_niche(brief.niche)
    ]
    brief.palette = ColorPalette(**tmpl["palette"])
    brief.typography = Typography(**tmpl["fonts"])
    brief.voice = tmpl["voice"]


def _safe_llm_brand_brief(
    store_id: str, niche: str, target_market: str,
) -> dict[str, Any]:
    """Defensive: ask the LLM brain for brand name
    suggestions + tagline + voice refinement."""
    try:
        from core.adapters.smart_router import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "router unavailable for brand LLM: %s",
            exc,
        )
        return {}
    prompt = (
        f"You are a brand strategist. The store sells "
        f"in the {niche or 'general consumer'} niche, "
        f"targeting {target_market or 'global'} "
        f"market.\n\n"
        f"Propose:\n"
        f"  1. Three concise brand name suggestions "
        f"(2-3 syllables each, brandable, easy to "
        f"pronounce).\n"
        f"  2. A single one-line tagline (under 60 "
        f"chars) that signals value + niche.\n"
        f"  3. Brand voice: 4-6 words that capture "
        f"tone (e.g. 'warm + aspirational + clean').\n\n"
        f"Output JSON ONLY in this exact shape:\n"
        f"{{\"names\": [...], \"tagline\": \"...\", "
        f"\"voice\": \"...\"}}"
    )
    try:
        result = router.execute(
            Capability.CHAT_COMPLETE,
            {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "max_tokens": 300,
                "temperature": 0.7,
            },
        )
        if not result.ok:
            return {}
        data = getattr(result, "data", None) or {}
        text = (
            data.get("text")
            or data.get("content")
            or ""
        )
        return _parse_llm_brand_json(text)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "LLM brand brief raised: %s", exc,
        )
        return {}


def _parse_llm_brand_json(
    text: str,
) -> dict[str, Any]:
    """Extract JSON from LLM output. Tolerant of code
    fences + leading prose."""
    if not text:
        return {}
    import json
    import re
    # Find first { ... } block
    m = re.search(
        r"\{[\s\S]*?\}", text,
    )
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(0))
        if not isinstance(parsed, dict):
            return {}
        return parsed
    except (json.JSONDecodeError, ValueError):
        return {}


def _safe_logo_concepts(
    brief: BrandBrief, count: int = 2,
) -> list[dict[str, str]]:
    """Try image-gen adapter to produce logo concept
    URLs. Fail-soft returns empty list."""
    if not brief.brand_name_suggestions:
        return []
    try:
        from core.adapters.smart_router import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "router unavailable for logo gen: %s",
            exc,
        )
        return []

    palette = brief.palette
    palette_hint = (
        f"colors: {palette.primary}, "
        f"{palette.secondary}, {palette.accent}"
        if palette else ""
    )
    out: list[dict[str, str]] = []
    for name in brief.brand_name_suggestions[:count]:
        prompt = (
            f"Minimalist vector logo for a brand "
            f"called '{name}' in the "
            f"{brief.niche or 'general'} niche. "
            f"{palette_hint}. Clean, modern, scalable. "
            f"White background, centered, no text "
            f"artifacts."
        )
        try:
            result = router.execute(
                Capability.GENERATE_IMAGE,
                {
                    "prompt": prompt,
                    "size": "1024x1024",
                    "n": 1,
                },
            )
            if not result.ok:
                continue
            data = getattr(
                result, "data", None,
            ) or {}
            images = data.get("images") or []
            if not images:
                continue
            url = ""
            if isinstance(images[0], dict):
                url = images[0].get("url", "")
            elif isinstance(images[0], str):
                url = images[0]
            if url:
                out.append({
                    "brand_name": name,
                    "url": url,
                    "source": "image_gen",
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "logo concept %s raised: %s",
                name, exc,
            )
            continue
    return out


def _safe_hero_candidates(
    niche: str, count: int = 3,
) -> list[dict[str, str]]:
    """Pexels search for niche-appropriate hero
    candidates. Fail-soft returns []."""
    try:
        from core.adapters.smart_router import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "router unavailable for hero gen: %s",
            exc,
        )
        return []
    query = (niche or "lifestyle").strip()
    try:
        result = router.execute(
            Capability.VIDEO_STOCK_SEARCH,
            {
                "query": query,
                "per_page": max(1, count),
                "media": "photo",
            },
        )
        if not result.ok:
            return []
        data = getattr(result, "data", None) or {}
        items = (
            data.get("videos")
            or data.get("photos")
            or data.get("items")
            or []
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "hero search raised: %s", exc,
        )
        return []
    out: list[dict[str, str]] = []
    for it in items[:count]:
        if not isinstance(it, dict):
            continue
        url = (
            it.get("url")
            or it.get("src", {}).get("large")
            or ""
        )
        if url:
            out.append({
                "url": str(url),
                "source": "pexels",
                "query": query,
            })
    return out


def build_brief(
    store_id: str,
    *,
    niche: str = "",
    target_market: str = "",
    logo_concept_count: int = 2,
    hero_count: int = 3,
) -> BrandBrief:
    """Compose the full brand identity brief."""
    if not store_id:
        raise ValueError("store_id required")
    brief = BrandBrief(
        store_id=store_id,
        niche=niche,
    )
    # 1. Seed palette + typography from niche template
    _apply_template(brief)
    if brief.niche != _normalise_niche(brief.niche):
        brief.notes.append(
            f"niche '{niche}' not in catalogue; "
            f"falling back to 'general' template"
        )
        brief.niche = _normalise_niche(brief.niche)

    # 2. Ask LLM to fill name suggestions + tagline
    llm = _safe_llm_brand_brief(
        store_id, niche, target_market,
    )
    if not llm:
        brief.notes.append(
            "LLM brand brief unavailable "
            "(check `shopai api-test --alias openai`)"
        )
    else:
        names = llm.get("names") or []
        if isinstance(names, list):
            brief.brand_name_suggestions = [
                str(n).strip() for n in names
                if str(n).strip()
            ][:3]
        tagline = llm.get("tagline")
        if isinstance(tagline, str):
            brief.tagline = tagline[:120].strip()
        voice = llm.get("voice")
        if (
            isinstance(voice, str) and voice.strip()
        ):
            brief.voice = voice.strip()[:120]

    # 3. Logo concepts (image gen)
    if brief.brand_name_suggestions:
        brief.logo_concepts = _safe_logo_concepts(
            brief, count=logo_concept_count,
        )
        if not brief.logo_concepts:
            brief.notes.append(
                "no logo concepts (check "
                "`shopai api-test --alias openai` "
                "or set GENERATE_IMAGE adapter)"
            )

    # 4. Hero candidates (Pexels)
    brief.hero_candidates = _safe_hero_candidates(
        niche=brief.niche, count=hero_count,
    )
    if not brief.hero_candidates:
        brief.notes.append(
            "no hero candidates (check "
            "`shopai api-test --alias pexels`)"
        )

    return brief


def brief_to_markdown(brief: BrandBrief) -> str:
    """Render brief for the approval queue narrative."""
    lines: list[str] = []
    lines.append(
        f"## Brand identity brief  -- "
        f"store={brief.store_id}"
    )
    lines.append("")
    lines.append(
        f"**Niche:** {brief.niche}"
    )
    lines.append(
        f"**Voice:** {brief.voice or '(unspecified)'}"
    )
    lines.append(
        f"**Tagline:** "
        f"{brief.tagline or '(none)'}"
    )
    lines.append("")
    if brief.brand_name_suggestions:
        lines.append("### Brand name candidates")
        for n in brief.brand_name_suggestions:
            lines.append(f"  - {n}")
        lines.append("")
    if brief.palette:
        p = brief.palette
        lines.append("### Color palette")
        lines.append(
            f"  - primary    `{p.primary}`"
        )
        lines.append(
            f"  - secondary  `{p.secondary}`"
        )
        lines.append(
            f"  - accent     `{p.accent}`"
        )
        lines.append(
            f"  - text       `{p.text}`"
        )
        lines.append(
            f"  - background `{p.background}`"
        )
        lines.append("")
    if brief.typography:
        lines.append("### Typography")
        lines.append(
            f"  - heading: {brief.typography.heading}"
        )
        lines.append(
            f"  - body:    {brief.typography.body}"
        )
        lines.append("")
    if brief.logo_concepts:
        lines.append("### Logo concepts")
        for i, lc in enumerate(
            brief.logo_concepts, start=1,
        ):
            lines.append(
                f"  {i}. {lc.get('brand_name', '?')}: "
                f"{lc.get('url', '?')}"
            )
        lines.append("")
    if brief.hero_candidates:
        lines.append("### Hero / banner candidates")
        for i, hc in enumerate(
            brief.hero_candidates, start=1,
        ):
            lines.append(
                f"  {i}. {hc.get('url', '?')}"
            )
        lines.append("")
    if brief.notes:
        lines.append("### Notes")
        for n in brief.notes:
            lines.append(f"  - {n}")
        lines.append("")
    lines.append(
        "**Approve** to push palette + typography to "
        "the Shopify theme, upload the first logo "
        "concept as the store logo, and add hero "
        "candidates to the brand-assets folder. "
        "**Reject** to discard."
    )
    return "\n".join(lines)
