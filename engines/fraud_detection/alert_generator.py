"""Fraud Detection Engine — alert generator.

Generates fraud alerts for orders with high or critical risk levels.
Only produces an alert when risk_level >= high.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Alert thresholds
# ---------------------------------------------------------------------------

_ALERT_RISK_LEVELS: set[str] = {"high", "critical"}


def generate_alert(
    verdict: str,
    risk_score: float,
    signals: dict[str, Any],
    order_id: str,
) -> dict[str, Any]:
    """Generate a fraud alert if risk level warrants it.

    Args:
        verdict: The fraud verdict (approve, review, reject).
        risk_score: Final combined risk score (0.0-1.0).
        signals: Dict of all signal results keyed by signal name.
        order_id: The order identifier.

    Returns:
        Structured dict with alert (or None if risk is low/medium).
    """
    try:
        signals = copy.deepcopy(signals)

        # Determine risk level from score
        if risk_score < 0.3:
            risk_level = "low"
        elif risk_score < 0.6:
            risk_level = "medium"
        elif risk_score < 0.8:
            risk_level = "high"
        else:
            risk_level = "critical"

        # Only generate alert for high/critical
        if risk_level not in _ALERT_RISK_LEVELS:
            return {
                "status": "success",
                "alert": None,
            }

        # Identify top contributing signals
        top_signals = _rank_signals(signals)

        # Generate recommended actions based on verdict and signals
        recommended_actions = _build_actions(verdict, risk_level, signals)

        alert = {
            "alert_id": uuid.uuid4().hex[:12],
            "order_id": order_id,
            "risk_level": risk_level,
            "risk_score": round(risk_score, 4),
            "verdict": verdict,
            "top_signals": top_signals,
            "recommended_actions": recommended_actions,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        return {
            "status": "success",
            "alert": alert,
        }
    except Exception as exc:
        return {
            "status": "error",
            "alert": None,
            "error": f"Alert generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rank_signals(signals: dict[str, Any]) -> list[str]:
    """Rank signals by score descending and return top contributors."""
    scored: list[tuple[str, float]] = []
    for name, data in signals.items():
        if isinstance(data, dict) and data.get("status") == "success":
            scored.append((name, float(data.get("score", 0.0))))

    scored.sort(key=lambda x: x[1], reverse=True)

    # Return names of signals with score > 0.3
    return [name for name, score in scored if score > 0.3]


def _build_actions(
    verdict: str,
    risk_level: str,
    signals: dict[str, Any],
) -> list[str]:
    """Build recommended actions based on verdict and signal details."""
    actions: list[str] = []

    if verdict == "reject":
        actions.append("Block order and flag account for review")
    elif verdict == "review":
        actions.append("Hold order for manual review before fulfillment")

    # Signal-specific actions
    blacklist = signals.get("blacklist", {})
    if isinstance(blacklist, dict):
        if blacklist.get("email_listed"):
            actions.append("Email is blacklisted — verify customer identity")
        if blacklist.get("ip_listed"):
            actions.append("IP address is blacklisted — check for proxy/VPN")

    velocity = signals.get("velocity", {})
    if isinstance(velocity, dict) and velocity.get("flag"):
        actions.append("High order velocity detected — review recent orders")

    address = signals.get("address", {})
    if isinstance(address, dict):
        if address.get("is_freight_forwarder"):
            actions.append("Shipping to known freight forwarder — verify destination")
        if not address.get("billing_shipping_match", True):
            actions.append("Billing/shipping address mismatch — request verification")

    pattern = signals.get("pattern", {})
    if isinstance(pattern, dict):
        patterns = pattern.get("detected_patterns", [])
        if "card_testing" in patterns:
            actions.append("Card testing pattern detected — consider CAPTCHA or velocity limit")
        if "gift_card_abuse" in patterns:
            actions.append("Gift card abuse pattern — limit gift card purchases")

    device = signals.get("device", {})
    if isinstance(device, dict) and device.get("is_bot"):
        actions.append("Bot/automation detected — challenge with CAPTCHA")

    if risk_level == "critical":
        actions.append("Escalate to fraud team immediately")

    return actions
