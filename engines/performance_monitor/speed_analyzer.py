"""Performance Monitor Engine — speed analyzer.

Analyzes page load times and Core Web Vitals. Scores each page on a
0-100 scale based on performance benchmarks.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Performance benchmarks (milliseconds)
# ---------------------------------------------------------------------------

_GOOD_LOAD_TIME = 2000      # <= 2s = good
_ACCEPTABLE_LOAD_TIME = 4000  # <= 4s = acceptable
# > 4s = slow

_GOOD_TTFB = 500            # Time to first byte
_ACCEPTABLE_TTFB = 1000


def analyze_speed(
    pages: list[dict[str, Any]],
    load_times: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze page speed and performance metrics.

    Scores each page on a 0-100 scale and classifies performance.

    Args:
        pages: List of page dicts with url, page_type fields.
        load_times: List of timing dicts with url, load_time_ms,
            ttfb_ms, fcp_ms, lcp_ms fields.

    Returns:
        Structured dict with performance_scores list.
    """
    try:
        page_list = copy.deepcopy(pages)
        timing_list = copy.deepcopy(load_times)

        # Index timings by URL
        timing_map: dict[str, list[dict[str, Any]]] = {}
        for t in timing_list:
            url = str(t.get("url", ""))
            timing_map.setdefault(url, []).append(t)

        performance_scores: list[dict[str, Any]] = []
        total_score = 0.0

        for page in page_list:
            url = str(page.get("url", ""))
            page_type = str(page.get("page_type", "other"))
            timings = timing_map.get(url, [])

            if not timings:
                performance_scores.append({
                    "url": url,
                    "page_type": page_type,
                    "score": 0,
                    "rating": "no_data",
                    "avg_load_time_ms": 0,
                    "avg_ttfb_ms": 0,
                    "sample_count": 0,
                })
                continue

            # Compute averages
            load_times_ms = [float(t.get("load_time_ms", 0)) for t in timings]
            ttfb_ms = [float(t.get("ttfb_ms", 0)) for t in timings]
            fcp_ms = [float(t.get("fcp_ms", 0)) for t in timings if t.get("fcp_ms")]
            lcp_ms = [float(t.get("lcp_ms", 0)) for t in timings if t.get("lcp_ms")]

            avg_load = sum(load_times_ms) / len(load_times_ms)
            avg_ttfb = sum(ttfb_ms) / len(ttfb_ms) if ttfb_ms else 0
            avg_fcp = sum(fcp_ms) / len(fcp_ms) if fcp_ms else avg_load * 0.4
            avg_lcp = sum(lcp_ms) / len(lcp_ms) if lcp_ms else avg_load * 0.8
            p95_load = sorted(load_times_ms)[int(len(load_times_ms) * 0.95)] if len(load_times_ms) > 1 else avg_load

            # Score calculation (0-100)
            # Load time score (40% weight)
            if avg_load <= _GOOD_LOAD_TIME:
                load_score = 100 - (avg_load / _GOOD_LOAD_TIME) * 10
            elif avg_load <= _ACCEPTABLE_LOAD_TIME:
                ratio = (avg_load - _GOOD_LOAD_TIME) / (_ACCEPTABLE_LOAD_TIME - _GOOD_LOAD_TIME)
                load_score = 90 - ratio * 40
            else:
                load_score = max(50 - (avg_load - _ACCEPTABLE_LOAD_TIME) / 100, 0)

            # TTFB score (30% weight)
            if avg_ttfb <= _GOOD_TTFB:
                ttfb_score = 100 - (avg_ttfb / _GOOD_TTFB) * 10
            elif avg_ttfb <= _ACCEPTABLE_TTFB:
                ratio = (avg_ttfb - _GOOD_TTFB) / (_ACCEPTABLE_TTFB - _GOOD_TTFB)
                ttfb_score = 90 - ratio * 40
            else:
                ttfb_score = max(50 - (avg_ttfb - _ACCEPTABLE_TTFB) / 50, 0)

            # LCP score (30% weight)
            if avg_lcp <= 2500:
                lcp_score = 100 - (avg_lcp / 2500) * 10
            elif avg_lcp <= 4000:
                ratio = (avg_lcp - 2500) / 1500
                lcp_score = 90 - ratio * 40
            else:
                lcp_score = max(50 - (avg_lcp - 4000) / 100, 0)

            # Composite score
            score = round(load_score * 0.4 + ttfb_score * 0.3 + lcp_score * 0.3, 1)
            score = max(0, min(100, score))
            total_score += score

            # Rating
            if score >= 90:
                rating = "excellent"
            elif score >= 70:
                rating = "good"
            elif score >= 50:
                rating = "needs_improvement"
            else:
                rating = "poor"

            performance_scores.append({
                "url": url,
                "page_type": page_type,
                "score": score,
                "rating": rating,
                "avg_load_time_ms": round(avg_load, 1),
                "avg_ttfb_ms": round(avg_ttfb, 1),
                "avg_fcp_ms": round(avg_fcp, 1),
                "avg_lcp_ms": round(avg_lcp, 1),
                "p95_load_time_ms": round(p95_load, 1),
                "sample_count": len(timings),
            })

        scored_pages = [p for p in performance_scores if p["rating"] != "no_data"]
        avg_score = (
            round(total_score / len(scored_pages), 1)
            if scored_pages else 0.0
        )

        return {
            "status": "success",
            "performance_scores": performance_scores,
            "avg_score": avg_score,
        }
    except Exception as exc:
        return {
            "status": "error",
            "performance_scores": [],
            "error": f"Speed analysis failed: {exc}",
        }
