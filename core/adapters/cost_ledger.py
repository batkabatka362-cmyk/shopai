"""Per-caller cost attribution — Option Z.

The existing ``BudgetLedger`` (Option T) tracks cumulative spend per
adapter, which is enough to enforce hard caps. But it can't answer
the question a human operator actually asks: *"why did this month's
OpenAI bill double?"*.  The spend might be one runaway reflection
loop, a new customer-support flow, or a drive-by experiment — and
without caller attribution, every debug session ends with ``grep``
across the codebase.

This module adds a second, independent ledger keyed by the
``(caller, adapter, capability)`` tuple.  The router books every
realised cost into it alongside the existing budget ledger; the
dashboard surfaces per-caller totals so operators can drill from
"total spend" → "which caller" → "which adapter/capability".

Design notes:

* **Additive**.  The module does NOT replace ``BudgetLedger``.  The
  enforcement path stays exactly where it is — this ledger is pure
  telemetry, so a bug here can never take the router offline.
* **Sanitised callers**.  Caller tags are lowercase alphanumerics
  plus ``_.-/`` so a stray user input can't explode the table.
  Anything else collapses to ``"unknown"``.
* **Bounded**.  Unique ``(caller, adapter, capability)`` tuples are
  capped (``max_keys``) so a buggy caller generating a fresh tag per
  request can't OOM the process.  Overflow counts into a single
  ``"__overflow__"`` bucket the dashboard surfaces explicitly.
* **Hot-path cheap**.  ``record`` is O(1), one lock, no allocation on
  the common "tuple already exists" path.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

logger = get_logger("adapters.cost_ledger")


# ── Constants ──────────────────────────────────────────────────

DEFAULT_CALLER = "unknown"
OVERFLOW_CALLER = "__overflow__"

# Caller tags must be short, filesystem-safe, and reversible to text.
# We deliberately forbid spaces and most punctuation so the tag can
# appear in logs, metric labels, and URLs without escaping.
_CALLER_RE = re.compile(r"^[a-z0-9_.\-/]{1,64}$")


# ── Dataclasses ────────────────────────────────────────────────


@dataclass
class CostEntry:
    """One cost-bucket row: a ``(caller, adapter, capability)`` total."""

    caller: str
    adapter: str
    capability: str
    total_usd: float = 0.0
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "adapter": self.adapter,
            "capability": self.capability,
            "total_usd": round(self.total_usd, 6),
            "calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


# ── Ledger ─────────────────────────────────────────────────────


class CostLedger:
    """Thread-safe per-caller cost accumulator.

    Usage from the router::

        ledger.record(
            caller="support_agent",
            adapter="openai",
            capability="chat_complete",
            usd=0.00043,
            tokens_in=812,
            tokens_out=140,
        )

    Usage from the dashboard::

        snap = ledger.snapshot()
        # -> {"total_usd": ..., "per_caller": [...], "rows": [...]}
    """

    def __init__(
        self,
        *,
        max_keys: int = 2048,
        clock: callable = time.time,
    ) -> None:
        if max_keys <= 0:
            raise ValueError("max_keys must be positive")
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str, str], CostEntry] = {}
        self._overflow_calls = 0
        self._overflow_usd = 0.0

    # ── Normalisation ──────────────────────────────────

    @staticmethod
    def normalise_caller(caller: str | None) -> str:
        """Return a safe caller tag, collapsing unknown shapes.

        Accepts ``None`` and arbitrary strings.  Lower-cases, strips,
        and validates against a conservative allow-list — anything
        that doesn't match is flattened to ``"unknown"`` so a buggy
        caller can't fragment the table or inject label shapes the
        dashboard doesn't expect.
        """
        if not caller:
            return DEFAULT_CALLER
        tag = str(caller).strip().lower()
        if not tag:
            return DEFAULT_CALLER
        if not _CALLER_RE.match(tag):
            return DEFAULT_CALLER
        return tag

    # ── Write path ─────────────────────────────────────

    def record(
        self,
        *,
        caller: str | None,
        adapter: str,
        capability: str,
        usd: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Book a realised cost into the ledger.

        Must NOT raise: the router calls this on the hot path after
        a successful adapter execution, and a ledger fault must
        never mask a good result.
        """
        try:
            if usd is None or float(usd) <= 0:
                return
            tag = self.normalise_caller(caller)
            ad = str(adapter or "unknown").strip() or "unknown"
            cap = str(capability or "unknown").strip() or "unknown"
            now = self._clock()
            key = (tag, ad, cap)
            with self._lock:
                entry = self._entries.get(key)
                if entry is None:
                    if len(self._entries) >= self._max_keys:
                        # Fold into the overflow bucket so the bill
                        # still adds up, but don't let a runaway
                        # caller fragment the table.
                        self._overflow_calls += 1
                        self._overflow_usd += float(usd)
                        return
                    entry = CostEntry(
                        caller=tag, adapter=ad, capability=cap,
                        first_seen=now,
                    )
                    self._entries[key] = entry
                entry.total_usd += float(usd)
                entry.calls += 1
                entry.tokens_in += int(tokens_in or 0)
                entry.tokens_out += int(tokens_out or 0)
                entry.last_seen = now
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("cost_ledger record failed: %s", exc)

    # ── Read path ──────────────────────────────────────

    def rows(self) -> list[dict[str, Any]]:
        """Flat list of every ``(caller, adapter, capability)`` row.

        Sorted by ``total_usd`` descending so the dashboard renders
        big spenders first without client-side sorting.
        """
        with self._lock:
            rows = [e.to_dict() for e in self._entries.values()]
        rows.sort(key=lambda r: r["total_usd"], reverse=True)
        return rows

    def per_caller(self) -> list[dict[str, Any]]:
        """Roll rows up to one row per caller."""
        acc: dict[str, dict[str, Any]] = {}
        with self._lock:
            for entry in self._entries.values():
                row = acc.setdefault(entry.caller, {
                    "caller": entry.caller,
                    "total_usd": 0.0,
                    "calls": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "adapters": set(),
                    "capabilities": set(),
                })
                row["total_usd"] += entry.total_usd
                row["calls"] += entry.calls
                row["tokens_in"] += entry.tokens_in
                row["tokens_out"] += entry.tokens_out
                row["adapters"].add(entry.adapter)
                row["capabilities"].add(entry.capability)
        out: list[dict[str, Any]] = []
        for row in acc.values():
            out.append({
                "caller": row["caller"],
                "total_usd": round(row["total_usd"], 6),
                "calls": row["calls"],
                "tokens_in": row["tokens_in"],
                "tokens_out": row["tokens_out"],
                "adapter_count": len(row["adapters"]),
                "capability_count": len(row["capabilities"]),
            })
        out.sort(key=lambda r: r["total_usd"], reverse=True)
        return out

    def total_usd(self) -> float:
        with self._lock:
            return round(
                sum(e.total_usd for e in self._entries.values())
                + self._overflow_usd,
                6,
            )

    def snapshot(self) -> dict[str, Any]:
        """Dashboard-ready envelope."""
        with self._lock:
            overflow = {
                "calls": self._overflow_calls,
                "usd": round(self._overflow_usd, 6),
                "active": self._overflow_calls > 0,
            }
            key_count = len(self._entries)
        return {
            "timestamp": self._clock(),
            "total_usd": self.total_usd(),
            "key_count": key_count,
            "max_keys": self._max_keys,
            "overflow": overflow,
            "per_caller": self.per_caller(),
            "rows": self.rows(),
        }

    # ── Admin ──────────────────────────────────────────

    def reset(self) -> None:
        """Test helper — forget everything."""
        with self._lock:
            self._entries.clear()
            self._overflow_calls = 0
            self._overflow_usd = 0.0


# ── Process-wide singleton ─────────────────────────────────────


_default_ledger: CostLedger | None = None
_default_ledger_lock = threading.Lock()


def get_cost_ledger() -> CostLedger:
    """Return the process-wide cost ledger singleton."""
    global _default_ledger
    if _default_ledger is None:
        with _default_ledger_lock:
            if _default_ledger is None:
                _default_ledger = CostLedger()
    return _default_ledger


def reset_cost_ledger() -> None:
    """Test helper — replace the singleton with a fresh ledger."""
    global _default_ledger
    with _default_ledger_lock:
        _default_ledger = CostLedger()
