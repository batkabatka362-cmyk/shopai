"""Adapter health score — Option W.

Options R through V each answered a single resilience question:
is the adapter tripped (breaker)? is it slow (SLA)? has it spent
too much (budget)? is it over quota (rate limit)? is the last call
still fresh (idempotency)? Each telemetry source renders cleanly on
its own panel, but an operator asking "which adapter is actually
having a bad day?" has to eyeball five panels and mentally OR them.

This module answers that question directly. It folds the existing
telemetry streams into a single composite score per adapter:

    score = Σ weight_i · component_i

with components in [0.0, 1.0] so a 0.92 reads the same as an A on
a report card. Weights are tunable but the defaults reflect the
actual severity order we've seen in practice: a tripped breaker
hurts more than a near-quota rate limit, and latency SLA violations
are the single best early signal of vendor trouble.

Design notes:

* **Read-only** — this module never calls a vendor, mutates state,
  or influences routing. It's a rollup for humans (and for the
  dashboard) built from telemetry that's already there. Routing
  integration can come later; shipping the summary first is cheap
  and lets us validate the scoring shape before wiring it into
  decisions.
* **Telemetry-agnostic** — the scorer takes plain dicts/lists as
  inputs, not singletons, so tests can feed synthetic data without
  monkeypatching. The dashboard collector is the only place that
  reaches into the real telemetry modules.
* **Missing-signal-friendly** — an adapter with no SLA budget or no
  rate-limit policy registered gets that component skipped instead
  of scored zero. The weights re-normalize across the components
  we actually have; a brand-new adapter with no data reads "unknown",
  not "unhealthy".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Grade bands ────────────────────────────────────────────────

#: Score ≥ this reads as "healthy" (green). Below it but above
#: ``DEGRADED_CUTOFF`` is "degraded" (amber); below that is
#: "unhealthy" (red). Tuned so that one breached component drops
#: the adapter into degraded, two drop it into unhealthy.
HEALTHY_CUTOFF = 0.80
DEGRADED_CUTOFF = 0.50

#: When every signal is "missing" (adapter has no policies, no
#: samples), the composite score is undefined. We report ``unknown``
#: instead of defaulting to zero so a fresh process doesn't look
#: like a widespread outage.
UNKNOWN_GRADE = "unknown"


# ── Default component weights ─────────────────────────────────

#: Sum to 1.0. Breaker weight is highest because an open breaker
#: means the adapter is actively failing; SLA is next because
#: latency breaches are the earliest reliable warning. Rate limit
#: is a soft cap (near-quota is not failure), so it carries the
#: least weight.
DEFAULT_WEIGHTS: dict[str, float] = {
    "breaker":    0.35,
    "sla":        0.30,
    "retry":      0.20,
    "rate_limit": 0.15,
}


# ── Component + overall result ─────────────────────────────────


@dataclass
class HealthComponent:
    """One dimension of an adapter's health."""

    name: str
    score: float
    detail: str
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "detail": self.detail,
            "available": self.available,
        }


@dataclass
class AdapterHealthScore:
    """Composite health score for a single adapter."""

    adapter: str
    score: float
    grade: str
    components: list[HealthComponent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "score": round(self.score, 4),
            "grade": self.grade,
            "components": [c.to_dict() for c in self.components],
        }


# ── Component scorers ──────────────────────────────────────────


def _sla_component(sla_row: dict[str, Any] | None) -> HealthComponent:
    """Map an ``SLAStatus.to_dict()`` row to a 0-1 score.

    ``evaluated=False`` means the adapter is still warming up
    (below the min-samples threshold). We mark the component as
    unavailable so the weight is redistributed rather than
    pretending everything is fine.
    """
    if not sla_row:
        return HealthComponent(
            name="sla", score=0.0, detail="no budget registered",
            available=False,
        )
    if not sla_row.get("evaluated", False):
        samples = int(sla_row.get("samples", 0))
        return HealthComponent(
            name="sla", score=0.0,
            detail=f"warming up ({samples} samples)",
            available=False,
        )
    grade = sla_row.get("grade", "ok")
    if grade == "breach":
        violations = sla_row.get("violations") or []
        detail = "; ".join(violations)[:120] or "breach"
        return HealthComponent(name="sla", score=0.0, detail=detail)
    if grade == "warn":
        warnings = sla_row.get("warnings") or []
        detail = "; ".join(warnings)[:120] or "warning"
        return HealthComponent(name="sla", score=0.5, detail=detail)
    return HealthComponent(
        name="sla", score=1.0,
        detail=(
            f"p95 {sla_row.get('p95_ms', 0):.0f}ms · "
            f"{float(sla_row.get('success_rate', 1.0)):.1%} ok"
        ),
    )


def _breaker_component(br: dict[str, Any] | None) -> HealthComponent:
    """Map a breaker snapshot dict to a 0-1 score.

    An open breaker is the worst signal we track — the adapter is
    actively refusing traffic. Half-open is mid-recovery (we've
    started probing again). Closed is the norm.
    """
    if not br:
        return HealthComponent(
            name="breaker", score=0.0, detail="no breaker state",
            available=False,
        )
    state = br.get("state", "closed")
    trips = int(br.get("trips", 0))
    if state == "open":
        return HealthComponent(
            name="breaker", score=0.0,
            detail=f"OPEN — {trips} trip(s)",
        )
    if state == "half_open":
        return HealthComponent(
            name="breaker", score=0.4,
            detail=f"half-open — probing recovery ({trips} trips)",
        )
    cf = int(br.get("consecutive_failures", 0))
    thresh = int(br.get("fail_threshold", 0))
    if thresh > 0 and cf >= thresh * 0.5:
        # Getting close to the trip threshold — not yet tripped,
        # but don't score full marks.
        return HealthComponent(
            name="breaker", score=0.7,
            detail=f"closed — {cf}/{thresh} failures queued",
        )
    return HealthComponent(
        name="breaker", score=1.0,
        detail=f"closed ({trips} historical trip(s))",
    )


def _rate_limit_component(rl_row: dict[str, Any] | None) -> HealthComponent:
    """Map a rate-limiter row to a 0-1 score."""
    if not rl_row:
        return HealthComponent(
            name="rate_limit", score=0.0, detail="no policy registered",
            available=False,
        )
    status = rl_row.get("status", "idle")
    if status == "throttled":
        return HealthComponent(
            name="rate_limit", score=0.0, detail="quota saturated",
        )
    if status == "near":
        pct_m = rl_row.get("minute_used_pct") or 0.0
        pct_h = rl_row.get("hour_used_pct") or 0.0
        pct = max(pct_m, pct_h)
        return HealthComponent(
            name="rate_limit", score=0.5,
            detail=f"{pct:.0%} of window used",
        )
    # "ok" or "idle" both read as healthy — idle just means no
    # calls have happened, which is not a negative signal.
    return HealthComponent(
        name="rate_limit", score=1.0, detail=status,
    )


def _retry_component(row: dict[str, Any] | None) -> HealthComponent:
    """Map a ``RetryTelemetry`` per-adapter row to a 0-1 score.

    We want the score to fall smoothly from 1.0 at "never failed"
    down to 0.0 as the give-up rate climbs. A give-up means the
    retry policy exhausted every attempt without success — that
    is much more informative than a raw success_rate (a call that
    succeeded on retry #3 still counts as a success).
    """
    if not row:
        return HealthComponent(
            name="retry", score=0.0, detail="no calls recorded",
            available=False,
        )
    calls = int(row.get("calls", 0))
    if calls < 5:
        # Not enough signal yet. Mark unavailable so the weight
        # doesn't drag the composite down on a fresh process.
        return HealthComponent(
            name="retry", score=0.0,
            detail=f"only {calls} calls — insufficient signal",
            available=False,
        )
    giveups = int(row.get("giveups", 0))
    retries = int(row.get("retries", 0))
    giveup_rate = giveups / calls if calls > 0 else 0.0
    retry_rate = retries / calls if calls > 0 else 0.0
    # 5% give-up rate → score 0.5. 10%+ → 0.0.
    base = max(0.0, 1.0 - giveup_rate * 10.0)
    # A high retry rate without give-ups still points to flaky
    # vendor behaviour — trim up to 30% off for that.
    base -= min(0.3, retry_rate * 0.5)
    score = max(0.0, min(1.0, base))
    return HealthComponent(
        name="retry", score=score,
        detail=(
            f"{calls} calls · {retry_rate:.1%} retried · "
            f"{giveup_rate:.1%} gave up"
        ),
    )


# ── Scorer ────────────────────────────────────────────────────


class HealthScorer:
    """Combine the four component streams into a composite score.

    Weights must sum to 1.0 ± 1e-6. A test-style override like
    ``HealthScorer(weights={"breaker": 1.0})`` works when you want
    a single-source score for debugging.
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        *,
        healthy_cutoff: float = HEALTHY_CUTOFF,
        degraded_cutoff: float = DEGRADED_CUTOFF,
    ) -> None:
        w = dict(weights if weights is not None else DEFAULT_WEIGHTS)
        total = sum(w.values())
        if not (0.999 <= total <= 1.001):
            raise ValueError(
                f"weights must sum to 1.0 (got {total:.4f})",
            )
        for name, val in w.items():
            if val < 0:
                raise ValueError(f"weight for {name!r} must be >= 0")
        if not (0.0 < degraded_cutoff < healthy_cutoff <= 1.0):
            raise ValueError(
                "need 0 < degraded_cutoff < healthy_cutoff <= 1",
            )
        self._weights = w
        self._healthy_cutoff = healthy_cutoff
        self._degraded_cutoff = degraded_cutoff

    # ── grading ──────────────────────────────────────────

    def _grade(self, score: float, any_available: bool) -> str:
        if not any_available:
            return UNKNOWN_GRADE
        if score >= self._healthy_cutoff:
            return "healthy"
        if score >= self._degraded_cutoff:
            return "degraded"
        return "unhealthy"

    # ── single-adapter score ─────────────────────────────

    def score(
        self,
        adapter: str,
        *,
        sla: dict[str, Any] | None = None,
        breaker: dict[str, Any] | None = None,
        rate_limit: dict[str, Any] | None = None,
        retry: dict[str, Any] | None = None,
    ) -> AdapterHealthScore:
        """Build one ``AdapterHealthScore`` from four telemetry rows."""
        components = [
            _breaker_component(breaker),
            _sla_component(sla),
            _retry_component(retry),
            _rate_limit_component(rate_limit),
        ]
        # Re-normalize weights across available components only so a
        # missing signal doesn't drag the composite to zero.
        total_weight = 0.0
        weighted = 0.0
        for comp in components:
            if not comp.available:
                continue
            w = self._weights.get(comp.name, 0.0)
            total_weight += w
            weighted += w * comp.score
        any_available = total_weight > 0.0
        score = (weighted / total_weight) if any_available else 0.0
        return AdapterHealthScore(
            adapter=adapter,
            score=score,
            grade=self._grade(score, any_available),
            components=components,
        )

    # ── all-adapter rollup ───────────────────────────────

    def score_all(
        self,
        *,
        sla_rows: list[dict[str, Any]] | None = None,
        breakers: list[dict[str, Any]] | None = None,
        rate_rows: list[dict[str, Any]] | None = None,
        retry_per_adapter: list[dict[str, Any]] | None = None,
    ) -> list[AdapterHealthScore]:
        """Score every adapter that appears in any telemetry stream.

        The union of adapter names is computed first so an adapter
        with partial data (e.g. breaker registered but no SLA
        budget) still gets a row. Output is sorted worst-first —
        unhealthy, then degraded, then healthy, then unknown —
        which matches the "what's on fire" rhythm the Reliability
        tab already uses for SLA and rate-limit panels.
        """
        by_name: dict[str, dict[str, Any]] = {
            "sla": {}, "breaker": {}, "rate": {}, "retry": {},
        }
        for row in sla_rows or []:
            name = row.get("adapter")
            if name:
                by_name["sla"][name] = row
        for row in breakers or []:
            name = row.get("adapter") or row.get("name")
            if name:
                by_name["breaker"][name] = row
        for row in rate_rows or []:
            name = row.get("adapter")
            if name:
                by_name["rate"][name] = row
        for row in retry_per_adapter or []:
            name = row.get("adapter")
            if name:
                by_name["retry"][name] = row

        adapters = (
            set(by_name["sla"]) | set(by_name["breaker"])
            | set(by_name["rate"]) | set(by_name["retry"])
        )
        results = [
            self.score(
                name,
                sla=by_name["sla"].get(name),
                breaker=by_name["breaker"].get(name),
                rate_limit=by_name["rate"].get(name),
                retry=by_name["retry"].get(name),
            )
            for name in adapters
        ]
        grade_rank = {
            "unhealthy": 0, "degraded": 1, "healthy": 2, UNKNOWN_GRADE: 3,
        }
        results.sort(key=lambda r: (grade_rank.get(r.grade, 4), -r.score, r.adapter))
        return results

    # ── rollup totals ────────────────────────────────────

    @staticmethod
    def totals(
        rows: list[AdapterHealthScore],
    ) -> dict[str, int]:
        """Return ``{"unhealthy":n,"degraded":n,"healthy":n,"unknown":n}``."""
        out = {"unhealthy": 0, "degraded": 0, "healthy": 0, UNKNOWN_GRADE: 0}
        for r in rows:
            out[r.grade] = out.get(r.grade, 0) + 1
        return out
