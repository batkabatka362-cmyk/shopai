"""Persistent log of substrate_fire outcomes (W840).

Each invocation of ``fire_armed_substrate_domains`` produces a
``SubstrateFireReport``. The recorder here persists each
outcome row to ``data/substrate_fire_log.json`` so operators
can audit "what fired in recent cycles?" via the W841
``shopai autonomy-fire-status`` CLI.

Uses the same ``core.automation.action_log`` substrate as the
per-domain logs (refund_log, ad_spend_log, etc.). Pattern J
test-environment guard inherited from action_log.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.automation.action_log import (
    log_size as _log_size,
    recent_events as _recent_events,
    record_event,
)

logger = logging.getLogger(__name__)

_LOG_PATH = Path("data") / "substrate_fire_log.json"


@dataclass
class SubstrateFireLogEntry:
    domain: str
    store_id: str = ""
    discovered: int = 0
    invoked: bool = False
    events: int = 0
    duration_ms: float = 0.0
    reason: str = ""
    error: str = ""
    recorded_at: float = field(default_factory=time.time)


def record_substrate_fire(
    outcome: Any, store_id: str | None = None,
) -> None:
    """Persist one SubstrateFireOutcome (from substrate_fire) to
    the log. No-op when the outcome reason is one of the
    'nothing happened' values + the discovered count is 0 --
    keeps the log focused on actionable history."""
    domain = getattr(outcome, "domain", "") or ""
    if not domain:
        return
    discovered = int(getattr(outcome, "discovered", 0) or 0)
    invoked = bool(getattr(outcome, "invoked", False))
    reason = getattr(outcome, "reason", "") or ""
    # Skip pure no-ops: no-discoverer with 0 rows + dry-run with
    # 0 rows. Keep anything that discovered rows OR fired OR
    # raised an error.
    if (
        not invoked
        and discovered == 0
        and reason in ("no_discoverer", "empty_payload")
    ):
        return
    sid = (
        store_id
        or getattr(outcome, "store_id", "")
        or ""
    )
    record_event(
        _LOG_PATH,
        SubstrateFireLogEntry(
            domain=domain,
            store_id=sid or "",
            discovered=discovered,
            invoked=invoked,
            events=int(getattr(outcome, "events", 0) or 0),
            duration_ms=float(
                getattr(outcome, "duration_ms", 0.0) or 0.0,
            ),
            reason=reason,
            error=getattr(outcome, "error", "") or "",
        ),
    )


def recent_substrate_fires(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    """Read recent entries with optional store_id + domain
    filters. Returns rows newest-first."""
    filters: dict[str, str] = {}
    if store_id:
        filters["store_id"] = store_id
    if domain:
        filters["domain"] = domain
    return _recent_events(
        _LOG_PATH,
        window_hours=window_hours,
        filters=filters or None,
    )


def substrate_fire_log_size() -> int:
    return _log_size(_LOG_PATH)
