"""Persistent log of auto-disarm decisions (W858).

Each invocation of ``maybe_auto_disarm`` produces decisions
for armed-at-threshold domains. This log persists every
``would_disarm`` or ``disarmed`` decision so the operator can
see the history of bridge actions (or what the bridge WOULD
have done if it were enabled).

Used by:
  * W858 notify integration -- emit alert when bridge fires
  * W859 re-arm cooldown -- block re-arming domain for N
    hours after auto-disarm
  * W860 `shopai autonomy-disarm-history` CLI

Pattern J test-env guard inherited from action_log.
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

_LOG_PATH = Path("data") / "substrate_fire_disarm_log.json"


@dataclass
class DisarmLogEntry:
    domain: str
    consecutive_days: int
    threshold: int
    would_disarm: bool = False
    disarmed: bool = False
    reason: str = ""
    bridge_enabled: bool = False
    recorded_at: float = field(default_factory=time.time)


def record_disarm_decisions(decisions: list[Any]) -> None:
    """Persist every decision in the list. Skips empty
    domains (defensive)."""
    for d in decisions or []:
        domain = getattr(d, "domain", "") or ""
        if not domain:
            continue
        # Only record decisions where the bridge actually
        # had something to say (would_disarm OR disarmed --
        # but maybe_auto_disarm already filters these).
        record_event(
            _LOG_PATH,
            DisarmLogEntry(
                domain=domain,
                consecutive_days=int(
                    getattr(d, "consecutive_days", 0) or 0,
                ),
                threshold=int(
                    getattr(d, "threshold", 0) or 0,
                ),
                would_disarm=bool(
                    getattr(d, "would_disarm", False),
                ),
                disarmed=bool(
                    getattr(d, "disarmed", False),
                ),
                reason=getattr(d, "reason", "") or "",
            ),
        )


def recent_disarms(
    *,
    window_hours: float = 720.0,  # 30 days default
    domain: str | None = None,
    only_disarmed: bool = False,
) -> list[dict[str, Any]]:
    """Read recent disarm decisions newest-first."""
    filters: dict[str, str] = {}
    if domain:
        filters["domain"] = domain
    rows = _recent_events(
        _LOG_PATH,
        window_hours=window_hours,
        filters=filters or None,
    )
    if only_disarmed:
        rows = [r for r in rows if r.get("disarmed")]
    return rows


def disarm_log_size() -> int:
    return _log_size(_LOG_PATH)


def last_disarm_at(domain: str) -> float | None:
    """Return the UNIX timestamp of the most-recent
    ``disarmed=True`` decision for ``domain``, or None if
    never auto-disarmed."""
    rows = recent_disarms(
        window_hours=24 * 365.0,  # effectively unbounded
        domain=domain,
        only_disarmed=True,
    )
    if not rows:
        return None
    ts = rows[0].get("recorded_at")
    return float(ts) if isinstance(ts, (int, float)) else None


def clear_history(domain: str) -> int:
    """Remove every disarm-log row for ``domain``. Returns
    the count of removed rows. Operator nuclear-option that
    effectively zeroes the cooldown for ``domain``.

    Pattern J test-env guard: under pytest the file write
    short-circuits but the return value still reflects what
    WOULD have been removed."""
    from core.automation.action_log import (  # noqa
        is_test_environment, load_log, save_log,
    )
    rows = load_log(_LOG_PATH)
    keep = [
        r for r in rows
        if not isinstance(r, dict) or r.get("domain") != domain
    ]
    removed = len(rows) - len(keep)
    if removed > 0 and not is_test_environment():
        save_log(_LOG_PATH, keep)
    return removed
