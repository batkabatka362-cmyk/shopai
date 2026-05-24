"""Subscription Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Plan Designer → Billing Manager →
  Churn Predictor → Upgrade Recommender → Memory Writer → Output

Engine contract:
  Input:  {status, data: {subscribers, plans, billing_history, products}, meta, error}
  Output: {status, data: {plan_recommendations, billing_summary, churn_risks, upgrade_opportunities, mrr}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .plan_designer import design_plans
from .billing_manager import manage_billing
from .churn_predictor import predict_churn
from .upgrade_recommender import recommend_upgrades
from .memory_reader import read_past_subscription_runs
from .memory_writer import write_subscription_result


class SubscriptionEngine:
    """Subscription Engine — orchestrator only, no logic."""

    ENGINE_NAME = "subscription"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full subscription pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            SubscriptionOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        subscribers = data.get("subscribers", [])
        plans = data.get("plans", [])
        billing_history = data.get("billing_history", [])
        products = data.get("products", [])

        if not subscribers and not plans:
            return self._fail("Subscribers or plans are required", 0.0)

        # ---- Stage 1: Read past subscription runs (non-blocking) ----
        _past = read_past_subscription_runs(limit=5)

        # ---- Stage 2: Plan Designer ----
        plan_result = design_plans(
            plans=plans,
            products=products,
            subscribers=subscribers,
        )
        if plan_result.get("status") == "error":
            return self._fail(
                f"Plan design failed: {plan_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        plan_recommendations = plan_result.get("recommendations", [])

        # ---- Stage 3: Billing Manager ----
        billing_result = manage_billing(
            subscribers=subscribers,
            plans=plans,
            billing_history=billing_history,
        )
        if billing_result.get("status") == "error":
            return self._fail(
                f"Billing management failed: {billing_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        billing_summary = billing_result.get("billing_summary", {})
        mrr = float(billing_summary.get("total_mrr", 0.0))

        # ---- Stage 4: Churn Predictor ----
        churn_result = predict_churn(
            subscribers=subscribers,
            billing_history=billing_history,
        )
        if churn_result.get("status") == "error":
            return self._fail(
                f"Churn prediction failed: {churn_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        churn_risks = churn_result.get("churn_risks", [])

        # ---- Stage 5: Upgrade Recommender ----
        upgrade_result = recommend_upgrades(
            subscribers=subscribers,
            plans=plans,
            billing_history=billing_history,
            churn_risks=churn_risks,
        )
        if upgrade_result.get("status") == "error":
            return self._fail(
                f"Upgrade recommendation failed: {upgrade_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        upgrade_opportunities = upgrade_result.get("opportunities", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_subscription_result(
            plan_recommendations=plan_recommendations,
            billing_summary=billing_summary,
            churn_risks=churn_risks,
            upgrade_opportunities=upgrade_opportunities,
            mrr=mrr,
        )

        # Phase 7: optional churn-risk tag apply. Opt-in via
        # data.apply_churn_risk_tags=True. Tags subscribers at
        # high/medium churn risk via SHOPIFY_TAG_CUSTOMER.
        tagged_churn_risks: list[dict[str, Any]] = []
        if bool(data.get("apply_churn_risk_tags")):
            try:
                from .tag_applier import apply_churn_risk_tags
                tagged_churn_risks = apply_churn_risk_tags(churn_risks)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).debug(
                    "subscription: apply loop raised: %s", exc,
                )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "plan_recommendations": plan_recommendations,
                "billing_summary": billing_summary,
                "churn_risks": churn_risks,
                "upgrade_opportunities": upgrade_opportunities,
                "mrr": mrr,
                "tagged_churn_risks": tagged_churn_risks,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
