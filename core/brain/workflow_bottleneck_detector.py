"""Workflow bottleneck detector — which phase eats time + breaks.

core_orchestrator.run_cycle is a 14+ phase chain. When the cycle
takes 30s instead of 5s, owners want to know *which phase* bloated —
and when error rate spikes, which phase failed. This module keeps
per-phase rolling statistics and surfaces:

  • slowest phases (by mean or p95 latency)
  • flakiest phases (error rate)
  • overall cycle breakdown

Each phase sample is a ``PhaseSample(phase, duration_ms, ok)``. The
detector keeps a bounded deque per phase, computes summary stats,
and ranks phases. Recommends the top bottleneck with a note about
whether it's latency- or error-driven.

Pure stdlib, deterministic. Complements ``integration_harness``
(which checks the whole loop succeeds) by isolating *where* trouble
lives.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Iterable

from utils.logger import get_logger


logger = get_logger("brain.workflow_bottleneck_detector")


_DEFAULT_WINDOW = 100


@dataclass
class PhaseSample:
    phase: str
    duration_ms: float
    ok: bool
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "duration_ms": round(self.duration_ms, 2),
            "ok": self.ok,
            "ts": self.ts,
        }


@dataclass
class PhaseStat:
    phase: str
    n: int
    mean_ms: float
    p95_ms: float
    error_rate: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "n": self.n,
            "mean_ms": round(self.mean_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "error_rate": round(self.error_rate, 4),
        }


@dataclass
class Bottleneck:
    phase: str
    reason: str   # "latency" | "errors"
    score: float
    stat: PhaseStat

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "reason": self.reason,
            "score": round(self.score, 4),
            "stat": self.stat.as_dict(),
        }


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * q
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_v[int(k)]
    d0 = sorted_v[int(f)] * (c - k)
    d1 = sorted_v[int(c)] * (k - f)
    return d0 + d1


class WorkflowBottleneckDetector:
    def __init__(
        self,
        *,
        window: int = _DEFAULT_WINDOW,
        slow_factor: float = 2.0,
        error_rate_floor: float = 0.1,
    ) -> None:
        if window < 10:
            raise ValueError("window must be ≥ 10")
        if slow_factor <= 1.0:
            raise ValueError("slow_factor must be > 1")
        if not 0.0 < error_rate_floor <= 1.0:
            raise ValueError(
                "error_rate_floor must be in (0, 1]",
            )
        self._lock = threading.Lock()
        self._window = int(window)
        self._slow_factor = float(slow_factor)
        self._error_floor = float(error_rate_floor)
        self._samples: dict[str, Deque[PhaseSample]] = (
            defaultdict(lambda: deque(maxlen=self._window))
        )

    # ── Intake ───────────────────────────────────────────

    def record(
        self,
        *,
        phase: str,
        duration_ms: float,
        ok: bool,
        ts: float | None = None,
    ) -> PhaseSample:
        if not phase:
            raise ValueError("phase required")
        if duration_ms < 0:
            raise ValueError("duration_ms must be ≥ 0")
        timestamp = float(ts if ts is not None else time.time())
        sample = PhaseSample(
            phase=str(phase),
            duration_ms=float(duration_ms),
            ok=bool(ok),
            ts=timestamp,
        )
        with self._lock:
            self._samples[sample.phase].append(sample)
        return sample

    # ── Stats ────────────────────────────────────────────

    def _stat(self, phase: str) -> PhaseStat | None:
        with self._lock:
            samples = list(self._samples.get(phase, ()))
        if not samples:
            return None
        durs = [s.duration_ms for s in samples]
        errors = sum(1 for s in samples if not s.ok)
        return PhaseStat(
            phase=phase,
            n=len(samples),
            mean_ms=sum(durs) / len(durs),
            p95_ms=_percentile(durs, 0.95),
            error_rate=errors / len(samples),
        )

    def all_stats(self) -> list[PhaseStat]:
        with self._lock:
            phases = list(self._samples.keys())
        out = [s for s in (self._stat(p) for p in phases) if s]
        out.sort(key=lambda s: -s.mean_ms)
        return out

    # ── Bottleneck ───────────────────────────────────────

    def top_bottleneck(self) -> Bottleneck | None:
        stats = self.all_stats()
        if not stats:
            return None
        overall_mean = (
            sum(s.mean_ms * s.n for s in stats)
            / max(1, sum(s.n for s in stats))
        )
        best_latency: Bottleneck | None = None
        best_error: Bottleneck | None = None
        for s in stats:
            # Latency bottleneck: mean is slow_factor × overall mean
            if (
                overall_mean > 0
                and s.mean_ms >= self._slow_factor * overall_mean
            ):
                score = s.mean_ms / overall_mean
                candidate = Bottleneck(
                    phase=s.phase,
                    reason="latency",
                    score=score,
                    stat=s,
                )
                if (
                    best_latency is None
                    or candidate.score > best_latency.score
                ):
                    best_latency = candidate
            # Error bottleneck: error_rate above floor
            if s.error_rate >= self._error_floor:
                score = s.error_rate
                candidate = Bottleneck(
                    phase=s.phase,
                    reason="errors",
                    score=score,
                    stat=s,
                )
                if (
                    best_error is None
                    or candidate.score > best_error.score
                ):
                    best_error = candidate
        # Errors beat latency (correctness first)
        if best_error is not None:
            return best_error
        return best_latency

    def all_bottlenecks(self) -> list[Bottleneck]:
        stats = self.all_stats()
        if not stats:
            return []
        overall_mean = (
            sum(s.mean_ms * s.n for s in stats)
            / max(1, sum(s.n for s in stats))
        )
        out: list[Bottleneck] = []
        for s in stats:
            if (
                overall_mean > 0
                and s.mean_ms >= self._slow_factor * overall_mean
            ):
                out.append(Bottleneck(
                    phase=s.phase,
                    reason="latency",
                    score=s.mean_ms / overall_mean,
                    stat=s,
                ))
            if s.error_rate >= self._error_floor:
                out.append(Bottleneck(
                    phase=s.phase,
                    reason="errors",
                    score=s.error_rate,
                    stat=s,
                ))
        out.sort(key=lambda b: -b.score)
        return out

    # ── Stats / maintenance ──────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_samples = sum(
                len(v) for v in self._samples.values()
            )
            return {
                "phases": len(self._samples),
                "total_samples": total_samples,
                "window": self._window,
                "slow_factor": self._slow_factor,
                "error_rate_floor": self._error_floor,
            }

    def reset(self) -> int:
        with self._lock:
            n = sum(
                len(v) for v in self._samples.values()
            )
            self._samples.clear()
        return n
