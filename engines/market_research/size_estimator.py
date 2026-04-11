"""Market Research Engine — size estimator.

Estimate total addressable market (TAM), serviceable (SAM), and obtainable (SOM).
"""
from __future__ import annotations

import copy
from typing import Any


def estimate_size(
    **kwargs: Any,
) -> dict[str, Any]:
    """Estimate market size.

    Args:
        **kwargs: Must include 'category', 'search_data', 'competitors'.

    Returns:
        Structured dict with market size estimates.
    """
    try:
        category = str(kwargs.get("category", ""))
        search_data = copy.deepcopy(kwargs.get("search_data", {}))
        competitors = kwargs.get("competitors", [])

        search_volume = int(search_data.get("monthly_volume", 0))
        avg_order_value = float(search_data.get("avg_order_value", 50.0))
        conversion_rate = float(search_data.get("conversion_rate", 0.02))

        # TAM from search volume * AOV
        tam = round(search_volume * avg_order_value * 12)
        # SAM = TAM * reachable fraction
        reachable = min(0.5, 1.0 / max(len(competitors), 1))
        sam = round(tam * reachable)
        # SOM = SAM * conversion
        som = round(sam * conversion_rate)

        return {
            "status": "success",
            "result": {
                "tam": tam,
                "sam": sam,
                "som": som,
                "category": category,
                "search_volume": search_volume,
                "num_competitors": len(competitors),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Size estimation failed: {exc}"}
