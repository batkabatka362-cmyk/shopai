"""Auto-replay coordinator for dead-letter entries — Upgrade 2.

The dead-letter ledger (Option Y) captures every exhausted router
call so it isn't silently lost. But a queued entry stays a dead
record forever unless an operator manually replays it — even
after the underlying adapter has fully recovered. The system
sees the adapter come back healthy and carries on serving new
traffic while the old failures stay stuck.

This module closes that gap.

``AutoReplayCoordinator`` periodically scans the dead-letter
ledger, classifies each entry by the CURRENT health of its
adapter, and emits a replay-readiness event for every entry
whose adapter has recovered since the record was written.

Why "coordinator" and not "engine"?
-----------------------------------

We deliberately do NOT execute the replays from inside this
module. The dead-letter ledger persists only a sanitized
``params_snapshot`` — never the full original params — because
the original dict may have contained PII or large prompt bodies
we refuse to persist unencrypted. Genuine replay therefore
requires the ORIGINAL caller to keep a reference to the full
params; the coordinator just signals "now is a good time".

The contract:

* ``scan()`` returns a typed report with three buckets:
    - ``ready``    — adapter is healthy, entry not yet replayed
    - ``degraded`` — adapter still unhealthy; entry stays dormant
    - ``replayed`` — entry previously marked replayed (idempotent)
* ``mark_replayed(entry_id)`` is called by upstream once replay
  is attempted, so the entry drops out of subsequent ``ready``
  buckets regardless of replay outcome.
* ``register_replay_callback(fn)`` lets a controller hook an
  "auto-execute" strategy in: the coordinator calls ``fn(entry)``
  on every ``ready`` entry during ``scan()``; the callback is
  responsible for deciding whether to actually execute and for
  calling ``mark_replayed`` on success.

Design rules:

* Rate-limited. Cap entries processed per scan
  (``max_ready_per_scan``) so a huge backlog can't starve the
  cycle loop.
* In-memory idempotency. The coordinator tracks replayed IDs in
  a bounded LRU so a long-running process doesn't grow memory.
  The dead-letter ledger is already the authoritative record.
* Health check is ledger-based — it asks the route-weight
  ledger AND the router's breaker snapshot. An entry is "ready"
  only when neither signal is blocking.
* Never raises. A failing callback or missing dep is swallowed
  with a WARN log; the coordinator keeps going.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger

logger = get_logger("adapters.auto_replay")


# ── Config ──────────────────────────────────────────────────

_DEFAULT_MAX_READY_PER_SCAN = 25
_DEFAULT_REPLAYED_LRU_MAX = 1024
# Minimum age before an entry is eligible — prevents the
# coordinator from replaying a brand-new failure that might still
# be in the router's retry loop on a different worker.
_DEFAULT_MIN_AGE_SEC = 60.0


# ── Report types ────────────────────────────────────────────


@dataclass
class ReplayCandidate:
    entry_id: str
    adapter: str
    capability: str
    age_s: float
    attempts: int
    reason: str
    params_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "adapter": self.adapter,
            "capability": self.capability,
            "age_s": round(self.age_s, 1),
            "attempts": self.attempts,
            "reason": self.reason,
            "params_snapshot": dict(self.params_snapshot),
        }


@dataclass
class ReplayReport:
    timestamp: float
    ready: list[ReplayCandidate] = field(default_factory=list)
    degraded: list[ReplayCandidate] = field(default_factory=list)
    replayed: list[str] = field(default_factory=list)
    skipped_recent: int = 0
    callback_invocations: int = 0
    callback_failures: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "ready": [c.to_dict() for c in self.ready],
            "degraded": [c.to_dict() for c in self.degraded],
            "replayed": list(self.replayed),
            "skipped_recent": self.skipped_recent,
            "callback_invocations": self.callback_invocations,
            "callback_failures": self.callback_failures,
        }


# ── Coordinator ─────────────────────────────────────────────


class AutoReplayCoordinator:
    """Process-wide coordinator; one instance per router/process."""

    def __init__(
        self,
        *,
        max_ready_per_scan: int = _DEFAULT_MAX_READY_PER_SCAN,
        replayed_lru_max: int = _DEFAULT_REPLAYED_LRU_MAX,
        min_age_sec: float = _DEFAULT_MIN_AGE_SEC,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_ready_per_scan < 1:
            raise ValueError("max_ready_per_scan must be >= 1")
        if replayed_lru_max < 1:
            raise ValueError("replayed_lru_max must be >= 1")
        self._max_ready = int(max_ready_per_scan)
        self._lru_max = int(replayed_lru_max)
        self._min_age = float(min_age_sec)
        self._clock = clock
        self._lock = threading.RLock()
        # OrderedDict preserves insertion order so we can evict
        # the oldest entries when the LRU hits its cap.
        self._replayed: OrderedDict[str, float] = OrderedDict()
        self._callback: Callable[[Any], Any] | None = None
        # Cumulative counters for the dashboard.
        self._total_scans = 0
        self._total_ready = 0
        self._total_callback_failures = 0

    # ── Public API ──────────────────────────────────────────

    def register_replay_callback(
        self,
        fn: Callable[[Any], Any] | None,
    ) -> None:
        """Install a callback called once per ``ready`` entry
        during ``scan()``. Pass ``None`` to unregister."""
        with self._lock:
            self._callback = fn

    def mark_replayed(self, entry_id: str) -> None:
        """Flag ``entry_id`` so it never shows up in ``ready``
        again. Idempotent: re-marking is a no-op. When the LRU is
        full we evict the oldest-flagged ID first."""
        if not entry_id:
            return
        now = self._clock()
        with self._lock:
            if entry_id in self._replayed:
                # Refresh position (move-to-end).
                self._replayed.move_to_end(entry_id)
                self._replayed[entry_id] = now
                return
            self._replayed[entry_id] = now
            while len(self._replayed) > self._lru_max:
                self._replayed.popitem(last=False)

    def is_replayed(self, entry_id: str) -> bool:
        with self._lock:
            return entry_id in self._replayed

    def reset(self) -> None:
        """Test helper — clear replay memory + counters."""
        with self._lock:
            self._replayed.clear()
            self._callback = None
            self._total_scans = 0
            self._total_ready = 0
            self._total_callback_failures = 0

    def snapshot(self) -> dict[str, Any]:
        """Dashboard-ready rollup."""
        with self._lock:
            return {
                "replayed_tracked": len(self._replayed),
                "replayed_lru_max": self._lru_max,
                "total_scans": self._total_scans,
                "total_ready": self._total_ready,
                "total_callback_failures": self._total_callback_failures,
                "max_ready_per_scan": self._max_ready,
                "min_age_sec": self._min_age,
                "callback_registered": self._callback is not None,
            }

    def scan(self) -> ReplayReport:
        """Walk the dead-letter ledger and classify each entry.

        Returns a ``ReplayReport``. Callers may treat the
        ``ready`` bucket as "please execute these now" or simply
        surface it on a dashboard.
        """
        now = self._clock()
        report = ReplayReport(timestamp=now)
        with self._lock:
            self._total_scans += 1

        # Pull the dead-letter snapshot defensively — dep errors
        # must never break the caller's cycle.
        try:
            from core.adapters.deadletter import get_dead_letter_ledger
            entries = get_dead_letter_ledger().recent(limit=500)
        except Exception as exc:  # noqa: BLE001
            logger.debug("auto_replay: ledger read failed: %s", exc)
            return report

        # Process OLDEST first for fairness — a chronic producer
        # of new failures must not starve stale-but-eligible
        # entries forever. ``recent`` returns newest-first; we
        # reverse so the backlog clears in arrival order.
        entries = list(reversed(entries))

        # Health probes (lazy imports: both modules are optional
        # for environments that don't ship the full adapter layer).
        try:
            from core.adapters import router as _router_mod
            router = getattr(_router_mod, "_router", None)
            breaker_map: dict[str, dict[str, Any]] = {}
            if router is not None:
                try:
                    breaker_map = dict(router.breaker_snapshot() or {})
                except Exception as exc:  # noqa: BLE001
                    logger.debug("auto_replay: breaker snap: %s", exc)
                    breaker_map = {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("auto_replay: router module missing: %s", exc)
            breaker_map = {}

        try:
            from core.adapters.route_weights import (
                get_route_weight_ledger,
            )
            weights = get_route_weight_ledger()
        except Exception as exc:  # noqa: BLE001
            logger.debug("auto_replay: route_weights missing: %s", exc)
            weights = None

        callback = None
        with self._lock:
            callback = self._callback

        ready_yielded = 0
        for entry in entries:
            eid = getattr(entry, "id", "") or ""
            if not eid:
                continue

            age_s = max(0.0, now - float(entry.timestamp))
            if age_s < self._min_age:
                report.skipped_recent += 1
                continue

            with self._lock:
                already = eid in self._replayed
            if already:
                report.replayed.append(eid)
                continue

            adapter_name = entry.adapter
            capability = entry.capability

            # Health assessment: entry is READY when both signals
            # are clear.
            blocked_by: list[str] = []
            breaker = breaker_map.get(adapter_name) or {}
            state = str(breaker.get("state", "closed") or "closed").lower()
            if state in ("open", "half_open"):
                blocked_by.append(f"breaker={state}")

            if weights is not None:
                w = weights.get(adapter_name, capability)
                # A weight below 0.5 means reflection has
                # specifically penalised this pair.
                if w < 0.5:
                    blocked_by.append(f"route_weight={w:.2f}")

            candidate = ReplayCandidate(
                entry_id=eid,
                adapter=adapter_name,
                capability=capability,
                age_s=age_s,
                attempts=int(getattr(entry, "attempts", 0) or 0),
                reason=(
                    "healthy"
                    if not blocked_by
                    else "|".join(blocked_by)
                ),
                params_snapshot=dict(
                    getattr(entry, "params_snapshot", {}) or {}
                ),
            )

            if blocked_by:
                report.degraded.append(candidate)
                continue

            # READY — respect the per-scan rate limit.
            if ready_yielded >= self._max_ready:
                # Everything beyond the cap stays in the backlog
                # for the next scan. We count it in neither bucket
                # so operators know "there's more but we throttled".
                continue
            report.ready.append(candidate)
            ready_yielded += 1

            with self._lock:
                self._total_ready += 1

            if callback is not None:
                report.callback_invocations += 1
                try:
                    result = callback(entry)
                except Exception as exc:  # noqa: BLE001
                    report.callback_failures += 1
                    with self._lock:
                        self._total_callback_failures += 1
                    logger.warning(
                        "auto_replay: callback failed for %s (%s/%s): %s",
                        eid, adapter_name, capability, exc,
                    )
                else:
                    # Truthy return → replay succeeded; mark the
                    # entry so it drops out of future scans. Falsy
                    # return → leave it for the next scan (caller
                    # decided not to replay, perhaps because the
                    # adapter was still tagged degraded upstream).
                    # This relieves the caller from having to call
                    # ``mark_replayed`` manually on the success
                    # path, which was the most common mistake in
                    # early integration code.
                    if result:
                        self.mark_replayed(eid)

        return report


# ── Singleton ────────────────────────────────────────────

_default_coordinator: AutoReplayCoordinator | None = None
_default_lock = threading.Lock()


def get_auto_replay_coordinator() -> AutoReplayCoordinator:
    """Process-wide singleton."""
    global _default_coordinator
    if _default_coordinator is None:
        with _default_lock:
            if _default_coordinator is None:
                _default_coordinator = AutoReplayCoordinator()
    return _default_coordinator


def reset_auto_replay_coordinator() -> None:
    """Test helper — drop the singleton."""
    global _default_coordinator
    with _default_lock:
        _default_coordinator = None
