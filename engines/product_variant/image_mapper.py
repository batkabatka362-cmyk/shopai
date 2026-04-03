"""Product Variant Engine — image mapper.

Matches product images to variants by searching for option value keywords
in the image alt text or filename.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import re
from typing import Any


def map_images(
    variants: list[dict[str, Any]],
    images: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match images to variants by color/option keywords in alt text or filename.

    Args:
        variants: List of variant dicts from variant_generator.
        images: List of image dicts with 'image_id', 'alt_text', 'filename'.

    Returns:
        Structured dict with image-to-variant mappings.
    """
    try:
        variants = copy.deepcopy(variants)
        images = copy.deepcopy(images) if images else []

        if not images:
            return {
                "status": "success",
                "mappings": [],
            }

        mappings: list[dict[str, Any]] = []

        for idx, variant in enumerate(variants):
            variant_options = variant.get("options", {})

            for image in images:
                image_id = str(image.get("image_id", ""))
                alt_text = str(image.get("alt_text", "")).lower()
                filename = str(image.get("filename", "")).lower()
                searchable = alt_text + " " + filename

                # Try matching each option value in the image metadata
                for axis_name, axis_value in variant_options.items():
                    value_lower = str(axis_value).lower()

                    if _keyword_match(value_lower, searchable):
                        matched_by = _determine_match_source(
                            value_lower, alt_text, filename,
                        )
                        mappings.append({
                            "variant_index": idx,
                            "image_id": image_id,
                            "matched_by": f"{axis_name}:{axis_value} in {matched_by}",
                        })
                        # Only match one image per option match per variant
                        break

        # Deduplicate: keep first mapping per (variant_index, image_id) pair
        seen: set[tuple[int, str]] = set()
        unique_mappings: list[dict[str, Any]] = []
        for mapping in mappings:
            key = (mapping["variant_index"], mapping["image_id"])
            if key not in seen:
                seen.add(key)
                unique_mappings.append(mapping)

        return {
            "status": "success",
            "mappings": unique_mappings,
        }
    except Exception as exc:
        return _fail(f"Image mapping failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _keyword_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a whole word/token in text.

    For short keywords (<=2 chars) we require word boundaries to avoid
    false positives like 'S' matching inside 'shirt'. For longer keywords
    a simple substring match is sufficient.
    """
    if len(keyword) <= 2:
        # Word-boundary match: surrounded by non-alphanumeric or string edges
        pattern = r"(?<![a-zA-Z0-9])" + re.escape(keyword) + r"(?![a-zA-Z0-9])"
        return bool(re.search(pattern, text))
    return keyword in text


def _determine_match_source(
    value: str,
    alt_text: str,
    filename: str,
) -> str:
    """Determine whether the match came from alt_text, filename, or both."""
    in_alt = _keyword_match(value, alt_text)
    in_file = _keyword_match(value, filename)
    if in_alt and in_file:
        return "alt_text+filename"
    if in_alt:
        return "alt_text"
    return "filename"


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "mappings": [],
        "error": reason,
    }
