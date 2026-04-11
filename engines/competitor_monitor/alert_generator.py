"""Competitor Monitor Engine — alert generator.

Generates alerts on significant competitor changes: large price drops,
new threatening products, and undercut situations that need attention.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default alert thresholds
# ---------------------------------------------------------------------------

_DEFAULT_PRICE_CHANGE_PCT = 5.0
_DEFAULT_UNDERCUT_PCT = 10.0


def generate_alerts(
    price_changes: list[dict[str, Any]],
    new_products: list[dict[str, Any]],
    alert_thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Generate alerts based on competitor price changes and new products.

    Args:
        price_changes: List of PriceChange dicts from price_watcher.
        new_products: List of NewCompetitorProduct dicts from product_scanner.
        alert_thresholds: AlertThresholds config dict.

    Returns:
        Structured dict with generated alerts.
    """
    try:
        changes = copy.deepcopy(price_changes)
        products = copy.deepcopy(new_products)

        price_threshold = float(
            alert_thresholds.get("price_change_pct", _DEFAULT_PRICE_CHANGE_PCT)
        )
        undercut_threshold = float(
            alert_thresholds.get("undercut_pct", _DEFAULT_UNDERCUT_PCT)
        )
        new_product_alert = bool(
            alert_thresholds.get("new_product_alert", True)
        )

        alerts: list[dict[str, Any]] = []

        # Price change alerts
        for change in changes:
            comp = str(change.get("competitor", ""))
            title = str(change.get("product_title", ""))
            pct = float(change.get("change_pct", 0.0))
            direction = str(change.get("direction", ""))
            new_price = float(change.get("new_price", 0.0))

            if direction == "competitor_lower" and abs(pct) >= undercut_threshold:
                alerts.append({
                    "alert_type": "price_undercut",
                    "severity": "critical",
                    "competitor": comp,
                    "message": (
                        f"{comp} undercuts our price on {title} by {abs(pct):.1f}% "
                        f"(their price: ${new_price:,.2f})"
                    ),
                    "recommended_action": "Review pricing immediately — consider matching or value differentiation",
                })
            elif direction == "competitor_lower" and abs(pct) >= price_threshold:
                alerts.append({
                    "alert_type": "price_drop",
                    "severity": "warning",
                    "competitor": comp,
                    "message": (
                        f"{comp} dropped price on {title} by {abs(pct):.1f}% "
                        f"(their price: ${new_price:,.2f})"
                    ),
                    "recommended_action": "Monitor trend — may need price adjustment if sustained",
                })
            elif direction == "competitor_higher" and abs(pct) >= price_threshold:
                alerts.append({
                    "alert_type": "price_increase",
                    "severity": "info",
                    "competitor": comp,
                    "message": (
                        f"{comp} raised price on {title} by {pct:.1f}% "
                        f"— opportunity to capture price-sensitive customers"
                    ),
                    "recommended_action": "Consider maintaining current price to capture market share",
                })

        # New product alerts
        if new_product_alert:
            for product in products:
                comp = str(product.get("competitor", ""))
                title = str(product.get("product_title", ""))
                threat = str(product.get("threat_level", "low"))
                price = float(product.get("price", 0.0))

                if threat == "high":
                    severity = "critical"
                    action = "Evaluate adding similar product or adjusting existing prices"
                elif threat == "medium":
                    severity = "warning"
                    action = "Monitor sales impact — consider adding to catalog"
                else:
                    severity = "info"
                    action = "Track for future reference"

                alerts.append({
                    "alert_type": "new_competitor_product",
                    "severity": severity,
                    "competitor": comp,
                    "message": (
                        f"{comp} launched new product: {title} at ${price:,.2f} "
                        f"(threat: {threat})"
                    ),
                    "recommended_action": action,
                })

        return {
            "status": "success",
            "alerts": alerts,
        }
    except Exception as exc:
        return {
            "status": "error",
            "alerts": [],
            "error": f"Alert generation failed: {exc}",
        }
