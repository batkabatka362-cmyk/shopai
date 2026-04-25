"""Anticipation engine — predict likely next events.

Reactive intelligence responds when something happens. Anticipatory
intelligence stages the reaction *before* it does. Examples the
store should anticipate:

  • Support ticket from a customer whose order was flagged
    delayed-by-carrier — proactively email an update.
  • A launch will likely cross its ROAS kill-threshold in the next
    48 h at current trajectory — propose the kill now for owner
    approval.
  • Inventory will run out inside 3 days at current conversion
    rate — queue a reorder.
  • A rule that has fired 30×/month will fire again this week —
    pre-cache its dependencies.

AnticipationEngine emits a ranked list of ``Prediction`` entries
each cycle. Two light prediction classes:

  1. Trend extrapolation — fit a linear regression to the last K
     data points of a signal and project forward T steps. If the
     projection crosses a threshold, emit a prediction.
  2. Poisson rate — count events per signature per day; project
     P(event in next Δt) via a rate estimate + exponential.

Both are cheap (O(K) per signal, no LLM) and produce a confidence
score so the owner digest can filter out low-probability noise.

Used by: oracle digest ("likely this week: …"), daemon proactive
queue ("pre-act on high-probability predictions"), dual-process
router (anticipated events escalate to System 2 if critical).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Prediction:
    subject: str
    kind: str                      # "threshold_cross" | "event_rate"
    text: str                      # human-readable
    confidence: float              # 0-1
    projected_at: float | None = None      # unix ts
    suggested_action: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "kind": self.kind,
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "projected_at": self.projected_at,
            "suggested_action": self.suggested_action,
            "detail": self.detail,
        }


# ── Trend extrapolation ─────────────────────────────────────

def linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Return (slope, intercept). Zero slope if insufficient data."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0, my
    slope = num / den
    intercept = my - slope * mx
    return slope, intercept


def extrapolate(
    subject: str,
    xs: list[float],
    ys: list[float],
    threshold: float,
    direction: str = "below",
    horizon_steps: int = 10,
    suggested_action: str = "",
) -> Prediction | None:
    """If the linear projection of ``ys`` crosses ``threshold`` within
    the next ``horizon_steps``, emit a Prediction.

    ``direction`` ∈ {"below", "above"}.
    """
    if len(xs) != len(ys) or len(ys) < 3:
        return None
    slope, intercept = linear_fit(xs, ys)
    # Find the x at which y = threshold (if any)
    if slope == 0:
        return None
    x_cross = (threshold - intercept) / slope
    # Must be in the future and within horizon
    x_last = xs[-1]
    if x_cross <= x_last:
        return None
    if x_cross - x_last > horizon_steps:
        return None
    # Direction check
    if direction == "below" and slope > 0:
        return None
    if direction == "above" and slope < 0:
        return None
    # Confidence: steeper slope → higher confidence, but bounded
    # by how close the points are to the line (inverse residual).
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    var = sum(r * r for r in residuals) / max(1, len(residuals) - 1)
    sigma = math.sqrt(var)
    slope_strength = min(1.0, abs(slope) / max(1e-6, sigma))
    closeness = max(0.0, 1.0 - (x_cross - x_last) / horizon_steps)
    confidence = round(min(1.0,
                            0.5 * slope_strength + 0.5 * closeness), 3)
    steps_left = x_cross - x_last
    text = (f"{subject} projected to cross {threshold:.2f} "
            f"in {steps_left:.1f} steps "
            f"(slope {slope:+.3f})")
    return Prediction(
        subject=subject,
        kind="threshold_cross",
        text=text,
        confidence=confidence,
        projected_at=time.time() + steps_left * 86_400,
        suggested_action=suggested_action,
        detail={
            "slope": round(slope, 4),
            "intercept": round(intercept, 4),
            "threshold": threshold,
            "steps_left": round(steps_left, 3),
            "direction": direction,
        },
    )


# ── Poisson rate ────────────────────────────────────────────

def event_rate_probability(
    subject: str,
    event_timestamps: list[float],
    horizon_s: float = 86_400,
    now: float | None = None,
    suggested_action: str = "",
) -> Prediction | None:
    """Given a list of past event timestamps, estimate P(≥1 event in
    the next ``horizon_s``) via Poisson rate from the most recent
    window.

    Only emits a prediction if the probability is meaningful
    (> 0.3) — low-probability events don't need a proactive
    prompt."""
    if not event_timestamps:
        return None
    now = now or time.time()
    # Consider the last 30 days' events for the rate estimate.
    window = 30 * 86_400
    recent = [t for t in event_timestamps if now - t <= window]
    if len(recent) < 2:
        return None
    rate = len(recent) / window         # events per second
    mu = rate * horizon_s
    p_at_least_one = 1.0 - math.exp(-mu)
    if p_at_least_one < 0.3:
        return None
    confidence = round(p_at_least_one, 3)
    text = (f"P(≥1 {subject} in next {int(horizon_s/3600)}h) "
            f"= {p_at_least_one:.0%}")
    return Prediction(
        subject=subject,
        kind="event_rate",
        text=text,
        confidence=confidence,
        projected_at=now + horizon_s,
        suggested_action=suggested_action,
        detail={
            "rate_per_day": round(rate * 86_400, 3),
            "recent_count": len(recent),
            "horizon_s": horizon_s,
        },
    )


# ── Composer ────────────────────────────────────────────────

def compose(
    predictions: Iterable[Prediction | None],
    min_confidence: float = 0.3,
    top_k: int = 10,
) -> list[Prediction]:
    """Filter None + low-confidence and return the top-K."""
    pool = [p for p in predictions if p is not None
             and p.confidence >= min_confidence]
    pool.sort(key=lambda p: -p.confidence)
    return pool[:top_k]
