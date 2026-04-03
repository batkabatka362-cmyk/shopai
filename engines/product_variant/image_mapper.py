"""Product Variant Engine — image mapper.

Matches product images to variants by searching for option-value keywords
in image alt text and filenames.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import os
from typing import Any


def map_images(
    variants: list[dict[str, Any]],
    images: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match images to variants by keyword matching in alt text or filename.

    Matching strategy (in priority order):
      1. Exact option value found in alt text
      2. Exact option value found in filename (without extension)

    If multiple images match a variant, all are included.
    If no images match a variant, it is omitted from the mappings list.

    Args:
        variants: List of GeneratedVariant dicts.
        images: List of ImageRecord dicts with image_id, alt, filename/src.

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

        # Pre-process images: normalize searchable text
        processed_images: list[dict[str, Any]] = []
        for img in images:
            image_id = str(img.get("image_id", ""))
            alt_text = str(img.get("alt", "")).lower().strip()

            # Extract filename from src if filename not provided
            filename = str(img.get("filename", ""))
            if not filename and img.get("src"):
                filename = os.path.basename(str(img["src"]))
            filename_base = os.path.splitext(filename)[0].lower().strip()
            # Normalize separators to spaces for better matching
            filename_normalized = (
                filename_base.replace("-", " ")
                .replace("_", " ")
                .replace(".", " ")
            )

            processed_images.append({
                "image_id": image_id,
                "alt_lower": alt_text,
                "filename_normalized": filename_normalized,
            })

        mappings: list[dict[str, Any]] = []

        for idx, variant in enumerate(variants):
            options = variant.get("options", {})

            for img in processed_images:
                matched_by = _find_match(options, img)
                if matched_by:
                    mappings.append({
                        "variant_index": idx,
                        "image_id": img["image_id"],
                        "matched_by": matched_by,
                    })

        return {
            "status": "success",
            "mappings": mappings,
        }
    except Exception as exc:
        return _fail(f"Image mapping failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_match(
    options: dict[str, str],
    processed_image: dict[str, str],
) -> str | None:
    """Check if any option value appears in the image's alt or filename.

    Returns a description of what matched, or None.
    """
    alt = processed_image["alt_lower"]
    fname = processed_image["filename_normalized"]

    for axis_name, value in options.items():
        needle = str(value).lower().strip()
        if not needle:
            continue

        if needle in alt:
            return f"alt_text:{axis_name}={value}"

        if needle in fname:
            return f"filename:{axis_name}={value}"

    return None


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "mappings": [],
        "error": reason,
    }
