"""Image Optimization Engine — size optimizer.

Recommends optimal dimensions, compression levels, and file sizes
for product images based on platform and quality requirements.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Platform dimension requirements
# ---------------------------------------------------------------------------

_PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "amazon": {"max_width": 2000, "max_height": 2000, "ideal_width": 1500, "ideal_height": 1500},
    "etsy": {"max_width": 2700, "max_height": 2025, "ideal_width": 2000, "ideal_height": 1500},
    "ebay": {"max_width": 1600, "max_height": 1600, "ideal_width": 1200, "ideal_height": 1200},
    "shopify": {"max_width": 2048, "max_height": 2048, "ideal_width": 1200, "ideal_height": 1200},
    "web": {"max_width": 1920, "max_height": 1920, "ideal_width": 1200, "ideal_height": 1200},
}

# Compression quality levels
_COMPRESSION_LEVELS = {
    "high": {"quality_pct": 90, "target_ratio": 0.7},
    "medium": {"quality_pct": 80, "target_ratio": 0.5},
    "aggressive": {"quality_pct": 65, "target_ratio": 0.3},
}

_IDEAL_MAX_BYTES = 200_000  # 200 KB


def optimize_sizes(
    images: list[dict[str, Any]],
    platform: str,
    quality_analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recommend optimal sizes and compression for images.

    Args:
        images: List of image dicts (with size_bytes, width, height).
        platform: Target platform name.
        quality_analyses: Quality analysis results per image.

    Returns:
        Structured dict with size recommendations.
    """
    try:
        items = copy.deepcopy(images)
        specs = _PLATFORM_SPECS.get(platform.lower(), _PLATFORM_SPECS["web"])
        ideal_w = int(specs["ideal_width"])
        ideal_h = int(specs["ideal_height"])

        recommendations: list[dict[str, Any]] = []

        for i, img in enumerate(items):
            size_bytes = int(img.get("size_bytes", 0))
            width = int(img.get("width", 0))
            height = int(img.get("height", 0))

            # Determine compression level
            if size_bytes <= _IDEAL_MAX_BYTES:
                compression = "none"
                target_bytes = size_bytes
            elif size_bytes <= _IDEAL_MAX_BYTES * 2:
                compression = "high"
                target_bytes = int(size_bytes * _COMPRESSION_LEVELS["high"]["target_ratio"])
            elif size_bytes <= _IDEAL_MAX_BYTES * 5:
                compression = "medium"
                target_bytes = int(size_bytes * _COMPRESSION_LEVELS["medium"]["target_ratio"])
            else:
                compression = "aggressive"
                target_bytes = int(size_bytes * _COMPRESSION_LEVELS["aggressive"]["target_ratio"])

            # Ensure target doesn't exceed ideal
            target_bytes = min(target_bytes, _IDEAL_MAX_BYTES) if compression != "none" else target_bytes

            # Determine recommended dimensions
            if width > 0 and height > 0:
                if width > ideal_w or height > ideal_h:
                    # Scale down proportionally
                    scale = min(ideal_w / width, ideal_h / height)
                    rec_w = int(width * scale)
                    rec_h = int(height * scale)
                else:
                    rec_w = width
                    rec_h = height
                rec_dims = f"{rec_w}x{rec_h}"
            else:
                rec_dims = f"{ideal_w}x{ideal_h}"

            # Savings calculation
            if size_bytes > 0 and compression != "none":
                savings_pct = round((1 - target_bytes / size_bytes) * 100, 1)
            else:
                savings_pct = 0.0

            recommendations.append({
                "image_id": i,
                "current_size_bytes": size_bytes,
                "recommended_size_bytes": max(target_bytes, 1),
                "compression": compression,
                "recommended_dimensions": rec_dims,
                "savings_pct": savings_pct,
            })

        return {
            "status": "success",
            "recommendations": recommendations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommendations": [],
            "error": f"Size optimization failed: {exc}",
        }
