"""Image Optimization Engine — gallery planner.

Plans optimal image gallery order and identifies missing image types
(lifestyle, detail, scale, packaging, etc.).

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Expected image types for a complete product gallery
# ---------------------------------------------------------------------------

_EXPECTED_TYPES = [
    "hero",       # Main product shot, white background
    "lifestyle",  # Product in use / context
    "detail",     # Close-up of features
    "scale",      # Product with size reference
    "packaging",  # How product arrives
    "alternate",  # Different angle
]

# Heuristic: classify image by position and alt text keywords
_TYPE_KEYWORDS: dict[str, list[str]] = {
    "lifestyle": ["lifestyle", "in use", "wearing", "using", "action", "outdoor"],
    "detail": ["detail", "close-up", "closeup", "zoom", "texture", "feature"],
    "scale": ["scale", "size", "comparison", "hand", "next to"],
    "packaging": ["packaging", "box", "unbox", "package"],
    "alternate": ["alternate", "side", "back", "angle", "view"],
}


def plan_gallery(
    images: list[dict[str, Any]],
    quality_analyses: list[dict[str, Any]],
    product: dict[str, Any],
) -> dict[str, Any]:
    """Plan gallery order and identify missing image types.

    Args:
        images: List of image dicts.
        quality_analyses: Quality analysis results per image.
        product: Product info dict.

    Returns:
        Structured dict with gallery order and missing types.
    """
    try:
        items = copy.deepcopy(images)
        analyses = copy.deepcopy(quality_analyses)

        # Build quality score map
        quality_map: dict[int, str] = {}
        for a in analyses:
            img_id = int(a.get("image_id", -1))
            quality_map[img_id] = str(a.get("quality_rating", "fair"))

        # Classify each image's type
        classified: list[dict[str, Any]] = []
        detected_types: set[str] = set()

        for i, img in enumerate(items):
            alt = str(img.get("alt", "")).lower()
            url = str(img.get("url", "")).lower()
            combined = f"{alt} {url}"

            img_type = "hero" if i == 0 else "alternate"
            for type_name, keywords in _TYPE_KEYWORDS.items():
                if any(kw in combined for kw in keywords):
                    img_type = type_name
                    break

            detected_types.add(img_type)

            # Priority: hero first, then quality-based
            quality_priority = {
                "excellent": 4, "good": 3, "fair": 2, "poor": 1,
            }
            priority = quality_priority.get(quality_map.get(i, "fair"), 2)
            if img_type == "hero":
                priority += 10
            elif img_type == "lifestyle":
                priority += 5
            elif img_type == "detail":
                priority += 3

            classified.append({
                "image_id": i,
                "image_type": img_type,
                "priority": priority,
                "quality": quality_map.get(i, "fair"),
            })

        # Sort by priority for gallery order
        classified.sort(key=lambda c: c["priority"], reverse=True)

        gallery_order: list[dict[str, Any]] = []
        for pos, item in enumerate(classified):
            gallery_order.append({
                "position": pos,
                "image_id": item["image_id"],
                "image_type": item["image_type"],
                "reason": f"Priority {item['priority']} ({item['quality']} quality)",
            })

        # Identify missing types
        missing_types = [t for t in _EXPECTED_TYPES if t not in detected_types]

        return {
            "status": "success",
            "gallery_order": gallery_order,
            "missing_types": missing_types,
        }
    except Exception as exc:
        return {
            "status": "error",
            "gallery_order": [],
            "missing_types": [],
            "error": f"Gallery planning failed: {exc}",
        }
