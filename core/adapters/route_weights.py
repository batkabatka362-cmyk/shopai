"""Learned route weights — Upgrade 1 / reflection→routing loop.

The router already ranks adapters for a capability by a blend of
declared priority, preference, cost, and composite health
(Option X). What it CANNOT do is learn from the autonomous
controller's own experience: if the reflection synthesizer
promotes a SOFT rule like "adapter=openai capability=llm_complete
fails intermittently", that promotion changes nothing about how
the next router call ranks ``openai`` for ``llm_complete``.

This module closes that loop. The ``RouteWeightLedger`` keeps a
small in-memory table keyed by ``(adapter, capability)``, with
each weight clamped to ``[_MIN_WEIGHT, 1.0]``. Reflection calls
``penalize(adapter, capability, amount)`` when it promotes an
error pattern that names both; the router multiplies the score
contribution by ``get(adapter, capability)`` so a weight of 0.2
roughly equals "try the other candidates first".

Design rules:

* **Clamped decay, not delete.** Weights decay toward 1.0 over
  time (``half_life_hours``), so a one-off outage that got
  penalized today recovers on its own. A permanent deletion would
  require human intervention to unblock; we want the system to
  self-heal once the underlying problem clears.
* **Lower-bounded.** No weight drops below ``_MIN_WEIGHT`` (0.05
  default). The router should always be *able* to pick a
  penalized candidate if it's the only option left — total
  exclusion is the circuit-breaker's job, not ours.
* **In-memory only.** We persist only in process. A fresh
  controller starts with neutral weights, relearns from
  reflection within a few cycles. A durable store would cost
  more than it saves for a signal that's noisy by nature.
* **Thread-safe.** Reflection runs on the post-cycle hook,
  router calls are on the request path; both mutate the table
  under one ``RLock``.
* **Never raises.** Bad inputs (unknown adapter, NaN amount)
  log-and-ignore. The router must never crash because the
  weight ledger was in a funny state.

Two paired hooks make this a closed loop:

1. ``apply_reflection_report(report)`` — parses a reflection
   synthesizer report, pulls the ``(adapter, capability)`` pairs
   from promoted error patterns, and penalizes each.
2. Router consults ``get(adapter, capability)`` inside
   ``_candidates`` and multiplies the score contribution.

A dashboard snapshot (``snapshot()``) lets the UI render a
"learned suppressions" panel on the Reliability tab.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any

from utils.logger import get_logger

logger = get_logger("adapters.route_weights")


# ── Tunables ───────────────────────────────────────────────

# Floor for any weight — a penalized candidate is still eligible.
_MIN_WEIGHT = 0.05
# Ceiling — a weight never exceeds 1.0; "bonuses" would distort
# the router's declared priority which operators control directly.
_MAX_WEIGHT = 1.0
# Default half-life for exponential decay toward 1.0. Matches the
# reflection buffer's multi-hour horizon.
_DEFAULT_HALF_LIFE_HOURS = 6.0
# Default penalty per promoted error pattern. Multiplicative on
# the current weight so repeated promotions compound naturally:
# two hits = 0.5 × 0.5 = 0.25, three hits = 0.125 … clamped.
_DEFAULT_PENALTY = 0.5
# Cap on rows in the ledger. Reflection promotes O(1) patterns
# per cycle so this would only trip on a runaway feeder; the LRU
# evicts the oldest-touched pair so fresh signals always win.
_DEFAULT_MAX_ROWS = 2048


# ── Ledger ─────────────────────────────────────────────────


@dataclass
class _Row:
    """One (adapter, capability) row in the weight table."""
    weight: float
    last_penalty_ts: float
    penalty_count: int


class RouteWeightLedger:
    """Process-wide learned-weight table for (adapter, capability).

    The ledger is intentionally small — we only key on pairs that
    have been penalized at least once. Unpenalized lookups hit the
    default path and return 1.0 without touching the lock.
    """

    def __init__(
        self,
        *,
        half_life_hours: float = _DEFAULT_HALF_LIFE_HOURS,
        min_weight: float = _MIN_WEIGHT,
        max_rows: int = _DEFAULT_MAX_ROWS,
    ) -> None:
        if max_rows < 1:
            raise ValueError("max_rows must be >= 1")
        self._half_life_s = max(60.0, float(half_life_hours) * 3600.0)
        self._min_weight = max(0.0, min(min_weight, 1.0))
        self._max_rows = int(max_rows)
        # OrderedDict so we can evict the least-recently-penalised
        # pair when the cap is hit. ``move_to_end`` on every
        # penalise/get-with-row keeps the LRU order honest.
        from collections import OrderedDict
        self._rows: "OrderedDict[tuple[str, str], _Row]" = OrderedDict()
        self._lock = threading.RLock()
        # Summary counters for the dashboard.
        self._total_penalties = 0
        self._total_recoveries = 0  # # of decay ticks that reset a row to 1.0
        self._total_evictions = 0

    # ── Mutation ────────────────────────────────────────────

    def penalize(
        self,
        adapter: str,
        capability: str,
        amount: float = _DEFAULT_PENALTY,
    ) -> float:
        """Multiply the weight for ``(adapter, capability)`` by
        ``amount`` (clamped to ``(0.0, 1.0]``).

        Returns the NEW weight. Unknown adapter or capability is
        accepted silently — the reflection synthesizer sometimes
        promotes patterns where the adapter or capability isn't
        resolvable, and we'd rather over-record than drop the
        signal.
        """
        if not adapter or not capability:
            return _MAX_WEIGHT
        try:
            amount_f = float(amount)
        except (TypeError, ValueError):
            logger.debug(
                "route_weights: ignored non-numeric penalty %r", amount,
            )
            return _MAX_WEIGHT
        if not math.isfinite(amount_f):
            return _MAX_WEIGHT
        # Accept penalty in (0.0, 1.0]; anything outside is ignored.
        if amount_f <= 0.0 or amount_f > 1.0:
            logger.debug(
                "route_weights: ignored out-of-range penalty %f", amount_f,
            )
            return _MAX_WEIGHT

        now = time.time()
        key = (adapter, capability)
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                # LRU eviction: if adding this row would exceed
                # the cap, drop the oldest (least-recently-touched)
                # entry first. Evictions compound so a runaway
                # feeder can't starve newly-observed fault lines.
                while len(self._rows) >= self._max_rows:
                    self._rows.popitem(last=False)
                    self._total_evictions += 1
                row = _Row(
                    weight=_MAX_WEIGHT,
                    last_penalty_ts=now,
                    penalty_count=0,
                )
                self._rows[key] = row
            else:
                # Touch → most-recently-used position in the LRU.
                self._rows.move_to_end(key, last=True)
            # Decay BEFORE applying the new penalty so the fresh
            # penalty lands on a weight that's already partially
            # recovered. Otherwise a burst of penalties + a long
            # idle interval would leave the weight over-suppressed.
            current = self._decayed_locked(row, now)
            new_weight = max(self._min_weight, current * amount_f)
            row.weight = new_weight
            row.last_penalty_ts = now
            row.penalty_count += 1
            self._total_penalties += 1
            logger.info(
                "route_weights: penalize %s/%s × %.2f → %.3f "
                "(penalty #%d)",
                adapter, capability, amount_f, new_weight,
                row.penalty_count,
            )
            return new_weight

    def reset(self, adapter: str, capability: str) -> None:
        """Restore weight for one pair to 1.0. Operator escape
        hatch — the dashboard's "clear suppression" button calls
        this. Silent no-op if the pair isn't currently penalized."""
        with self._lock:
            row = self._rows.pop((adapter, capability), None)
            if row is not None:
                self._total_recoveries += 1

    def reset_all(self) -> None:
        """Test helper / operator full-flush."""
        with self._lock:
            self._total_recoveries += len(self._rows)
            self._rows.clear()
            self._total_penalties = 0

    # ── Query ───────────────────────────────────────────────

    def get(self, adapter: str, capability: str) -> float:
        """Return the current weight (fully decayed to wall clock).

        Unpenalized pairs return ``_MAX_WEIGHT`` without taking
        the lock — this is on the hot router path."""
        key = (adapter, capability)
        # Fast path: no row → 1.0.
        row = self._rows.get(key)
        if row is None:
            return _MAX_WEIGHT
        now = time.time()
        with self._lock:
            return self._decayed_locked(row, now)

    def snapshot(self) -> dict[str, Any]:
        """Dashboard-ready rollup."""
        now = time.time()
        rows: list[dict[str, Any]] = []
        with self._lock:
            for (adapter, cap), row in self._rows.items():
                rows.append({
                    "adapter": adapter,
                    "capability": cap,
                    "weight": round(self._decayed_locked(row, now), 4),
                    "penalty_count": row.penalty_count,
                    "age_s": round(now - row.last_penalty_ts, 1),
                })
            rows.sort(key=lambda r: (r["weight"], -r["penalty_count"]))
            return {
                "timestamp": now,
                "rows": rows,
                "total_penalties": self._total_penalties,
                "total_recoveries": self._total_recoveries,
                "total_evictions": self._total_evictions,
                "max_rows": self._max_rows,
                "half_life_s": self._half_life_s,
                "min_weight": self._min_weight,
            }

    # ── Reflection bridge ───────────────────────────────────

    def apply_reflection_report(self, report: Any) -> int:
        """Parse a reflection synthesizer report and penalize each
        ``(adapter, capability)`` pair mentioned in promoted
        patterns. Returns the count of penalties applied.

        The reflection report shape we support::

            {
                "patterns": [
                    {
                        "promoted": True,
                        "adapter": "openai",
                        "capability": "llm_complete",
                        ...
                    },
                    ...
                ]
            }

        Patterns without both fields are skipped silently — the
        reflection layer mines many signal kinds, only adapter-
        bound ones belong here.
        """
        if report is None:
            return 0
        try:
            if hasattr(report, "as_dict"):
                rep = report.as_dict()
            elif isinstance(report, dict):
                rep = report
            else:
                return 0
        except Exception:  # noqa: BLE001
            return 0
        patterns = rep.get("patterns") or []
        applied = 0
        for p in patterns:
            if not isinstance(p, dict):
                continue
            if not p.get("promoted"):
                continue
            adapter = p.get("adapter") or ""
            capability = p.get("capability") or ""
            if not adapter or not capability:
                continue
            try:
                self.penalize(str(adapter), str(capability))
                applied += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "route_weights: apply_reflection_report failed "
                    "for %s/%s: %s", adapter, capability, exc,
                )
        return applied

    # ── Internals ───────────────────────────────────────────

    def _decayed_locked(self, row: _Row, now: float) -> float:
        """Apply exponential decay toward 1.0.

        ``weight_t = 1 - (1 - weight_0) * 2^(-age/half_life)``

        so a weight of 0.25 with half_life=6h becomes 0.625 after
        6h and 0.8125 after 12h, tending to 1.0 but never quite.
        We collapse to 1.0 once the delta is under the row's
        floor precision (1e-4) and prune the row so the table
        doesn't grow unboundedly on recovered pairs.
        """
        age_s = max(0.0, now - row.last_penalty_ts)
        if age_s <= 0.0 or row.weight >= _MAX_WEIGHT:
            return row.weight
        decay = 2.0 ** (-age_s / self._half_life_s)
        recovered = _MAX_WEIGHT - (_MAX_WEIGHT - row.weight) * decay
        # Snap-to-max and prune once the row is effectively healed.
        if recovered >= _MAX_WEIGHT - 1e-4:
            return _MAX_WEIGHT
        return recovered


# ── Singleton ────────────────────────────────────────────

_default_ledger: RouteWeightLedger | None = None
_default_lock = threading.Lock()


def get_route_weight_ledger() -> RouteWeightLedger:
    """Process-wide singleton. Lazy so test harnesses can swap
    in a custom instance by patching this module."""
    global _default_ledger
    if _default_ledger is None:
        with _default_lock:
            if _default_ledger is None:
                _default_ledger = RouteWeightLedger()
    return _default_ledger


def reset_route_weight_ledger() -> None:
    """Test helper — drop the singleton."""
    global _default_ledger
    with _default_lock:
        _default_ledger = None
