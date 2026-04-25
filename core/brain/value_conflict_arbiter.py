"""Value conflict arbiter — resolve competing owner values.

A decision often scores high on one owner value and low on another:
"raise price by 15%" scores +margin but -novelty (same SKU, same
look). utility_blender *blends* those scores into a single number,
but blending hides the tension. This module explicitly names the
conflict and arbitrates using the learned value_weighter.

Input: a ``ConflictCase`` with per-option score dicts mapping
*value* → score. Output: a ``Resolution`` with:

  • winner_option   — the option that wins under current weights
  • contested_value — the highest-lift value the loser was better on
  • margin          — weighted-score delta
  • reasoning       — human-readable trade-off statement

If the margin is below ``tie_margin``, verdict = ``"tie"`` so the
caller can abstain or ask the owner.

Pure stdlib, deterministic.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.value_conflict_arbiter")


Verdict = Literal["pick", "tie"]


@dataclass
class OptionScore:
    option_id: str
    name: str
    scores: dict[str, float]    # value_name → 0..1

    def as_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "name": self.name,
            "scores": {
                k: round(v, 4) for k, v in self.scores.items()
            },
        }


@dataclass
class ConflictCase:
    id: str
    options: list[OptionScore]

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError(
                "at least two options required",
            )


@dataclass
class Resolution:
    case_id: str
    verdict: Verdict
    winner_option: str
    contested_value: str
    margin: float
    reasoning: str
    scores: dict[str, float]    # option_id → weighted score
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "verdict": self.verdict,
            "winner_option": self.winner_option,
            "contested_value": self.contested_value,
            "margin": round(self.margin, 4),
            "reasoning": self.reasoning,
            "scores": {
                k: round(v, 4) for k, v in self.scores.items()
            },
            "ts": self.ts,
        }


_DEFAULT_TIE_MARGIN = 0.05


class ValueConflictArbiter:
    def __init__(
        self,
        *,
        tie_margin: float = _DEFAULT_TIE_MARGIN,
    ) -> None:
        if not 0.0 <= tie_margin < 1.0:
            raise ValueError(
                "tie_margin must be in [0, 1)",
            )
        self._lock = threading.Lock()
        self._tie_margin = float(tie_margin)
        self._history: list[Resolution] = []

    def set_tie_margin(self, margin: float) -> None:
        if not 0.0 <= margin < 1.0:
            raise ValueError(
                "margin must be in [0, 1)",
            )
        with self._lock:
            self._tie_margin = float(margin)

    # ── Arbitrate ────────────────────────────────────────

    def arbitrate(
        self,
        case: ConflictCase,
        *,
        value_weights: dict[str, float] | None = None,
    ) -> Resolution:
        weights = dict(value_weights or {})
        # Any value in a score dict that wasn't weighted gets
        # equal share over the residual 0.1
        all_values = sorted({
            v
            for opt in case.options
            for v in opt.scores.keys()
        })
        if not all_values:
            raise ValueError(
                "at least one value dimension required",
            )
        # Fill missing weights with a small default so unseen
        # values still contribute.
        seen_weight = sum(
            max(0.0, weights.get(v, 0.0)) for v in all_values
        )
        residual = max(0.0, 1.0 - seen_weight)
        missing = [
            v for v in all_values if v not in weights
        ]
        if missing:
            share = (
                residual / len(missing) if missing else 0.0
            )
            for v in missing:
                weights[v] = share
        # Compute weighted scores per option
        weighted: dict[str, float] = {}
        for opt in case.options:
            total = 0.0
            for v, s in opt.scores.items():
                total += weights.get(v, 0.0) * float(s)
            weighted[opt.option_id] = total
        ranked = sorted(
            case.options,
            key=lambda o: -weighted[o.option_id],
        )
        winner = ranked[0]
        runner_up = ranked[1]
        margin = (
            weighted[winner.option_id]
            - weighted[runner_up.option_id]
        )
        # Find most-contested value (max delta in runner's favour)
        contested = ""
        max_delta = 0.0
        for v in all_values:
            delta = (
                runner_up.scores.get(v, 0.0)
                - winner.scores.get(v, 0.0)
            ) * weights.get(v, 0.0)
            if delta > max_delta:
                max_delta = delta
                contested = v
        if margin < self._tie_margin:
            verdict: Verdict = "tie"
            reasoning = (
                f"top two within tie_margin "
                f"{self._tie_margin:.3f}; need owner call"
            )
            winner_id = ""
        else:
            verdict = "pick"
            bits = [
                f"winner {winner.name!r} wins by {margin:.3f}",
            ]
            if contested:
                bits.append(
                    f"trade-off: lost {contested!r} "
                    f"worth {max_delta:.3f}",
                )
            reasoning = "; ".join(bits)
            winner_id = winner.option_id
        resolution = Resolution(
            case_id=case.id,
            verdict=verdict,
            winner_option=winner_id,
            contested_value=contested,
            margin=margin,
            reasoning=reasoning,
            scores=weighted,
            ts=time.time(),
        )
        with self._lock:
            self._history.append(resolution)
            if len(self._history) > 200:
                del self._history[: len(self._history) - 200]
        return resolution

    # ── Queries ──────────────────────────────────────────

    def recent(self, *, limit: int = 20) -> list[Resolution]:
        with self._lock:
            return list(
                self._history[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_verdict: dict[str, int] = {}
            for r in self._history:
                by_verdict[r.verdict] = (
                    by_verdict.get(r.verdict, 0) + 1
                )
            return {
                "arbitrations": len(self._history),
                "by_verdict": by_verdict,
                "tie_margin": self._tie_margin,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n
