"""LTV:CAC Dashboard Engine — CAC calculator.

Calculates customer acquisition cost by channel.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def calculate_cac(
    marketing_spend: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    channels: list[str],
) -> dict[str, Any]:
    """Calculate customer acquisition cost per channel.

    Args:
        marketing_spend: Spend records [{channel, amount, period}].
        customers: Customer list with acquisition channel.
        channels: Channel names to analyze.

    Returns:
        Structured dict with CAC by channel and overall.
    """
    try:
        # Spend per channel
        channel_spend: dict[str, float] = {}
        for record in marketing_spend:
            ch = str(record.get("channel", "unknown"))
            amount = float(record.get("amount", 0.0))
            channel_spend[ch] = channel_spend.get(ch, 0.0) + amount

        # Customers per channel
        channel_customers: dict[str, int] = {}
        for c in customers:
            ch = str(c.get("acquisition_channel", c.get("channel", "unknown")))
            channel_customers[ch] = channel_customers.get(ch, 0) + 1

        total_spend = sum(channel_spend.values())
        total_customers = sum(channel_customers.values())
        avg_cac = round(total_spend / total_customers, 2) if total_customers > 0 else 0.0

        by_channel: dict[str, float] = {}
        for ch in channels or list(channel_spend.keys()):
            spend = channel_spend.get(ch, 0.0)
            custs = channel_customers.get(ch, 0)
            by_channel[ch] = round(spend / custs, 2) if custs > 0 else 0.0

        return {
            "status": "success",
            "cac": {"average": avg_cac, "by_channel": by_channel},
        }
    except Exception as exc:
        return {"status": "error", "cac": {}, "error": f"CAC calculation failed: {exc}"}
