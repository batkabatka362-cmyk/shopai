"""Value weighter — learn the owner's implicit value vector.

owner_model stores explicit preferences owners state. But owners also
*reveal* preferences through approvals, rejections, and praise. Over
many decisions a pattern emerges: owner praises "margin-positive"
actions more than "revenue-growth" ones. The brain should mirror that.

Each decision surfaces a feature vector across named *values*:

    {"revenue": 0.8, "margin": 0.4, "novelty": 0.1,
     "risk": 0.2, "owner_effort": 0.3}

After the decision, owner feedback arrives as one of:

  • "approve"       — value[+1]
  • "reject"        — value[-1]
  • "praise"        — value[+2]
  • "criticise"     — value[-2]

``ValueWeighter`` performs an online gradient update: features that
correlate with approve/praise get their weight raised, reject/
criticise lowers it. Output weights normalise to a probability
simplex (sum = 1) for use by utility_blender.

Pure stdlib, deterministic, LLM-free.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.value_weighter")


Feedback = Literal["approve", "reject", "praise", "criticise"]
_FEEDBACK_SIGN = {
    "approve": 1.0,
    "praise": 2.0,
    "reject": -1.0,
    "criticise": -2.0,
}


@dataclass
class WeightTrace:
    value: str
    weight: float
    observation_count: int
    support: float
    oppose: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "weight": round(self.weight, 4),
            "observation_count": self.observation_count,
            "support": round(self.support, 4),
            "oppose": round(self.oppose, 4),
        }


class ValueWeighter:
    def __init__(
        self,
        *,
        learning_rate: float = 0.15,
        floor: float = 0.05,
        initial_weights: dict[str, float] | None = None,
    ) -> None:
        if not 0.0 < learning_rate <= 1.0:
            raise ValueError(
                "learning_rate must be in (0, 1]",
            )
        if not 0.0 <= floor < 1.0:
            raise ValueError("floor must be in [0, 1)")
        self._lock = threading.RLock()
        self._lr = float(learning_rate)
        self._floor = float(floor)
        self._raw_weights: dict[str, float] = dict(
            initial_weights or {},
        )
        self._support: dict[str, float] = defaultdict(float)
        self._oppose: dict[str, float] = defaultdict(float)
        self._counts: dict[str, int] = defaultdict(int)

    # ── Intake ───────────────────────────────────────────

    def observe(
        self,
        *,
        value_scores: dict[str, float],
        feedback: Feedback,
    ) -> dict[str, float]:
        if feedback not in _FEEDBACK_SIGN:
            raise ValueError(
                f"feedback must be one of {list(_FEEDBACK_SIGN)}",
            )
        if not value_scores:
            raise ValueError("value_scores required")
        sign = _FEEDBACK_SIGN[feedback]
        with self._lock:
            for value, raw_score in value_scores.items():
                if not value:
                    continue
                try:
                    score = float(raw_score)
                except (TypeError, ValueError):
                    continue
                score = max(0.0, min(1.0, score))
                # Update support/oppose accumulators
                if sign > 0:
                    self._support[value] += score * abs(sign)
                else:
                    self._oppose[value] += score * abs(sign)
                self._counts[value] += 1
                # Gradient step on raw_weights
                current = self._raw_weights.get(value, 0.0)
                self._raw_weights[value] = (
                    current + self._lr * sign * score
                )
            return self.weights()

    # ── Weights ──────────────────────────────────────────

    def _normalised(
        self, raw: dict[str, float],
    ) -> dict[str, float]:
        clipped = {
            k: max(self._floor, v) for k, v in raw.items()
        }
        total = sum(clipped.values())
        if total <= 0:
            n = max(1, len(raw))
            return {k: 1.0 / n for k in raw}
        return {k: v / total for k, v in clipped.items()}

    def weights(self) -> dict[str, float]:
        with self._lock:
            normalised = self._normalised(
                dict(self._raw_weights),
            )
        return {k: round(v, 6) for k, v in normalised.items()}

    def raw_weights(self) -> dict[str, float]:
        with self._lock:
            return dict(self._raw_weights)

    # ── Queries ──────────────────────────────────────────

    def trace(self, value: str) -> WeightTrace | None:
        with self._lock:
            if value not in self._raw_weights:
                return None
            normalised = self._normalised(
                dict(self._raw_weights),
            )
            return WeightTrace(
                value=value,
                weight=normalised.get(value, 0.0),
                observation_count=self._counts.get(value, 0),
                support=self._support.get(value, 0.0),
                oppose=self._oppose.get(value, 0.0),
            )

    def ranked(self) -> list[WeightTrace]:
        with self._lock:
            keys = list(self._raw_weights.keys())
        out = [t for t in (self.trace(k) for k in keys) if t]
        out.sort(key=lambda t: -t.weight)
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "values_tracked": len(self._raw_weights),
                "total_observations": sum(self._counts.values()),
                "learning_rate": self._lr,
                "floor": self._floor,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._raw_weights)
            self._raw_weights.clear()
            self._support.clear()
            self._oppose.clear()
            self._counts.clear()
        return n
