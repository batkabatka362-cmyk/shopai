"""Decision reversal detector — flag indecision in the brain.

A mature system should commit to a decision and watch it play out.
Flipping between "launch → pause → launch" on the same target within
a short window is usually noise or a broken rule, not real learning.
This module tracks per-target decision history and flags:

  • direct reversals   — A, then not-A, within ``window_seconds``
  • oscillations       — 3+ flips in a rolling window
  • churn_rate         — reversals / total decisions on that target

When oscillation_threshold is exceeded the module emits a
``ReversalAlert`` so the decision_brain can back off or escalate to
owner. Pure stdlib, deterministic.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Iterable

from utils.logger import get_logger


logger = get_logger("brain.decision_reversal_detector")


_DEFAULT_WINDOW_S = 6 * 3600
_DEFAULT_OSCILLATION_THRESHOLD = 3


@dataclass
class DecisionRecord:
    target: str
    action: str           # canonical action label
    ts: float
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "action": self.action,
            "ts": self.ts,
            "rationale": self.rationale,
        }


@dataclass
class ReversalAlert:
    id: str
    target: str
    kind: str                    # "direct" | "oscillation"
    flip_count: int
    window_seconds: float
    history: tuple[str, ...]     # recent action labels
    note: str
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "kind": self.kind,
            "flip_count": self.flip_count,
            "window_seconds": round(self.window_seconds, 1),
            "history": list(self.history),
            "note": self.note,
            "ts": self.ts,
        }


class DecisionReversalDetector:
    def __init__(
        self,
        *,
        window_seconds: float = _DEFAULT_WINDOW_S,
        oscillation_threshold: int = (
            _DEFAULT_OSCILLATION_THRESHOLD
        ),
        history_size: int = 20,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if oscillation_threshold < 2:
            raise ValueError(
                "oscillation_threshold must be ≥ 2",
            )
        if history_size < 3:
            raise ValueError("history_size must be ≥ 3")
        self._lock = threading.Lock()
        self._window = float(window_seconds)
        self._osc_threshold = int(oscillation_threshold)
        self._history_size = int(history_size)
        self._history: dict[str, Deque[DecisionRecord]] = (
            defaultdict(lambda: deque(maxlen=self._history_size))
        )
        self._alerts: list[ReversalAlert] = []

    # ── Intake ───────────────────────────────────────────

    def record(
        self,
        *,
        target: str,
        action: str,
        rationale: str = "",
        ts: float | None = None,
    ) -> ReversalAlert | None:
        if not target:
            raise ValueError("target required")
        if not action:
            raise ValueError("action required")
        timestamp = float(ts if ts is not None else time.time())
        rec = DecisionRecord(
            target=str(target),
            action=str(action),
            ts=timestamp,
            rationale=str(rationale),
        )
        alert: ReversalAlert | None = None
        with self._lock:
            history = self._history[rec.target]
            history.append(rec)
            alert = self._detect(rec.target, list(history))
            if alert is not None:
                self._alerts.append(alert)
                if len(self._alerts) > 200:
                    del self._alerts[: len(self._alerts) - 200]
        return alert

    def _detect(
        self, target: str, history: list[DecisionRecord],
    ) -> ReversalAlert | None:
        if len(history) < 2:
            return None
        latest = history[-1]
        prev = history[-2]
        within_window = (latest.ts - prev.ts) <= self._window
        # Direct reversal: latest action != previous within window
        if within_window and latest.action != prev.action:
            # Check for stricter "negation": prev was "kill", now
            # "launch", or vice versa. We detect flips between any
            # two distinct actions as long as we see *repeat* flips
            # later.
            pass
        # Oscillation: count distinct action changes in window
        cutoff = latest.ts - self._window
        recent = [r for r in history if r.ts >= cutoff]
        flips = 0
        for i in range(1, len(recent)):
            if recent[i].action != recent[i - 1].action:
                flips += 1
        if flips >= self._osc_threshold:
            history_actions = tuple(r.action for r in recent[-10:])
            return ReversalAlert(
                id=uuid.uuid4().hex,
                target=target,
                kind="oscillation",
                flip_count=flips,
                window_seconds=self._window,
                history=history_actions,
                note=(
                    f"{flips} flips on {target} in "
                    f"{self._window/3600:.1f}h — indecision"
                ),
                ts=latest.ts,
            )
        if within_window and flips == 1:
            return ReversalAlert(
                id=uuid.uuid4().hex,
                target=target,
                kind="direct",
                flip_count=1,
                window_seconds=latest.ts - prev.ts,
                history=(prev.action, latest.action),
                note=(
                    f"reversal on {target}: "
                    f"{prev.action} → {latest.action}"
                ),
                ts=latest.ts,
            )
        return None

    # ── Queries ──────────────────────────────────────────

    def churn_rate(self, target: str) -> float:
        with self._lock:
            history = list(self._history.get(target, ()))
        if len(history) < 2:
            return 0.0
        flips = sum(
            1 for i in range(1, len(history))
            if history[i].action != history[i - 1].action
        )
        return flips / (len(history) - 1)

    def history(
        self, target: str,
    ) -> list[DecisionRecord]:
        with self._lock:
            return list(self._history.get(target, ()))

    def alerts(
        self, *, limit: int = 20,
    ) -> list[ReversalAlert]:
        with self._lock:
            return list(self._alerts[-max(1, int(limit)):])

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tracked_targets": len(self._history),
                "alerts": len(self._alerts),
                "window_seconds": self._window,
                "oscillation_threshold": self._osc_threshold,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history) + len(self._alerts)
            self._history.clear()
            self._alerts.clear()
        return n
