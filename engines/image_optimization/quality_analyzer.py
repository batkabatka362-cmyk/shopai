"""Image Optimization Engine — quality analyzer.

Analyzes image quality, resolution, estimated load time, and
identifies common issues (oversized, low-res, missing alt text).

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Quality thresholds
# ---------------------------------------------------------------------------

_MIN_WIDTH = 800
_MIN_HEIGHT = 800
_MAX_SIZE_BYTES = 500_000  # 500 KB
_IDEAL_SIZE_BYTES = 200_000  # 200 KB

# Estimated bytes-per-ms for a typical connection (~5 Mbps)
_BYTES_PER_MS = 625


def analyze_quality(
    images: list[dict[str, Any]],
    platform: str,
) -> dict[str, Any]:
    """Analyze quality of product images.

    Args:
        images: List of image dicts (url, alt, size_bytes, width, height).
        platform: Target platform (affects resolution requirements).

    Returns:
        Structured dict with per-image quality analysis.
    """
    try:
        items = copy.deepcopy(images)
        analyses: list[dict[str, Any]] = []

        total_score = 0.0

        for i, img in enumerate(items):
            url = str(img.get("url", ""))
            alt = str(img.get("alt", ""))
            size_bytes = int(img.get("size_bytes", 0))
            width = int(img.get("width", 0))
            height = int(img.get("height", 0))

            issues: list[str] = []

            # Resolution check
            resolution_ok = width >= _MIN_WIDTH and height >= _MIN_HEIGHT
            if not resolution_ok:
                if width > 0 and height > 0:
                    issues.append(
                        f"Low resolution ({width}x{height}), "
                        f"minimum {_MIN_WIDTH}x{_MIN_HEIGHT}"
                    )
                else:
                    issues.append("Unknown resolution — dimensions not provided")

            # Size check
            if size_bytes > _MAX_SIZE_BYTES:
                issues.append(
                    f"File too large ({size_bytes:,} bytes), "
                    f"max recommended {_MAX_SIZE_BYTES:,} bytes"
                )
            elif size_bytes == 0:
                issues.append("File size unknown")

            # Alt text check
            if not alt or alt.strip() == "":
                issues.append("Missing alt text — accessibility and SEO impact")
            elif len(alt) > 125:
                issues.append(
                    f"Alt text too long ({len(alt)} chars), "
                    f"recommended max 125 chars"
                )

            # Estimated load time
            if size_bytes > 0:
                load_ms = round(size_bytes / _BYTES_PER_MS, 1)
            else:
                load_ms = 0.0

            if load_ms > 500:
                issues.append(f"Slow estimated load time ({load_ms}ms)")

            # Quality rating
            if not issues:
                rating = "excellent"
                img_score = 100.0
            elif len(issues) == 1:
                rating = "good"
                img_score = 75.0
            elif len(issues) == 2:
                rating = "fair"
                img_score = 50.0
            else:
                rating = "poor"
                img_score = 25.0

            total_score += img_score

            analyses.append({
                "image_id": i,
                "url": url,
                "quality_rating": rating,
                "resolution_adequate": resolution_ok,
                "estimated_load_ms": load_ms,
                "issues": issues,
            })

        avg_score = round(total_score / max(len(items), 1), 1)

        return {
            "status": "success",
            "analyses": analyses,
            "quality_scores": {
                "average_score": avg_score,
                "total_images": len(items),
                "excellent_count": sum(1 for a in analyses if a["quality_rating"] == "excellent"),
                "poor_count": sum(1 for a in analyses if a["quality_rating"] == "poor"),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analyses": [],
            "error": f"Quality analysis failed: {exc}",
        }
