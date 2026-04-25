"""Salience tuner — learn which signals actually matter.

attention_filter ranks items by a weighted sum of features. The
weights were hand-picked. Over time, some features prove predictive
(they track what attention_calibrator says really mattered) and
others don't. salience_tuner learns a per-feature weight adjustment
from paired (ranking_features, outcome) observations.

A gradient-free, online update rule:

  • for each feature, track (sum_weight * outcome_importance) vs
    (sum_weight * (1 - outcome_importance))
  • compute a "lift" = positive_mean − negative_mean per feature
  • normalise lifts into a weight vector that sums to 1.0
  • expose ``weights()`` for attention_filter to consume and
    ``recommend_weight(feature)`` for per-feature queries

Conservative: the tuner only returns a recommendation; the caller
decides when to apply it. Updates are smoothed with EMA
(``ema_alpha``) so a single weird cycle doesn't swing weights wildly.

Pure stdlib, deterministic, LLM-free.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.salience_tuner")


_DEFAULT_EMA_ALPHA = 0.2
_FLOOR = 1e-6


@dataclass
class FeatureStat:
    feature: str
    positive_mass: float
    negative_mass: float
    n_samples: int

    @property
    def lift(self) -> float:
        if self.positive_mass + self.negative_mass <= _FLOOR:
            return 0.0
        pos = self.positive_mass / max(self.n_samples, 1)
        neg = self.negative_mass / max(self.n_samples, 1)
        return pos - neg

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "positive_mass": round(self.positive_mass, 4),
            "negative_mass": round(self.negative_mass, 4),
            "n_samples": self.n_samples,
            "lift": round(self.lift, 4),
        }


class SalienceTuner:
    def __init__(
        self,
        *,
        ema_alpha: float = _DEFAULT_EMA_ALPHA,
    ) -> None:
        if not 0.0 < ema_alpha <= 1.0:
            raise ValueError("ema_alpha must be in (0, 1]")
        self._lock = threading.Lock()
        self._alpha = float(ema_alpha)
        self._stats: dict[str, FeatureStat] = {}
        self._weights: dict[str, float] = {}

    # ── Intake ───────────────────────────────────────────

    def observe(
        self,
        *,
        features: dict[str, float],
        outcome_importance: float,
    ) -> None:
        """``features``: feature → score-in-ranking (0..1 preferred).
        ``outcome_importance``: realised importance after the fact
        (0..1 — how salient did this item actually turn out to be?).
        """
        if not features:
            raise ValueError("features required")
        if not 0.0 <= outcome_importance <= 1.0:
            raise ValueError(
                "outcome_importance must be in [0, 1]",
            )
        with self._lock:
            for feat, raw_score in features.items():
                if not feat:
                    continue
                try:
                    score = float(raw_score)
                except (TypeError, ValueError):
                    continue
                stat = self._stats.get(feat)
                if stat is None:
                    stat = FeatureStat(
                        feature=feat,
                        positive_mass=0.0,
                        negative_mass=0.0,
                        n_samples=0,
                    )
                    self._stats[feat] = stat
                stat.n_samples += 1
                stat.positive_mass += score * outcome_importance
                stat.negative_mass += score * (
                    1.0 - outcome_importance
                )
            self._rebalance_weights()

    # ── Weights ──────────────────────────────────────────

    def _rebalance_weights(self) -> None:
        lifts = {
            feat: max(0.0, s.lift)
            for feat, s in self._stats.items()
        }
        total = sum(lifts.values())
        if total <= _FLOOR:
            # Fall back to uniform
            n = max(1, len(self._stats))
            target = {feat: 1.0 / n for feat in self._stats}
        else:
            target = {
                feat: v / total for feat, v in lifts.items()
            }
        alpha = self._alpha
        for feat, tgt in target.items():
            prev = self._weights.get(feat, 0.0)
            self._weights[feat] = (
                (1 - alpha) * prev + alpha * tgt
            )
        # Drop features no longer seen
        for old in list(self._weights.keys()):
            if old not in target:
                del self._weights[old]

    def weights(self) -> dict[str, float]:
        with self._lock:
            return {
                k: round(v, 6) for k, v in self._weights.items()
            }

    def recommend_weight(self, feature: str) -> float:
        with self._lock:
            return float(self._weights.get(feature, 0.0))

    # ── Queries ──────────────────────────────────────────

    def feature_stats(self) -> list[FeatureStat]:
        with self._lock:
            out = list(self._stats.values())
        out.sort(key=lambda s: -s.lift)
        return out

    def low_lift_features(
        self, *, floor: float = 0.05,
    ) -> list[str]:
        with self._lock:
            return sorted(
                s.feature for s in self._stats.values()
                if s.lift < floor
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "features": len(self._stats),
                "ema_alpha": self._alpha,
                "top_weight": (
                    max(self._weights.values())
                    if self._weights else 0.0
                ),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._stats)
            self._stats.clear()
            self._weights.clear()
        return n
