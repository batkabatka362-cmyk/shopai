"""Operations Agent — orchestrates Inventory, Shipping, and Supplier engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {products, orders, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}

Phase 6 note: ``execute()`` now also queries the adapter
``SmartRouter`` for real carrier shipping rates when the
dispatcher has injected ``context["_router"]`` and the caller
has supplied a ``from_address`` + ``default_parcel`` (so the
brain's operations decisions benefit from real carrier data,
not just the local engine heuristics).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results

logger = get_logger("agent.operations")


class OperationsAgent(BaseAgent):
    """Operations Agent — manages inventory, shipping, suppliers.

    Combines Inventory, Stock Prediction, Supplier, Shipping Optimization,
    and Returns Management engines to answer: "How do we run ops efficiently?"
    """

    def __init__(self) -> None:
        super().__init__(name="operations_agent")

    def plan(self, goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
        """Delegate planning to planner module."""
        return create_plan(goal, context, constraints)

    def execute(self, plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Delegate execution to executor module, then augment
        with real carrier shipping rates via the adapter
        SmartRouter when available.
        """
        results = execute_plan(plan, context)
        if not isinstance(results, dict):
            results = {}
        augmentation = self._augment_with_shipping_rates(context)
        if augmentation is not None:
            results.setdefault("adapter_augmentations", {})
            results["adapter_augmentations"]["shipping_rate_quote"] = augmentation
        return results

    def _augment_with_shipping_rates(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Ask the router for a real shipping rate quote using
        data from the per-call context.

        Returns ``None`` when:

          * the dispatcher hasn't injected a ``_router``
          * the context doesn't carry a ``from_address`` /
            ``default_parcel`` / a shipping-address-bearing
            order
          * the router has no configured shipping adapter
            (``NoAdapterAvailable``) or every candidate fails

        The return value, when present, is a small envelope
        suitable for merging into ``results.adapter_augmentations``
        so the recommender can incorporate the real carrier
        number into its findings.
        """
        router = context.get("_router") if isinstance(context, dict) else None
        if router is None:
            return None

        from_address = context.get("from_address") if isinstance(context, dict) else None
        default_parcel = context.get("default_parcel") if isinstance(context, dict) else None
        if not isinstance(from_address, dict) or not isinstance(default_parcel, dict):
            return None

        # Find the first order that carries a usable shipping
        # address. If none do, skip the augmentation silently —
        # the engine-based plan still ran.
        orders = context.get("orders") or context.get("order_data") or []
        to_address = None
        for order in orders:
            if not isinstance(order, dict):
                continue
            addr = order.get("shipping_address")
            if not isinstance(addr, dict):
                continue
            if addr.get("zip") and addr.get("country") or addr.get("country_code"):
                to_address = {
                    "street1": addr.get("address1") or addr.get("street1") or "unknown",
                    "city": addr.get("city", ""),
                    "state": addr.get("province_code", "") or addr.get("state", ""),
                    "zip": addr.get("zip") or addr.get("postal_code", ""),
                    "country": (
                        addr.get("country_code") or addr.get("country") or ""
                    )[:2].upper(),
                }
                break
        if to_address is None:
            return None

        try:
            from core.adapters import Capability
        except Exception:  # noqa: BLE001
            return None

        try:
            result = router.execute(
                Capability.SHIPPING_RATE_QUOTE,
                {
                    "from_address": from_address,
                    "to_address": to_address,
                    "parcel": default_parcel,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("shipping augmentation raised: %s", exc)
            return None

        if not result.ok:
            return None

        data = result.data or {}
        return {
            "adapter": result.adapter,
            "rate_count": int(data.get("count", 0) or 0),
            "cheapest": data.get("cheapest"),
            "fastest": data.get("fastest"),
        }

    def evaluate(self, results: dict[str, Any], goal: str) -> dict[str, Any]:
        """Delegate evaluation to evaluator module."""
        return evaluate_results(results, goal)

    def recommend(self, results: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        """Generate final recommendation from combined operations data."""
        score = evaluation.get("score", 0)
        quality = evaluation.get("quality", "low")

        engine_results = results.get("engine_results", {})
        inv = engine_results.get("inventory", {})
        sp = engine_results.get("stock_prediction", {})
        sup = engine_results.get("supplier", {})

        # Extract key findings
        findings = []

        # Inventory findings
        if inv.get("status") == "success":
            inv_data = inv.get("data", {})
            if inv_data.get("inventory_health"):
                findings.append(f"Inventory health: {inv_data['inventory_health']}")
            if inv_data.get("stockout_risks"):
                findings.append(f"Stockout risks identified: {len(inv_data['stockout_risks'])} items")

        # Stock prediction findings
        if sp.get("status") == "success":
            sp_data = sp.get("data", {})
            if sp_data.get("stock_forecast"):
                findings.append("Stock forecast generated for planning horizon")

        # Supplier findings
        if sup.get("status") == "success":
            sup_data = sup.get("data", {})
            if sup_data.get("supplier_scores"):
                findings.append("Supplier scores evaluated")

        # Final recommendation
        if score >= 70 and quality == "high":
            action = "place_reorder"
            confidence = "high"
            reason = "Inventory levels and supplier data support immediate reorder"
        elif score >= 50:
            action = "find_backup_supplier"
            confidence = "medium"
            reason = "Operations data shows potential supply chain risks"
        elif score >= 30:
            action = "clear_dead_stock"
            confidence = "medium"
            reason = "Inventory analysis reveals excess stock that should be cleared"
        else:
            action = "no_action_needed"
            confidence = "low"
            reason = "Insufficient data to recommend operational changes"

        return {
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "findings": findings,
            "next_steps": self._next_steps(action),
            "quality_score": score,
        }

    def _next_steps(self, action: str) -> list[str]:
        """Generate specific next steps based on recommendation."""
        if action == "place_reorder":
            return [
                "Generate purchase orders for low-stock items",
                "Confirm lead times with preferred suppliers",
                "Update reorder points based on forecast",
                "Schedule receiving and warehousing",
            ]
        if action == "find_backup_supplier":
            return [
                "Run supplier discovery for at-risk categories",
                "Request quotes from alternative suppliers",
                "Evaluate supplier reliability scores",
                "Set up dual-sourcing for critical products",
            ]
        if action == "clear_dead_stock":
            return [
                "Identify slow-moving inventory over 90 days",
                "Create clearance pricing strategy",
                "Bundle dead stock with popular items",
                "Consider liquidation channels",
            ]
        return [
            "Continue monitoring inventory levels",
            "Review operations dashboard weekly",
            "Update demand forecasts with new data",
        ]
