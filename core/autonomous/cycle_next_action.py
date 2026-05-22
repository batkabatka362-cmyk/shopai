"""Cycle next-action recommender.

After an autonomous-cycle run, this module looks at the
cycle's outcomes + ambient state (alerts, candidates) and
returns a concrete suggested next move for the operator.

Same shape as launch_audit's next_action recommendation:
operators get a CLI-ready command they can run. The
recommendation is deterministic + rule-based (no LLM); the
rules encode the decision tree we'd otherwise document in
runbooks.

Priority order (first match wins):
  1. Cycle errored on any phase -> investigate logs first
  2. Bridge thrashing -> manual demote-clear required
  3. Cycle alerts present -> inspect with --alerts
  4. Substrate has release candidates -> approve them
  5. Substrate has demote candidates but bridge gate off
     -> consider enabling
  6. ADVANCE refused all -> reliability gate too tight
  7. ADVANCE advanced stores -> measure outcomes
  8. Healthy + nothing to do -> all clear
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NextAction:
    """One recommended next move. ``priority`` is a short
    string from a fixed set; ``detail`` explains why; ``cmd``
    is a CLI-ready command operator can copy-paste."""

    priority: str
    detail: str
    cmd: str = ""


def recommend(summary: dict[str, Any]) -> NextAction:
    """Inspect a cycle summary + ambient state; return one
    suggested next action.

    Args:
        summary: The dict produced by ``_cmd_autonomous_cycle``
            containing ``advance``, ``defend``, ``correlate``,
            and ``executed`` keys.

    Returns:
        A NextAction. Never raises -- subsystem-loading
        failures produce a generic 'investigate' suggestion.
    """
    if not isinstance(summary, dict):
        return NextAction(
            priority="investigate",
            detail=(
                "Cycle summary was not a dict -- something "
                "is very wrong."
            ),
            cmd="shopai autonomous-cycle --history",
        )

    # Rule 1: errored phase -> investigate
    for phase_key in ("advance", "defend", "correlate"):
        phase = summary.get(phase_key) or {}
        if isinstance(phase, dict) and phase.get("error"):
            return NextAction(
                priority="investigate_error",
                detail=(
                    f"{phase_key.upper()} phase errored: "
                    f"{phase['error']}"
                ),
                cmd="shopai autonomous-cycle --history",
            )

    defend = summary.get("defend") or {}
    advance = summary.get("advance") or {}

    # Rule 2: bridge thrashing -- needs operator intervention
    # (we look up history here, not from summary, because
    # thrashing is a longitudinal signal)
    try:
        from core.capability_planner import (
            auto_demote_history as _adh,
        )
        thrashing = _adh.find_thrashing(
            window_seconds=86400 * 14,
        )
        if thrashing:
            names = ", ".join(
                t["capability"] for t in thrashing[:3]
            )
            return NextAction(
                priority="clear_thrashing",
                detail=(
                    f"{len(thrashing)} capability/-ies "
                    f"thrashing: {names}. Investigate "
                    "root cause, then clear the override."
                ),
                cmd=(
                    f"shopai capabilities clear-override "
                    f"{thrashing[0]['capability']}"
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "next_action: thrashing lookup raised: %s",
            exc,
        )

    # Rule 3: cycle alerts -- low_advance_rate /
    # substrate_shrinking surface here. Promote severity
    # when consecutive_days streak is large.
    try:
        from core.autonomous import cycle_alerts as _ca
        alerts = _ca.compute_cycle_alerts(
            window_seconds=86400 * 7,
        )
        # Skip cycle_silent + stale_cycle (this run JUST
        # ran, those don't apply mid-cycle).
        relevant = [
            a for a in alerts
            if a.kind not in (
                "cycle_silent", "stale_cycle",
            )
        ]
        if relevant:
            # Lookup persistent streak so a 3-day pattern
            # gets the stronger recommendation.
            streak_per_kind: dict[str, int] = {}
            try:
                from core.autonomous import (
                    cycle_alert_history as _cah,
                )
                streak_per_kind = (
                    _cah.consecutive_days_per_kind(
                        window_seconds=86400 * 14,
                    )
                )
            except Exception:
                streak_per_kind = {}
            max_streak = max(
                (
                    streak_per_kind.get(a.kind, 0)
                    for a in relevant
                ),
                default=0,
            )
            kinds = ", ".join(a.kind for a in relevant)
            if max_streak >= 3:
                # Persistent pattern -- stronger phrasing +
                # specific suggestion based on the dominant
                # kind.
                dominant = max(
                    relevant,
                    key=lambda a: streak_per_kind.get(
                        a.kind, 0,
                    ),
                )
                if dominant.kind == "low_advance_rate":
                    return NextAction(
                        priority=(
                            "persistent_low_advance_rate"
                        ),
                        detail=(
                            f"low_advance_rate has fired "
                            f"on {max_streak} distinct "
                            "days. Reliability gate may "
                            "be permanently too tight -- "
                            "consider lowering "
                            "SHOPAI_AUTO_EXECUTE_THRESHOLD "
                            "or running without "
                            "--require-reliable."
                        ),
                        cmd=(
                            "shopai fleet-plan --execute "
                            "--yes"
                        ),
                    )
                if dominant.kind == "substrate_shrinking":
                    return NextAction(
                        priority=(
                            "persistent_substrate_shrinking"
                        ),
                        detail=(
                            f"substrate_shrinking has "
                            f"fired on {max_streak} "
                            "distinct days. Bridge is "
                            "over-tight OR the substrate "
                            "needs structural review."
                        ),
                        cmd=(
                            "shopai capabilities "
                            "auto-demote-history "
                            "--thrashing"
                        ),
                    )
                # Generic persistent-pattern fallback
                return NextAction(
                    priority="address_persistent_alerts",
                    detail=(
                        f"Cycle alerts persistent "
                        f"({max_streak}d streak): "
                        f"{kinds}. Address root cause."
                    ),
                    cmd="shopai autonomous-cycle --alerts",
                )
            return NextAction(
                priority="address_cycle_alerts",
                detail=(
                    f"Cycle alerts active: {kinds}. "
                    "Inspect detail + adjust thresholds "
                    "or operator review."
                ),
                cmd="shopai autonomous-cycle --alerts",
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "next_action: alerts lookup raised: %s", exc,
        )

    # Rule 4: release candidates ready
    n_released = int(defend.get("released", 0) or 0)
    n_recovered = int(
        defend.get("recovered_candidates", 0) or 0,
    )
    if n_recovered > 0 and n_released == 0:
        # Recovered capabilities exist but weren't released
        # this run (either dry-run or no --yes). Suggest the
        # follow-up.
        return NextAction(
            priority="apply_releases",
            detail=(
                f"{n_recovered} capability/-ies recovered "
                "from demote. Run with --yes to release."
            ),
            cmd="shopai capabilities auto-demote-release-candidates --yes",
        )

    # Rule 5: actionable demote candidates but bridge OFF
    n_actionable = int(defend.get("actionable", 0) or 0)
    gate_on = bool(defend.get("gate_enabled", False))
    if n_actionable > 0 and not gate_on:
        return NextAction(
            priority="enable_bridge",
            detail=(
                f"{n_actionable} capability/-ies would be "
                "auto-demoted if the bridge were enabled. "
                "Review then opt in via "
                "SHOPAI_AUTO_DEMOTE_DEGRADED=1."
            ),
            cmd="shopai capabilities auto-demote-degraded",
        )

    # Rule 6: ADVANCE refused everything -> reliability too tight
    refused = int(advance.get("refused_reliability", 0) or 0)
    advanced = int(advance.get("executed_ok", 0) or 0)
    stores = int(advance.get("stores_processed", 0) or 0)
    if stores > 0 and refused > 0 and advanced == 0:
        return NextAction(
            priority="relax_reliability",
            detail=(
                f"ADVANCE refused all {refused} store(s) "
                "on reliability. Threshold too tight, or "
                "no historical success yet (run "
                "without --require-reliable for first "
                "passes)."
            ),
            cmd="shopai fleet-plan --execute --yes",
        )

    # Rule 7: stores advanced -> wait + measure
    if advanced > 0:
        return NextAction(
            priority="measure_outcomes",
            detail=(
                f"ADVANCE executed on {advanced} store(s). "
                "Wait 24h+ for measurement window, then "
                "auto-correlate."
            ),
            cmd="shopai plan --auto-correlate",
        )

    # Rule 8: healthy + nothing to do
    return NextAction(
        priority="all_clear",
        detail=(
            "Cycle ran cleanly with no pending substrate "
            "actions. Substrate healthy."
        ),
        cmd="shopai status",
    )
