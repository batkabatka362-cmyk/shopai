"""Per-adapter cost budget enforcement — Option T.

The metrics layer already records cumulative ``cost_usd_total`` per
adapter. What was missing is an *enforcement* layer: a hard-stop
that skips an adapter once its daily or monthly spend exceeds a
declared cap. Without this, a misbehaving vendor or a runaway
prompt can silently burn through the monthly budget before an
operator notices.

This module supplies three small primitives:

* ``CostBudget`` — declarative per-adapter caps: ``daily_usd``,
  ``monthly_usd``, ``per_call_usd``. Every field is optional.
* ``BudgetLedger`` — thread-safe per-adapter spend counters with
  UTC-midnight daily reset and first-of-month monthly reset. The
  router feeds it after each successful call; the enforcer reads.
* ``BudgetEnforcer`` — joins budgets + ledger into a single
  ``can_call(adapter) -> Decision`` gate the router consults
  before dispatching. Emits a typed ``deny`` outcome the UI can
  surface so the operator sees *why* an adapter was skipped.

All state lives in memory. A restart re-reads the ledger from the
metrics collector (best-effort) so brief process bounces don't
reset the daily window — but the cap is always re-enforced.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


# ── Budget declaration ─────────────────────────────────────────


@dataclass
class CostBudget:
    """Per-adapter spend cap.

    Leave a field at ``None`` to skip that check. ``per_call_usd``
    rejects a single call whose *estimated* cost exceeds the cap
    without waiting for the daily window to close — useful for
    catching a runaway prompt that would burn the whole day's
    budget in one shot.
    """

    daily_usd: float | None = None
    monthly_usd: float | None = None
    per_call_usd: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("daily_usd", "monthly_usd", "per_call_usd"):
            val = getattr(self, field_name)
            if val is not None and val < 0:
                raise ValueError(f"{field_name} must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_usd": self.daily_usd,
            "monthly_usd": self.monthly_usd,
            "per_call_usd": self.per_call_usd,
        }


# ── Decision record ────────────────────────────────────────────


@dataclass
class BudgetDecision:
    """Result of a ``BudgetEnforcer.can_call`` check.

    * ``allow`` — True iff the call may proceed
    * ``reason`` — empty when allowed; otherwise a short
      human-readable explanation suitable for the dashboard
    * ``daily_used_pct`` / ``monthly_used_pct`` — fraction of the
      respective cap burned so far (0.0-1.0 or ``None`` if no cap)
    """

    allow: bool
    adapter: str
    reason: str = ""
    daily_used_pct: float | None = None
    monthly_used_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow": self.allow,
            "adapter": self.adapter,
            "reason": self.reason,
            "daily_used_pct": self.daily_used_pct,
            "monthly_used_pct": self.monthly_used_pct,
        }


# ── Ledger ─────────────────────────────────────────────────────


_DAY_SECONDS = 24 * 60 * 60
#: ~30 days — good enough for monthly caps. Dashboards render
#: actual wall-clock month boundaries so operators don't get
#: surprised; the ledger just needs a consistent reset cadence.
_MONTH_SECONDS = 30 * _DAY_SECONDS


@dataclass
class _Bucket:
    """Private spend accumulator for one adapter."""
    spent_daily: float = 0.0
    spent_monthly: float = 0.0
    daily_reset_epoch: float = 0.0
    monthly_reset_epoch: float = 0.0
    call_count_daily: int = 0


class BudgetLedger:
    """Thread-safe per-adapter spend counters with wall-clock resets.

    The ledger is fed by the router (or wherever cost is realised)
    via ``record(adapter, usd)``. Readers use ``spent(adapter)`` or
    ``snapshot()`` — both auto-refresh the reset windows so a long
    uptime doesn't carry yesterday's count into today.
    """

    def __init__(self, clock: callable = time.time) -> None:
        self._lock = threading.RLock()
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def record(self, adapter: str, usd: float) -> None:
        if usd <= 0:
            return
        with self._lock:
            b = self._buckets.get(adapter) or _Bucket()
            self._refresh(b)
            b.spent_daily += float(usd)
            b.spent_monthly += float(usd)
            b.call_count_daily += 1
            self._buckets[adapter] = b

    def spent(self, adapter: str) -> tuple[float, float]:
        """Return ``(daily_usd, monthly_usd)`` for *adapter*."""
        with self._lock:
            b = self._buckets.get(adapter)
            if b is None:
                return (0.0, 0.0)
            self._refresh(b)
            return (round(b.spent_daily, 4), round(b.spent_monthly, 4))

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Dashboard-ready view. Refreshes reset windows on read."""
        out: dict[str, dict[str, Any]] = {}
        with self._lock:
            for name, b in self._buckets.items():
                self._refresh(b)
                out[name] = {
                    "spent_daily_usd": round(b.spent_daily, 4),
                    "spent_monthly_usd": round(b.spent_monthly, 4),
                    "daily_reset_epoch": b.daily_reset_epoch,
                    "monthly_reset_epoch": b.monthly_reset_epoch,
                    "call_count_daily": b.call_count_daily,
                }
        return out

    def reset(self, adapter: str | None = None) -> None:
        """Test helper — forget every counter or just one adapter."""
        with self._lock:
            if adapter is None:
                self._buckets.clear()
            else:
                self._buckets.pop(adapter, None)

    # ── Private ───────────────────────────────────────

    def _refresh(self, b: _Bucket) -> None:
        """Roll the bucket forward if the current window has closed.

        Must be called with ``_lock`` held. Safe to call many times
        per record — idempotent between resets.
        """
        now = self._clock()
        if b.daily_reset_epoch == 0.0:
            b.daily_reset_epoch = now + _DAY_SECONDS
        elif now >= b.daily_reset_epoch:
            b.spent_daily = 0.0
            b.call_count_daily = 0
            b.daily_reset_epoch = now + _DAY_SECONDS
        if b.monthly_reset_epoch == 0.0:
            b.monthly_reset_epoch = now + _MONTH_SECONDS
        elif now >= b.monthly_reset_epoch:
            b.spent_monthly = 0.0
            b.monthly_reset_epoch = now + _MONTH_SECONDS


# ── Enforcer ───────────────────────────────────────────────────


class BudgetEnforcer:
    """Decides whether an adapter may run, given its cost budget.

    Construction:

        enforcer = BudgetEnforcer()                     # empty catalog
        enforcer = BudgetEnforcer(budgets={"openai":    # pre-loaded
                                          CostBudget(daily_usd=5.0)})

    Typical usage inside the router:

        decision = enforcer.can_call("openai", estimated_cost)
        if not decision.allow:
            continue   # skip this adapter, try the next one
        result = adapter.execute(...)
        enforcer.record("openai", result.cost_usd)
    """

    def __init__(
        self,
        budgets: dict[str, CostBudget] | None = None,
        ledger: BudgetLedger | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._budgets: dict[str, CostBudget] = dict(budgets or {})
        self._ledger = ledger or BudgetLedger()

    # ── Catalog management ──────────────────────────────

    def set_budget(self, adapter: str, budget: CostBudget) -> None:
        with self._lock:
            self._budgets[adapter] = budget

    def get_budget(self, adapter: str) -> CostBudget | None:
        with self._lock:
            return self._budgets.get(adapter)

    def budgets(self) -> dict[str, CostBudget]:
        with self._lock:
            return dict(self._budgets)

    @property
    def ledger(self) -> BudgetLedger:
        return self._ledger

    # ── Gate ────────────────────────────────────────────

    def can_call(
        self,
        adapter: str,
        estimated_cost_usd: float = 0.0,
    ) -> BudgetDecision:
        """Return a ``BudgetDecision`` for *adapter*.

        An adapter with no configured budget is always allowed
        (the router keeps full flexibility by default). A budget
        with a ``per_call_usd`` cap and a too-expensive estimate
        is rejected even if the daily window is still open.
        """
        budget = self._budgets.get(adapter)
        daily_spent, monthly_spent = self._ledger.spent(adapter)

        daily_pct = self._fraction(daily_spent, budget.daily_usd) if budget else None
        monthly_pct = self._fraction(monthly_spent, budget.monthly_usd) if budget else None

        if budget is None:
            return BudgetDecision(
                allow=True, adapter=adapter,
                daily_used_pct=None, monthly_used_pct=None,
            )

        if (budget.per_call_usd is not None
                and estimated_cost_usd > budget.per_call_usd):
            return BudgetDecision(
                allow=False,
                adapter=adapter,
                reason=(
                    f"per-call ${estimated_cost_usd:.4f} exceeds "
                    f"cap ${budget.per_call_usd:.4f}"
                ),
                daily_used_pct=daily_pct,
                monthly_used_pct=monthly_pct,
            )

        if (budget.daily_usd is not None
                and daily_spent + estimated_cost_usd > budget.daily_usd):
            return BudgetDecision(
                allow=False,
                adapter=adapter,
                reason=(
                    f"daily ${daily_spent:.2f} + ${estimated_cost_usd:.4f} "
                    f"would exceed cap ${budget.daily_usd:.2f}"
                ),
                daily_used_pct=daily_pct,
                monthly_used_pct=monthly_pct,
            )

        if (budget.monthly_usd is not None
                and monthly_spent + estimated_cost_usd > budget.monthly_usd):
            return BudgetDecision(
                allow=False,
                adapter=adapter,
                reason=(
                    f"monthly ${monthly_spent:.2f} + ${estimated_cost_usd:.4f} "
                    f"would exceed cap ${budget.monthly_usd:.2f}"
                ),
                daily_used_pct=daily_pct,
                monthly_used_pct=monthly_pct,
            )

        return BudgetDecision(
            allow=True,
            adapter=adapter,
            daily_used_pct=daily_pct,
            monthly_used_pct=monthly_pct,
        )

    def record(self, adapter: str, usd: float) -> None:
        """Book a realised cost into the ledger."""
        self._ledger.record(adapter, usd)

    # ── Dashboard ───────────────────────────────────────

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a UI-ready per-adapter rollup.

        Rows include adapters with a configured budget as well as
        any adapter that has spend recorded, so the dashboard can
        show "unconfigured but spending" in a clear row.
        """
        out: list[dict[str, Any]] = []
        ledger_snap = self._ledger.snapshot()
        with self._lock:
            names = set(self._budgets) | set(ledger_snap)
            for name in sorted(names):
                budget = self._budgets.get(name)
                row = ledger_snap.get(name, {
                    "spent_daily_usd": 0.0,
                    "spent_monthly_usd": 0.0,
                    "daily_reset_epoch": 0.0,
                    "monthly_reset_epoch": 0.0,
                    "call_count_daily": 0,
                })
                daily_pct = self._fraction(
                    row["spent_daily_usd"],
                    budget.daily_usd if budget else None,
                )
                monthly_pct = self._fraction(
                    row["spent_monthly_usd"],
                    budget.monthly_usd if budget else None,
                )
                out.append({
                    "adapter": name,
                    "budget": budget.to_dict() if budget else None,
                    "spent_daily_usd": row["spent_daily_usd"],
                    "spent_monthly_usd": row["spent_monthly_usd"],
                    "daily_used_pct": daily_pct,
                    "monthly_used_pct": monthly_pct,
                    "call_count_daily": row.get("call_count_daily", 0),
                    "status": self._grade(daily_pct, monthly_pct),
                })
        return out

    # ── Private ─────────────────────────────────────────

    @staticmethod
    def _fraction(spent: float, cap: float | None) -> float | None:
        if cap is None or cap <= 0:
            return None
        return round(min(1.0, spent / cap), 4)

    @staticmethod
    def _grade(daily_pct: float | None, monthly_pct: float | None) -> str:
        """Traffic-light grade for the UI row.

        * ``exceeded``    — at least one cap is fully consumed
        * ``warn``        — at or above 80% of any configured cap
        * ``ok``          — everything within budget
        * ``unconfigured`` — no budget at all (informational)
        """
        pcts = [p for p in (daily_pct, monthly_pct) if p is not None]
        if not pcts:
            return "unconfigured"
        if max(pcts) >= 1.0:
            return "exceeded"
        if max(pcts) >= 0.8:
            return "warn"
        return "ok"


# ── Process-wide singleton ─────────────────────────────────────


_enforcer: BudgetEnforcer | None = None
_enforcer_lock = threading.Lock()


def get_budget_enforcer() -> BudgetEnforcer:
    """Return the process-wide enforcer singleton."""
    global _enforcer
    if _enforcer is None:
        with _enforcer_lock:
            if _enforcer is None:
                _enforcer = BudgetEnforcer()
    return _enforcer


def reset_budget_enforcer() -> None:
    """Test helper — replace the singleton with a fresh enforcer."""
    global _enforcer
    with _enforcer_lock:
        _enforcer = BudgetEnforcer()
