"""Monte-Carlo pre-execution simulator.

Before committing a money-on-the-line decision (kill a launch,
scale a budget, change a price), simulate the likely outcomes by
drawing from the distribution of *past similar* launches. Gives
the brain a projected KPI + 80 % credible interval without
burning live ad spend.

Supported interventions:

  kill_launch   — stop ad spend immediately. Outcome = "saved X
                  over the next N days, foregone revenue Y".
  scale_launch  — multiply daily budget by F. Outcome = "expected
                  revenue Z, probability of ROAS > kill_threshold".
  change_price  — set target price P. Outcome = distribution over
                  CVR and AOV conditional on historical
                  (niche, price_band) neighbours.

Implementation:

  1. Pull historical launches that match the intervention's
     context (niche, price band, margin band, tone) via the
     semantic index + exact filters.
  2. Bootstrap-sample their realised ROAS / revenue / CVR with
     replacement, apply the intervention, aggregate the posterior.
  3. Return percentiles + a short narrative.

No LLM — pure numeric simulation. 1_000 trials run in a few ms.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any


_DEFAULT_TRIALS = 1000
_DEFAULT_HORIZON_DAYS = 3


@dataclass
class SimulationInput:
    intervention: str                           # kill_launch | scale_launch | change_price
    launch_id: str
    params: dict[str, Any] = field(default_factory=dict)
    # Historical sample used to bootstrap. Each row: {"roas", "cvr",
    # "aov", "revenue_usd", "days_live", "ad_budget_day"}
    history: list[dict[str, float]] = field(default_factory=list)
    horizon_days: int = _DEFAULT_HORIZON_DAYS
    trials: int = _DEFAULT_TRIALS


@dataclass
class SimulationResult:
    intervention: str
    launch_id: str
    trials: int
    kpi: str                     # "revenue_usd" | "saved_usd" | "cvr"
    mean: float
    p10: float
    p50: float
    p90: float
    p_positive: float            # fraction of trials with kpi > 0
    narrative: str = ""
    horizon_days: int = _DEFAULT_HORIZON_DAYS

    def as_dict(self) -> dict[str, Any]:
        return {
            "intervention": self.intervention,
            "launch_id": self.launch_id,
            "trials": self.trials,
            "kpi": self.kpi,
            "mean": round(self.mean, 3),
            "p10": round(self.p10, 3),
            "p50": round(self.p50, 3),
            "p90": round(self.p90, 3),
            "p_positive": round(self.p_positive, 3),
            "narrative": self.narrative,
            "horizon_days": self.horizon_days,
        }


def simulate(spec: SimulationInput) -> SimulationResult:
    """Run the Monte-Carlo simulation. Returns a neutral result when
    history is empty so callers can fall through."""
    if not spec.history:
        return _empty(spec, kpi="revenue_usd",
                      narrative="no historical neighbours — simulation neutral")

    samples = _bootstrap(spec.history, spec.trials)
    if spec.intervention == "kill_launch":
        return _sim_kill(spec, samples)
    if spec.intervention == "scale_launch":
        return _sim_scale(spec, samples)
    if spec.intervention == "change_price":
        return _sim_price(spec, samples)
    return _empty(spec, kpi="revenue_usd",
                  narrative=f"unknown intervention {spec.intervention!r}")


# ── Intervention-specific simulators ─────────────────────────

def _sim_kill(spec: SimulationInput, samples: list[dict[str, float]]) -> SimulationResult:
    """Kill immediately. Saved spend = ad_budget_day × horizon;
    foregone revenue = revenue_per_day × horizon (from the sample's
    realised run-rate)."""
    budget = float(spec.params.get("ad_budget_day") or 0)
    horizon = spec.horizon_days
    deltas = []
    for row in samples:
        revenue_per_day = row.get("revenue_usd", 0.0) / max(row.get("days_live", 1), 1)
        saved = budget * horizon
        forgone = revenue_per_day * horizon
        deltas.append(saved - forgone)
    return _summarise(
        spec, kpi="net_saved_usd", values=deltas,
        narrative_template=(
            "Killing saves ~${p50:.2f} net over {days} days "
            "(budget saved − revenue forgone). "
            "P(net positive) = {p_pos:.0%}."
        ),
    )


def _sim_scale(spec: SimulationInput, samples: list[dict[str, float]]) -> SimulationResult:
    """Scale budget by factor F. Projected revenue = ROAS × new_spend
    drawn from the history. Assumes diminishing-returns factor f (0.85
    default) so 2× budget doesn't linearly 2× revenue."""
    factor = float(spec.params.get("scale_factor") or 2.0)
    diminishing = float(spec.params.get("diminishing") or 0.85)
    budget = float(spec.params.get("ad_budget_day") or 0)
    horizon = spec.horizon_days
    values = []
    for row in samples:
        roas = row.get("roas", 0.0)
        new_spend = budget * factor * diminishing * horizon
        values.append(roas * new_spend)
    return _summarise(
        spec, kpi="projected_revenue_usd", values=values,
        narrative_template=(
            "Scaling ×{factor:.1f} projects ~${p50:.2f} revenue over "
            "{days} days (p10 ${p10:.2f}, p90 ${p90:.2f})."
        ),
        extra={"factor": factor},
    )


def _sim_price(spec: SimulationInput, samples: list[dict[str, float]]) -> SimulationResult:
    """Change price. CVR distribution is drawn from samples; revenue
    = CVR × price × expected_clicks (from history)."""
    new_price = float(spec.params.get("new_price") or 0)
    old_price = float(spec.params.get("old_price") or 0)
    horizon = spec.horizon_days
    price_ratio = new_price / old_price if old_price > 0 else 1.0
    # Empirical price-elasticity — lightly pessimistic: every +1 %
    # price cuts CVR by 0.7 %.
    elasticity = -0.7
    values = []
    for row in samples:
        cvr = row.get("cvr", 0.0)
        clicks_per_day = (
            row.get("aov", 1.0) > 0
            and row.get("revenue_usd", 0.0) / row.get("aov", 1.0)
            or 0.0
        )
        projected_cvr = max(
            0.0,
            cvr * (1 + elasticity * (price_ratio - 1.0)),
        )
        values.append(projected_cvr * new_price * clicks_per_day * horizon)
    return _summarise(
        spec, kpi="projected_revenue_usd", values=values,
        narrative_template=(
            "Changing price {old:.2f} → {new:.2f} projects ${p50:.2f} "
            "revenue over {days} days (assumed elasticity −0.7). "
            "Upside p90 ${p90:.2f}, downside p10 ${p10:.2f}."
        ),
        extra={"old": old_price, "new": new_price},
    )


# ── Helpers ─────────────────────────────────────────────────

def _bootstrap(history: list[dict[str, float]], trials: int) -> list[dict[str, float]]:
    n = len(history)
    return [history[random.randrange(n)] for _ in range(trials)]


def _summarise(
    spec: SimulationInput,
    kpi: str,
    values: list[float],
    narrative_template: str,
    extra: dict[str, Any] | None = None,
) -> SimulationResult:
    values.sort()
    mean = statistics.fmean(values) if values else 0.0
    p10 = values[int(len(values) * 0.1)] if values else 0.0
    p50 = values[int(len(values) * 0.5)] if values else 0.0
    p90 = values[int(len(values) * 0.9)] if values else 0.0
    p_pos = sum(1 for v in values if v > 0) / len(values) if values else 0.0
    ctx = {"p10": p10, "p50": p50, "p90": p90, "p_pos": p_pos,
           "days": spec.horizon_days}
    ctx.update(extra or {})
    return SimulationResult(
        intervention=spec.intervention,
        launch_id=spec.launch_id,
        trials=len(values),
        kpi=kpi, mean=mean, p10=p10, p50=p50, p90=p90,
        p_positive=p_pos,
        narrative=narrative_template.format(**ctx),
        horizon_days=spec.horizon_days,
    )


def _empty(spec: SimulationInput, kpi: str, narrative: str) -> SimulationResult:
    return SimulationResult(
        intervention=spec.intervention,
        launch_id=spec.launch_id,
        trials=0,
        kpi=kpi, mean=0.0, p10=0.0, p50=0.0, p90=0.0, p_positive=0.0,
        narrative=narrative, horizon_days=spec.horizon_days,
    )
