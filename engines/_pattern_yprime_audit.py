"""Pattern Y' audit: autonomy 5-piece template completeness (W229).

The Phase 11+ autonomy template prescribes 5 modules per domain:

  - log     -- bounded event log (record_X_event /
               recent_X_events)
  - state   -- pause flag (is_paused / pause / resume)
  - health  -- adapter_failed ratio analyzer +
               maybe_auto_pause_X bridge
  - applier -- the writer module (router.execute + Pattern Z's
               record_writeback)
  - status  -- DomainSummary builder (consumed by autonomy_status
               rollup, world-model, daily-brief)

Pattern P already catches "didn't adopt the substrate"; Pattern Q'
already catches "summary shape drifted"; Pattern X already catches
"summary not wired into rollup". Pattern Y' catches the cheapest
structural bug: somebody shipped a domain missing one of the 5
pieces entirely. The downstream symptoms are confusing (autopause
flag exists but applier doesn't check it, applier writes but no
log captures it, etc.) -- much faster to assert presence at PR
time.

The marketing_budget domain happens to name its log
``ad_spend_log.py`` (Phase 11.B legacy), so the catalog records
explicit per-domain expected filenames rather than computing
``<prefix>_log.py``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain expected (package_dir, {role: filename}) catalog.
_DOMAIN_TEMPLATE: dict[
    str, tuple[str, dict[str, str]],
] = {
    "customer_support_refund": (
        "engines/returns_management",
        {
            "log": "refund_log.py",
            "state": "refund_state.py",
            "health": "refund_health.py",
            "applier": "refund_applier.py",
            "status": "refund_status.py",
        },
    ),
    "marketing_budget": (
        "engines/roas_guardrails",
        {
            "log": "ad_spend_log.py",
            "state": "budget_state.py",
            "health": "budget_health.py",
            "applier": "budget_applier.py",
            "status": "marketing_status.py",
        },
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy",
        {
            "log": "fulfillment_log.py",
            "state": "fulfillment_state.py",
            "health": "fulfillment_health.py",
            "applier": "fulfillment_applier.py",
            "status": "fulfillment_status.py",
        },
    ),
    "inventory": (
        "engines/inventory_autonomy",
        {
            "log": "inventory_log.py",
            "state": "inventory_state.py",
            "health": "inventory_health.py",
            "applier": "inventory_applier.py",
            "status": "inventory_status.py",
        },
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy",
        {
            "log": "cleanup_log.py",
            "state": "cleanup_state.py",
            "health": "cleanup_health.py",
            "applier": "cleanup_applier.py",
            "status": "cleanup_status.py",
        },
    ),
    "order_followup": (
        "engines/order_followup_autonomy",
        {
            "log": "followup_log.py",
            "state": "followup_state.py",
            "health": "followup_health.py",
            "applier": "followup_applier.py",
            "status": "followup_status.py",
        },
    ),
    "product_seo": (
        "engines/product_seo_autonomy",
        {
            "log": "seo_log.py",
            "state": "seo_state.py",
            "health": "seo_health.py",
            "applier": "seo_applier.py",
            "status": "seo_status.py",
        },
    ),
    "customer_outreach": (
        "engines/customer_outreach_autonomy",
        {
            "log": "outreach_log.py",
            "state": "outreach_state.py",
            "health": "outreach_health.py",
            "applier": "outreach_applier.py",
            "status": "outreach_status.py",
        },
    ),
    "catalog_quality": (
        "engines/catalog_quality_autonomy",
        {
            "log": "quality_log.py",
            "state": "quality_state.py",
            "health": "quality_health.py",
            "applier": "quality_applier.py",
            "status": "quality_status.py",
        },
    ),
    "shipping_alert": (
        "engines/shipping_alert_autonomy",
        {
            "log": "shipping_log.py",
            "state": "shipping_state.py",
            "health": "shipping_health.py",
            "applier": "shipping_applier.py",
            "status": "shipping_status.py",
        },
    ),
}


_TEMPLATE_ROLES = ("log", "state", "health", "applier", "status")


@dataclass
class PatternYPrimeViolation:
    domain: str
    missing_roles: list[str] = field(default_factory=list)
    package_dir: str = ""
    reason: str = ""


@dataclass
class PatternYPrimeReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternYPrimeViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def run_pattern_yprime_audit() -> PatternYPrimeReport:
    """Verify every autonomy domain ships all 5 template
    modules."""
    report = PatternYPrimeReport()
    for domain, (pkg_dir, roles) in _DOMAIN_TEMPLATE.items():
        report.domains_scanned.append(domain)
        pkg = Path(pkg_dir)
        if not pkg.exists():
            report.violations.append(PatternYPrimeViolation(
                domain=domain,
                package_dir=pkg_dir,
                missing_roles=list(_TEMPLATE_ROLES),
                reason=(
                    f"package directory {pkg_dir} not found"
                ),
            ))
            continue
        missing: list[str] = []
        for role in _TEMPLATE_ROLES:
            fname = roles.get(role, "")
            if not fname:
                missing.append(role)
                continue
            mod = pkg / fname
            if not mod.exists():
                missing.append(role)
        if missing:
            report.violations.append(PatternYPrimeViolation(
                domain=domain,
                package_dir=pkg_dir,
                missing_roles=missing,
                reason=(
                    f"{len(missing)} template role(s) missing"
                ),
            ))
        else:
            report.clean_domains.append(domain)
    return report
