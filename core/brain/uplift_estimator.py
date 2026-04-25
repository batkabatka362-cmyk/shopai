"""Uplift estimator — learn treatment-effect curves from experience.

Counterfactual_simulator answers *"what if I'd done X"* via policy
rollouts. It needs a transition model. uplift_estimator *is* the
transition model. Given past records

    (treatment, covariates, outcome)

it estimates the average treatment effect (ATE) on an outcome for a
given treatment vs a control. Supports:

  • Binary treatment       — did we apply the discount or not?
  • Categorical treatment  — which of N variants?
  • Conditional ATE        — ATE restricted to a subgroup of covariates
  • Confidence interval    — Welford pooled variance → ±1.96σ

The estimator is deterministic and pure-stdlib; it intentionally
does NOT use a trained ML model (scope + dependency cost). Methods:

  • observe(treatment, covariates, outcome)
  • ate(treatment_value, control_value, outcome_key)  → UpliftEstimate
  • cate(treatment_value, control_value, outcome_key, covariates_subset)
  • best_treatment(control_value, outcome_key, candidates)

Used by: cycle_planner (which variant to prefer), counterfactual
simulator (transition function), experiment_manager (promote winner).

Pure stdlib. In-memory (SQLite backup optional via ``persist``).
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class Observation:
    treatment: str
    covariates: dict[str, Any]
    outcome: dict[str, float]
    ts: float = 0.0


@dataclass
class UpliftEstimate:
    treatment_value: str
    control_value: str
    outcome_key: str
    ate: float                  # mean(treatment) − mean(control)
    ci_low: float
    ci_high: float
    n_treatment: int
    n_control: int
    treatment_mean: float
    control_mean: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "treatment_value": self.treatment_value,
            "control_value": self.control_value,
            "outcome_key": self.outcome_key,
            "ate": round(self.ate, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "n_treatment": self.n_treatment,
            "n_control": self.n_control,
            "treatment_mean": round(self.treatment_mean, 4),
            "control_mean": round(self.control_mean, 4),
        }

    @property
    def significant(self) -> bool:
        """Zero NOT in the 95% CI."""
        return (self.ci_low > 0 and self.ci_high > 0) or (
            self.ci_low < 0 and self.ci_high < 0
        )


# ── Welford pooled stats over streaming data ──────────────

class _WelfordStats:
    __slots__ = ("n", "mean", "m2")

    def __init__(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def add(self, value: float) -> None:
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        return self.m2 / (self.n - 1) if self.n > 1 else 0.0


def _subgroup_match(
    covariates: dict[str, Any],
    subset: dict[str, Any] | None,
) -> bool:
    if not subset:
        return True
    for k, v in subset.items():
        if covariates.get(k) != v:
            return False
    return True


# ── Estimator ─────────────────────────────────────────────

class UpliftEstimator:
    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._observations: list[Observation] = []
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            self._db = Path(db_path)
            self._db.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db), check_same_thread=False,
            )
            self._init_schema()

    def _init_schema(self) -> None:
        assert self._conn is not None
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         REAL NOT NULL,
                    treatment  TEXT NOT NULL,
                    covariates TEXT NOT NULL,
                    outcome    TEXT NOT NULL
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_tx "
                "ON observations(treatment)"
            )
            self._conn.commit()

    # ── Intake ────────────────────────────────────────────

    def observe(
        self,
        treatment: str,
        covariates: dict[str, Any],
        outcome: dict[str, float],
    ) -> None:
        if not treatment:
            raise ValueError("treatment required")
        obs = Observation(
            treatment=str(treatment),
            covariates=dict(covariates or {}),
            outcome={k: float(v) for k, v in (outcome or {}).items()},
            ts=time.time(),
        )
        with self._lock:
            self._observations.append(obs)
            if self._conn is not None:
                import json
                self._conn.execute(
                    "INSERT INTO observations"
                    "(ts, treatment, covariates, outcome) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        obs.ts, obs.treatment,
                        json.dumps(obs.covariates, sort_keys=True),
                        json.dumps(obs.outcome, sort_keys=True),
                    ),
                )
                self._conn.commit()

    # ── Estimates ─────────────────────────────────────────

    def _partition(
        self,
        treatment_value: str,
        control_value: str,
        outcome_key: str,
        covariates_subset: dict[str, Any] | None,
    ) -> tuple[_WelfordStats, _WelfordStats]:
        t_stats = _WelfordStats()
        c_stats = _WelfordStats()
        with self._lock:
            obs_copy = list(self._observations)
        for obs in obs_copy:
            if not _subgroup_match(obs.covariates, covariates_subset):
                continue
            if outcome_key not in obs.outcome:
                continue
            value = float(obs.outcome[outcome_key])
            if obs.treatment == treatment_value:
                t_stats.add(value)
            elif obs.treatment == control_value:
                c_stats.add(value)
        return t_stats, c_stats

    def ate(
        self,
        *,
        treatment_value: str,
        control_value: str,
        outcome_key: str,
        covariates_subset: dict[str, Any] | None = None,
    ) -> UpliftEstimate:
        t_stats, c_stats = self._partition(
            treatment_value, control_value,
            outcome_key, covariates_subset,
        )
        ate = t_stats.mean - c_stats.mean
        # Standard error for the difference in means.
        pooled_var = (
            (t_stats.variance / max(1, t_stats.n))
            + (c_stats.variance / max(1, c_stats.n))
        )
        se = math.sqrt(max(0.0, pooled_var))
        half = 1.96 * se
        return UpliftEstimate(
            treatment_value=treatment_value,
            control_value=control_value,
            outcome_key=outcome_key,
            ate=ate,
            ci_low=ate - half,
            ci_high=ate + half,
            n_treatment=t_stats.n,
            n_control=c_stats.n,
            treatment_mean=t_stats.mean,
            control_mean=c_stats.mean,
        )

    def cate(
        self,
        *,
        treatment_value: str,
        control_value: str,
        outcome_key: str,
        covariates_subset: dict[str, Any],
    ) -> UpliftEstimate:
        return self.ate(
            treatment_value=treatment_value,
            control_value=control_value,
            outcome_key=outcome_key,
            covariates_subset=covariates_subset,
        )

    def best_treatment(
        self,
        *,
        control_value: str,
        outcome_key: str,
        candidates: Iterable[str],
        min_samples: int = 5,
    ) -> UpliftEstimate | None:
        best: UpliftEstimate | None = None
        for cand in candidates:
            if cand == control_value:
                continue
            est = self.ate(
                treatment_value=cand,
                control_value=control_value,
                outcome_key=outcome_key,
            )
            if est.n_treatment < min_samples:
                continue
            if best is None or est.ate > best.ate:
                best = est
        return best

    # ── Maintenance ───────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            n = len(self._observations)
            treatments = {
                o.treatment for o in self._observations
            }
        return {
            "n_observations": n,
            "distinct_treatments": len(treatments),
            "treatments": sorted(treatments),
        }

    def clear(self) -> int:
        with self._lock:
            n = len(self._observations)
            self._observations.clear()
            if self._conn is not None:
                self._conn.execute("DELETE FROM observations")
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
