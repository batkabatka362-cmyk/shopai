"""Competitor Monitor Engine — strategy advisor.

Advises responses to competitor moves based on price changes,
new products, and overall competitive landscape analysis.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def advise_strategy(
    price_changes: list[dict[str, Any]],
    new_products: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    our_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Advise strategic responses to competitor moves.

    Args:
        price_changes: List of PriceChange dicts from price_watcher.
        new_products: List of NewCompetitorProduct dicts from product_scanner.
        alerts: List of CompetitorAlert dicts from alert_generator.
        our_products: List of OurProduct dicts for margin analysis.

    Returns:
        Structured dict with strategic recommendations.
    """
    try:
        changes = copy.deepcopy(price_changes)
        products = copy.deepcopy(new_products)

        # Build our margin map
        margin_map: dict[str, float] = {}
        from utils.finance import margin_pct
        for prod in our_products:
            pid = str(prod.get("product_id", ""))
            if float(prod.get("price", 0.0)) > 0:
                margin_map[pid] = margin_pct(
                    prod.get("price", 0), prod.get("cost", 0),
                    require_cost=False, precision=1,
                )

        # Track competitors with most aggressive moves
        comp_aggression: dict[str, int] = {}
        for change in changes:
            if change.get("direction") == "competitor_lower":
                comp = str(change.get("competitor", ""))
                comp_aggression[comp] = comp_aggression.get(comp, 0) + 1

        responses: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Respond to price undercuts
        for change in changes:
            comp = str(change.get("competitor", ""))
            direction = str(change.get("direction", ""))
            pid = str(change.get("product_id", ""))
            pct = float(change.get("change_pct", 0.0))
            title = str(change.get("product_title", ""))

            if direction != "competitor_lower":
                continue

            key = f"{comp}:{pid}"
            if key in seen:
                continue
            seen.add(key)

            margin = margin_map.get(pid, 30.0)

            if abs(pct) <= margin * 0.5:
                # We can match and still be profitable
                response = f"Match price on {title} — margin allows {abs(pct):.1f}% reduction"
                impact = f"Maintain market share; margin drops from {margin:.1f}% to {margin - abs(pct):.1f}%"
                urgency = "high"
            elif abs(pct) <= margin:
                # Can partially match
                partial = round(abs(pct) * 0.5, 1)
                response = f"Partially match on {title} — reduce by {partial:.1f}% and emphasize value"
                impact = f"Retain some share; margin drops to {margin - partial:.1f}%"
                urgency = "medium"
            else:
                # Cannot match profitably
                response = f"Do not match on {title} — differentiate on quality, service, or bundling"
                impact = "May lose price-sensitive customers; protect margins"
                urgency = "low"

            responses.append({
                "competitor": comp,
                "situation": f"{comp} undercuts {title} by {abs(pct):.1f}%",
                "recommended_response": response,
                "expected_impact": impact,
                "urgency": urgency,
            })

        # Respond to aggressive competitors overall
        for comp, count in comp_aggression.items():
            if count >= 3:
                key = f"aggression:{comp}"
                if key not in seen:
                    seen.add(key)
                    responses.append({
                        "competitor": comp,
                        "situation": f"{comp} is aggressively undercutting across {count} products",
                        "recommended_response": "Consider a strategic price review across overlapping categories",
                        "expected_impact": "Prevent market share erosion from coordinated competitor pricing",
                        "urgency": "high",
                    })

        # Respond to high-threat new products
        for product in products:
            threat = str(product.get("threat_level", "low"))
            if threat != "high":
                continue

            comp = str(product.get("competitor", ""))
            title = str(product.get("product_title", ""))
            price = float(product.get("price", 0.0))
            category = str(product.get("category", ""))

            key = f"newprod:{comp}:{title}"
            if key in seen:
                continue
            seen.add(key)

            responses.append({
                "competitor": comp,
                "situation": f"{comp} launched {title} at ${price:,.2f} in {category}",
                "recommended_response": f"Evaluate sourcing a competing product in {category} or adjusting existing pricing",
                "expected_impact": "Protect category market share against new entrant",
                "urgency": "medium",
            })

        return {
            "status": "success",
            "responses": responses,
        }
    except Exception as exc:
        return {
            "status": "error",
            "responses": [],
            "error": f"Strategy advising failed: {exc}",
        }
