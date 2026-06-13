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


_VERDICT_EMOJI = {
    "idle": "[.]",
    "armed": "[~]",
    "active": "[>]",
    "degraded": "[!]",
}


def render_text(snap: "OverviewSnapshot") -> str:
    """Wave 892 default: one key=value line."""
    scope = (
        f"store={snap.store_id}" if snap.store_id else "fleet"
    )
    return (
        f"verdict={snap.verdict}  "
        f"armed={snap.armed_total}  "
        f"fires={snap.fires_invoked}/{snap.fires_total}  "
        f"errors={snap.fires_errors}  "
        f"cooldown_blocked={snap.cooldown_blocked}  "
        f"alerts={snap.alerts_critical}c/{snap.alerts_warn}w  "
        f"({scope}, {snap.window_hours:.0f}h)"
    )


def render_markdown(snap: "OverviewSnapshot") -> str:
    """Wave 897: GitHub-flavored markdown table.

    Suitable for embedding in PR comments, status pages, or
    GitHub Actions summaries. Header line + one row.
    """
    scope = (
        f"`{snap.store_id}`" if snap.store_id else "fleet"
    )
    return (
        f"### Autonomy overview ({scope}, "
        f"{snap.window_hours:.0f}h)\n"
        "\n"
        "| verdict | armed | fires | errors | cooldown |"
        " alerts |\n"
        "|---|---|---|---|---|---|\n"
        f"| **{snap.verdict}** | {snap.armed_total} |"
        f" {snap.fires_invoked}/{snap.fires_total} |"
        f" {snap.fires_errors} | {snap.cooldown_blocked} |"
        f" {snap.alerts_critical}c/{snap.alerts_warn}w |"
    )


def render_shell_prompt(snap: "OverviewSnapshot") -> str:
    """Wave 898: minimal shell-prompt token.

    Designed for `PS1` / `$PROMPT` embedding. Compact form:
    one short marker + counts. No trailing newline.
    """
    marker = _VERDICT_EMOJI.get(snap.verdict, "[?]")
    return (
        f"{marker}{snap.verdict[:3]}"
        f" a{snap.armed_total}"
        f" f{snap.fires_invoked}/{snap.fires_total}"
        f" e{snap.fires_errors}"
        f" !{snap.alerts_critical}"
    )


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

    # Wave 900: persist snapshot to history (Pattern J guard
    # in record_snapshot short-circuits under pytest).
    try:
        from core.automation.autonomy_overview_history import (
            record_snapshot,
        )
        record_snapshot(snap)
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview history record raised: %s", exc)

    return snap
