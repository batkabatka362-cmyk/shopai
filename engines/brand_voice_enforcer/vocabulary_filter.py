"""Brand Voice Enforcer Engine — vocabulary filter.

Flags off-brand words and suggests on-brand alternatives.
Uses brand voice vocabulary and dos/donts to evaluate word choices.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Common off-brand word → on-brand replacement suggestions
# ---------------------------------------------------------------------------

_GENERIC_REPLACEMENTS: dict[str, list[str]] = {
    "cheap": ["affordable", "value-driven", "accessible"],
    "buy": ["invest in", "discover", "explore"],
    "stuff": ["products", "collection", "offerings"],
    "things": ["essentials", "items", "solutions"],
    "nice": ["exceptional", "remarkable", "refined"],
    "good": ["excellent", "outstanding", "superior"],
    "bad": ["suboptimal", "challenging", "concerning"],
    "big": ["substantial", "significant", "expansive"],
    "small": ["compact", "refined", "curated"],
    "get": ["acquire", "receive", "obtain"],
    "very": ["remarkably", "exceptionally", "truly"],
    "really": ["genuinely", "truly", "remarkably"],
    "a lot": ["extensively", "significantly", "considerably"],
    "ok": ["satisfactory", "acceptable", "adequate"],
    "awesome": ["exceptional", "outstanding", "remarkable"],
    "cool": ["impressive", "innovative", "compelling"],
}


def filter_vocabulary(
    content: list[dict[str, Any]],
    brand_voice: dict[str, Any],
) -> dict[str, Any]:
    """Filter vocabulary for brand alignment.

    Args:
        content: List of content item dicts.
        brand_voice: Brand voice spec with vocabulary and donts.

    Returns:
        Structured dict with per-content vocabulary filter results.
    """
    try:
        on_brand_vocab = set(
            w.lower() for w in brand_voice.get("vocabulary", [])
        )
        donts = brand_voice.get("donts", [])

        # Extract prohibited word patterns from donts
        prohibited_patterns: set[str] = set()
        for dont in donts:
            dont_lower = dont.lower()
            if "slang" in dont_lower:
                prohibited_patterns.update({"gonna", "wanna", "gotta", "tbh", "imo", "lol", "omg"})
            if "casual" in dont_lower:
                prohibited_patterns.update({"hey", "yeah", "nope", "nah", "yep", "cool", "awesome"})
            if "exclamation" in dont_lower:
                prohibited_patterns.add("!!!")
            if "discount" in dont_lower or "salesy" in dont_lower:
                prohibited_patterns.update({"free", "bargain", "clearance", "blowout", "cheapest"})

        results: list[dict[str, Any]] = []

        for idx, item in enumerate(content):
            text = str(item.get("text", ""))
            words = text.lower().split()
            clean_words = [w.strip(".,!?;:\"'()") for w in words]

            off_brand: list[str] = []
            replacements: dict[str, str] = {}
            on_brand_count = 0

            for word in clean_words:
                if word in on_brand_vocab:
                    on_brand_count += 1

                if word in prohibited_patterns:
                    off_brand.append(word)
                    if word in _GENERIC_REPLACEMENTS:
                        replacements[word] = _GENERIC_REPLACEMENTS[word][0]

                if word in _GENERIC_REPLACEMENTS and word not in on_brand_vocab:
                    if word not in off_brand:
                        off_brand.append(word)
                    replacements[word] = _GENERIC_REPLACEMENTS[word][0]

            # Deduplicate off_brand
            off_brand = list(dict.fromkeys(off_brand))

            results.append({
                "content_idx": idx,
                "off_brand_words": off_brand,
                "suggested_replacements": replacements,
                "on_brand_word_count": on_brand_count,
            })

        return {
            "status": "success",
            "vocabulary_results": results,
        }
    except Exception as exc:
        return {
            "status": "error",
            "vocabulary_results": [],
            "error": f"Vocabulary filtering failed: {exc}",
        }
