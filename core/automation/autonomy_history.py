"""Autonomy history (W313): unified timeline across domains.

Each autonomy domain logs events to its own append-only JSON
file (Pattern AF: ``record_X_event`` + ``recent_X_events``).
``autonomy-history`` aggregates events across all 7 domains
into ONE chronological timeline -- useful for post-incident
forensics ("what was the autonomy substrate doing in the hour
before the alert fired?") and routine ops ("show me everything
the autonomous loop did today").

Output shape:
  - newest-first timeline (matches operator scanning pattern)
  - each entry: timestamp + domain + action + status + key fields
  - optional --store filter (delegates to each log module's
    store_id arg)
  - optional --window-hours filter (default 24h)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any


# Per-domain (display name, package, recent_fn module name,
# recent_fn name). recent_events_fn signature is
# (*, window_hours, store_id=None).
_DOMAIN_LOGS = [
    (
        "refund",
        "returns_management",
        "refund_log",
        "recent_refunds",
    ),
    (
        "marketing",
        "roas_guardrails",
        "ad_spend_log",
        "recent_events",
    ),
    (
        "fulfillment",
        "fulfillment_autonomy",
        "fulfillment_log",
        "recent_events",
    ),
    (
        "inventory",
        "inventory_autonomy",
        "inventory_log",
        "recent_events",
    ),
    (
        "cleanup",
        "discount_cleanup_autonomy",
        "cleanup_log",
        "recent_events",
    ),
    (
        "followup",
        "order_followup_autonomy",
        "followup_log",
        "recent_events",
    ),
    (
        "seo",
        "product_seo_autonomy",
        "seo_log",
        "recent_events",
    ),
    (
        "outreach",
        "customer_outreach_autonomy",
        "outreach_log",
        "recent_events",
    ),
    (
        "quality",
        "catalog_quality_autonomy",
        "quality_log",
        "recent_events",
    ),
]


@dataclass
class HistoryEntry:
    timestamp: str
    domain: str
    action: str = ""
    status: str = ""
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoryReport:
    entries: list[HistoryEntry] = field(default_factory=list)
    window_hours: float = 24.0
    store_id: str | None = None
    per_domain_count: dict[str, int] = field(
        default_factory=dict,
    )

    @property
    def total(self) -> int:
        return len(self.entries)


def _coerce_entry(domain: str, raw: Any) -> HistoryEntry:
    """Normalize a raw log entry (dict OR dataclass) into a
    HistoryEntry."""
    # Dataclass entries (Phase 11.A/B refund_log) come through
    # as dicts via recent_refunds; Phase 12+ template events
    # come back as dicts too. Just defensively handle both.
    if hasattr(raw, "__dict__") and not isinstance(raw, dict):
        d = dict(vars(raw))
    elif isinstance(raw, dict):
        d = dict(raw)
    else:
        d = {}
    # Common timestamp fields: created_at, timestamp, ts
    ts = (
        d.get("created_at")
        or d.get("timestamp")
        or d.get("ts")
        or ""
    )
    action = (
        d.get("action")
        or d.get("event")
        or d.get("kind")
        or ""
    )
    status = (
        d.get("status")
        or d.get("verdict")
        or ("applied" if d.get("applied") else "")
    )
    detail = ""
    # Build a compact detail line from common fields
    for key in (
        "order_id", "product_id", "customer_id",
        "discount_id", "campaign_id", "store_id",
    ):
        if key in d and d[key]:
            detail = f"{key}={d[key]}"
            break
    return HistoryEntry(
        timestamp=str(ts),
        domain=domain,
        action=str(action),
        status=str(status),
        detail=detail,
        raw=d,
    )


def _domain_events(
    domain: str,
    pkg: str,
    log_modname: str,
    fn_name: str,
    window_hours: float,
    store_id: str | None,
) -> list[HistoryEntry]:
    """Best-effort fetch + normalize one domain's events."""
    try:
        mod = import_module(f"engines.{pkg}.{log_modname}")
        fn = getattr(mod, fn_name, None)
        if fn is None:
            return []
        try:
            raw_events = fn(
                window_hours=window_hours,
                store_id=store_id,
            )
        except TypeError:
            # Phase 11.A's recent_refunds may not accept
            # store_id -- retry without it
            raw_events = fn(window_hours=window_hours)
        return [
            _coerce_entry(domain, r) for r in raw_events
        ]
    except Exception:  # noqa: BLE001
        return []


def run_autonomy_history(
    *,
    window_hours: float = 24.0,
    store_id: str | None = None,
) -> HistoryReport:
    """Aggregate recent events across every autonomy domain into
    one chronological timeline (newest first)."""
    report = HistoryReport(
        window_hours=window_hours, store_id=store_id,
    )
    for domain, pkg, log_modname, fn_name in _DOMAIN_LOGS:
        events = _domain_events(
            domain, pkg, log_modname, fn_name,
            window_hours, store_id,
        )
        report.per_domain_count[domain] = len(events)
        report.entries.extend(events)
    # Newest first: sort descending on timestamp; missing
    # timestamps sink to the bottom
    report.entries.sort(
        key=lambda e: (e.timestamp or ""), reverse=True,
    )
    return report
