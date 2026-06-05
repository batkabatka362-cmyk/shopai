"""Compute the day-over-day Phase 4 verdict diff."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_VERDICT_RANK = {
    "no_data":         0,
    "organic_only":    1,
    "attributed_loss": 2,
    "earning":         3,
}


@dataclass
class BriefDiff:
    samples_available: int = 0
    sufficient: bool = False
    previous_ts: float = 0.0
    current_ts: float = 0.0
    previous_verdict: str = "no_data"
    current_verdict: str = "no_data"
    verdict_change: str = "no_change"
    gross_profit_delta: float = 0.0
    attribution_pct_delta: float = 0.0
    monthly_run_rate_delta: float = 0.0
    history_trend_previous: str = "no_data"
    history_trend_current: str = "no_data"
    direction: str = "no_data"  # improved / regressed
                                # / unchanged / shifted /
                                # no_data
    headline: str = ""
    next_action: str = ""
    drift_notes: list[str] = field(default_factory=list)


def _classify_verdict_change(
    prev: str, cur: str,
) -> str:
    if prev == cur:
        return "no_change"
    if (
        _VERDICT_RANK.get(cur, 0)
        > _VERDICT_RANK.get(prev, 0)
    ):
        return "improved"
    return "regressed"


def _classify_direction(
    diff: BriefDiff,
) -> str:
    """Apply the rules:
      verdict rank up   -> improved
      verdict rank down -> regressed
      same verdict + significant profit drop -> regressed
      same verdict + significant profit gain -> improved
      else                                   -> unchanged
    'shifted' is reserved for same-rank verdict change
    which the rank table doesn't currently emit (all 4
    verdicts have distinct ranks).
    """
    change = diff.verdict_change
    if change == "improved":
        return "improved"
    if change == "regressed":
        return "regressed"
    # Verdict unchanged: judge by profit magnitude
    abs_delta = abs(diff.gross_profit_delta)
    if abs_delta < 5.0:
        return "unchanged"
    # Relative: > 5% of previous if known
    if diff.gross_profit_delta > 0:
        return "improved"
    return "regressed"


def _build_drift_notes(diff: BriefDiff) -> list[str]:
    notes: list[str] = []
    if abs(diff.gross_profit_delta) >= 5.0:
        notes.append(
            f"gross_profit {'+' if diff.gross_profit_delta >= 0 else ''}"
            f"${diff.gross_profit_delta:.0f}"
        )
    if abs(diff.attribution_pct_delta) >= 0.5:
        notes.append(
            f"attribution {'+' if diff.attribution_pct_delta >= 0 else ''}"
            f"{diff.attribution_pct_delta:.1f}pp"
        )
    if abs(diff.monthly_run_rate_delta) >= 20.0:
        notes.append(
            f"run-rate "
            f"{'+' if diff.monthly_run_rate_delta >= 0 else ''}"
            f"${diff.monthly_run_rate_delta:.0f}/mo"
        )
    if (
        diff.history_trend_previous
        != diff.history_trend_current
    ):
        notes.append(
            f"trend {diff.history_trend_previous}"
            f" -> {diff.history_trend_current}"
        )
    return notes


def _build_headline(diff: BriefDiff) -> str:
    if not diff.sufficient:
        return (
            "Need at least 2 history snapshots to "
            "compute a diff."
        )
    if diff.direction == "improved":
        return (
            f"IMPROVED: {diff.previous_verdict} -> "
            f"{diff.current_verdict}"
            if diff.verdict_change == "improved"
            else (
                f"IMPROVED: {diff.current_verdict} "
                f"(profit +${diff.gross_profit_delta:.0f})"
            )
        )
    if diff.direction == "regressed":
        return (
            f"REGRESSED: {diff.previous_verdict} -> "
            f"{diff.current_verdict}"
            if diff.verdict_change == "regressed"
            else (
                f"REGRESSED: {diff.current_verdict} "
                f"(profit ${diff.gross_profit_delta:.0f})"
            )
        )
    return (
        f"Unchanged: {diff.current_verdict}, drift below "
        "significance threshold."
    )


def _build_next_action(diff: BriefDiff) -> str:
    if not diff.sufficient:
        return (
            "shopai morning-brief --record to seed the "
            "history; one more cycle later, this surfaces "
            "a real diff."
        )
    if diff.direction == "regressed":
        return (
            "Run shopai anomalies + shopai action-critic "
            "before acting -- the regression may be a "
            "single-cycle dip."
        )
    if diff.direction == "improved":
        return (
            "Compound the win: shopai next-actions to "
            "find what to reinforce."
        )
    return (
        "Stay the course -- shopai morning-brief for "
        "today's plan."
    )


def compute_diff(
    *,
    snapshots_override: list[dict[str, Any]] | None = None,
) -> BriefDiff:
    """Build the diff. Reads the two newest history
    snapshots; falls back to empty when fewer than 2 exist."""
    diff = BriefDiff()
    if snapshots_override is not None:
        snaps = list(snapshots_override)
    else:
        try:
            from engines.agi_earnings_history import (
                store as h,
            )
            snaps = h.query(days=365, limit=2)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "brief_diff: history raised: %s", exc,
            )
            snaps = []
    diff.samples_available = len(snaps)
    if len(snaps) < 2:
        diff.headline = _build_headline(diff)
        diff.next_action = _build_next_action(diff)
        return diff

    # newest first per W963-50.query contract
    current, previous = snaps[0], snaps[1]
    diff.sufficient = True
    diff.current_ts = float(current.get("ts", 0) or 0)
    diff.previous_ts = float(previous.get("ts", 0) or 0)
    diff.current_verdict = str(
        current.get("verdict") or "no_data",
    )
    diff.previous_verdict = str(
        previous.get("verdict") or "no_data",
    )
    diff.verdict_change = _classify_verdict_change(
        diff.previous_verdict, diff.current_verdict,
    )
    diff.gross_profit_delta = round(
        float(current.get("gross_profit", 0) or 0)
        - float(previous.get("gross_profit", 0) or 0),
        2,
    )
    diff.attribution_pct_delta = round(
        float(current.get("attribution_pct", 0) or 0)
        - float(previous.get("attribution_pct", 0) or 0),
        2,
    )
    diff.monthly_run_rate_delta = round(
        float(current.get("monthly_run_rate", 0) or 0)
        - float(previous.get("monthly_run_rate", 0) or 0),
        2,
    )
    diff.history_trend_previous = str(
        previous.get("trend_verdict") or "no_data",
    )
    diff.history_trend_current = str(
        current.get("trend_verdict") or "no_data",
    )
    diff.direction = _classify_direction(diff)
    diff.drift_notes = _build_drift_notes(diff)
    diff.headline = _build_headline(diff)
    diff.next_action = _build_next_action(diff)
    return diff
