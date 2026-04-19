"""Bayesian belief state — explicit distributions over unknowns.

Everywhere the brain emits a confidence number (predictor
win_probability, skill confidence, adapter SLA, calibration bias)
it treats that confidence as a point estimate. Real Bayesian
reasoning maintains distributions: "the conversion rate is
anywhere between 2 % and 6 % with a peak at 3.5 %".

This module tracks two distribution families and lets subsystems:

  • beta_binomial(alpha, beta)           — success probability
  • gaussian(mean, stddev, n)            — continuous metric

API:
  ``Belief.beta(name, alpha, beta)``    — register or update
  ``Belief.gauss(name, sample)``         — streaming mean/stddev update
  ``Belief.quantile(name, p)``           — posterior percentile
  ``Belief.credible_interval(name, ci)`` — lower/upper bounds

Updates are conjugate-updates, O(1) per sample. Stored as JSON —
no numpy dependency. Persistent across restarts at
``data/beliefs.json`` and also exposed via a singleton.

Usage inside the predictor::

    beliefs.beta_update("predictor_winrate_electronics",
                        success=True)
    lower, upper = beliefs.credible_interval(
        "predictor_winrate_electronics", ci=0.8,
    )
    # lower/upper now narrows as samples accumulate.
"""
from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


_STORE = Path("data/beliefs.json")
_lock = threading.Lock()


# ── Distributions ────────────────────────────────────────────

@dataclass
class BetaDist:
    alpha: float = 1.0
    beta: float = 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        a, b = self.alpha, self.beta
        denom = (a + b) ** 2 * (a + b + 1)
        return a * b / denom if denom > 0 else 0.0

    @property
    def stddev(self) -> float:
        return math.sqrt(self.variance)

    def update(self, success: bool) -> None:
        if success:
            self.alpha += 1
        else:
            self.beta += 1

    def credible_interval(self, ci: float = 0.95) -> tuple[float, float]:
        """Normal approximation when α+β > 10; else collapse to
        [mean - stddev, mean + stddev]."""
        if self.alpha + self.beta <= 10:
            lo = max(0.0, self.mean - self.stddev)
            hi = min(1.0, self.mean + self.stddev)
            return lo, hi
        import math
        z = {0.5: 0.67, 0.8: 1.28, 0.9: 1.64, 0.95: 1.96,
             0.99: 2.58}.get(ci, 1.96)
        lo = max(0.0, self.mean - z * self.stddev)
        hi = min(1.0, self.mean + z * self.stddev)
        return lo, hi

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "beta",
            "alpha": round(self.alpha, 3),
            "beta": round(self.beta, 3),
            "mean": round(self.mean, 4),
            "stddev": round(self.stddev, 4),
        }


@dataclass
class GaussDist:
    """Running mean/variance via Welford."""
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0                      # Σ (x - mean)^2

    @property
    def variance(self) -> float:
        if self.n < 2:
            return 0.0
        return self.m2 / (self.n - 1)

    @property
    def stddev(self) -> float:
        return math.sqrt(self.variance)

    def update(self, sample: float) -> None:
        self.n += 1
        delta = sample - self.mean
        self.mean += delta / self.n
        delta2 = sample - self.mean
        self.m2 += delta * delta2

    def credible_interval(self, ci: float = 0.95) -> tuple[float, float]:
        if self.n < 2:
            return self.mean, self.mean
        z = {0.5: 0.67, 0.8: 1.28, 0.9: 1.64, 0.95: 1.96,
             0.99: 2.58}.get(ci, 1.96)
        half = z * self.stddev / math.sqrt(self.n)
        return self.mean - half, self.mean + half

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "gauss",
            "n": self.n,
            "mean": round(self.mean, 4),
            "stddev": round(self.stddev, 4),
        }


# ── Belief store ────────────────────────────────────────────

class BeliefStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else _STORE

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        import os
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str),
                       encoding="utf-8")
        os.replace(tmp, self._path)

    # ── Beta API ────────────────────────────────────────────

    def beta_update(self, name: str, success: bool) -> BetaDist:
        with _lock:
            state = self._load()
            entry = state.get(name)
            if entry and entry.get("kind") == "beta":
                dist = BetaDist(alpha=float(entry.get("alpha", 1)),
                                 beta=float(entry.get("beta", 1)))
            else:
                dist = BetaDist()
            dist.update(success)
            state[name] = {
                "kind": "beta",
                "alpha": dist.alpha,
                "beta": dist.beta,
                "updated_at": time.time(),
            }
            self._save(state)
            return dist

    # ── Gauss API ───────────────────────────────────────────

    def gauss_update(self, name: str, sample: float) -> GaussDist:
        with _lock:
            state = self._load()
            entry = state.get(name)
            if entry and entry.get("kind") == "gauss":
                dist = GaussDist(
                    n=int(entry.get("n", 0)),
                    mean=float(entry.get("mean", 0)),
                    m2=float(entry.get("m2", 0)),
                )
            else:
                dist = GaussDist()
            dist.update(float(sample))
            state[name] = {
                "kind": "gauss",
                "n": dist.n,
                "mean": dist.mean,
                "m2": dist.m2,
                "updated_at": time.time(),
            }
            self._save(state)
            return dist

    # ── Common queries ──────────────────────────────────────

    def get(self, name: str) -> dict[str, Any] | None:
        entry = self._load().get(name)
        if not entry:
            return None
        if entry.get("kind") == "beta":
            d = BetaDist(alpha=float(entry.get("alpha", 1)),
                          beta=float(entry.get("beta", 1)))
            return d.as_dict()
        if entry.get("kind") == "gauss":
            d = GaussDist(
                n=int(entry.get("n", 0)),
                mean=float(entry.get("mean", 0)),
                m2=float(entry.get("m2", 0)),
            )
            return d.as_dict()
        return None

    def credible_interval(self, name: str, ci: float = 0.95) -> tuple[float, float] | None:
        entry = self._load().get(name)
        if not entry:
            return None
        if entry.get("kind") == "beta":
            d = BetaDist(alpha=float(entry.get("alpha", 1)),
                          beta=float(entry.get("beta", 1)))
            return d.credible_interval(ci)
        if entry.get("kind") == "gauss":
            d = GaussDist(
                n=int(entry.get("n", 0)),
                mean=float(entry.get("mean", 0)),
                m2=float(entry.get("m2", 0)),
            )
            return d.credible_interval(ci)
        return None

    def list_names(self, prefix: str | None = None) -> list[str]:
        names = list(self._load().keys())
        if prefix:
            names = [n for n in names if n.startswith(prefix)]
        return sorted(names)

    def reset(self, name: str) -> bool:
        with _lock:
            state = self._load()
            if name not in state:
                return False
            del state[name]
            self._save(state)
            return True


# ── Singleton ────────────────────────────────────────────────

_BELIEF_LOCK = threading.Lock()
_BELIEF: BeliefStore | None = None


def beliefs() -> BeliefStore:
    global _BELIEF
    with _BELIEF_LOCK:
        if _BELIEF is None:
            _BELIEF = BeliefStore()
    return _BELIEF
