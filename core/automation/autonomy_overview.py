"""One-line autonomy overview substrate (W892).

Operators want a compact "is the autonomous merchant healthy
right now?" signal suitable for shell prompts, monitoring
scripts, or alerting integrations. ``autonomy-overview``
returns one structured ``OverviewSnapshot`` aggregating the
key counts:

  - armed domains (fleet + per-store)
  - actionable fire events in last 24h
  - error events in last 24h
  - cooldown-blocked domains
  - degradation alerts

Designed to be cheap (single read of each underlying log /
catalog; no Shopify fetches). Output renders as a single
``key=value`` formatted line by default; JSON mode for cron.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class OverviewSnapshot:
    captured_at: float = field(default_factory=time.time)
    store_id: str | None = None
    window_hours: float = 24.0

    # Armed-state counts
    armed_total: int = 0
    armed_engine_mode: int = 0
    armed_substrate_with_discoverer: int = 0
    armed_substrate_no_discoverer: int = 0

    # Fire activity in window
    fires_total: int = 0
    fires_invoked: int = 0
    fires_errors: int = 0

    # Cooldown + alerts
    cooldown_blocked: int = 0
    alerts_critical: int = 0
    alerts_warn: int = 0

    @property
    def verdict(self) -> str:
        if self.alerts_critical > 0 or self.fires_errors > 0:
            return "degraded"
        if self.armed_total == 0:
            return "idle"
        if self.fires_invoked > 0:
            return "active"
        return "armed"


def build_overview(
    *,
    window_hours: float = 24.0,
    store_id: str | None = None,
) -> OverviewSnapshot:
    """Build the snapshot. Never raises."""
    snap = OverviewSnapshot(
        window_hours=window_hours, store_id=store_id,
    )

    # Armed-state counts
    try:
        from core.automation.autonomy_armed import (
            DOMAIN_FIRING_MODE, list_armed,
        )
        from core.automation.payload_discoverer import (
            registered_domains,
        )
        from core.automation import (  # noqa: F401
            discoverer_registry,
        )
        regs = set(registered_domains())
        entries = (
            list_armed(store_id=store_id) if store_id
            else list_armed()
        )
        snap.armed_total = len(entries)
        for e in entries:
            mode = DOMAIN_FIRING_MODE.get(e.domain, "unknown")
            if mode == "engine":
                snap.armed_engine_mode += 1
            elif mode == "substrate":
                if e.domain in regs:
                    snap.armed_substrate_with_discoverer += 1
                else:
                    snap.armed_substrate_no_discoverer += 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview armed probe raised: %s", exc)

    # Fire activity
    try:
        from core.automation.substrate_fire_log import (
            recent_substrate_fires,
        )
        rows = recent_substrate_fires(
            window_hours=window_hours,
            store_id=store_id,
        )
        snap.fires_total = len(rows)
        for r in rows:
            if r.get("invoked"):
                snap.fires_invoked += 1
            if r.get("reason") in (
                "applier_error", "discoverer_error",
            ):
                snap.fires_errors += 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview fire probe raised: %s", exc)

    # Cooldown
    try:
        from core.automation.autonomy_armed import (
            DOMAIN_APPLY_FLAGS, _cooldown_hours as _cd,
        )
        from core.automation.substrate_fire_disarm_log import (
            last_disarm_at,
        )
        for d in DOMAIN_APPLY_FLAGS:
            ts = last_disarm_at(
                d, store_id=store_id or None,
            )
            if ts is None:
                continue
            elapsed_h = (time.time() - ts) / 3600.0
            if elapsed_h < _cd(d):
                snap.cooldown_blocked += 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview cooldown probe raised: %s", exc)

    # Alerts
    try:
        from core.automation.substrate_fire_alerts import (
            compute_fire_alerts,
        )
        ar = compute_fire_alerts(
            window_hours=window_hours,
            store_id=store_id,
        )
        snap.alerts_critical = ar.critical_count
        snap.alerts_warn = ar.warn_count
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview alerts probe raised: %s", exc)

    return snap
