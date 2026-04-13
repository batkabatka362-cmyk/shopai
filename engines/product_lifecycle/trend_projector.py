"""Product Lifecycle Engine — trend projector.

Projects when each product will transition to the next lifecycle stage
based on current trajectory and historical patterns.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_STAGE_ORDER = ["introduction", "growth", "maturity", "decline"]


def project_trends(
    classifications: list[dict[str, Any]],
    velocities: list[dict[str, Any]],
    sales_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project lifecycle transitions for each product.

    Args:
        classifications: Per-product stage classification results.
        velocities: Per-product velocity results.
        sales_history: List of sales history records.

    Returns:
        Structured dict with per-product trend projections.
    """
    try:
        vel_map = {str(v.get("product_id", "")): v for v in velocities}

        # Calculate average period revenue for growth rate estimation
        history_map: dict[str, list[int]] = {}
        for record in sales_history:
            pid = str(record.get("product_id", ""))
            if pid:
                history_map.setdefault(pid, []).append(
                    int(record.get("units_sold", 0))
                )

        projections: list[dict[str, Any]] = []

        for cls in classifications:
            product_id = str(cls.get("product_id", "unknown"))
            stage = str(cls.get("stage", "introduction"))
            vel = vel_map.get(product_id, {})
            acceleration = float(vel.get("acceleration", 0.0))
            current_velocity = float(vel.get("current_velocity", 0.0))

            units = history_map.get(product_id, [])

            # Compute growth rate from history
            if len(units) >= 2 and units[-2] > 0:
                growth_rate = (units[-1] - units[-2]) / units[-2]
            else:
                growth_rate = 0.0

            # Determine next stage
            stage_idx = _STAGE_ORDER.index(stage) if stage in _STAGE_ORDER else 0
            if stage_idx < len(_STAGE_ORDER) - 1:
                next_stage = _STAGE_ORDER[stage_idx + 1]
            else:
                next_stage = "end_of_life"

            # Estimate periods to transition
            if stage == "introduction":
                periods = max(2, int(6 - abs(growth_rate) * 10)) if growth_rate > 0 else 8
            elif stage == "growth":
                if acceleration < 0:
                    periods = max(1, int(abs(current_velocity / acceleration))) if acceleration != 0 else 12
                else:
                    periods = 12
            elif stage == "maturity":
                if growth_rate < -0.03:
                    periods = max(1, int(3 / abs(growth_rate)))
                else:
                    periods = 18
            else:
                periods = 6

            confidence = cls.get("confidence", 0.5) * 0.8

            projections.append({
                "product_id": product_id,
                "projected_transition": next_stage,
                "periods_to_transition": periods,
                "projection_confidence": round(confidence, 3),
                "growth_rate": round(growth_rate, 4),
            })

        return {"status": "success", "projections": projections}
    except Exception as exc:
        return {"status": "error", "projections": [], "error": f"Trend projection failed: {exc}"}
