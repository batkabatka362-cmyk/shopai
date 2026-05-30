"""Auto-disarm bridge for chronically-degraded autonomy domains (W854).

When a substrate-mode domain has been critical for N consecutive
days (per W853 alert history), the bridge automatically calls
``autonomy_armed.disarm(domain)`` so the operator's armed flag
gets revoked and the next cycle won't fire it. Operator can
re-arm after investigating.

Env-gated to prevent surprise disarms:

  SHOPAI_AUTO_DISARM_FROM_ALERTS=1     (default OFF)
  SHOPAI_AUTO_DISARM_CONSECUTIVE_DAYS  (default 3)
  SHOPAI_AUTO_DISARM_WINDOW_DAYS       (default 7)

When OFF the bridge still REPORTS what it WOULD do (so daily-
brief can surface the consecutive-day count), it just doesn't
call disarm.

Mirrors [[project-engine-health-observability]]'s
``alert_quarantine`` bridge but scoped to the substrate-fire
domain catalog (10 domains) rather than the engine catalog
(135 engines).

Pattern J test-env guard short-circuits under pytest -- the
state file never gets touched.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _bridge_enabled() -> bool:
    return os.environ.get(
        "SHOPAI_AUTO_DISARM_FROM_ALERTS", "",
    ) in ("1", "true", "yes")


def _consecutive_days_threshold() -> int:
    raw = os.environ.get(
        "SHOPAI_AUTO_DISARM_CONSECUTIVE_DAYS", "3",
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


def _window_days() -> int:
    raw = os.environ.get(
        "SHOPAI_AUTO_DISARM_WINDOW_DAYS", "7",
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 7


@dataclass
class AutoDisarmDecision:
    domain: str
    consecutive_days: int
    threshold: int
    would_disarm: bool = False
    disarmed: bool = False
    reason: str = ""


@dataclass
class AutoDisarmReport:
    bridge_enabled: bool = False
    window_days: int = 7
    threshold: int = 3
    decisions: list[AutoDisarmDecision] = field(
        default_factory=list,
    )

    @property
    def disarmed_count(self) -> int:
        return sum(1 for d in self.decisions if d.disarmed)

    @property
    def would_disarm_count(self) -> int:
        return sum(
            1 for d in self.decisions if d.would_disarm
        )


def maybe_auto_disarm() -> AutoDisarmReport:
    """Walk armed domains + auto-disarm any with N consecutive
    critical days. Always safe under pytest (Pattern J)."""
    report = AutoDisarmReport(
        bridge_enabled=_bridge_enabled(),
        window_days=_window_days(),
        threshold=_consecutive_days_threshold(),
    )
    if _is_test_environment():
        return report

    try:
        from core.automation.autonomy_armed import (
            DOMAIN_APPLY_FLAGS, disarm, list_armed,
        )
        from core.automation.substrate_fire_alert_history import (  # noqa
            consecutive_critical_days,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto-disarm import raised: %s", exc,
        )
        return report

    threshold = report.threshold
    window = report.window_days

    for entry in list_armed():
        domain = entry.domain
        if domain not in DOMAIN_APPLY_FLAGS:
            continue
        try:
            days = consecutive_critical_days(
                domain, window_days=window,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "consecutive_critical_days raised for "
                "%s: %s", domain, exc,
            )
            continue
        decision = AutoDisarmDecision(
            domain=domain,
            consecutive_days=days,
            threshold=threshold,
        )
        if days >= threshold:
            decision.would_disarm = True
            if report.bridge_enabled:
                try:
                    if disarm(domain):
                        decision.disarmed = True
                        decision.reason = (
                            f"auto-disarmed: {days}d "
                            f">= {threshold}d critical"
                        )
                except Exception as exc:  # noqa: BLE001
                    decision.reason = (
                        f"disarm raised: {exc!s:.150}"
                    )
            else:
                decision.reason = (
                    f"would disarm: {days}d >= {threshold}d "
                    "critical (bridge OFF)"
                )
            report.decisions.append(decision)

    return report
