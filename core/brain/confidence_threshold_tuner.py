"""Confidence threshold tuner — per-decision-kind min_confidence.

A hard-coded ``min_confidence=0.7`` works for generic decisions but
is wrong for specific kinds: price changes can tolerate 0.5 (small
blast), account-suspension needs 0.95 (irreversible). The tuner
learns a per-kind threshold that keeps the win rate above a target
floor and rejects false positives.

For each decision_kind the tuner tracks (confidence, outcome_ok)
pairs. On demand it computes the *smallest* threshold τ such that
P(ok | confidence ≥ τ) ≥ target_win_rate, across the observed
history. This is a simple sweep over candidate thresholds, not a
gradient — deterministic, reproducible.

Queries:
  * ``threshold(kind)`` — recommended τ
  * ``accepts(kind, confidence)`` — quick gate
  * ``traces(kind)`` — inspection

Pure stdlib, deterministic. Complements `meta_reasoner` (which
tracks calibration) by using the calibration data to *set* a gate.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.confidence_threshold_tuner")


_DEFAULT_TARGET_WIN_RATE = 0.7
_DEFAULT_FALLBACK = 0.7
_CANDIDATE_STEPS = tuple(i / 100 for i in range(101))


@dataclass
class DecisionSample:
    kind: str
    confidence: float
    outcome_ok: bool
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "confidence": round(self.confidence, 4),
            "outcome_ok": self.outcome_ok,
            "ts": self.ts,
        }


@dataclass
class KindSummary:
    kind: str
    n_samples: int
    win_rate: float
    recommended_threshold: float
    coverage_at_threshold: float     # fraction of samples that pass
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "n_samples": self.n_samples,
            "win_rate": round(self.win_rate, 4),
            "recommended_threshold": round(
                self.recommended_threshold, 4,
            ),
            "coverage_at_threshold": round(
                self.coverage_at_threshold, 4,
            ),
            "note": self.note,
        }


class ConfidenceThresholdTuner:
    def __init__(
        self,
        *,
        target_win_rate: float = _DEFAULT_TARGET_WIN_RATE,
        min_samples: int = 10,
        fallback_threshold: float = _DEFAULT_FALLBACK,
    ) -> None:
        if not 0.0 < target_win_rate <= 1.0:
            raise ValueError(
                "target_win_rate must be in (0, 1]",
            )
        if min_samples < 5:
            raise ValueError("min_samples must be ≥ 5")
        if not 0.0 < fallback_threshold <= 1.0:
            raise ValueError(
                "fallback_threshold must be in (0, 1]",
            )
        self._lock = threading.Lock()
        self._target = float(target_win_rate)
        self._min_samples = int(min_samples)
        self._fallback = float(fallback_threshold)
        self._samples: dict[str, list[DecisionSample]] = (
            defaultdict(list)
        )
        self._overrides: dict[str, float] = {}

    # ── Intake ───────────────────────────────────────────

    def record(
        self,
        *,
        kind: str,
        confidence: float,
        outcome_ok: bool,
        ts: float | None = None,
    ) -> DecisionSample:
        if not kind:
            raise ValueError("kind required")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                "confidence must be in [0, 1]",
            )
        timestamp = float(ts if ts is not None else time.time())
        sample = DecisionSample(
            kind=str(kind),
            confidence=float(confidence),
            outcome_ok=bool(outcome_ok),
            ts=timestamp,
        )
        with self._lock:
            self._samples[sample.kind].append(sample)
        return sample

    # ── Overrides ────────────────────────────────────────

    def set_override(self, kind: str, threshold: float) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError(
                "threshold must be in (0, 1]",
            )
        with self._lock:
            self._overrides[kind] = float(threshold)

    def clear_override(self, kind: str) -> bool:
        with self._lock:
            return self._overrides.pop(kind, None) is not None

    # ── Compute ──────────────────────────────────────────

    def _best_threshold(
        self, samples: list[DecisionSample],
    ) -> tuple[float, float, float]:
        """Return (threshold, win_rate_at_threshold, coverage)."""
        total = len(samples)
        for tau in _CANDIDATE_STEPS:
            pass_samples = [
                s for s in samples if s.confidence >= tau
            ]
            if len(pass_samples) < max(
                5, int(self._min_samples * 0.3),
            ):
                # too sparse — keep going up, but floor the search
                continue
            wins = sum(1 for s in pass_samples if s.outcome_ok)
            rate = wins / len(pass_samples)
            if rate >= self._target:
                return (
                    tau, rate, len(pass_samples) / total,
                )
        # No threshold meets target — return fallback
        return (self._fallback, 0.0, 0.0)

    def threshold(self, kind: str) -> float:
        with self._lock:
            if kind in self._overrides:
                return self._overrides[kind]
            samples = list(self._samples.get(kind, ()))
        if len(samples) < self._min_samples:
            return self._fallback
        tau, _, _ = self._best_threshold(samples)
        return tau

    def accepts(
        self, kind: str, confidence: float,
    ) -> bool:
        return float(confidence) >= self.threshold(kind)

    def summary(self, kind: str) -> KindSummary:
        with self._lock:
            samples = list(self._samples.get(kind, ()))
            override = self._overrides.get(kind)
        total = len(samples)
        if total == 0:
            return KindSummary(
                kind=kind, n_samples=0,
                win_rate=0.0,
                recommended_threshold=(
                    override if override is not None
                    else self._fallback
                ),
                coverage_at_threshold=0.0,
                note=(
                    "no data; using "
                    + ("override" if override else "fallback")
                ),
            )
        overall_wins = sum(1 for s in samples if s.outcome_ok)
        win_rate = overall_wins / total
        if override is not None:
            recommended = override
            passing = [
                s for s in samples if s.confidence >= override
            ]
            coverage = (
                len(passing) / total if total else 0.0
            )
            note = "override in effect"
        elif total < self._min_samples:
            recommended = self._fallback
            coverage = 0.0
            note = (
                f"need ≥ {self._min_samples} samples; have {total}"
            )
        else:
            recommended, _, coverage = self._best_threshold(samples)
            note = (
                f"tuned for target={self._target:.2f}"
            )
        return KindSummary(
            kind=kind,
            n_samples=total,
            win_rate=win_rate,
            recommended_threshold=recommended,
            coverage_at_threshold=coverage,
            note=note,
        )

    # ── Queries ──────────────────────────────────────────

    def traces(self, kind: str) -> list[DecisionSample]:
        with self._lock:
            return list(self._samples.get(kind, ()))

    def known_kinds(self) -> list[str]:
        with self._lock:
            return sorted(self._samples.keys())

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = sum(
                len(v) for v in self._samples.values()
            )
            return {
                "kinds": len(self._samples),
                "total_samples": total,
                "target_win_rate": self._target,
                "min_samples": self._min_samples,
                "overrides": dict(self._overrides),
            }

    def reset(self) -> int:
        with self._lock:
            n = sum(
                len(v) for v in self._samples.values()
            )
            self._samples.clear()
            self._overrides.clear()
        return n
