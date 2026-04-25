"""Budget allocator — distribute money / time / API calls optimally.

Every subsystem competes for 3 scarce resources:

  • ad_spend_usd     — daily Meta Ads budget
  • llm_tokens       — free-tier + paid caps across adapters
  • cycle_time_s      — how long a daemon cycle is allowed to take

Today each subsystem has its own hard-coded cap (ad_budget_day=20,
max_tokens=500, etc.). Nothing aggregates total spend or reallocates
from quiet subsystems to busy ones. A run-away launch can eat the
entire ads budget; a verbose reasoner can exhaust the LLM cap.

core.brain.budget_allocator.BudgetPool holds the three pools and
exposes request/reserve/consume. Allocations follow a weighted
fair-share policy:

    share_i = (priority_i × demand_i) / Σ(priority × demand)

Priority comes from the v6-D1 goal agenda (sum of priorities of
the active goals that map to this subsystem). Demand is the
subsystem's *asked* quantity — the allocator returns min(asked,
share × pool).

Thread-safe, persistent across restarts (data/budget.json).
``stats()`` lets the dashboard show utilisation percentages.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_STORE = Path("data/budget.json")
_lock = threading.Lock()


_DEFAULTS = {
    "ad_spend_usd": {
        "daily_cap": 100.0,
        "remaining": 100.0,
        "reset_every_s": 86_400,
        "last_reset": 0.0,
    },
    "llm_tokens": {
        "daily_cap": 500_000.0,
        "remaining": 500_000.0,
        "reset_every_s": 86_400,
        "last_reset": 0.0,
    },
    "cycle_time_s": {
        "daily_cap": 3_600.0,       # 1 hr of cycle time per day
        "remaining": 3_600.0,
        "reset_every_s": 86_400,
        "last_reset": 0.0,
    },
}


@dataclass
class Allocation:
    resource: str
    requester: str
    requested: float
    granted: float
    remaining_after: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "requester": self.requester,
            "requested": round(self.requested, 2),
            "granted": round(self.granted, 2),
            "remaining_after": round(self.remaining_after, 2),
        }


class BudgetPool:
    """Three resources, persisted as JSON. All balances are floats."""

    def __init__(self, store: Path | str | None = None) -> None:
        self._store = Path(store) if store else _STORE

    # ── CRUD ────────────────────────────────────────────────

    def set_cap(self, resource: str, daily_cap: float) -> None:
        with _lock:
            state = self._load()
            entry = state.setdefault(resource, {
                "daily_cap": daily_cap,
                "remaining": daily_cap,
                "reset_every_s": 86_400,
                "last_reset": time.time(),
            })
            entry["daily_cap"] = float(daily_cap)
            # Clamp remaining to new cap on a shrink
            if entry["remaining"] > daily_cap:
                entry["remaining"] = float(daily_cap)
            self._save(state)

    def reset(self, resource: str) -> None:
        """Force a mid-day reset for a resource (owner override)."""
        with _lock:
            state = self._load()
            entry = state.setdefault(resource, dict(_DEFAULTS.get(resource, {})))
            entry["remaining"] = float(entry.get("daily_cap", 0.0))
            entry["last_reset"] = time.time()
            self._save(state)

    def stats(self) -> dict[str, Any]:
        state = self._load()
        out: dict[str, Any] = {}
        now = time.time()
        for name, entry in state.items():
            self._maybe_auto_reset(entry, now)
            cap = float(entry.get("daily_cap") or 0.0)
            rem = float(entry.get("remaining") or 0.0)
            utilised = 0.0 if cap <= 0 else max(0.0, 1.0 - rem / cap)
            out[name] = {
                "daily_cap": round(cap, 2),
                "remaining": round(rem, 2),
                "utilised_pct": round(utilised * 100, 1),
            }
        return out

    # ── Allocation ──────────────────────────────────────────

    def consume(
        self,
        resource: str,
        requester: str,
        requested: float,
        priority: float = 50.0,
        competing: list[tuple[str, float, float]] | None = None,
    ) -> Allocation:
        """Reserve *requested* units for *requester*. If *competing*
        is supplied (list of (other_name, other_priority, other_demand))
        the grant is capped to the fair-share of this requester.
        Returns the granted amount (≤ requested; never negative)."""
        requested = max(0.0, float(requested))
        priority = max(0.0, float(priority))
        with _lock:
            state = self._load()
            entry = state.setdefault(resource, dict(_DEFAULTS.get(resource, {
                "daily_cap": requested, "remaining": requested,
                "reset_every_s": 86_400, "last_reset": time.time(),
            })))
            now = time.time()
            self._maybe_auto_reset(entry, now)
            remaining = float(entry.get("remaining") or 0.0)
            if remaining <= 0 or requested <= 0:
                alloc = Allocation(
                    resource=resource, requester=requester,
                    requested=requested, granted=0.0,
                    remaining_after=remaining,
                )
                return alloc
            granted = min(requested, remaining)
            # Apply fair-share cap when competitors exist
            if competing:
                my_weight = priority * requested
                total = my_weight + sum(
                    max(0.0, p) * max(0.0, d) for _, p, d in competing
                )
                if total > 0:
                    fair_share = my_weight / total * remaining
                    granted = min(granted, fair_share)
            granted = max(0.0, granted)
            entry["remaining"] = remaining - granted
            self._save(state)
            return Allocation(
                resource=resource, requester=requester,
                requested=requested, granted=granted,
                remaining_after=entry["remaining"],
            )

    def can_spend(self, resource: str, amount: float) -> bool:
        with _lock:
            state = self._load()
            entry = state.get(resource) or {}
            self._maybe_auto_reset(entry, time.time())
            return float(entry.get("remaining") or 0.0) >= float(amount)

    # ── Internals ───────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if not self._store.exists():
            return {k: dict(v) for k, v in _DEFAULTS.items()}
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            # Merge defaults so new resources gain sensible values
            for k, v in _DEFAULTS.items():
                if k not in data:
                    data[k] = dict(v)
            return data
        except Exception:
            return {k: dict(v) for k, v in _DEFAULTS.items()}

    def _save(self, state: dict[str, Any]) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        import os
        tmp = self._store.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str),
                       encoding="utf-8")
        os.replace(tmp, self._store)

    @staticmethod
    def _maybe_auto_reset(entry: dict[str, Any], now: float) -> None:
        if not entry:
            return
        last = float(entry.get("last_reset") or 0.0)
        every = float(entry.get("reset_every_s") or 86_400)
        if now - last >= every:
            entry["remaining"] = float(entry.get("daily_cap") or 0.0)
            entry["last_reset"] = now


# ── Singleton ────────────────────────────────────────────────

_BUDGET_LOCK = threading.Lock()
_BUDGET: BudgetPool | None = None


def budget() -> BudgetPool:
    global _BUDGET
    with _BUDGET_LOCK:
        if _BUDGET is None:
            _BUDGET = BudgetPool()
    return _BUDGET
