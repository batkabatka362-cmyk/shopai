"""Performance Monitor Engine — bottleneck finder.

Finds performance bottlenecks by analyzing speed scores, uptime data,
and page-level metrics. Identifies the root causes of slowness.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Bottleneck thresholds
# ---------------------------------------------------------------------------

_SLOW_TTFB_MS = 800         # Server-side bottleneck
_SLOW_FCP_MS = 3000          # Render-blocking bottleneck
_LARGE_LCP_GAP_MS = 2000     # LCP much slower than FCP = asset bottleneck


def find_bottlenecks(
    performance_scores: list[dict[str, Any]],
    uptime_pct: float,
    downtime_windows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find performance bottlenecks across the store.

    Analyzes timing breakdowns to identify server-side, rendering,
    and asset-loading bottlenecks.

    Args:
        performance_scores: Per-page scores from speed_analyzer.
        uptime_pct: Uptime percentage from uptime_tracker.
        downtime_windows: Downtime periods from uptime_tracker.

    Returns:
        Structured dict with bottlenecks list.
    """
    try:
        scores = copy.deepcopy(performance_scores)
        bottlenecks: list[dict[str, Any]] = []

        # --- Per-page bottleneck analysis ---
        for page in scores:
            url = str(page.get("url", ""))
            rating = str(page.get("rating", ""))
            avg_ttfb = float(page.get("avg_ttfb_ms", 0))
            avg_fcp = float(page.get("avg_fcp_ms", 0))
            avg_lcp = float(page.get("avg_lcp_ms", 0))
            avg_load = float(page.get("avg_load_time_ms", 0))

            if rating in ("no_data",):
                continue

            # Server-side bottleneck (slow TTFB)
            if avg_ttfb > _SLOW_TTFB_MS:
                bottlenecks.append({
                    "type": "slow_server_response",
                    "severity": "high" if avg_ttfb > 1500 else "medium",
                    "url": url,
                    "metric": f"TTFB: {round(avg_ttfb)}ms",
                    "description": (
                        f"Page '{url}' has slow server response time "
                        f"({round(avg_ttfb)}ms TTFB). Check server config, "
                        f"database queries, and caching."
                    ),
                })

            # Render-blocking bottleneck (slow FCP)
            if avg_fcp > _SLOW_FCP_MS:
                bottlenecks.append({
                    "type": "render_blocking",
                    "severity": "high" if avg_fcp > 5000 else "medium",
                    "url": url,
                    "metric": f"FCP: {round(avg_fcp)}ms",
                    "description": (
                        f"Page '{url}' has render-blocking resources "
                        f"({round(avg_fcp)}ms FCP). Defer non-critical CSS/JS."
                    ),
                })

            # Asset loading bottleneck (large gap between FCP and LCP)
            lcp_gap = avg_lcp - avg_fcp
            if lcp_gap > _LARGE_LCP_GAP_MS and avg_fcp > 0:
                bottlenecks.append({
                    "type": "slow_asset_loading",
                    "severity": "medium",
                    "url": url,
                    "metric": f"LCP-FCP gap: {round(lcp_gap)}ms",
                    "description": (
                        f"Page '{url}' has slow main content loading "
                        f"({round(lcp_gap)}ms gap between FCP and LCP). "
                        f"Optimize hero images and lazy-load below-fold assets."
                    ),
                })

            # Overall slow page
            if avg_load > 5000 and rating == "poor":
                bottlenecks.append({
                    "type": "overall_slow_page",
                    "severity": "high",
                    "url": url,
                    "metric": f"Load time: {round(avg_load)}ms",
                    "description": (
                        f"Page '{url}' loads in {round(avg_load)}ms — "
                        f"well above the 4s acceptable threshold."
                    ),
                })

        # --- Uptime bottleneck ---
        if uptime_pct < 99.5:
            bottlenecks.append({
                "type": "uptime_degradation",
                "severity": "critical" if uptime_pct < 99.0 else "high",
                "url": "store-wide",
                "metric": f"Uptime: {uptime_pct}%",
                "description": (
                    f"Store uptime is {uptime_pct}% with "
                    f"{len(downtime_windows)} downtime windows. "
                    f"Investigate infrastructure reliability."
                ),
            })

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        bottlenecks.sort(
            key=lambda b: severity_order.get(b.get("severity", "low"), 4),
        )

        return {
            "status": "success",
            "bottlenecks": bottlenecks,
            "total_bottlenecks": len(bottlenecks),
        }
    except Exception as exc:
        return {
            "status": "error",
            "bottlenecks": [],
            "error": f"Bottleneck finding failed: {exc}",
        }
