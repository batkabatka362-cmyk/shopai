"""Cart Recovery Engine — orchestrates the full recovery pipeline.

This is the FLOW file.  It ONLY orchestrates — no business logic here.
Every step delegates to a dedicated module; this file wires them together.

Pipeline:
  Abandoned Cart Data -> Cart Analyzer -> Abandonment Classifier ->
  Recovery Strategy Selector -> Incentive Calculator -> Message Builder ->
  Timing Optimizer -> Channel Selector -> Value Estimator -> Output

Engine contract:
  Input:  {status, data: {cart, customer, store}, meta, error}
  Output: {status, data: {strategy, incentive, message, timing, channel,
           recovery_probability, expected_revenue, confidence}, meta, error}

Model usage summary:
  - Abandonment Classifier:      Mistral (analytical classification)
  - Recovery Strategy Selector:  Mistral (analytical strategy selection)
  - Message Builder:             LLaMA   (creative message generation)
  - Channel Selector:            Qwen    (channel selection)
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .cart_analyzer import analyze_cart
from .abandonment_classifier import classify_abandonment
from .recovery_strategy_selector import select_recovery_strategy
from .incentive_calculator import calculate_incentive
from .message_builder import build_message
from .timing_optimizer import optimize_timing
from .channel_selector import select_channel
from .value_estimator import estimate_value
from .memory_writer import write_to_memory
from .memory_reader import find_past_recoveries


class CartRecoveryEngine:
    """Cart Recovery Engine — orchestrator only, no logic."""

    ENGINE_NAME = "cart_recovery"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full cart recovery pipeline.

        Accepts a raw dict (will be validated and deep-copied).
        Returns a CartRecoveryOutput-shaped dict — always structured,
        never raises.
        """
        start = time.monotonic()

        try:
            return self._execute_pipeline(input_payload, start)
        except Exception as exc:
            return self._error_output(
                reason=f"Unexpected pipeline error: {exc}",
                elapsed=time.monotonic() - start,
            )

    # ------------------------------------------------------------------
    # Private pipeline
    # ------------------------------------------------------------------

    def _execute_pipeline(
        self,
        input_payload: dict[str, Any],
        start: float,
    ) -> dict[str, Any]:
        """Run each pipeline stage in sequence, short-circuiting on failure."""

        # Stage 0: Input validation and deep copy
        parsed = self._validate_input(input_payload)
        if parsed is None:
            return self._error_output(
                reason=(
                    "Invalid input: requires 'cart' (with items and total) "
                    "and 'customer' (with email)."
                ),
                elapsed=time.monotonic() - start,
            )

        cart: dict[str, Any] = parsed["cart"]
        customer: dict[str, Any] = parsed["customer"]
        store: dict[str, Any] = parsed["store"]

        # Stage 0.5: Check memory for past recovery attempts
        prior = find_past_recoveries(
            cart.get("customer_id", ""),
            min_confidence=0.1,
            max_results=3,
        )

        # Stage 1: Cart Analyzer (no model — deterministic)
        analysis_result = analyze_cart(cart, customer)
        if analysis_result.get("status") != "success":
            return self._error_output(
                reason=analysis_result.get("error", "Cart analysis failed."),
                elapsed=time.monotonic() - start,
            )
        analysis = analysis_result["analysis"]

        # Stage 2: Abandonment Classifier (model: Mistral)
        classification_result = classify_abandonment(analysis, customer, store)
        if classification_result.get("status") != "success":
            return self._error_output(
                reason=classification_result.get("error", "Abandonment classification failed."),
                elapsed=time.monotonic() - start,
            )
        classification = classification_result["classification"]

        # Stage 3: Recovery Strategy Selector (model: Mistral)
        strategy_result = select_recovery_strategy(analysis, classification)
        if strategy_result.get("status") != "success":
            return self._error_output(
                reason=strategy_result.get("error", "Recovery strategy selection failed."),
                elapsed=time.monotonic() - start,
            )
        strategy = strategy_result["strategy"]

        # Stage 4: Incentive Calculator (no model — deterministic)
        incentive_result = calculate_incentive(
            strategy,
            analysis,
            store,
        )
        if incentive_result.get("status") != "success":
            return self._error_output(
                reason=incentive_result.get("error", "Incentive calculation failed."),
                elapsed=time.monotonic() - start,
            )
        incentive = incentive_result["incentive"]

        # Stage 5: Message Builder (model: LLaMA)
        message_result = build_message(
            strategy,
            incentive,
            cart,
            customer,
        )
        if message_result.get("status") != "success":
            return self._error_output(
                reason=message_result.get("error", "Message building failed."),
                elapsed=time.monotonic() - start,
            )
        message = message_result["message"]

        # Stage 6: Timing Optimizer (no model — deterministic)
        timing_result = optimize_timing(
            analysis,
            classification,
            strategy,
        )
        if timing_result.get("status") != "success":
            return self._error_output(
                reason=timing_result.get("error", "Timing optimization failed."),
                elapsed=time.monotonic() - start,
            )
        timing = timing_result["timing"]

        # Stage 7: Channel Selector (model: Qwen)
        channel_result = select_channel(
            strategy,
            customer,
            analysis,
        )
        if channel_result.get("status") != "success":
            return self._error_output(
                reason=channel_result.get("error", "Channel selection failed."),
                elapsed=time.monotonic() - start,
            )
        channel_selection = channel_result["channel_selection"]

        # Stage 8: Value Estimator (no model — deterministic)
        value_result = estimate_value(
            analysis,
            classification,
            strategy,
            incentive,
            channel_selection,
        )
        if value_result.get("status") != "success":
            return self._error_output(
                reason=value_result.get("error", "Value estimation failed."),
                elapsed=time.monotonic() - start,
            )
        value_estimate = value_result["estimate"]

        # Stage 9: Build final output
        elapsed = time.monotonic() - start

        output: dict[str, Any] = {
            "status": "success",
            "data": {
                "strategy": strategy.get("strategy", "email_reminder"),
                "incentive": {
                    "type": incentive.get("type", "none"),
                    "value": incentive.get("value", 0),
                },
                "message": {
                    "subject": message.get("subject", ""),
                    "body": message.get("body", ""),
                    "cta": message.get("cta", ""),
                },
                "timing": {
                    "send_at": timing.get("send_at", ""),
                    "sequence": timing.get("sequence", []),
                },
                "channel": channel_selection.get("channel", "email"),
                "recovery_probability": value_estimate.get("recovery_probability", 0.0),
                "expected_revenue": value_estimate.get("expected_revenue", 0.0),
                "confidence": value_estimate.get("confidence", 0.0),
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
                "models": {
                    "abandonment_classifier": "mistral",
                    "recovery_strategy_selector": "mistral",
                    "message_builder": "llama",
                    "channel_selector": "qwen",
                },
                "pipeline_stats": {
                    "cart_value": analysis.get("total_value", 0.0),
                    "items_count": analysis.get("items_count", 0),
                    "customer_type": analysis.get("customer_type", "unknown"),
                    "abandonment_reason": classification.get("reason", "unknown"),
                    "strategy_priority": strategy.get("priority", "medium"),
                    "incentive_margin_safe": incentive.get("margin_safe", True),
                },
                "prior_recoveries_found": len(prior),
            },
            "error": None,
        }

        # Stage 10: Persist to memory
        write_to_memory(output)

        return output

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Validate and normalise the input into a usable dict.

        Returns ``None`` if the input is unusable.
        Never mutates *payload*.
        """
        if not isinstance(payload, dict):
            return None

        safe = copy.deepcopy(payload)

        # Engine contract: payload is {status, data, meta, error}
        data = safe.get("data", safe)  # fallback to raw dict
        if not isinstance(data, dict):
            return None

        cart = data.get("cart", {})
        if not isinstance(cart, dict):
            return None

        # Cart must have items
        items = cart.get("items", [])
        if not isinstance(items, list) or not items:
            return None

        customer = data.get("customer", {})
        if not isinstance(customer, dict):
            return None

        # Customer must have email
        email = customer.get("email", "")
        if not isinstance(email, str) or not email.strip():
            return None

        store = data.get("store", {})
        if not isinstance(store, dict):
            store = {}

        # Apply defaults for store config
        store.setdefault("avg_margin", 0.40)
        store.setdefault("free_shipping_threshold", 75.0)

        # Apply default total if missing
        if "total" not in cart or not isinstance(cart.get("total"), (int, float)):
            cart["total"] = sum(
                float(item.get("price", 0)) * int(item.get("quantity", 1))
                for item in items
                if isinstance(item, dict)
            )

        return {
            "cart": cart,
            "customer": customer,
            "store": store,
        }

    # ------------------------------------------------------------------
    # Error output helper
    # ------------------------------------------------------------------

    def _error_output(self, *, reason: str, elapsed: float) -> dict[str, Any]:
        """Build a well-formed error response."""
        return {
            "status": "fail",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
