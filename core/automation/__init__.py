"""AutomationLoop — complete closed-loop automation.

Event → Analyze → Decide → Execute → Track → Learn → Improve

This is the BRAIN — takes any Shopify event and runs the full
intelligence pipeline, produces actions, tracks outcomes, and
feeds results back into the learning system.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("automation")


class AutomationLoop:
    """Closed-loop: Event → Intelligence → Action → Track → Learn."""

    def __init__(self) -> None:
        self._log: list[dict[str, Any]] = []

    def process_event(self, event_type: str, event_data: dict[str, Any]) -> dict[str, Any]:
        """Process any event through the full loop."""
        loop_id = generate_id("loop")
        start = time.monotonic()

        # 1. ANALYZE — what does this event mean?
        analysis = self._analyze_event(event_type, event_data)

        # 2. DECIDE — what should we do?
        decisions = self._make_decisions(event_type, analysis, event_data)

        # 3. EXECUTE — create action plans
        actions = self._plan_actions(decisions, event_data)

        # 4. TRACK — record for learning
        self._track(loop_id, event_type, analysis, decisions, actions)

        elapsed = time.monotonic() - start

        result = {
            "loop_id": loop_id,
            "event_type": event_type,
            "elapsed_seconds": round(elapsed, 3),
            "analysis": analysis,
            "decisions": decisions,
            "actions": actions,
            "action_count": len(actions),
        }
        self._log.append(result)
        if len(self._log) > 500:
            self._log = self._log[-500:]

        return result

    def process_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Process a new order — full intelligence pipeline."""
        return self.process_event("order_created", order)

    def process_product_change(self, product: dict[str, Any]) -> dict[str, Any]:
        """Process product change — re-analyze pricing, SEO, content."""
        return self.process_event("product_updated", product)

    def process_customer_activity(self, customer: dict[str, Any]) -> dict[str, Any]:
        """Process customer activity — segment, predict, personalize."""
        return self.process_event("customer_activity", customer)

    def get_log(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._log[-limit:])

    # --- Internal Pipeline ---

    def _analyze_event(self, event_type: str, data: dict) -> dict[str, Any]:
        """Step 1: Understand what happened."""
        analysis = {"event": event_type, "data_fields": len(data)}

        if event_type == "order_created":
            total = float(data.get("total", data.get("total_price", 0)))
            items = data.get("items", data.get("line_items", []))
            analysis["order_value"] = total
            analysis["item_count"] = len(items) if isinstance(items, list) else 0
            analysis["is_high_value"] = total > 100
            analysis["needs_inventory_check"] = True
            analysis["trigger_post_purchase"] = True

        elif event_type == "product_updated":
            price = float(data.get("price", 0))
            prev_price = float(data.get("previous_price", price))
            analysis["price_changed"] = price != prev_price
            analysis["price_direction"] = "up" if price > prev_price else "down" if price < prev_price else "unchanged"
            analysis["needs_seo_check"] = True
            analysis["needs_content_check"] = True

        elif event_type == "customer_activity":
            orders = int(data.get("orders", 0))
            days_inactive = int(data.get("days_since_last_order", 0))
            analysis["is_new"] = orders <= 1
            analysis["is_at_risk"] = days_inactive > 60
            analysis["is_vip"] = float(data.get("total_spent", 0)) > 500
            analysis["needs_segmentation"] = True

        return analysis

    def _make_decisions(self, event_type: str, analysis: dict, data: dict) -> list[dict[str, Any]]:
        """Step 2: Decide what to do based on analysis."""
        decisions = []

        if event_type == "order_created":
            if analysis.get("is_high_value"):
                decisions.append({"action": "vip_followup", "priority": "high",
                                  "reason": f"High value order ${analysis.get('order_value', 0)}"})
            decisions.append({"action": "update_inventory", "priority": "high", "reason": "New order placed"})
            decisions.append({"action": "post_purchase_email", "priority": "medium",
                              "reason": "Send thank you + cross-sell"})
            if analysis.get("item_count", 0) >= 3:
                decisions.append({"action": "analyze_bundle", "priority": "low",
                                  "reason": f"{analysis['item_count']} items — potential bundle"})

        elif event_type == "product_updated":
            if analysis.get("price_changed"):
                decisions.append({"action": "competitor_check", "priority": "high",
                                  "reason": f"Price {analysis['price_direction']}"})
            if analysis.get("needs_seo_check"):
                decisions.append({"action": "seo_audit", "priority": "medium", "reason": "Product updated"})
            if analysis.get("needs_content_check"):
                decisions.append({"action": "content_review", "priority": "low", "reason": "Check description quality"})

        elif event_type == "customer_activity":
            if analysis.get("is_at_risk"):
                decisions.append({"action": "win_back_campaign", "priority": "high",
                                  "reason": f"Inactive {data.get('days_since_last_order', 0)} days"})
            elif analysis.get("is_vip"):
                decisions.append({"action": "vip_reward", "priority": "medium",
                                  "reason": f"VIP — ${data.get('total_spent', 0)} lifetime"})
            elif analysis.get("is_new"):
                decisions.append({"action": "welcome_series", "priority": "medium", "reason": "New customer"})

        return decisions

    def _plan_actions(self, decisions: list[dict], data: dict) -> list[dict[str, Any]]:
        """Step 3: Convert decisions into executable actions."""
        actions = []
        for d in decisions:
            action = {
                "action_type": d["action"],
                "priority": d["priority"],
                "reason": d["reason"],
                "status": "planned",
                "target": self._resolve_target(d["action"]),
            }

            # Enrich with intelligence
            if d["action"] == "post_purchase_email":
                from core.intelligence.email_intelligence import EmailIntelligence
                flow = EmailIntelligence().build_automation_flow("post_purchase")
                action["email_flow"] = flow.get("name")
                action["emails_count"] = len(flow.get("emails", []))

            elif d["action"] == "seo_audit":
                from core.intelligence.seo_intelligence import SEOIntelligence
                title = data.get("name", data.get("title", ""))
                if title:
                    audit = SEOIntelligence().audit_page({"title": title, "keyword": data.get("category", "product")})
                    action["seo_score"] = audit.get("score", 0)
                    action["seo_issues"] = audit.get("issue_count", 0)

            elif d["action"] == "win_back_campaign":
                from core.intelligence.email_intelligence import EmailIntelligence
                flow = EmailIntelligence().build_automation_flow("win_back")
                action["recovery_estimate"] = flow.get("estimated_recovery", "3-8%")

            actions.append(action)
        return actions

    def _track(self, loop_id: str, event_type: str, analysis: dict, decisions: list, actions: list) -> None:
        """Step 4: Record for learning system."""
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            ot.record_decision(loop_id, f"automation_{event_type}", {
                "analysis": {k: v for k, v in analysis.items() if not isinstance(v, (list, dict))},
                "decision_count": len(decisions),
                "action_count": len(actions),
            })
        except Exception:
            pass  # Non-critical

    @staticmethod
    def _resolve_target(action: str) -> str:
        targets = {
            "update_inventory": "shopify_inventory",
            "post_purchase_email": "email_system",
            "vip_followup": "crm",
            "vip_reward": "loyalty_system",
            "win_back_campaign": "email_system",
            "welcome_series": "email_system",
            "seo_audit": "seo_engine",
            "content_review": "content_engine",
            "competitor_check": "pricing_engine",
            "analyze_bundle": "product_engine",
        }
        return targets.get(action, "general")
