"""Fraud Detection Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Validate → Memory Reader → Risk Scorer → Velocity Checker →
  Address Verifier → Pattern Detector → Blacklist Checker →
  Device Fingerprinter → Decision Maker → Alert Generator →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {order, device}, meta, error}
  Output: {status, data: {order_id, verdict, risk_score, risk_level, confidence, signals, recommended_actions, alert}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Any

from .risk_scorer import score_base_risk
from .velocity_checker import check_velocity
from .address_verifier import verify_address
from .pattern_detector import detect_patterns
from .blacklist_checker import check_blacklists
from .device_fingerprinter import analyze_device
from .decision_maker import make_decision
from .alert_generator import generate_alert
from .memory_reader import read_fraud_history, read_past_orders
from .memory_writer import write_fraud_decision
from engines._shopify_hydrator import hydrate_one


class FraudDetectionEngine:
    """Fraud Detection Engine — orchestrator only, no logic."""

    ENGINE_NAME = "fraud_detection"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full fraud detection pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            FraudOutput dict.
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

        order = data.get("order", {})

        # Auto-hydrate a single order from Shopify when caller left
        # the dict empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        order = hydrate_one(
            supplied=order if isinstance(order, dict) else {},
            capability_name="SHOPIFY_FETCH_ORDERS",
            list_field="orders",
            query=data.get("hydrate_query"),
        )

        if not isinstance(order, dict) or not order:
            return self._fail("Order data is required", 0.0)

        device = data.get("device", {})
        order_id = str(order.get("id", "unknown"))
        email = str(order.get("email", ""))
        ip_address = str(order.get("ip_address", ""))
        phone = str(order.get("customer", {}).get("phone", ""))
        customer = order.get("customer", {})
        if not isinstance(customer, dict):
            customer = {}
        shipping = order.get("shipping_address", {})
        billing = order.get("billing_address", {})

        # ---- Stage 1: Memory Reader (non-blocking) ----
        _history = read_fraud_history(email=email, limit=50)
        past_orders = read_past_orders(email=email, ip=ip_address, limit=50)

        # ---- Stage 2: Risk Scorer ----
        base_risk_result = score_base_risk(
            order=order,
            customer=customer,
        )
        if base_risk_result.get("status") == "error":
            return self._fail(
                f"Base risk scoring failed: {base_risk_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 3: Velocity Checker ----
        velocity_result = check_velocity(
            order=order,
            past_orders=past_orders,
        )
        if velocity_result.get("status") == "error":
            return self._fail(
                f"Velocity check failed: {velocity_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 4: Address Verifier ----
        address_result = verify_address(
            shipping=shipping,
            billing=billing,
        )
        if address_result.get("status") == "error":
            return self._fail(
                f"Address verification failed: {address_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 5: Pattern Detector ----
        pattern_result = detect_patterns(
            order=order,
            customer=customer,
            past_orders=past_orders,
        )
        if pattern_result.get("status") == "error":
            return self._fail(
                f"Pattern detection failed: {pattern_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 6: Blacklist Checker ----
        address_hash = _compute_address_hash(shipping)
        blacklist_result = check_blacklists(
            email=email,
            ip=ip_address,
            phone=phone,
            address_hash=address_hash,
        )
        if blacklist_result.get("status") == "error":
            return self._fail(
                f"Blacklist check failed: {blacklist_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 7: Device Fingerprinter ----
        device_result = analyze_device(
            device=device,
        )
        if device_result.get("status") == "error":
            return self._fail(
                f"Device analysis failed: {device_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 8: Decision Maker ----
        signals = {
            "base_risk": base_risk_result,
            "velocity": velocity_result,
            "address": address_result,
            "pattern": pattern_result,
            "blacklist": blacklist_result,
            "device": device_result,
        }

        decision_result = make_decision(signals=signals)
        if decision_result.get("status") == "error":
            return self._fail(
                f"Decision making failed: {decision_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        verdict = decision_result.get("verdict", "review")
        risk_score = decision_result.get("risk_score", 0.5)
        risk_level = decision_result.get("risk_level", "medium")
        confidence = decision_result.get("confidence", 0.0)

        # ---- Stage 9: Alert Generator ----
        alert_result = generate_alert(
            verdict=verdict,
            risk_score=risk_score,
            signals=signals,
            order_id=order_id,
        )
        if alert_result.get("status") == "error":
            return self._fail(
                f"Alert generation failed: {alert_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        alert = alert_result.get("alert")
        recommended_actions = (
            alert.get("recommended_actions", []) if alert else []
        )

        # ---- Stage 10: Memory Writer (non-fatal) ----
        order_summary = {
            "id": order_id,
            "email": email,
            "ip_address": ip_address,
            "total_price": order.get("total_price", 0.0),
            "shipping_address": shipping,
            "created_at": order.get("created_at", ""),
        }

        _write_result = write_fraud_decision(
            order_id=order_id,
            verdict=verdict,
            risk_score=risk_score,
            signals=signals,
            order_summary=order_summary,
            alert=alert,
        )

        # ---- Stage 10.5: Phase 7 writeback (opt-in) ----
        # Default OFF. Operator opts in via either:
        #   data.require_approval=True -- queue path (recommended;
        #     order tagging is operator-visible)
        #   data.apply_fraud_tag=True  -- direct execute path
        # The queue path takes precedence when both are set.
        fraud_data_block = {
            "order_id": order_id,
            "verdict": verdict,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "confidence": confidence,
        }
        apply_results: list[dict[str, Any]] = []
        if data.get("require_approval"):
            from .fraud_applier import (
                enqueue_fraud_tag_for_approval,
            )
            apply_results = enqueue_fraud_tag_for_approval(
                fraud_data_block,
            )
        elif data.get("apply_fraud_tag"):
            from .fraud_applier import apply_fraud_tag
            apply_results = apply_fraud_tag(fraud_data_block)

        # ---- Stage 11: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "order_id": order_id,
                "verdict": verdict,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "confidence": confidence,
                "signals": {
                    "base_risk": base_risk_result,
                    "velocity": velocity_result,
                    "address": address_result,
                    "pattern": pattern_result,
                    "blacklist": blacklist_result,
                    "device": device_result,
                },
                "recommended_actions": recommended_actions,
                "alert": alert,
                "fraud_pending_actions": apply_results,
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


# ---------------------------------------------------------------------------
# Module-level helpers (used only by flow)
# ---------------------------------------------------------------------------

def _compute_address_hash(address: dict[str, Any]) -> str:
    """Compute a deterministic hash of an address for blacklist lookup."""
    try:
        parts = [
            str(address.get("line1", "")).lower().strip(),
            str(address.get("city", "")).lower().strip(),
            str(address.get("state", "")).lower().strip(),
            str(address.get("zip", "")).strip(),
            str(address.get("country", "")).upper().strip(),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""
