"""Causal graph — discover which features *cause* KPI movements.

uplift_estimator answers *"does treatment X affect outcome Y?"* for a
chosen treatment. causal_graph goes one layer higher: given a stream
of observations, *which* of many candidate features actually drive a
KPI? Correlation alone is misleading — ad_spend correlates with
revenue, but so does time_of_day; we need to isolate real drivers
from spurious confounders.

Approach — deliberately pragmatic, pure-stdlib:

  1. For each candidate feature X and each KPI Y we compute the
     Pearson correlation r(X, Y).
  2. We then compute the *partial* correlation r(X, Y | Z) for each
     other candidate Z. If |r(X, Y | Z)| drops by > ``shrinkage``
     when we condition on Z, Z is flagged as a likely confounder.
  3. A feature survives as a "causal candidate" when it has |r| ≥
     ``min_correlation`` AND its partial correlation survives
     conditioning on every other candidate.

The output is a ``CausalReport`` per KPI listing each feature's
  - raw correlation
  - surviving partial correlation
  - confounders it failed against
  - status: "driver" / "confounded" / "noise"

This is NOT a causal graph discovery algorithm in the formal sense
(no PC / FCI). It is, however, rigorous enough to beat blind
correlation, pure-stdlib, and deterministic. Pure function over an
in-memory observation buffer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.causal_graph")


Status = Literal["driver", "confounded", "noise"]


@dataclass
class Observation:
    features: dict[str, float]
    kpi: str
    value: float


@dataclass
class FeatureVerdict:
    feature: str
    raw_correlation: float
    surviving_correlation: float
    confounders: list[str] = field(default_factory=list)
    status: Status = "noise"

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "raw_correlation": round(self.raw_correlation, 4),
            "surviving_correlation": round(
                self.surviving_correlation, 4,
            ),
            "confounders": list(self.confounders),
            "status": self.status,
        }


@dataclass
class CausalReport:
    kpi: str
    n_obs: int
    verdicts: list[FeatureVerdict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kpi": self.kpi,
            "n_obs": self.n_obs,
            "verdicts": [v.as_dict() for v in self.verdicts],
            "drivers": [
                v.feature for v in self.verdicts if v.status == "driver"
            ],
        }


# ── Correlation math ──────────────────────────────────────

def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n) or 0.0
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n) or 0.0
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    r = cov / (sx * sy)
    return max(-1.0, min(1.0, r))


def _partial_correlation(
    xs: list[float], ys: list[float], zs: list[float],
) -> float:
    """r(X, Y | Z) = (r_xy − r_xz · r_yz) / √((1 − r_xz²)(1 − r_yz²))."""
    rxy = _pearson(xs, ys)
    rxz = _pearson(xs, zs)
    ryz = _pearson(ys, zs)
    denom_sq = (1.0 - rxz * rxz) * (1.0 - ryz * ryz)
    if denom_sq <= 0:
        return 0.0
    denom = math.sqrt(denom_sq)
    if denom == 0:
        return 0.0
    return max(-1.0, min(1.0, (rxy - rxz * ryz) / denom))


# ── Engine ────────────────────────────────────────────────

class CausalGraph:
    def __init__(
        self,
        *,
        max_observations: int = 5_000,
        min_correlation: float = 0.2,
        shrinkage_threshold: float = 0.5,
    ) -> None:
        if max_observations <= 0 or min_correlation < 0:
            raise ValueError("config thresholds must be positive")
        self._max = int(max_observations)
        self._min_corr = float(min_correlation)
        self._shrinkage = float(shrinkage_threshold)
        self._obs: list[Observation] = []

    def observe(
        self,
        features: dict[str, Any],
        kpi: str,
        value: float,
    ) -> None:
        if not kpi:
            raise ValueError("kpi required")
        numeric: dict[str, float] = {}
        for k, v in (features or {}).items():
            try:
                numeric[k] = float(v)
            except (TypeError, ValueError):
                continue
        self._obs.append(Observation(
            features=numeric, kpi=kpi, value=float(value),
        ))
        if len(self._obs) > self._max:
            # Drop oldest
            self._obs = self._obs[-self._max:]

    # ── Report ────────────────────────────────────────────

    def _feature_keys(self, kpi: str) -> list[str]:
        keys: set[str] = set()
        for obs in self._obs:
            if obs.kpi != kpi:
                continue
            keys.update(obs.features.keys())
        return sorted(keys)

    def _columns(
        self, kpi: str, feature_keys: list[str],
    ) -> tuple[dict[str, list[float]], list[float]]:
        cols: dict[str, list[float]] = {k: [] for k in feature_keys}
        ys: list[float] = []
        for obs in self._obs:
            if obs.kpi != kpi:
                continue
            # Require every feature key to be present in this row —
            # keeps vector lengths aligned for correlation math.
            if not all(k in obs.features for k in feature_keys):
                continue
            for k in feature_keys:
                cols[k].append(obs.features[k])
            ys.append(obs.value)
        return cols, ys

    def report(self, kpi: str) -> CausalReport:
        keys = self._feature_keys(kpi)
        cols, ys = self._columns(kpi, keys)
        verdicts: list[FeatureVerdict] = []
        if len(ys) < 3:
            return CausalReport(kpi=kpi, n_obs=len(ys), verdicts=verdicts)

        for k in keys:
            xs = cols[k]
            raw = _pearson(xs, ys)
            if abs(raw) < self._min_corr:
                verdicts.append(FeatureVerdict(
                    feature=k, raw_correlation=raw,
                    surviving_correlation=raw,
                    status="noise",
                ))
                continue
            # Condition on every other candidate
            surviving = raw
            confounders: list[str] = []
            for other in keys:
                if other == k:
                    continue
                zs = cols[other]
                partial = _partial_correlation(xs, ys, zs)
                if abs(partial) < abs(surviving):
                    surviving = partial
                # Confounder: partial shrinks by > shrinkage × raw
                if (
                    abs(raw) > 0
                    and (abs(raw) - abs(partial)) / abs(raw)
                        > self._shrinkage
                ):
                    confounders.append(other)
            status: Status = (
                "driver"
                if abs(surviving) >= self._min_corr and not confounders
                else "confounded"
                if confounders
                else "noise"
            )
            verdicts.append(FeatureVerdict(
                feature=k,
                raw_correlation=raw,
                surviving_correlation=surviving,
                confounders=confounders, status=status,
            ))
        verdicts.sort(key=lambda v: -abs(v.surviving_correlation))
        return CausalReport(kpi=kpi, n_obs=len(ys), verdicts=verdicts)

    def drivers(self, kpi: str) -> list[str]:
        return [v.feature for v in self.report(kpi).verdicts
                if v.status == "driver"]

    def stats(self) -> dict[str, Any]:
        kpis: dict[str, int] = {}
        for o in self._obs:
            kpis[o.kpi] = kpis.get(o.kpi, 0) + 1
        return {
            "n_obs": len(self._obs),
            "kpis": kpis,
            "max_observations": self._max,
        }

    def clear(self, kpi: str | None = None) -> int:
        if kpi is None:
            n = len(self._obs)
            self._obs.clear()
            return n
        before = len(self._obs)
        self._obs = [o for o in self._obs if o.kpi != kpi]
        return before - len(self._obs)
