"""Per-store spend cap + auto-pause on overspend.

Wave 47: real-money safety substrate. Operators going live
worry about runaway spend (e.g. a misconfigured Meta Ads
spend, a discount that prints money out, a fraudulent
inventory drain). Without a cap, the autonomous loop can
do real damage before operator notices.

This module:

  1. Tracks per-store daily / weekly spend from approval-queue
     outcomes (where ``revenue`` is positive AND ``cost`` is
     positive on action records).
  2. Compares against configured caps (env vars +
     ``data/spend_caps.json`` overrides).
  3. When a cap is exceeded, auto-adds spend-class engines to
     quarantine.alert_paused so further actions get rejected
     until operator releases.

## What counts as "spend"

ApprovalQueue action records carry a ``metrics`` dict via
``record_outcome``. We sum:
  - ``metrics.cost`` (explicit cost field on the action)
  - ``metrics.ad_spend`` (advertising cost)
  - ``metrics.discount_value`` (when discount minted)

NOT counted:
  - ``revenue`` (positive money inflow)
  - ``refunded_revenue`` (negative money flow but not a SPEND
    -- already accounted by attribution)

## Env-var contract

  - ``SHOPAI_SPEND_CAP_DAILY_USD`` -- per-store daily cap.
    Default: unset (no enforcement).
  - ``SHOPAI_SPEND_CAP_WEEKLY_USD`` -- per-store weekly cap.
  - ``SHOPAI_AUTO_PAUSE_ON_OVERSPEND=1`` -- enable the bridge.
    Default OFF.

## Pattern J

Under pytest, ``maybe_auto_pause_on_overspend`` returns []
without touching state. Tests lift the guard explicitly.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)


_ENV_DAILY = "SHOPAI_SPEND_CAP_DAILY_USD"
_ENV_WEEKLY = "SHOPAI_SPEND_CAP_WEEKLY_USD"
_ENV_ENABLED = "SHOPAI_AUTO_PAUSE_ON_OVERSPEND"

# Engine names that incur spend. When a cap is breached, these
# get auto-paused on the offending store. Curated -- not every
# engine is a spend source.
_SPEND_CLASS_ENGINES: frozenset[str] = frozenset({
    # Ad spend
    "ad_creative_generator",
    "campaign_strategy",
    "audience_targeting",
    "conversion_tracking",
    "email_marketing",
    "influencer",
    # Discount value
    "discount_strategy",
    "loyalty",
    "churn_prediction",
    "browse_recovery",
    "cart_recovery",
    "wholesale_b2b",
    # Affiliate commission
    "affiliate",
})


@dataclass
class SpendRollup:
    store_id: str | None
    window_label: str  # "daily" / "weekly"
    window_hours: float
    total_spend: float = 0.0
    contributing_engines: dict[str, float] = field(default_factory=dict)
    actions_counted: int = 0

    @property
    def top_spender(self) -> str | None:
        if not self.contributing_engines:
            return None
        return max(
            self.contributing_engines.items(),
            key=lambda kv: kv[1],
        )[0]


def daily_cap_usd() -> float | None:
    raw = os.environ.get(_ENV_DAILY)
    if not raw:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def weekly_cap_usd() -> float | None:
    raw = os.environ.get(_ENV_WEEKLY)
    if not raw:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def is_enabled() -> bool:
    return os.environ.get(_ENV_ENABLED) == "1"


def _is_test_environment() -> bool:
    # Pattern J test-environment guard with production-override
    # escape hatch.
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).strip().lower() in ("1", "true", "yes", "on"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def compute_spend_rollup(
    *,
    window_hours: float,
    store_id: str | None = None,
    window_label: str = "window",
) -> SpendRollup:
    """Sum spend-class metrics from recent action outcomes.

    Reads ApprovalQueue.get_outcomes() (or equivalent) and
    aggregates spend metrics. Per-store when store_id passed;
    fleet-wide otherwise.
    """
    rollup = SpendRollup(
        store_id=store_id,
        window_label=window_label,
        window_hours=window_hours,
    )
    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
    except Exception:  # noqa: BLE001
        return rollup

    cutoff = time.time() - (window_hours * 3600.0)
    try:
        actions = (
            queue.list_by_status("executed") or []
        )
    except Exception:  # noqa: BLE001
        return rollup

    for action in actions:
        action_id = getattr(action, "id", None)
        if action_id is None:
            continue
        # Per-store filter
        action_store = getattr(action, "store_id", None)
        if store_id is not None and action_store != store_id:
            continue
        # Outcomes carry the spend metrics
        try:
            outcomes = queue.get_outcomes(action_id) or []
        except Exception:  # noqa: BLE001
            continue
        for outcome in outcomes:
            captured_at = (
                outcome.get("captured_at", 0)
                if isinstance(outcome, dict) else 0
            )
            try:
                if float(captured_at) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            metrics = (
                outcome.get("metrics") or {}
                if isinstance(outcome, dict) else {}
            )
            spend = 0.0
            for key in ("cost", "ad_spend", "discount_value"):
                try:
                    spend += float(metrics.get(key, 0) or 0)
                except (TypeError, ValueError):
                    continue
            if spend <= 0:
                continue
            engine = getattr(action, "engine", None) or "unknown"
            rollup.total_spend = round(
                rollup.total_spend + spend, 2,
            )
            rollup.contributing_engines[engine] = round(
                rollup.contributing_engines.get(engine, 0.0)
                + spend, 2,
            )
            rollup.actions_counted += 1
    return rollup


def daily_spend(
    *, store_id: str | None = None,
) -> SpendRollup:
    """24-hour spend rollup."""
    return compute_spend_rollup(
        window_hours=24.0,
        store_id=store_id,
        window_label="daily",
    )


def weekly_spend(
    *, store_id: str | None = None,
) -> SpendRollup:
    """7-day spend rollup."""
    return compute_spend_rollup(
        window_hours=168.0,
        store_id=store_id,
        window_label="weekly",
    )


@dataclass
class CapBreach:
    store_id: str | None
    window_label: str
    cap_usd: float
    actual_spend: float
    over_by: float
    contributing_engines: dict[str, float]


def check_caps(
    *, store_id: str | None = None,
) -> list[CapBreach]:
    """Compute spend rollups; report any breached caps."""
    breaches: list[CapBreach] = []
    daily_cap = daily_cap_usd()
    weekly_cap = weekly_cap_usd()
    if daily_cap is not None:
        rollup = daily_spend(store_id=store_id)
        if rollup.total_spend > daily_cap:
            breaches.append(CapBreach(
                store_id=store_id,
                window_label="daily",
                cap_usd=daily_cap,
                actual_spend=rollup.total_spend,
                over_by=round(rollup.total_spend - daily_cap, 2),
                contributing_engines=rollup.contributing_engines,
            ))
    if weekly_cap is not None:
        rollup = weekly_spend(store_id=store_id)
        if rollup.total_spend > weekly_cap:
            breaches.append(CapBreach(
                store_id=store_id,
                window_label="weekly",
                cap_usd=weekly_cap,
                actual_spend=rollup.total_spend,
                over_by=round(rollup.total_spend - weekly_cap, 2),
                contributing_engines=rollup.contributing_engines,
            ))
    return breaches


def maybe_auto_pause_on_overspend(
    *, store_id: str | None = None,
) -> list[str]:
    """When a cap is breached AND bridge is enabled, auto-pause
    spend-class engines for the offending store.

    Returns the list of engine names newly paused. Empty when:
      - bridge disabled (SHOPAI_AUTO_PAUSE_ON_OVERSPEND != 1)
      - under pytest (Pattern J guard)
      - no breaches
      - all spend-class engines already paused
    """
    if not is_enabled():
        return []
    if _is_test_environment():
        return []
    breaches = check_caps(store_id=store_id)
    if not breaches:
        return []
    try:
        from core.approval import quarantine
        state = quarantine.load_state()
        existing = set(state.alert_paused or set())
    except Exception:  # noqa: BLE001
        return []
    # Pause every spend-class engine that's not already paused.
    # Per-store scope when store_id given.
    newly_paused: list[str] = []
    for engine in sorted(_SPEND_CLASS_ENGINES):
        pause_key = (engine, store_id)
        # Fleet pause supersedes per-store
        if (engine, None) in existing:
            continue
        if pause_key in existing:
            continue
        try:
            quarantine.add_alert_pause(
                engine, store_id=store_id,
            )
            newly_paused.append(engine)
            logger.warning(
                "spend-cap auto-pause: engine=%s store=%s "
                "breaches=%s",
                engine, store_id or "fleet",
                [b.window_label for b in breaches],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "spend-cap pause failed for %s: %s",
                engine, exc,
            )
    return newly_paused
