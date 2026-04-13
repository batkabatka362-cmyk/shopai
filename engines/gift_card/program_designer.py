"""Gift Card Engine — program designer.

Designs gift card program: denominations, expiry policies,
corporate tiers, and seasonal planning.
"""
from __future__ import annotations

import copy
from typing import Any


def design_program(
    gift_cards: list[dict[str, Any]],
    program_config: dict[str, Any],
) -> dict[str, Any]:
    """Design/evaluate gift card program.

    Args:
        gift_cards: Existing gift card records.
        program_config: Program configuration.

    Returns:
        Structured dict with program health metrics.
    """
    try:
        cards = copy.deepcopy(gift_cards)
        config = copy.deepcopy(program_config)

        total_issued = len(cards)
        total_value_issued = sum(float(c.get("initial_value", 0)) for c in cards)
        total_balance = sum(float(c.get("balance", 0)) for c in cards)

        active_cards = [c for c in cards if float(c.get("balance", 0)) > 0]
        expired_cards = [c for c in cards if c.get("status") == "expired"]
        fully_redeemed = [c for c in cards if float(c.get("balance", 0)) == 0 and c.get("status") != "expired"]

        # Utilization rate
        used_value = total_value_issued - total_balance
        utilization_rate = round(used_value / total_value_issued * 100, 1) if total_value_issued > 0 else 0.0

        # Denomination analysis
        denoms: dict[float, int] = {}
        for card in cards:
            val = float(card.get("initial_value", 0))
            denoms[val] = denoms.get(val, 0) + 1

        popular_denoms = sorted(denoms.items(), key=lambda x: x[1], reverse=True)

        program_health: dict[str, Any] = {
            "total_issued": total_issued,
            "total_value_issued": round(total_value_issued, 2),
            "total_outstanding_balance": round(total_balance, 2),
            "active_cards_count": len(active_cards),
            "expired_cards_count": len(expired_cards),
            "fully_redeemed_count": len(fully_redeemed),
            "utilization_rate_pct": utilization_rate,
            "popular_denominations": [{"value": d[0], "count": d[1]} for d in popular_denoms[:5]],
        }

        return {
            "status": "success",
            "program_health": program_health,
            "active_cards": active_cards,
        }
    except Exception as exc:
        return {
            "status": "error",
            "program_health": {},
            "error": f"Program design failed: {exc}",
        }
