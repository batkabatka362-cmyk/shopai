"""Trend scorer — aggregate all signals into a unified trend score.

Combines search, social, marketplace, and emerging niche signals into
a single composite score with confidence assessment and classification.

Input: {signals: {search: {...}, social: {...}, marketplace: {...}, emerging: {...}},
        trend_name, category}
Output: {composite_score, classification, confidence, signal_agreement, action, details}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .data import SIGNAL_WEIGHTS, SCORE_THRESHOLDS, HISTORICAL_ACCURACY
from .rules import evaluate_rules, MIN_SIGNAL_SCORE


def score_trend(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Score a trend by aggregating all signal sources — engine contract."""
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    data = copy.deepcopy(input_payload.get("data", {}))
    signals = _normalize_signals(data.get("signals", {}))
    composite = _compute_composite(signals)
    agreement = _assess_agreement(signals)
    classification = _classify_trend(composite)
    confidence = _compute_confidence(signals, agreement)

    rule_ctx = {
        "signals": {k: v["score"] for k, v in signals.items()},
        "signal_timestamps": {k: v.get("timestamp", 0) for k, v in signals.items()},
        "active_bets": data.get("active_bets", 0),
        "recommended_action": _pick_action(composite, confidence),
    }
    rule_result = evaluate_rules(rule_ctx)

    # Cap confidence if rules require
    if not rule_result["passed"]:
        confidence = min(confidence, 0.40)

    result = {
        "trend_name": data.get("trend_name", "unknown"),
        "category": data.get("category", ""),
        "composite_score": composite,
        "classification": classification,
        "confidence": confidence,
        "signal_agreement": agreement,
        "signal_scores": {k: v["score"] for k, v in signals.items()},
        "signal_count": sum(1 for v in signals.values() if v["score"] >= MIN_SIGNAL_SCORE),
        "action": _pick_action(composite, confidence),
        "signal_combo_accuracy": _get_combo_accuracy(signals),
        "rules": rule_result,
    }

    output_check = _validate_output(result)
    if not output_check["valid"]:
        return _error_output(output_check["reason"])

    return {
        "status": "success",
        "data": result,
        "meta": {
            "engine": "trend_scorer",
            "confidence": confidence,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "Input must be a dict"}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Input.data must be a dict"}
    signals = data.get("signals")
    if not isinstance(signals, dict) or len(signals) == 0:
        return {"valid": False, "reason": "Input.data.signals must be a non-empty dict"}
    return {"valid": True, "reason": "OK"}


def _normalize_signals(raw_signals: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize each signal source to a consistent {score, raw, timestamp} format."""
    normalized: dict[str, dict[str, Any]] = {}
    for source in ("search", "social", "marketplace", "emerging"):
        entry = raw_signals.get(source, {})
        if isinstance(entry, (int, float)):
            normalized[source] = {"score": max(0, min(100, round(entry))), "raw": entry, "timestamp": time.time()}
        elif isinstance(entry, dict):
            score = entry.get("score", entry.get("trend_score", entry.get("opportunity_score", 0)))
            normalized[source] = {
                "score": max(0, min(100, round(float(score)))),
                "raw": entry,
                "timestamp": entry.get("timestamp", time.time()),
            }
        else:
            normalized[source] = {"score": 0, "raw": None, "timestamp": 0}
    return normalized


def _compute_composite(signals: dict[str, dict[str, Any]]) -> int:
    """Weighted sum of all signal scores."""
    total = 0.0
    weight_sum = 0.0
    for source, weight in SIGNAL_WEIGHTS.items():
        score = signals.get(source, {}).get("score", 0)
        if score >= MIN_SIGNAL_SCORE:
            total += score * weight
            weight_sum += weight
    if weight_sum == 0:
        return 0
    # Re-normalize to account for missing signals
    return round(total / weight_sum)


def _assess_agreement(signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Detect signal agreement or conflict."""
    active = {k: v["score"] for k, v in signals.items() if v["score"] >= MIN_SIGNAL_SCORE}
    if len(active) < 2:
        return {"level": "insufficient", "detail": "Not enough active signals to assess agreement", "conflict": False}
    scores = list(active.values())
    spread = max(scores) - min(scores)
    avg = sum(scores) / len(scores)

    if spread <= 15:
        level = "strong_agreement"
    elif spread <= 30:
        level = "moderate_agreement"
    elif spread <= 50:
        level = "weak_agreement"
    else:
        level = "conflict"

    return {
        "level": level,
        "detail": f"{len(active)} signals, spread={spread}, avg={avg:.0f}",
        "conflict": spread > 50,
        "active_sources": list(active.keys()),
        "spread": spread,
    }


def _classify_trend(composite_score: int) -> str:
    """Map composite score to a classification tier."""
    for tier in ("exploding", "strong", "moderate", "weak"):
        if composite_score >= SCORE_THRESHOLDS[tier]["min_score"]:
            return tier
    return "declining"


def _compute_confidence(signals: dict[str, dict[str, Any]], agreement: dict[str, Any]) -> float:
    """Confidence based on signal count, agreement, and historical accuracy."""
    active_count = sum(1 for v in signals.values() if v["score"] >= MIN_SIGNAL_SCORE)
    base = 0.15 + active_count * 0.18  # 1 sig=0.33, 2=0.51, 3=0.69, 4=0.87

    # Agreement bonus/penalty
    level = agreement.get("level", "insufficient")
    if level == "strong_agreement":
        base += 0.10
    elif level == "conflict":
        base -= 0.15

    return round(max(0.05, min(0.95, base)), 2)


def _pick_action(composite: int, confidence: float) -> str:
    """Decide action based on score and confidence."""
    if composite >= 70 and confidence >= 0.60:
        return "act_now"
    if composite >= 50 and confidence >= 0.45:
        return "prepare"
    if composite >= 25:
        return "monitor"
    return "ignore"


def _get_combo_accuracy(signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Look up historical accuracy for the active signal combination."""
    active = sorted(k for k, v in signals.items() if v["score"] >= MIN_SIGNAL_SCORE)
    if len(active) == 4:
        key = "all_four"
    elif active == ["marketplace", "search"]:
        key = "search+marketplace"
    elif active == ["marketplace", "search", "social"]:
        key = "search+social+marketplace"
    elif active == ["search", "social"]:
        key = "search+social"
    elif active == ["emerging", "marketplace"]:
        key = "marketplace+emerging"
    elif active == ["social"]:
        key = "social_only"
    elif active == ["emerging"]:
        key = "emerging_only"
    else:
        key = "+".join(active) if active else "none"
    return HISTORICAL_ACCURACY.get(key, {"accuracy": 0.30, "description": "Uncommon combination", "false_positive_rate": 0.40})


def _validate_output(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Output must be a dict"}
    if "composite_score" not in data or "classification" not in data:
        return {"valid": False, "reason": "Missing required output fields"}
    return {"valid": True, "reason": "OK"}


def _error_output(reason: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "data": None,
        "meta": {"engine": "trend_scorer", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "error": {"reason": reason},
    }
