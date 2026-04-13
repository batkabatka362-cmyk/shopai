"""Trend scorer rules — constraints on scoring and confidence.

Hard rules that override scoring:
  - Minimum signal sources for confidence tiers
  - Maximum simultaneous trend bets
  - Signal recency requirements
  - Data quality gates
"""
from __future__ import annotations

import time
from typing import Any


# Maximum age of signal data in days
MAX_SIGNAL_AGE_DAYS = 30

# Minimum signal sources required per confidence tier
MIN_SOURCES_MEDIUM_CONFIDENCE = 2
MIN_SOURCES_HIGH_CONFIDENCE = 3

# Maximum active trend bets at any time
MAX_ACTIVE_BETS = 3

# Minimum individual signal score to count as "present"
MIN_SIGNAL_SCORE = 10

RULES = [
    {
        "id": "min_sources_medium",
        "name": "Minimum sources for medium confidence",
        "description": "Need at least 2 signal sources scoring >10 for medium confidence",
        "severity": "warning",
        "check": lambda ctx: _count_active_signals(ctx) >= MIN_SOURCES_MEDIUM_CONFIDENCE,
        "action": "Confidence capped at 'low' — insufficient signal sources",
    },
    {
        "id": "min_sources_high",
        "name": "Minimum sources for high confidence",
        "description": "Need at least 3 signal sources scoring >10 for high confidence",
        "severity": "info",
        "check": lambda ctx: _count_active_signals(ctx) >= MIN_SOURCES_HIGH_CONFIDENCE,
        "action": "Confidence capped at 'medium' — need 3+ signal sources for high",
    },
    {
        "id": "max_active_bets",
        "name": "Maximum active trend bets",
        "description": "No more than 3 active trend bets at any time",
        "severity": "blocker",
        "check": lambda ctx: ctx.get("active_bets", 0) < MAX_ACTIVE_BETS,
        "action": "At max capacity — must drop a trend before adding a new one",
    },
    {
        "id": "signal_recency",
        "name": "Signal data recency",
        "description": "All signal data must be less than 30 days old",
        "severity": "warning",
        "check": lambda ctx: _check_recency(ctx),
        "action": "Stale data detected — refresh signals before making decisions",
    },
    {
        "id": "no_single_source_high_action",
        "name": "No high-action on single source",
        "description": "Cannot recommend 'act_now' with only one signal source",
        "severity": "blocker",
        "check": lambda ctx: not (
            ctx.get("recommended_action") == "act_now"
            and _count_active_signals(ctx) < 2
        ),
        "action": "Cannot act on single signal — gather more data first",
    },
    {
        "id": "conflict_flag",
        "name": "Signal conflict detection",
        "description": "Flag when signals significantly disagree",
        "severity": "warning",
        "check": lambda ctx: not _has_signal_conflict(ctx),
        "action": "Signals conflict — investigate before committing resources",
    },
]


def evaluate_rules(context: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all rules against the scoring context."""
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](context)
        except Exception:
            passed = True

        if not passed:
            entry = {"rule_id": rule["id"], "name": rule["name"], "action": rule["action"]}
            if rule["severity"] == "blocker":
                blockers.append(entry)
            elif rule["severity"] == "warning":
                warnings.append(entry)
            else:
                info.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(RULES),
    }


def _count_active_signals(ctx: dict[str, Any]) -> int:
    """Count how many signal sources have a score above the minimum threshold."""
    signals = ctx.get("signals", {})
    return sum(1 for score in signals.values() if score >= MIN_SIGNAL_SCORE)


def _check_recency(ctx: dict[str, Any]) -> bool:
    """Verify all signal timestamps are within the allowed recency window."""
    timestamps = ctx.get("signal_timestamps", {})
    if not timestamps:
        return False
    now = time.time()
    max_age_seconds = MAX_SIGNAL_AGE_DAYS * 86400
    for ts in timestamps.values():
        if isinstance(ts, (int, float)) and (now - ts) > max_age_seconds:
            return False
    return True


def _has_signal_conflict(ctx: dict[str, Any]) -> bool:
    """Detect if signals significantly disagree (some high, some very low)."""
    signals = ctx.get("signals", {})
    scores = [v for v in signals.values() if isinstance(v, (int, float))]
    if len(scores) < 2:
        return False
    return (max(scores) - min(scores)) > 50
