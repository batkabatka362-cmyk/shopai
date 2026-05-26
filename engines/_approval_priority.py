"""Approval queue priority scoring.

At empire scale (20+ stores, 12 engines/cycle, hourly), the
approval queue grows to 5,760+ actions/day. Without
prioritization, the operator drowns. Wave 60 scores each
pending action so highest-impact + highest-risk surfaces
first.

## Score components (0.0 -- 1.0 each, weighted)

  - risk_weight (0.30): destructive=1.0, modification=0.6,
    additive=0.2, unknown=0.4
  - spend_weight (0.25): action's expected $ stake from
    metrics.cost/ad_spend/discount_value. Normalized log-
    scale so $100 != $10,000.
  - roas_weight (0.20): engine's recent ROAS. Negative ROAS
    -> high priority (operator needs to review losing
    engines). Strong ROAS -> low priority (engine is
    earning, operator can trust auto-approve).
  - regression_weight (0.15): engine has fired in recent
    regression alerts -> high priority.
  - confidence_weight (0.10): engine's confidence on the
    action. Low confidence -> high priority.

Total score: 0.0 (auto-approve candidate) -- 1.0 (urgent
human review).

## API

  score_action(action) -> PriorityScore
  score_pending() -> list[PriorityScore]  (sorted desc)

PriorityScore.recommendation:
  - urgent (>= 0.7): human MUST review
  - normal (0.4 -- 0.7): standard review
  - auto-ok (< 0.4): safe for bulk-approve
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


_RISK_WEIGHTS = {
    "destructive": 1.0,
    "modification": 0.6,
    "additive": 0.2,
    "unknown": 0.4,
}


@dataclass
class PriorityScore:
    action_id: str
    engine: str
    risk_class: str
    score: float  # 0.0 -- 1.0
    components: dict[str, float]
    recommendation: str  # urgent / normal / auto-ok

    @property
    def reason(self) -> str:
        """Top-2 contributing components for operator-readable
        rationale."""
        sorted_c = sorted(
            self.components.items(),
            key=lambda kv: -kv[1],
        )[:2]
        return ", ".join(
            f"{k}={v:.2f}" for k, v in sorted_c if v > 0
        )


def _recommendation(score: float) -> str:
    if score >= 0.7:
        return "urgent"
    if score >= 0.4:
        return "normal"
    return "auto-ok"


def _spend_component(action: Any) -> float:
    """Estimated $ stake (0.0 -- 1.0 via log scale)."""
    spend = 0.0
    params = getattr(action, "params", None) or {}
    if isinstance(params, dict):
        for key in (
            "cost", "ad_spend", "discount_value",
            "amount", "budget",
        ):
            try:
                v = float(params.get(key, 0) or 0)
                spend = max(spend, v)
            except (TypeError, ValueError):
                continue
    if spend <= 0:
        return 0.0
    # log-scaled: $10 -> ~0.5, $100 -> ~0.66, $1000 -> ~0.83,
    # $10,000 -> ~1.0
    return min(1.0, math.log10(spend + 1) / 4.0)


def _roas_component(
    engine: str,
    roas_lookup: dict[str, float] | None,
) -> float:
    """Inverse-ROAS priority. Low ROAS -> high priority."""
    if roas_lookup is None:
        return 0.0
    roas = roas_lookup.get(engine)
    if roas is None:
        return 0.0  # no data -> no priority delta
    if roas >= 2.0:
        return 0.0  # strong earner -> trust
    if roas >= 1.0:
        return 0.3  # break-even -> normal
    if roas >= 0.5:
        return 0.7  # losing money -> high priority
    return 1.0  # heavily negative -> urgent


def _regression_component(
    engine: str,
    regressing_engines: set[str] | None,
) -> float:
    """Engine recently appeared in revenue regression alert."""
    if regressing_engines is None:
        return 0.0
    return 1.0 if engine in regressing_engines else 0.0


def _confidence_component(action: Any) -> float:
    """Engine's confidence on the action. Low confidence ->
    high priority."""
    conf = getattr(action, "confidence", None)
    if conf is None:
        return 0.5  # unknown -> medium
    try:
        return max(0.0, 1.0 - float(conf))
    except (TypeError, ValueError):
        return 0.5


def score_action(
    action: Any,
    *,
    roas_lookup: dict[str, float] | None = None,
    regressing_engines: set[str] | None = None,
) -> PriorityScore:
    """Score a single pending action."""
    risk = (
        getattr(action, "risk_class", None) or "unknown"
    )
    engine = getattr(action, "engine", None) or "unknown"
    action_id = str(getattr(action, "id", "?"))

    risk_w = _RISK_WEIGHTS.get(risk, 0.4)
    spend_w = _spend_component(action)
    roas_w = _roas_component(engine, roas_lookup)
    regression_w = _regression_component(
        engine, regressing_engines,
    )
    confidence_w = _confidence_component(action)

    # Weighted sum
    score = (
        risk_w * 0.30
        + spend_w * 0.25
        + roas_w * 0.20
        + regression_w * 0.15
        + confidence_w * 0.10
    )
    score = max(0.0, min(1.0, score))

    return PriorityScore(
        action_id=action_id,
        engine=engine,
        risk_class=risk,
        score=round(score, 3),
        components={
            "risk": round(risk_w, 3),
            "spend": round(spend_w, 3),
            "roas": round(roas_w, 3),
            "regression": round(regression_w, 3),
            "confidence": round(confidence_w, 3),
        },
        recommendation=_recommendation(score),
    )


def _build_roas_lookup(
    window_hours: float = 168.0,
) -> dict[str, float]:
    """ROAS map keyed by engine name."""
    try:
        from engines._roas_report import compute_roas_report
        report = compute_roas_report(window_hours=window_hours)
    except Exception:  # noqa: BLE001
        return {}
    lookup: dict[str, float] = {}
    for e in report.per_engine:
        if e.roas is not None:
            lookup[e.engine] = e.roas
    return lookup


def _build_regressing_engines() -> set[str]:
    """Engines that appeared in the latest delta's regression
    alerts."""
    try:
        from engines._attribution_delta import latest_delta
        delta = latest_delta()
        if delta is None:
            return set()
        return {
            a.name for a in delta.alerts
            if a.scope == "engine"
        }
    except Exception:  # noqa: BLE001
        return set()


def score_pending(
    actions: list[Any] | None = None,
    *,
    use_context: bool = True,
) -> list[PriorityScore]:
    """Score pending actions, sorted desc by score.

    Args:
        actions: List of approval-queue actions. If None,
            pulls list_pending() from get_approval_queue().
        use_context: When True, pulls ROAS + regression
            context once + threads it through. Disable for
            unit tests.

    Returns:
        List of PriorityScore sorted by score desc.
    """
    if actions is None:
        try:
            from core.approval.queue import get_approval_queue
            actions = (
                get_approval_queue().list_pending(limit=10_000)
                or []
            )
        except Exception:  # noqa: BLE001
            actions = []

    roas_lookup = _build_roas_lookup() if use_context else None
    regressing = (
        _build_regressing_engines() if use_context else None
    )

    scored = [
        score_action(
            a,
            roas_lookup=roas_lookup,
            regressing_engines=regressing,
        )
        for a in actions
    ]
    scored.sort(key=lambda s: -s.score)
    return scored
