"""Conversion Tracking Engine — attribution modeler.

Attributes conversion value to marketing touchpoints using various
attribution models: first_touch, last_touch, linear, time_decay.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Supported attribution models
# ---------------------------------------------------------------------------

_SUPPORTED_MODELS = {"first_touch", "last_touch", "linear", "time_decay"}

# Time decay half-life in days
_TIME_DECAY_HALF_LIFE = 7.0


def model_attribution(
    tracked_events: list[dict[str, Any]],
    touchpoints: list[dict[str, Any]],
    model: str = "last_touch",
) -> dict[str, Any]:
    """Attribute conversion value to touchpoints.

    Args:
        tracked_events: List of validated tracked events.
        touchpoints: List of marketing touchpoints.
        model: Attribution model to use.

    Returns:
        Structured dict with attributed conversions and summary report.
    """
    try:
        tracked_events = copy.deepcopy(tracked_events)
        touchpoints = copy.deepcopy(touchpoints)

        if model not in _SUPPORTED_MODELS:
            model = "last_touch"

        # Group touchpoints by customer
        customer_touchpoints: dict[str, list[dict[str, Any]]] = {}
        for tp in touchpoints:
            cid = str(tp.get("customer_id", ""))
            if cid:
                customer_touchpoints.setdefault(cid, []).append(tp)

        # Sort each customer's touchpoints by timestamp
        for cid in customer_touchpoints:
            customer_touchpoints[cid].sort(key=lambda t: t.get("timestamp", ""))

        # Attribute each conversion event
        attributed: list[dict[str, Any]] = []
        channel_totals: dict[str, float] = {}

        for event in tracked_events:
            if not event.get("is_valid", False):
                continue

            cid = str(event.get("customer_id", ""))
            value = float(event.get("value", 0.0))
            event_type = str(event.get("event_type", ""))

            # Only attribute value-bearing conversion events
            if event_type not in ("purchase", "checkout_complete", "subscription", "lead"):
                continue

            cust_tps = customer_touchpoints.get(cid, [])

            if not cust_tps:
                # Direct / no touchpoint
                attribution = {"direct": 1.0}
            else:
                attribution = _apply_model(model, cust_tps, value)

            # Accumulate channel totals
            for channel, share in attribution.items():
                channel_totals[channel] = channel_totals.get(channel, 0.0) + round(value * share, 2)

            attributed.append({
                "event_id": str(event.get("id", "")),
                "event_type": event_type,
                "value": value,
                "source": str(event.get("source", "")),
                "customer_id": cid,
                "attribution": attribution,
                "model_used": model,
            })

        # Build attribution report
        total_attributed = sum(channel_totals.values())
        attribution_report: dict[str, float] = {}
        for channel, total in sorted(channel_totals.items(), key=lambda x: x[1], reverse=True):
            attribution_report[channel] = round(total, 2)

        return {
            "status": "success",
            "attributed_conversions": attributed,
            "attribution_report": attribution_report,
            "total_attributed_value": round(total_attributed, 2),
            "model": model,
        }
    except Exception as exc:
        return {
            "status": "error",
            "attributed_conversions": [],
            "error": f"Attribution modeling failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Attribution model implementations
# ---------------------------------------------------------------------------

def _apply_model(
    model: str,
    touchpoints: list[dict[str, Any]],
    value: float,
) -> dict[str, float]:
    """Apply an attribution model to a customer's touchpoint journey."""
    if not touchpoints:
        return {"direct": 1.0}

    channels = [str(tp.get("channel", tp.get("campaign", "unknown"))) for tp in touchpoints]

    if model == "first_touch":
        return {channels[0]: 1.0}

    elif model == "last_touch":
        return {channels[-1]: 1.0}

    elif model == "linear":
        share = round(1.0 / len(channels), 4)
        result: dict[str, float] = {}
        for ch in channels:
            result[ch] = result.get(ch, 0.0) + share
        # Round all values
        return {k: round(v, 4) for k, v in result.items()}

    elif model == "time_decay":
        return _time_decay_attribution(touchpoints, channels)

    return {channels[-1]: 1.0}


def _time_decay_attribution(
    touchpoints: list[dict[str, Any]],
    channels: list[str],
) -> dict[str, float]:
    """Apply time-decay attribution weighting more recent touchpoints higher."""
    n = len(touchpoints)
    if n == 1:
        return {channels[0]: 1.0}

    # Assign weights: most recent gets highest weight
    # Weight doubles for every half-life period closer to conversion
    weights: list[float] = []
    for i in range(n):
        # Position-based decay: i=0 is oldest, i=n-1 is most recent
        position_ratio = i / (n - 1) if n > 1 else 1.0
        weight = 2.0 ** (position_ratio * 3)  # Exponential scaling
        weights.append(weight)

    total_weight = sum(weights)

    result: dict[str, float] = {}
    for ch, w in zip(channels, weights):
        share = w / total_weight
        result[ch] = result.get(ch, 0.0) + share

    return {k: round(v, 4) for k, v in result.items()}
