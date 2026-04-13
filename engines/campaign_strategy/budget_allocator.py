"""Campaign Strategy Engine — budget allocator.

Allocates budget across channels and phases.
"""
from __future__ import annotations

from typing import Any


def allocate_budget(
    budget: float,
    channel_plans: list[dict[str, Any]],
    phases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Allocate budget across channels and phases."""
    try:
        allocations: list[dict[str, Any]] = []

        ch_pct_map = {cp.get("channel", ""): float(cp.get("budget_pct", 0)) for cp in channel_plans}

        for phase in phases:
            phase_name = phase.get("name", "")
            phase_pct = float(phase.get("budget_pct", 0)) / 100.0
            phase_budget = budget * phase_pct
            phase_channels = phase.get("channels", [])

            # Distribute phase budget among its channels
            total_ch_weight = sum(ch_pct_map.get(ch, 1) for ch in phase_channels)

            for ch in phase_channels:
                ch_weight = ch_pct_map.get(ch, 1)
                ch_share = ch_weight / max(total_ch_weight, 1)
                amount = round(phase_budget * ch_share, 2)

                allocations.append({
                    "channel": ch,
                    "phase": phase_name,
                    "amount": amount,
                    "pct_of_total": round(amount / max(budget, 1) * 100, 1),
                })

        return {"status": "success", "allocations": allocations}
    except Exception as exc:
        return {"status": "error", "allocations": [], "error": f"Budget allocation failed: {exc}"}
