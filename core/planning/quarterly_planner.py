"""Quarterly planner — long-horizon goal → weekly milestones (L4).

Sprint 3 S3-12 (P3). ``goal_decomposer`` (core/brain) turns a
*single-cycle* goal into a DAG of sub-goals. That's right for
"launch this product in 15 min". It's the wrong shape for "grow
this store to $5k/month by end of Q3" — horizons of weeks/months
need *milestones*, not sub-tasks, and they need a check-in loop
that compares current state against the schedule.

This module provides:

  * ``QuarterlyGoal``    — owner's target (revenue, SKU count, ROAS,
                           deadline). Pure data.
  * ``Milestone``        — a dated checkpoint with expected cumulative
                           revenue / SKUs-live / ROAS. Emitted by
                           ``build_quarterly_plan``.
  * ``QuarterlyPlan``    — list of milestones + metadata.
  * ``check_in(plan, state)`` — compares the current KPI snapshot
                           against the most recent past milestone and
                           returns a ``ProgressReport`` with a verdict
                           (ahead / on-track / behind / at-risk).

Design choices (auditable, owner-facing):

  * Weekly cadence by default. Too granular for a quarter-scale
    goal is noisy; monthly is too coarse for course-correction.
  * Linear revenue ramp unless the owner supplies a different
    ``ramp_curve`` (linear | front_loaded | back_loaded). The
    assumption stays visible to the owner in every milestone.
  * At-risk = behind by ≥ 25% cumulative revenue target OR ≥ two
    milestones missed. Threshold configurable.
  * Verdict is deterministic from (plan, state, now): same inputs
    → same answer. No LLM, no RNG.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


_WEEK_S = 7 * 24 * 3600.0
_DEFAULT_RAMP = "linear"
_VALID_RAMPS = ("linear", "front_loaded", "back_loaded")

_DEFAULT_AT_RISK_SHORTFALL = 0.25
_DEFAULT_AT_RISK_MISSED = 2


@dataclass
class QuarterlyGoal:
    """Owner's long-horizon target. Deadline-bound."""

    revenue_target_monthly_usd: float      # $/month at deadline
    deadline_ts: float                     # UTC epoch seconds
    start_ts: float = 0.0                  # default = now
    sku_target: int = 20                   # SKUs live at deadline
    roas_target: float = 1.8               # portfolio ROAS floor
    ramp_curve: str = _DEFAULT_RAMP
    niche: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.revenue_target_monthly_usd <= 0:
            raise ValueError(
                "revenue_target_monthly_usd must be > 0",
            )
        if self.sku_target < 1:
            raise ValueError("sku_target must be ≥ 1")
        if self.roas_target <= 0:
            raise ValueError("roas_target must be > 0")
        if self.ramp_curve not in _VALID_RAMPS:
            raise ValueError(
                f"ramp_curve must be one of {_VALID_RAMPS}",
            )
        if self.start_ts <= 0:
            self.start_ts = time.time()
        if self.deadline_ts <= self.start_ts:
            raise ValueError(
                "deadline_ts must be after start_ts",
            )

    def duration_s(self) -> float:
        return float(self.deadline_ts - self.start_ts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "revenue_target_monthly_usd": round(
                self.revenue_target_monthly_usd, 2,
            ),
            "deadline_ts": self.deadline_ts,
            "start_ts": self.start_ts,
            "sku_target": self.sku_target,
            "roas_target": round(self.roas_target, 4),
            "ramp_curve": self.ramp_curve,
            "niche": self.niche,
            "note": self.note,
        }


@dataclass
class Milestone:
    week_index: int                         # 1-based
    target_ts: float                        # UTC epoch
    cumulative_revenue_usd: float           # owner-facing total
    skus_live_target: int
    roas_target: float
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "week_index": self.week_index,
            "target_ts": self.target_ts,
            "cumulative_revenue_usd": round(
                self.cumulative_revenue_usd, 2,
            ),
            "skus_live_target": self.skus_live_target,
            "roas_target": round(self.roas_target, 4),
            "note": self.note,
        }


@dataclass
class QuarterlyPlan:
    goal: QuarterlyGoal
    milestones: tuple[Milestone, ...]
    cadence_s: float = _WEEK_S

    def active_milestone(
        self, *, now_ts: float,
    ) -> Milestone | None:
        """Most recent milestone whose target_ts has passed.
        Returns None when no milestone is due yet."""
        due = [
            m for m in self.milestones
            if m.target_ts <= now_ts
        ]
        return due[-1] if due else None

    def next_milestone(
        self, *, now_ts: float,
    ) -> Milestone | None:
        upcoming = [
            m for m in self.milestones
            if m.target_ts > now_ts
        ]
        return upcoming[0] if upcoming else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal.as_dict(),
            "cadence_s": self.cadence_s,
            "milestones": [
                m.as_dict() for m in self.milestones
            ],
        }


@dataclass
class ProgressReport:
    verdict: str                # ahead | on_track | behind | at_risk
    ratio: float                # cumulative_actual / cumulative_target
    missed_milestones: int
    current_milestone: Milestone | None
    next_milestone: Milestone | None
    recommendation: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "ratio": round(self.ratio, 4),
            "missed_milestones": self.missed_milestones,
            "current_milestone": (
                self.current_milestone.as_dict()
                if self.current_milestone else None
            ),
            "next_milestone": (
                self.next_milestone.as_dict()
                if self.next_milestone else None
            ),
            "recommendation": self.recommendation,
            "reason": self.reason,
        }


# ── Ramp curves ────────────────────────────────────────────

def _ramp_fraction(curve: str, progress: float) -> float:
    """Return the cumulative revenue fraction at ``progress`` in
    [0, 1] through the plan. All curves hit 0 at 0 and 1 at 1."""
    p = max(0.0, min(1.0, float(progress)))
    if curve == "front_loaded":
        # Square-root — ramps fast early, plateaus late
        return math.sqrt(p)
    if curve == "back_loaded":
        # Square — ramps slow early, sprints late
        return p * p
    # linear (default)
    return p


# ── Builder ────────────────────────────────────────────────


def build_quarterly_plan(
    goal: QuarterlyGoal,
    *,
    cadence_s: float = _WEEK_S,
) -> QuarterlyPlan:
    """Decompose a quarterly goal into weekly milestones."""
    if cadence_s <= 0:
        raise ValueError("cadence_s must be > 0")
    duration = goal.duration_s()
    if duration <= 0:
        raise ValueError("goal duration must be > 0")
    total_weeks = max(1, int(math.ceil(duration / cadence_s)))
    # End-state monthly target → total revenue across all weeks by
    # integrating the ramp. Scale so the FINAL milestone equals
    # goal.revenue_target_monthly_usd. We treat the monthly figure
    # as the run-rate at deadline, not total accumulation; the
    # cumulative series then reflects "what you'd see by week N"
    # if the store hit that run-rate at the end.
    cumulative_target_at_end = (
        goal.revenue_target_monthly_usd
        * (duration / (30.0 * 24 * 3600.0))
    )
    milestones: list[Milestone] = []
    for i in range(1, total_weeks + 1):
        progress = i / total_weeks
        frac = _ramp_fraction(goal.ramp_curve, progress)
        cum_revenue = cumulative_target_at_end * frac
        sku_target = max(
            1, int(round(goal.sku_target * frac)),
        )
        roas_target = goal.roas_target
        target_ts = goal.start_ts + i * cadence_s
        note = (
            f"week {i}/{total_weeks} · "
            f"{goal.ramp_curve} ramp"
        )
        milestones.append(Milestone(
            week_index=i,
            target_ts=target_ts,
            cumulative_revenue_usd=cum_revenue,
            skus_live_target=sku_target,
            roas_target=roas_target,
            note=note,
        ))
    return QuarterlyPlan(
        goal=goal,
        milestones=tuple(milestones),
        cadence_s=float(cadence_s),
    )


# ── Check-in ───────────────────────────────────────────────


def check_in(
    plan: QuarterlyPlan,
    *,
    current_revenue_usd: float,
    current_skus_live: int = 0,
    current_roas: float = 0.0,
    now_ts: float | None = None,
    at_risk_shortfall: float = _DEFAULT_AT_RISK_SHORTFALL,
    at_risk_missed: int = _DEFAULT_AT_RISK_MISSED,
    ahead_margin: float = 0.10,
) -> ProgressReport:
    """Compare the current KPI snapshot against the plan."""
    now_ts = (
        float(now_ts)
        if now_ts is not None else time.time()
    )
    current = plan.active_milestone(now_ts=now_ts)
    upcoming = plan.next_milestone(now_ts=now_ts)
    if current is None:
        # Plan hasn't started yet
        return ProgressReport(
            verdict="on_track",
            ratio=0.0,
            missed_milestones=0,
            current_milestone=None,
            next_milestone=upcoming,
            recommendation=(
                "Plan not yet started — no check-in needed."
            ),
            reason="no milestone due",
        )
    target = current.cumulative_revenue_usd
    ratio = (
        current_revenue_usd / target if target > 0 else 0.0
    )
    # Count behind milestones (cumulative target not met at their
    # deadline). All past milestones share the same cumulative
    # denominator; we only count ones clearly missed.
    past = [
        m for m in plan.milestones
        if m.target_ts <= now_ts
    ]
    missed = sum(
        1 for m in past
        if current_revenue_usd < m.cumulative_revenue_usd
    )
    if missed >= at_risk_missed or ratio < (
        1.0 - at_risk_shortfall
    ):
        verdict = "at_risk"
        reason = (
            f"{missed} milestone(s) missed, cumulative "
            f"ratio {ratio:.0%} < "
            f"{(1 - at_risk_shortfall):.0%}"
        )
        recommendation = (
            "Pause new launches; review winning SKUs + ad "
            "ROAS; consider cutting low-ROAS campaigns via "
            "shopai risk status."
        )
    elif ratio < 1.0:
        verdict = "behind"
        reason = (
            f"cumulative revenue ${current_revenue_usd:.2f}"
            f" < target ${target:.2f} "
            f"({ratio:.0%})"
        )
        recommendation = (
            "Speed up winner discovery (shopai notify for "
            "top trends) and bump budgets on rising niches."
        )
    elif ratio > 1.0 + ahead_margin:
        verdict = "ahead"
        reason = (
            f"revenue ${current_revenue_usd:.2f} > target "
            f"${target:.2f} ({ratio:.0%})"
        )
        recommendation = (
            "On fire. Raise SKU target next quarter and "
            "scale winning budgets."
        )
    else:
        verdict = "on_track"
        reason = (
            f"revenue ${current_revenue_usd:.2f} vs "
            f"target ${target:.2f} ({ratio:.0%})"
        )
        recommendation = (
            "Keep current cadence; no change needed."
        )
    # SKU / ROAS overlays can demote from on_track → behind
    if (
        verdict in ("on_track", "ahead")
        and current.skus_live_target > 0
        and current_skus_live
        < current.skus_live_target * 0.5
    ):
        verdict = "behind"
        reason += (
            f"; SKUs live {current_skus_live} "
            f"< half target {current.skus_live_target}"
        )
        recommendation = (
            "Shipping too few SKUs. Run shopai autopilot "
            "to publish more winners."
        )
    return ProgressReport(
        verdict=verdict,
        ratio=ratio,
        missed_milestones=missed,
        current_milestone=current,
        next_milestone=upcoming,
        recommendation=recommendation,
        reason=reason,
    )
