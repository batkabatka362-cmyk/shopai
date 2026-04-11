"""Cart Recovery Engine — timing optimizer.

Optimizes when to send recovery messages and builds a multi-touch
sequence based on purchase urgency and abandonment context.

Timing strategy:
  - 1hr:  browse reminder (gentle nudge)
  - 24hr: incentive offer (main recovery attempt)
  - 72hr: last chance (final urgency push)

Model note: no model usage — deterministic timing rules.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Timing constants
# ---------------------------------------------------------------------------

_DELAY_BROWSE_REMINDER_HR = 1.0
_DELAY_INCENTIVE_HR = 24.0
_DELAY_LAST_CHANCE_HR = 72.0

# Urgency thresholds based on hours since abandonment
_URGENCY_HIGH_HR = 2.0
_URGENCY_LOW_HR = 48.0


def optimize_timing(
    analysis: dict[str, Any],
    classification: dict[str, Any],
    strategy: dict[str, Any],
) -> dict[str, Any]:
    """Optimize send timing and build a recovery sequence.

    Args:
        analysis: CartAnalysis from cart analyzer.
        classification: AbandonmentClassification from classifier.
        strategy: RecoveryStrategy from strategy selector.

    Returns:
        Structured dict with TimingPlan data and status.
    """
    try:
        safe_analysis = copy.deepcopy(analysis)
        safe_classification = copy.deepcopy(classification)
        safe_strategy = copy.deepcopy(strategy)

        hours_since = float(safe_analysis.get("hours_since_abandonment", 0))
        cart_value_tier = str(safe_analysis.get("cart_value_tier", "medium"))
        reason = str(safe_classification.get("reason", "distraction"))
        strategy_name = str(safe_strategy.get("strategy", "email_reminder"))
        priority = str(safe_strategy.get("priority", "medium"))

        # --- Determine urgency level ---
        urgency_level = _compute_urgency(
            hours_since, cart_value_tier, priority, reason,
        )

        # --- Compute first send time ---
        first_delay_hr = _compute_first_delay(hours_since, urgency_level, reason)
        send_at = _compute_send_at(first_delay_hr)

        # --- Build sequence ---
        sequence = _build_sequence(
            strategy_name, urgency_level, cart_value_tier, hours_since,
        )

        rationale = (
            f"Urgency: {urgency_level}. First touch at +{first_delay_hr:.1f}hr "
            f"(hours since abandonment: {hours_since:.1f}). "
            f"{len(sequence)}-step sequence for '{strategy_name}' strategy."
        )

        return {
            "status": "success",
            "timing": {
                "send_at": send_at,
                "sequence": sequence,
                "urgency_level": urgency_level,
                "rationale": rationale,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "timing": {},
            "error": f"Timing optimization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_urgency(
    hours_since: float,
    cart_value_tier: str,
    priority: str,
    reason: str,
) -> str:
    """Determine urgency level from context signals."""
    score = 0.0

    # Time-based urgency
    if hours_since < _URGENCY_HIGH_HR:
        score += 0.4
    elif hours_since > _URGENCY_LOW_HR:
        score -= 0.2

    # Value-based urgency
    if cart_value_tier == "high":
        score += 0.3
    elif cart_value_tier == "low":
        score -= 0.1

    # Priority-based
    if priority in ("critical", "high"):
        score += 0.2

    # Reason-based
    if reason in ("distraction", "payment_issue"):
        score += 0.1  # Quick recovery more likely
    elif reason == "just_browsing":
        score -= 0.2  # Low intent

    if score >= 0.5:
        return "high"
    if score >= 0.2:
        return "medium"
    return "low"


def _compute_first_delay(
    hours_since: float,
    urgency_level: str,
    reason: str,
) -> float:
    """Compute hours until first message send."""
    # If cart was just abandoned, wait for browse reminder window
    if hours_since < _DELAY_BROWSE_REMINDER_HR:
        return max(_DELAY_BROWSE_REMINDER_HR - hours_since, 0.25)

    # If we're already past the browse reminder window
    if hours_since < _DELAY_INCENTIVE_HR:
        if urgency_level == "high":
            return 0.5  # Send quickly for high urgency
        return max(2.0 - (hours_since - _DELAY_BROWSE_REMINDER_HR) * 0.1, 0.5)

    # Already past 24hr — send last chance soon
    if urgency_level == "high":
        return 0.5
    return 2.0


def _compute_send_at(delay_hours: float) -> str:
    """Compute ISO-8601 send timestamp from delay in hours."""
    send_epoch = time.time() + (delay_hours * 3600)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(send_epoch))


def _build_sequence(
    strategy_name: str,
    urgency_level: str,
    cart_value_tier: str,
    hours_since: float,
) -> list[dict[str, Any]]:
    """Build a multi-touch recovery sequence."""
    sequence: list[dict[str, Any]] = []

    # Step 1: Browse reminder (1hr mark)
    if hours_since < _DELAY_BROWSE_REMINDER_HR:
        sequence.append({
            "delay_hours": _DELAY_BROWSE_REMINDER_HR,
            "action": "send_reminder",
            "message_type": "browse_reminder",
        })

    # Step 2: Incentive offer (24hr mark)
    if strategy_name in ("discount_offer", "free_shipping"):
        sequence.append({
            "delay_hours": _DELAY_INCENTIVE_HR,
            "action": "send_incentive",
            "message_type": "incentive_offer",
        })
    else:
        sequence.append({
            "delay_hours": _DELAY_INCENTIVE_HR,
            "action": "send_followup",
            "message_type": "followup_reminder",
        })

    # Step 3: Last chance (72hr mark) — only for medium+ value or high urgency
    if cart_value_tier in ("medium", "high") or urgency_level == "high":
        sequence.append({
            "delay_hours": _DELAY_LAST_CHANCE_HR,
            "action": "send_last_chance",
            "message_type": "last_chance",
        })

    # For critical cases, add a 48hr intermediate touch
    if urgency_level == "high" and cart_value_tier == "high":
        sequence.insert(-1, {
            "delay_hours": 48.0,
            "action": "send_escalation",
            "message_type": "escalation_offer",
        })

    return sequence
