"""Heuristic bank — cheap O(1) decision shortcuts with tracking.

Per CLAUDE.md §4b/A (95/5 rule), most decisions should *not* reach
an LLM. This module centralises the deterministic shortcuts:

  • ``roas_below_kill``     — kill if ROAS < 1.5 after 3 days
  • ``cpm_spike``           — alert if CPM jumps 2× baseline
  • ``stockout_soon``       — inventory < 3 days of sales
  • ``churn_risk``          — inactive customer ≥ 30 days

Each heuristic is a small callable producing a ``Verdict``. The bank
tracks (fires, hits, misses) per heuristic so owners can retire
heuristics that no longer fire or drop false positives. Registration
takes a predicate + action + cost + priority. Evaluation runs
through registered heuristics in priority order and returns the
first verdict or None.

Pure stdlib, deterministic, LLM-free. Complements ``policy_library``
(stored policies) and ``skill_library`` by being a *shortcut*
catalog, not a long-term-learned policy.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.heuristic_bank")


Action = Literal["act", "alert", "abstain", "escalate"]


@dataclass
class HeuristicVerdict:
    heuristic_id: str
    action: Action
    reason: str
    confidence: float
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "heuristic_id": self.heuristic_id,
            "action": self.action,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "ts": self.ts,
        }


@dataclass
class Heuristic:
    id: str
    name: str
    predicate: Callable[[dict[str, Any]], bool]
    action: Action
    reason_template: str
    confidence: float = 0.8
    priority: int = 100        # lower wins
    description: str = ""


@dataclass
class HeuristicStats:
    id: str
    fires: int
    hits: int                   # confirmed correct
    misses: int                 # confirmed wrong
    last_fired_ts: float

    @property
    def hit_rate(self) -> float:
        decided = self.hits + self.misses
        return self.hits / decided if decided else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fires": self.fires,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "last_fired_ts": self.last_fired_ts,
        }


def _roas_below_kill(ctx: dict[str, Any]) -> bool:
    return (
        float(ctx.get("roas", 999)) < 1.5
        and int(ctx.get("days_live", 0)) >= 3
    )


def _cpm_spike(ctx: dict[str, Any]) -> bool:
    cpm = float(ctx.get("cpm", 0))
    baseline = float(ctx.get("cpm_baseline", 0))
    return baseline > 0 and cpm >= 2.0 * baseline


def _stockout_soon(ctx: dict[str, Any]) -> bool:
    stock = int(ctx.get("inventory_units", 0))
    daily = float(ctx.get("daily_sales", 0.0))
    if daily <= 0:
        return False
    return stock / daily < 3.0


def _churn_risk(ctx: dict[str, Any]) -> bool:
    days_inactive = int(ctx.get("days_inactive", 0))
    return days_inactive >= 30


_DEFAULT_HEURISTICS: tuple[Heuristic, ...] = (
    Heuristic(
        id="roas_kill",
        name="kill_losing_ad",
        predicate=_roas_below_kill,
        action="act",
        reason_template="ROAS<1.5 after 3 days — kill",
        confidence=0.9,
        priority=10,
    ),
    Heuristic(
        id="cpm_spike",
        name="cpm_spike_alert",
        predicate=_cpm_spike,
        action="alert",
        reason_template="CPM ≥ 2× baseline — investigate",
        confidence=0.8,
        priority=20,
    ),
    Heuristic(
        id="stockout_soon",
        name="stockout_warning",
        predicate=_stockout_soon,
        action="alert",
        reason_template="less than 3 days of stock — reorder",
        confidence=0.85,
        priority=15,
    ),
    Heuristic(
        id="churn_risk",
        name="churn_risk_flag",
        predicate=_churn_risk,
        action="alert",
        reason_template=(
            "customer inactive 30+ days — churn watch"
        ),
        confidence=0.7,
        priority=40,
    ),
)


class HeuristicBank:
    def __init__(
        self,
        *,
        heuristics: Iterable[Heuristic] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._heuristics: list[Heuristic] = list(
            heuristics
            if heuristics is not None else _DEFAULT_HEURISTICS,
        )
        self._heuristics.sort(key=lambda h: h.priority)
        self._stats: dict[str, HeuristicStats] = {
            h.id: HeuristicStats(
                id=h.id, fires=0, hits=0,
                misses=0, last_fired_ts=0.0,
            )
            for h in self._heuristics
        }
        self._verdict_history: list[HeuristicVerdict] = []

    # ── Registry ─────────────────────────────────────────

    def register(self, h: Heuristic) -> None:
        with self._lock:
            self._heuristics.append(h)
            self._heuristics.sort(key=lambda x: x.priority)
            if h.id not in self._stats:
                self._stats[h.id] = HeuristicStats(
                    id=h.id, fires=0, hits=0,
                    misses=0, last_fired_ts=0.0,
                )

    def unregister(self, heuristic_id: str) -> bool:
        with self._lock:
            before = len(self._heuristics)
            self._heuristics = [
                h for h in self._heuristics
                if h.id != heuristic_id
            ]
            return len(self._heuristics) < before

    # ── Evaluate ─────────────────────────────────────────

    def evaluate(
        self, ctx: dict[str, Any],
    ) -> HeuristicVerdict | None:
        if not isinstance(ctx, dict):
            raise ValueError("ctx must be a dict")
        with self._lock:
            heuristics = list(self._heuristics)
        for h in heuristics:
            try:
                if not h.predicate(ctx):
                    continue
            except Exception as exc:
                logger.debug(
                    "heuristic %s predicate raised: %s",
                    h.id, exc,
                )
                continue
            verdict = HeuristicVerdict(
                heuristic_id=h.id,
                action=h.action,
                reason=h.reason_template,
                confidence=h.confidence,
                ts=time.time(),
            )
            with self._lock:
                stats = self._stats.get(h.id)
                if stats is not None:
                    stats.fires += 1
                    stats.last_fired_ts = verdict.ts
                self._verdict_history.append(verdict)
                if len(self._verdict_history) > 500:
                    del self._verdict_history[
                        : len(self._verdict_history) - 500
                    ]
            return verdict
        return None

    # ── Feedback ─────────────────────────────────────────

    def record_outcome(
        self, heuristic_id: str, *, was_correct: bool,
    ) -> bool:
        with self._lock:
            stats = self._stats.get(heuristic_id)
            if stats is None:
                return False
            if was_correct:
                stats.hits += 1
            else:
                stats.misses += 1
            return True

    # ── Queries ──────────────────────────────────────────

    def heuristics(self) -> list[Heuristic]:
        with self._lock:
            return list(self._heuristics)

    def stats(self, heuristic_id: str | None = None) -> Any:
        with self._lock:
            if heuristic_id is not None:
                return self._stats.get(heuristic_id)
            return {
                "heuristics": len(self._heuristics),
                "fires_total": sum(
                    s.fires for s in self._stats.values()
                ),
                "by_id": {
                    k: v.as_dict()
                    for k, v in self._stats.items()
                },
            }

    def recent_verdicts(
        self, *, limit: int = 20,
    ) -> list[HeuristicVerdict]:
        with self._lock:
            return list(
                self._verdict_history[-max(1, int(limit)):],
            )

    def reset(self) -> int:
        with self._lock:
            n = sum(s.fires for s in self._stats.values())
            for s in self._stats.values():
                s.fires = 0
                s.hits = 0
                s.misses = 0
                s.last_fired_ts = 0.0
            self._verdict_history.clear()
        return n
