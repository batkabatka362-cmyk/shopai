"""Competitive Loop — continuously monitor and respond to competitor changes.

Tracks competitor prices, products, and positioning.
Automatically triggers responses when competitors make moves.

Flow: Monitor → Detect Change → Analyze Impact → Recommend Response → Execute
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, generate_id

logger = get_logger("intelligence.competitive_loop")


class CompetitiveLoop:
    """Continuous competitive monitoring and response system."""

    def __init__(self) -> None:
        self._competitor_snapshots: dict[str, dict[str, Any]] = {}  # competitor_id → last snapshot
        self._alerts: list[dict[str, Any]] = []
        self._responses: list[dict[str, Any]] = []

    def monitor(self, our_products: list[dict[str, Any]],
                competitors: list[dict[str, Any]]) -> dict[str, Any]:
        """Run one monitoring cycle. Detects changes and generates responses."""
        cycle_id = generate_id("comp")
        start = time.monotonic()

        changes = self._detect_changes(competitors)
        impact = self._analyze_impact(our_products, competitors, changes)
        responses = self._generate_responses(our_products, impact)
        market = self._market_position(our_products, competitors)

        self._responses.extend(responses)
        if len(self._responses) > 500:
            self._responses = self._responses[-500:]

        elapsed = time.monotonic() - start

        return {
            "cycle_id": cycle_id,
            "elapsed_seconds": round(elapsed, 3),
            "competitors_tracked": len(competitors),
            "changes_detected": len(changes),
            "changes": changes,
            "impact": impact,
            "responses": responses,
            "market_position": market,
            "alerts": [a for a in self._alerts[-10:]],
        }

    def _detect_changes(self, competitors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect changes since last snapshot."""
        changes = []
        for comp in competitors:
            if not isinstance(comp, dict):
                continue
            cid = comp.get("id", comp.get("name", "unknown"))
            prev = self._competitor_snapshots.get(cid, {})

            # Price change detection
            for product in comp.get("products", []):
                if not isinstance(product, dict):
                    continue
                pid = product.get("id", product.get("name", ""))
                new_price = safe_float(product.get("price"))
                old_price = safe_float(prev.get("prices", {}).get(pid))

                if old_price > 0 and new_price > 0 and abs(new_price - old_price) / old_price > 0.05:
                    change_pct = round((new_price - old_price) / old_price * 100, 1)
                    change = {
                        "type": "price_change",
                        "competitor": cid,
                        "product": pid,
                        "old_price": old_price,
                        "new_price": new_price,
                        "change_pct": change_pct,
                        "direction": "increase" if new_price > old_price else "decrease",
                    }
                    changes.append(change)

                    if change_pct < -15:
                        self._alerts.append({
                            "type": "competitor_price_war",
                            "competitor": cid,
                            "product": pid,
                            "message": f"{cid} dropped {pid} price by {abs(change_pct):.1f}%",
                            "severity": "high",
                            "timestamp": time.time(),
                        })

            # New product detection
            current_products = set(p.get("id", p.get("name", "")) for p in comp.get("products", []) if isinstance(p, dict))
            prev_products = set(prev.get("product_ids", []))
            new_products = current_products - prev_products
            for np in new_products:
                if np:
                    changes.append({
                        "type": "new_product",
                        "competitor": cid,
                        "product": np,
                    })

            # Update snapshot
            self._competitor_snapshots[cid] = {
                "prices": {p.get("id", p.get("name", "")): safe_float(p.get("price"))
                           for p in comp.get("products", []) if isinstance(p, dict)},
                "product_ids": list(current_products),
                "last_updated": time.time(),
            }

        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]

        return changes

    def _analyze_impact(self, our_products: list[dict[str, Any]],
                        competitors: list[dict[str, Any]],
                        changes: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze impact of competitor changes on our business."""
        if not changes:
            return {"threat_level": "none", "affected_products": 0}

        price_drops = [c for c in changes if c.get("type") == "price_change" and c.get("direction") == "decrease"]
        new_products = [c for c in changes if c.get("type") == "new_product"]

        # Find our products that overlap with changed competitor products
        our_names = {p.get("name", "").lower(): p for p in our_products if isinstance(p, dict)}
        our_categories = {p.get("category", "").lower() for p in our_products if isinstance(p, dict)}

        affected = 0
        for change in price_drops:
            product_name = str(change.get("product", "")).lower()
            if any(product_name in name or name in product_name for name in our_names):
                affected += 1

        threat = "high" if affected > 2 or len(price_drops) > 3 else \
                 "medium" if affected > 0 or len(price_drops) > 1 else \
                 "low" if changes else "none"

        return {
            "threat_level": threat,
            "price_drops": len(price_drops),
            "new_products": len(new_products),
            "affected_products": affected,
            "total_changes": len(changes),
        }

    def _generate_responses(self, our_products: list[dict[str, Any]],
                            impact: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate strategic responses to competitor moves."""
        responses = []
        threat = impact.get("threat_level", "none")

        if threat == "high":
            responses.append({
                "type": "defensive_pricing",
                "priority": "high",
                "action": "Review and selectively match competitor prices on overlapping products",
                "estimated_impact": "Prevent 10-20% revenue loss",
            })
            responses.append({
                "type": "differentiation",
                "priority": "high",
                "action": "Highlight unique value props — better reviews, faster shipping, better support",
                "estimated_impact": "Retain price-sensitive customers",
            })

        if threat in ("high", "medium"):
            responses.append({
                "type": "bundle_defense",
                "priority": "medium",
                "action": "Create product bundles that competitors can't easily match",
                "estimated_impact": "Increase AOV while maintaining margins",
            })
            responses.append({
                "type": "loyalty_push",
                "priority": "medium",
                "action": "Push loyalty rewards to existing customers to prevent switching",
                "estimated_impact": "Reduce churn by 5-10%",
            })

        if impact.get("new_products", 0) > 0:
            responses.append({
                "type": "product_gap_analysis",
                "priority": "medium",
                "action": "Analyze competitor new products for potential catalog expansion",
                "estimated_impact": "Identify new revenue opportunities",
            })

        if not responses:
            responses.append({
                "type": "maintain",
                "priority": "low",
                "action": "No significant competitor changes — continue current strategy",
                "estimated_impact": "Steady state",
            })

        return responses

    def _market_position(self, our_products: list[dict[str, Any]],
                         competitors: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate our current market position vs competitors."""
        our_prices = [safe_float(p.get("price")) for p in our_products
                      if isinstance(p, dict) and safe_float(p.get("price")) > 0]
        if not our_prices:
            return {"position": "unknown"}

        our_avg = sum(our_prices) / len(our_prices)

        comp_prices = []
        for comp in competitors:
            if not isinstance(comp, dict):
                continue
            for p in comp.get("products", []):
                if isinstance(p, dict):
                    cp = safe_float(p.get("price"))
                    if cp > 0:
                        comp_prices.append(cp)

        if not comp_prices:
            return {"position": "no_competitor_data", "our_avg_price": round(our_avg, 2)}

        comp_avg = sum(comp_prices) / len(comp_prices)
        price_index = round(our_avg / comp_avg * 100, 1)

        if price_index > 120:
            position = "premium"
        elif price_index > 105:
            position = "above_market"
        elif price_index > 95:
            position = "at_market"
        elif price_index > 80:
            position = "below_market"
        else:
            position = "value_leader"

        return {
            "position": position,
            "price_index": price_index,
            "our_avg_price": round(our_avg, 2),
            "market_avg_price": round(comp_avg, 2),
            "our_products": len(our_prices),
            "competitor_products": len(comp_prices),
        }

    def get_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._alerts[-limit:])

    def get_response_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._responses[-limit:])
