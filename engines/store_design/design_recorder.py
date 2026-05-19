"""Store Design Engine -- writeback recorder.

The store_design engine produces recommendations (layout,
color palette, navigation, mobile optimizations) but doesn't
yet APPLY them to a live Shopify theme. The output is text
recommendations consumed by the operator manually.

That leaves a visibility gap: every other engine that produces
actions (loyalty, dynamic_pricing, tag_management,
product_lifecycle, affiliate, discount_strategy) calls
``record_writeback`` so the action enters the Pattern 8
learning loop (MemoryIntelligence + DataArchitecture +
LearningLoop). The store_design engine currently doesn't, which
means:

  * ``shopai daily-brief`` doesn't see "store_design ran today"
  * ``shopai engine summary store_design`` shows zero activity
  * The recommendations never become reviewable approval
    queue entries
  * No outcome attribution: did running the design engine
    actually move conversion lift?

This module is the bridge. ``record_design_run`` takes the
engine's output dict and records ONE writeback event summarising
the run, using a synthetic capability tag
(``SHOPIFY_DESIGN_RECOMMENDATIONS``) since the recommendations
aren't yet pushed to a real Shopify endpoint.

When a future PR wires actual ``SHOPIFY_UPSERT_THEME_FILES``
calls for the per-recommendation appliers, this module's
capability tag should be updated and the metrics dict gain
``files_written`` / ``theme_id`` fields.
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Synthetic capability name -- the design engine doesn't yet
# call a real Shopify mutation, so this tag is a placeholder
# in the writeback log that future appliers will replace with
# the actual capability (likely SHOPIFY_UPSERT_THEME_FILES).
_DESIGN_CAPABILITY = "SHOPIFY_DESIGN_RECOMMENDATIONS"


def record_design_run(
    engine_output: dict[str, Any],
    *,
    store_id: str | None = None,
) -> None:
    """Record a single store_design run to the learning loop.

    The engine produces a single envelope per run with
    layout / color / navigation / mobile sub-blocks. This
    helper aggregates the counts into one writeback event so
    daily-brief + engine summary surfaces register the
    activity, and the recommendations become traceable in the
    Phase 8 action log.

    Args:
        engine_output: Full ``StoreDesignEngine.run()`` output
            dict (the ``{status, data, meta, error}`` envelope).
            Failures are recorded with ``success=False`` so the
            engine's reliability is visible alongside its
            recommendations.
        store_id: Optional store_id for per-store scope. When
            omitted, the active-store thread-local (set by the
            autonomous loop's ``run_cycle`` wrapper) provides
            the tag.

    Returns:
        ``None``. The function never raises; recording failures
        are swallowed by ``record_writeback`` itself (Pattern J
        guard, etc.).
    """
    if not isinstance(engine_output, dict):
        logger.debug(
            "record_design_run: non-dict input ignored: %r",
            type(engine_output).__name__,
        )
        return

    status = engine_output.get("status")
    success = status == "success"
    data = engine_output.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    error_str: str | None = None
    if not success:
        err = engine_output.get("error")
        error_str = str(err) if err else "design engine failure"

    layout_count = (
        len(data.get("layout_recommendations") or [])
        if isinstance(data.get("layout_recommendations"), list)
        else 0
    )
    palette = data.get("color_palette") or {}
    palette_count = (
        len(palette) if isinstance(palette, dict) else 0
    )
    nav = data.get("navigation") or {}
    nav_count = (
        len(nav.get("primary_links") or [])
        if isinstance(nav, dict) and isinstance(
            nav.get("primary_links"), list,
        )
        else 0
    )
    mobile_count = (
        len(data.get("mobile_optimizations") or [])
        if isinstance(data.get("mobile_optimizations"), list)
        else 0
    )
    lift_raw = data.get("estimated_conversion_lift", 0.0)
    try:
        lift = float(lift_raw or 0.0)
    except (TypeError, ValueError):
        lift = 0.0
    total_recommendations = (
        layout_count + palette_count + nav_count + mobile_count
    )

    params: dict[str, Any] = {
        "layout_count": layout_count,
        "palette_count": palette_count,
        "navigation_count": nav_count,
        "mobile_optimization_count": mobile_count,
        "total_recommendations": total_recommendations,
    }
    if store_id:
        params["store_id"] = str(store_id)

    metrics: dict[str, Any] = {
        "estimated_conversion_lift": lift,
        # Synthetic field: the design engine's lift estimate
        # is a heuristic over recommendation strings, NOT a
        # measured outcome. Future PRs that wire the actual
        # apply path should replace this with real before/after
        # conversion deltas from webhook-driven measurement.
        "lift_source": "heuristic_estimate",
    }

    record_writeback(
        engine="store_design",
        action_type="generate_recommendations",
        capability=_DESIGN_CAPABILITY,
        params=params,
        success=success,
        error=error_str,
        metrics=metrics,
    )
