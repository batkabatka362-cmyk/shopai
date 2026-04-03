"""Fraud Detection Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Memory Reader → Risk Scorer → Velocity Checker → Address Verifier →
  Pattern Detector → Blacklist Checker → Device Fingerprinter →
  Decision Maker → Alert Generator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {order, device}, meta, error}
  Output: {status, data: {order_id, verdict, risk_score, risk_level, confidence, signals, alert}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import hashlib
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
from .memory_reader import read_fraud_history
from .memory_writer import write_fraud_decision


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
        device = data.get("device", {})

        if not order:
            return self._fail("order is required", 0.0)

        order_id = str(order.get("id", "unknown"))
        email = str(order.get("email", ""))
        ip_address = str(order.get("ip_address", ""))
        phone = str(order.get("phone", ""))
        total_price = float(order.get("total_price", 0))
        shipping_address = order.get("shipping_address", {})
        billing_address = order.get("billing_address", {})
        customer = order.get("customer", {})

        # ---- Stage 1: Memory Reader (non-blocking) ----
        history = read_fraud_history(email=email, limit=50)
        past_orders = history.get("records", [])

        # ---- Stage 2: Risk Scorer (Mistral) ----
        risk_result = score_base_risk(order=order, customer=customer)
        if risk_result.get("status") == "error":
            return self._fail(
                f"Risk scoring failed: {risk_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 3: Velocity Checker ----
        velocity_result = check_velocity(order=order, past_orders=past_orders)
        if velocity_result.get("status") == "error":
            return self._fail(
                f"Velocity check failed: {velocity_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 4: Address Verifier ----
        address_result = verify_address(
            shipping=shipping_address,
            billing=billing_address,
        )
        if address_result.get("status") == "error":
            return self._fail(
                f"Address verification failed: {address_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 5: Pattern Detector (Mistral) ----
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
        address_hash = _hash_address(shipping_address)
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
        device_result = analyze_device(device=device)
        if device_result.get("status") == "error":
            return self._fail(
                f"Device analysis failed: {device_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 8: Decision Maker (Qwen) ----
        signals = {
            "base_risk": risk_result,
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
            risk_level=risk_level,
            signals=signals,
            order_id=order_id,
        )
        alert = alert_result.get("alert")

        # Build recommended actions
        recommended_actions: list[str] = []
        if alert and isinstance(alert, dict):
            recommended_actions = alert.get("recommended_actions", [])

        # ---- Stage 10: Memory Writer (non-fatal) ----
        _write = write_fraud_decision(
            order_id=order_id,
            email=email,
            ip_address=ip_address,
            verdict=verdict,
            risk_score=risk_score,
            risk_level=risk_level,
            signals=signals,
            total_price=total_price,
        )

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
                    "base_risk": {
                        "score": risk_result.get("score", 0.0),
                        "factors": risk_result.get("factors", []),
                    },
                    "velocity": {
                        "score": velocity_result.get("score", 0.0),
                        "orders_1h": velocity_result.get("orders_1h", 0),
                        "orders_24h": velocity_result.get("orders_24h", 0),
                        "orders_7d": velocity_result.get("orders_7d", 0),
                        "flag": velocity_result.get("flag"),
                    },
                    "address": {
                        "score": address_result.get("score", 0.0),
                        "billing_shipping_match": address_result.get("billing_shipping_match", True),
                        "is_po_box": address_result.get("is_po_box", False),
                        "is_freight_forwarder": address_result.get("is_freight_forwarder", False),
                        "country_risk": address_result.get("country_risk", "low"),
                    },
                    "pattern": {
                        "score": pattern_result.get("score", 0.0),
                        "detected_patterns": pattern_result.get("detected_patterns", []),
                        "model_note": pattern_result.get("model_note", ""),
                    },
                    "blacklist": {
                        "score": blacklist_result.get("score", 0.0),
                        "email_listed": blacklist_result.get("email_listed", False),
                        "ip_listed": blacklist_result.get("ip_listed", False),
                        "address_listed": blacklist_result.get("address_listed", False),
                        "phone_listed": blacklist_result.get("phone_listed", False),
                    },
                    "device": {
                        "score": device_result.get("score", 0.0),
                        "is_bot": device_result.get("is_bot", False),
                        "timezone_consistent": device_result.get("timezone_consistent", True),
                        "fingerprint_hash": device_result.get("fingerprint_hash", ""),
                    },
                },
                "recommended_actions": recommended_actions,
                "alert": alert,
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


def _hash_address(address: dict[str, Any]) -> str:
    """Create a stable hash of an address for blacklist comparison."""
    parts = [
        str(address.get("address1", "")).lower().strip(),
        str(address.get("city", "")).lower().strip(),
        str(address.get("province", "")).lower().strip(),
        str(address.get("zip", "")).lower().strip(),
        str(address.get("country_code", "")).lower().strip(),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
