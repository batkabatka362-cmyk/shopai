"""W963-120: per-store autopause bridge.

Reads critical_stores() from W963-119 + autopauses
spend-class autonomy domains for THAT store only.
Other stores in the empire continue unaffected.

Env contract:

  SHOPAI_QUOTA_AUTOPAUSE=1
    Required opt-in. Default OFF -- the function STILL
    reports what WOULD be paused but does not actually
    disarm. Operator opts in when they trust the cap
    configuration.

  SHOPAI_QUOTA_AUTOPAUSE_DOMAINS=marketing,customer_outreach
    Optional override of the spend-class domain list.
    Default = the canonical 4 domains that directly
    consume money: marketing (ad budget mutations),
    customer_outreach (email/SMS sends), customer_support
    (refunds), discount_cleanup (code mints).

Designed to integrate into the cycle_run --yes
post-cycle bridge chain alongside the W47 spend-cap
bridge -- W963-120 covers ADAPTER cost; W47 covers
ENGINE outcome cost.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from .tracker import critical_stores

logger = logging.getLogger(__name__)


# Default spend-class domains. Operator can override via
# SHOPAI_QUOTA_AUTOPAUSE_DOMAINS env var (comma-separated).
_DEFAULT_SPEND_DOMAINS = (
    "marketing",
    "customer_outreach",
    "customer_support",
    "discount_cleanup",
)


def _resolve_spend_domains() -> tuple[str, ...]:
    raw = os.environ.get(
        "SHOPAI_QUOTA_AUTOPAUSE_DOMAINS", "",
    ).strip()
    if not raw:
        return _DEFAULT_SPEND_DOMAINS
    parts = tuple(
        p.strip() for p in raw.split(",") if p.strip()
    )
    return parts or _DEFAULT_SPEND_DOMAINS


def _is_autopause_enabled() -> bool:
    """Operator opt-in for autopause action. When disabled
    the bridge still REPORTS what would be paused (dry-run
    style)."""
    return os.environ.get(
        "SHOPAI_QUOTA_AUTOPAUSE", "",
    ).strip().lower() in ("1", "true", "yes")


@dataclass
class AutopauseAction:
    """One pending autopause decision."""
    store_id: str
    domain: str
    reason: str
    applied: bool = False
    error: str = ""


@dataclass
class AutopauseReport:
    """Summary of one bridge invocation."""
    enabled: bool
    spend_domains: tuple[str, ...]
    window_hours: float
    critical_store_count: int = 0
    actions: list[AutopauseAction] = field(
        default_factory=list,
    )

    @property
    def applied_count(self) -> int:
        return sum(1 for a in self.actions if a.applied)

    @property
    def would_apply_count(self) -> int:
        return len(self.actions)


def maybe_autopause(
    *,
    window_hours: float = 24.0,
) -> AutopauseReport:
    """Compute and (optionally) apply per-store autopause
    for spend-class domains.

    When SHOPAI_QUOTA_AUTOPAUSE=1, this CALLS disarm() for
    each (store, spend_domain) in CRITICAL state. Otherwise
    the report lists the decisions but ``applied`` stays
    False -- operator can preview before opt-in.

    Per-store scope:
      Each critical (store, adapter) pair only autopauses
      THAT STORE's spend domains -- never the whole
      fleet. A hot-spending store_a does not pause
      store_b's loop.

    Idempotent:
      arm_safe_defaults / arm already gracefully no-op
      when a domain is already armed/disarmed; this bridge
      is similarly idempotent. Re-running across cycles
      adds nothing for stores that already had their
      spend domains paused.
    """
    spend_domains = _resolve_spend_domains()
    enabled = _is_autopause_enabled()
    report = AutopauseReport(
        enabled=enabled,
        spend_domains=spend_domains,
        window_hours=window_hours,
    )

    try:
        critical = critical_stores(
            window_hours=window_hours,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "autopause: critical_stores raised: %s", exc,
        )
        return report

    # Group by store_id so we don't enumerate
    # (store_a, openai, total spend) AND
    # (store_a, openai, per-adapter spend) as two distinct
    # pause events. One store -> one set of paused
    # domains.
    stores_at_critical: set[str] = set()
    for snap in critical:
        # Skip synthetic "(fleet)" key (cap exceeded by
        # fleet-level events with no active_store).
        sid = snap.store_id
        if sid in ("(fleet)", ""):
            continue
        stores_at_critical.add(sid)

    report.critical_store_count = len(stores_at_critical)

    if not stores_at_critical:
        return report

    # W963-126 round-8 #6: detect fleet-wide armed
    # domains BEFORE attempting per-store disarm.
    # autonomy_armed.disarm(domain, store_id=sid) only
    # removes the exact (domain, sid) tuple -- it does
    # NOT match the fleet-wide (domain, '') entry. So
    # when operator armed customer_outreach fleet-wide,
    # the per-store autopause attempt is a silent no-op:
    # the spend domain keeps firing for the offending
    # store. Bug class: autopause-that-does-not-pause.
    #
    # Fix: detect the fleet-wide arm, surface a clear
    # error per action telling the operator to either
    # (a) lift the fleet arm + re-arm per-store for the
    # stores that should keep firing, or (b) accept the
    # known limitation. Bridge no longer silently fails.
    fleet_armed_domains: set[str] = set()
    try:
        from core.automation.autonomy_armed import is_armed
        for d in spend_domains:
            if is_armed(d, store_id=""):
                fleet_armed_domains.add(d)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "autopause: fleet-arm probe raised: %s", exc,
        )

    # Plan + (optionally) apply.
    for sid in sorted(stores_at_critical):
        for domain in spend_domains:
            action = AutopauseAction(
                store_id=sid,
                domain=domain,
                reason=(
                    f"per-store quota exceeded "
                    f"(window={window_hours:.0f}h)"
                ),
            )
            if enabled:
                if domain in fleet_armed_domains:
                    # W963-126: fleet-arm collision.
                    # Per-store disarm is a no-op against
                    # the fleet entry. Surface honestly.
                    action.error = (
                        f"fleet-wide arm prevents "
                        f"per-store disarm of {domain!r} "
                        f"for {sid!r}. Lift the fleet "
                        f"arm with `shopai autonomy-"
                        f"disarm {domain}` then re-arm "
                        f"per-store for stores that "
                        f"should keep firing."
                    )
                else:
                    try:
                        from core.automation.autonomy_armed import (
                            disarm,
                        )
                        removed = disarm(
                            domain, store_id=sid,
                        )
                        action.applied = bool(removed)
                    except Exception as exc:  # noqa: BLE001
                        action.error = str(exc)[:160]
                        logger.debug(
                            "autopause: disarm raised "
                            "for %s/%s: %s",
                            sid, domain, exc,
                        )
            report.actions.append(action)

    return report
