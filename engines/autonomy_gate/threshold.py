"""Autonomy-gate threshold computation.

Reads existing substrate signals to derive per-store
stability:
  - cycle_history runs WHERE store_id touched + error
    count
  - autonomy fire log (W858+) -- shouldn't be firing
    auto-disarms
  - quota autopause (W963-120) -- shouldn't be firing
  - approval queue rejected actions

For each store, count incidents in the proof window.
Zero incidents AND minimum cycle activity = 'stable'.

Five-store-stable + minimum proof window = unlocked.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Env-var configurable thresholds (defaults match
# operator's stated requirement).
_DEFAULT_REQUIRED_STORES = 5
_DEFAULT_PROOF_DAYS = 30
_DEFAULT_MIN_CYCLES = (
    10  # each store must have run at
        # least this many cycles
)


def _resolve_int_env(
    name: str, default: int,
) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


@dataclass
class StoreStability:
    """One store's stability assessment."""
    store_id: str
    cycle_count: int = 0
    cycle_errors: int = 0
    autopause_fires: int = 0
    refund_anomalies: int = 0
    autonomy_alerts: int = 0
    rejected_actions: int = 0

    @property
    def total_incidents(self) -> int:
        return (
            self.cycle_errors
            + self.autopause_fires
            + self.refund_anomalies
            + self.autonomy_alerts
            + self.rejected_actions
        )

    @property
    def is_stable(self) -> bool:
        """Stable iff: ran at least min_cycles AND
        ZERO incidents."""
        min_cycles = _resolve_int_env(
            "SHOPAI_AUTONOMY_GATE_MIN_CYCLES",
            _DEFAULT_MIN_CYCLES,
        )
        return (
            self.cycle_count >= min_cycles
            and self.total_incidents == 0
        )


@dataclass
class AutonomyGateReport:
    """Gate state envelope."""
    required_stores: int
    proof_window_days: int
    min_cycles_per_store: int
    stores: list[StoreStability] = field(
        default_factory=list,
    )
    stable_count: int = 0
    unlocked: bool = False
    blockers: list[str] = field(
        default_factory=list,
    )

    @property
    def progress_pct(self) -> float:
        if self.required_stores <= 0:
            return 100.0
        return min(
            100.0,
            self.stable_count
            / self.required_stores * 100.0,
        )


def _safe_cycle_history_per_store(
    store_id: str,
    *,
    window_seconds: float,
) -> tuple[int, int]:
    """Returns (cycle_count, cycle_errors) over the
    window. Defensive: missing module returns (0, 0)."""
    try:
        from engines._cycle_history import runs_for_store
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cycle_history import raised: %s", exc,
        )
        return 0, 0
    try:
        cutoff = time.time() - window_seconds
        runs = runs_for_store(store_id, limit=500)
        in_window = [
            r for r in runs
            if float(
                getattr(r, "started_at", 0),
            ) >= cutoff
        ]
        count = len(in_window)
        errors = sum(
            int(getattr(r, "total_errors", 0))
            for r in in_window
        )
        return count, errors
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "runs_for_store raised: %s", exc,
        )
        return 0, 0


def _safe_autopause_fires(
    store_id: str,
    *,
    window_seconds: float,
) -> int:
    """How many quota autopause fires happened for this
    store in the window.

    W963-153: must use READ-ONLY ``critical_stores()``
    rather than ``maybe_autopause()``. The latter has
    SIDE EFFECTS when ``SHOPAI_QUOTA_AUTOPAUSE=1`` (calls
    ``disarm()`` on every critical pair). Using it here
    means the gate PROBE silently disarms spend-class
    domains across the empire -- once per store per
    check_autonomy_gate call.
    """
    try:
        from engines.per_store_quota.tracker import (
            critical_stores,
        )
        snapshots = critical_stores(
            window_hours=window_seconds / 3600.0,
        )
        return sum(
            1 for s in snapshots
            if s.store_id == store_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "autopause probe raised: %s", exc,
        )
        return 0


def _safe_rejected_actions(
    store_id: str,
) -> int:
    """How many actions for this store were REJECTED in
    the approval queue."""
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
        rows = queue.list_by_status(
            "rejected",
            store_id=store_id,
            limit=200,
        ) or []
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "approval queue probe raised: %s", exc,
        )
        return 0


def _list_active_stores() -> list[str]:
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        stores = StoreManager().list_stores() or []
        return [
            s.get("store_id")
            for s in stores
            if isinstance(s, dict)
            and s.get("store_id")
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "list_active_stores raised: %s", exc,
        )
        return []


def check_autonomy_gate() -> AutonomyGateReport:
    """Build the full gate report.

    Env-var thresholds:
      SHOPAI_AUTONOMY_GATE_REQUIRED_STORES (default 5)
      SHOPAI_AUTONOMY_GATE_PROOF_DAYS (default 30)
      SHOPAI_AUTONOMY_GATE_MIN_CYCLES (default 10)
    """
    required = _resolve_int_env(
        "SHOPAI_AUTONOMY_GATE_REQUIRED_STORES",
        _DEFAULT_REQUIRED_STORES,
    )
    days = _resolve_int_env(
        "SHOPAI_AUTONOMY_GATE_PROOF_DAYS",
        _DEFAULT_PROOF_DAYS,
    )
    min_cycles = _resolve_int_env(
        "SHOPAI_AUTONOMY_GATE_MIN_CYCLES",
        _DEFAULT_MIN_CYCLES,
    )
    window_seconds = days * 86400.0

    report = AutonomyGateReport(
        required_stores=required,
        proof_window_days=days,
        min_cycles_per_store=min_cycles,
    )

    sids = _list_active_stores()
    if not sids:
        report.blockers.append(
            "no stores registered in StoreManager"
        )
        return report

    for sid in sids:
        cycles, errors = (
            _safe_cycle_history_per_store(
                sid, window_seconds=window_seconds,
            )
        )
        autopause = _safe_autopause_fires(
            sid, window_seconds=window_seconds,
        )
        rejected = _safe_rejected_actions(sid)
        stability = StoreStability(
            store_id=sid,
            cycle_count=cycles,
            cycle_errors=errors,
            autopause_fires=autopause,
            rejected_actions=rejected,
            # refund_anomalies + autonomy_alerts left
            # at 0 for now; future commits can wire
            # them once the relevant substrate exposes
            # per-store counts.
        )
        report.stores.append(stability)

    report.stable_count = sum(
        1 for s in report.stores if s.is_stable
    )
    report.unlocked = (
        report.stable_count >= required
    )

    if not report.unlocked:
        deficit = (
            required - report.stable_count
        )
        report.blockers.append(
            f"need {deficit} more stable store(s) "
            f"({report.stable_count}/{required})"
        )
        # Surface the closest-to-stable stores
        for s in report.stores:
            if (
                not s.is_stable
                and s.cycle_count >= min_cycles
            ):
                report.blockers.append(
                    f"{s.store_id}: "
                    f"{s.total_incidents} "
                    f"incident(s)"
                )
            elif s.cycle_count < min_cycles:
                report.blockers.append(
                    f"{s.store_id}: "
                    f"only {s.cycle_count} cycle(s) "
                    f"(need {min_cycles})"
                )

    return report


def is_autonomy_unlocked() -> bool:
    """Quick boolean check for callers that only need
    yes/no. Operator's transfer engine consults this
    BEFORE auto-promoting any recipe."""
    try:
        return check_autonomy_gate().unlocked
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "is_autonomy_unlocked raised: %s", exc,
        )
        return False
