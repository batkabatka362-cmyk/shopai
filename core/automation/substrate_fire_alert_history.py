"""Persistent log of substrate-fire alert firings (W853).

The W849 alerter computes alerts fresh each call from the
substrate_fire log. For multi-day trends + the W854
auto-disarm bridge, we need persistence: each call appends the
current alerts (with severity + reason) to disk so future
calls can count "how many distinct days has domain X been
critical?"

Same action_log substrate as W840 (substrate_fire_log) +
W117 (action_log generic). Pattern J test-env guard inherited.
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

_LOG_PATH = Path("data") / "substrate_fire_alert_history.json"


@dataclass
class AlertHistoryEntry:
    domain: str
    kind: str  # "low_success_rate" | "high_error_count"
    severity: str  # "warn" | "critical"
    store_id: str = ""
    success_rate: float = 0.0
    errors: int = 0
    sample_size: int = 0
    reason: str = ""
    recorded_at: float = field(default_factory=time.time)


def record_alerts(
    alerts: list[Any],
    *,
    store_id: str | None = None,
) -> None:
    """Persist every alert in the list. Idempotent within the
    same second (action_log will dedup by timestamp+payload
    in practice if the recorder doesn't guard it -- here we
    just append and the consumer aggregates)."""
    for a in alerts or []:
        domain = getattr(a, "domain", "") or ""
        if not domain:
            continue
        sid = (
            store_id
            or getattr(a, "store_id", "")
            or ""
        )
        record_event(
            _LOG_PATH,
            AlertHistoryEntry(
                domain=domain,
                kind=getattr(a, "kind", "") or "",
                severity=(
                    getattr(a, "severity", "") or ""
                ),
                store_id=sid or "",
                success_rate=float(
                    getattr(a, "success_rate", 0.0) or 0.0,
                ),
                errors=int(
                    getattr(a, "errors", 0) or 0,
                ),
                sample_size=int(
                    getattr(a, "sample_size", 0) or 0,
                ),
                reason=getattr(a, "reason", "") or "",
            ),
        )


def recent_alerts(
    *,
    window_hours: float = 720.0,  # 30 days default
    store_id: str | None = None,
    domain: str | None = None,
    severity: str | None = None,
) -> list[dict[str, Any]]:
    """Read recent alert history rows newest-first."""
    filters: dict[str, str] = {}
    if store_id:
        filters["store_id"] = store_id
    if domain:
        filters["domain"] = domain
    if severity:
        filters["severity"] = severity
    return _recent_events(
        _LOG_PATH,
        window_hours=window_hours,
        filters=filters or None,
    )


def alert_history_log_size() -> int:
    return _log_size(_LOG_PATH)


def consecutive_critical_days(
    domain: str,
    *,
    store_id: str | None = None,
    window_days: int = 7,
) -> int:
    """Count distinct UTC days in the window where ``domain``
    has at least one critical alert. Used by W854's auto-
    disarm bridge to decide whether a domain has degraded for
    long enough to warrant emergency action."""
    rows = recent_alerts(
        window_hours=window_days * 24.0,
        store_id=store_id,
        domain=domain,
        severity="critical",
    )
    if not rows:
        return 0
    seen_days: set[str] = set()
    for r in rows:
        ts = r.get("recorded_at")
        if not isinstance(ts, (int, float)):
            continue
        day = time.strftime(
            "%Y-%m-%d", time.gmtime(float(ts)),
        )
        seen_days.add(day)
    return len(seen_days)
