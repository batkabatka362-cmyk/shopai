"""Compute budget — per-cycle compute / latency / token caps.

CLAUDE.md says cycle LLM cost should stay under $0.10 and that no
LLM-blocking call should sit in the hot path. This module makes
those commitments concrete:

  • ``register_budget(kind, max_per_cycle, warn_at)`` — caps per
    resource kind (usd, tokens, latency_ms, api_calls, ...)
  • ``spend(kind, amount)`` — charge a resource draw
  • ``remaining(kind)`` — what's left
  • ``check(kind)`` — raises ``OverBudgetError`` if over the cap;
    issues a ``BudgetAlert`` when warn_at is crossed

A cycle is demarcated by ``begin_cycle(cycle_id)`` /
``end_cycle(cycle_id)``. Between calls the detector accumulates
spend and emits alerts via a callback. After end_cycle the per-cycle
spend is archived and next cycle starts clean.

Pure stdlib, thread-safe, deterministic. Complements
``meta_reasoner`` (which watches *quality* of reasoning) by watching
the *cost* of it.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.compute_budget")


@dataclass
class BudgetSpec:
    kind: str
    max_per_cycle: float
    warn_at: float              # fraction (0..1) of cap to warn

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("kind required")
        if self.max_per_cycle <= 0:
            raise ValueError("max_per_cycle must be > 0")
        if not 0.0 < self.warn_at <= 1.0:
            raise ValueError(
                "warn_at must be in (0, 1]",
            )


@dataclass
class BudgetAlert:
    id: str
    cycle_id: str
    kind: str
    level: str                  # "warn" | "over"
    spent: float
    cap: float
    note: str
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cycle_id": self.cycle_id,
            "kind": self.kind,
            "level": self.level,
            "spent": round(self.spent, 6),
            "cap": round(self.cap, 6),
            "note": self.note,
            "ts": self.ts,
        }


@dataclass
class CycleReport:
    cycle_id: str
    spent_by_kind: dict[str, float]
    caps: dict[str, float]
    started_ts: float
    ended_ts: float
    alerts: list[BudgetAlert]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "spent_by_kind": {
                k: round(v, 6)
                for k, v in self.spent_by_kind.items()
            },
            "caps": {
                k: round(v, 6) for k, v in self.caps.items()
            },
            "started_ts": self.started_ts,
            "ended_ts": self.ended_ts,
            "alerts": [a.as_dict() for a in self.alerts],
        }


class OverBudgetError(RuntimeError):
    pass


class ComputeBudget:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._budgets: dict[str, BudgetSpec] = {}
        self._current_cycle: str | None = None
        self._current_started: float = 0.0
        self._current_spent: dict[str, float] = defaultdict(float)
        self._current_alerts: list[BudgetAlert] = []
        self._warned: set[tuple[str, str]] = set()
        # (cycle_id, kind) pairs already warned
        self._archive: list[CycleReport] = []
        self._alert_callback: Callable[[BudgetAlert], None] | None = None

    # ── Config ───────────────────────────────────────────

    def register_budget(self, spec: BudgetSpec) -> None:
        with self._lock:
            self._budgets[spec.kind] = spec

    def set_alert_callback(
        self,
        callback: Callable[[BudgetAlert], None] | None,
    ) -> None:
        with self._lock:
            self._alert_callback = callback

    # ── Cycle lifecycle ──────────────────────────────────

    def begin_cycle(
        self,
        cycle_id: str,
        *,
        ts: float | None = None,
    ) -> None:
        if not cycle_id:
            raise ValueError("cycle_id required")
        with self._lock:
            if self._current_cycle is not None:
                raise ValueError(
                    f"cycle {self._current_cycle!r} still open",
                )
            self._current_cycle = cycle_id
            self._current_started = float(
                ts if ts is not None else time.time(),
            )
            self._current_spent.clear()
            self._current_alerts.clear()
            self._warned.clear()

    def end_cycle(
        self,
        *,
        ts: float | None = None,
    ) -> CycleReport | None:
        with self._lock:
            if self._current_cycle is None:
                return None
            report = CycleReport(
                cycle_id=self._current_cycle,
                spent_by_kind=dict(self._current_spent),
                caps={
                    k: b.max_per_cycle
                    for k, b in self._budgets.items()
                },
                started_ts=self._current_started,
                ended_ts=float(
                    ts if ts is not None else time.time(),
                ),
                alerts=list(self._current_alerts),
            )
            self._archive.append(report)
            if len(self._archive) > 200:
                del self._archive[: len(self._archive) - 200]
            self._current_cycle = None
            self._current_started = 0.0
            self._current_spent.clear()
            self._current_alerts.clear()
            self._warned.clear()
            return report

    # ── Spend ────────────────────────────────────────────

    def spend(
        self, kind: str, amount: float,
    ) -> BudgetAlert | None:
        if not kind:
            raise ValueError("kind required")
        if amount < 0:
            raise ValueError("amount must be ≥ 0")
        with self._lock:
            if self._current_cycle is None:
                # allow spend outside a cycle — no enforcement
                return None
            self._current_spent[kind] += float(amount)
            spec = self._budgets.get(kind)
            if spec is None:
                return None
            cap = spec.max_per_cycle
            spent = self._current_spent[kind]
            if spent > cap:
                alert = BudgetAlert(
                    id=uuid.uuid4().hex,
                    cycle_id=self._current_cycle,
                    kind=kind,
                    level="over",
                    spent=spent,
                    cap=cap,
                    note=(
                        f"over-budget: {spent:.4f} > cap {cap:.4f}"
                    ),
                    ts=time.time(),
                )
                self._current_alerts.append(alert)
                self._dispatch(alert)
                return alert
            warn_line = cap * spec.warn_at - 1e-9
            if spent >= warn_line:
                key = (self._current_cycle, kind)
                if key not in self._warned:
                    self._warned.add(key)
                    alert = BudgetAlert(
                        id=uuid.uuid4().hex,
                        cycle_id=self._current_cycle,
                        kind=kind,
                        level="warn",
                        spent=spent,
                        cap=cap,
                        note=(
                            f"{spent/cap*100:.1f}% of cap; "
                            f"warn at {spec.warn_at*100:.0f}%"
                        ),
                        ts=time.time(),
                    )
                    self._current_alerts.append(alert)
                    self._dispatch(alert)
                    return alert
            return None

    def check(self, kind: str) -> None:
        with self._lock:
            if self._current_cycle is None:
                return
            spec = self._budgets.get(kind)
            if spec is None:
                return
            spent = self._current_spent.get(kind, 0.0)
            if spent > spec.max_per_cycle:
                raise OverBudgetError(
                    f"{kind}: {spent:.4f} > {spec.max_per_cycle:.4f}",
                )

    def remaining(self, kind: str) -> float:
        with self._lock:
            spec = self._budgets.get(kind)
            if spec is None:
                return float("inf")
            return max(
                0.0,
                spec.max_per_cycle
                - self._current_spent.get(kind, 0.0),
            )

    def _dispatch(self, alert: BudgetAlert) -> None:
        cb = self._alert_callback
        if cb is None:
            return
        try:
            cb(alert)
        except Exception as exc:
            logger.debug(
                "alert callback raised: %s", exc,
            )

    # ── Queries ──────────────────────────────────────────

    def current_spend(self) -> dict[str, float]:
        with self._lock:
            return dict(self._current_spent)

    def current_alerts(self) -> list[BudgetAlert]:
        with self._lock:
            return list(self._current_alerts)

    def archive(
        self, *, limit: int = 10,
    ) -> list[CycleReport]:
        with self._lock:
            return list(self._archive[-max(1, int(limit)):])

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "current_cycle": self._current_cycle,
                "budgets": {
                    k: {
                        "cap": s.max_per_cycle,
                        "warn_at": s.warn_at,
                    }
                    for k, s in self._budgets.items()
                },
                "archived_cycles": len(self._archive),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._archive)
            self._budgets.clear()
            self._current_cycle = None
            self._current_spent.clear()
            self._current_alerts.clear()
            self._warned.clear()
            self._archive.clear()
        return n
