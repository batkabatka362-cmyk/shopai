"""Autonomy bulk pause/resume (W347): empire-wide halt switch.

During maintenance windows (Shopify API outage, ad-platform
issue, post-incident sanity hold) the operator wants ONE command
to halt every autonomous action across every domain. Otherwise
they're running 7 separate ``shopai {domain}-pause`` commands
manually.

``autonomy-bulk-pause`` invokes each domain's ``state.pause(
reason=...)`` in turn + reports per-domain success/fail.
``autonomy-bulk-resume`` is the symmetric clear.

High blast radius -- gated by ``SHOPAI_AUTONOMY_BULK_PAUSE_CONFIRM=1``
env var so a typo can't accidentally halt the empire. Without
the gate the function returns a no-op report with an
explanatory reason.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import import_module


# Per-domain (display name, package, state module name).
_DOMAIN_STATE_MODULES = [
    ("customer_support_refund", "returns_management",
     "refund_state"),
    ("marketing_budget", "roas_guardrails",
     "budget_state"),
    ("fulfillment", "fulfillment_autonomy",
     "fulfillment_state"),
    ("inventory", "inventory_autonomy",
     "inventory_state"),
    ("discount_cleanup", "discount_cleanup_autonomy",
     "cleanup_state"),
    ("order_followup", "order_followup_autonomy",
     "followup_state"),
    ("product_seo", "product_seo_autonomy",
     "seo_state"),
    ("customer_outreach", "customer_outreach_autonomy",
     "outreach_state"),
]


_BULK_CONFIRM_ENV = "SHOPAI_AUTONOMY_BULK_PAUSE_CONFIRM"


@dataclass
class BulkDomainResult:
    domain: str
    ok: bool = False
    action: str = ""  # "paused" / "resumed" / "skipped"
    error: str = ""


@dataclass
class BulkReport:
    action: str = ""  # "pause" / "resume"
    confirm_set: bool = False
    reason: str = ""
    domains: list[BulkDomainResult] = field(
        default_factory=list,
    )

    @property
    def ok_count(self) -> int:
        return sum(1 for d in self.domains if d.ok)

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.domains if not d.ok)

    @property
    def total(self) -> int:
        return len(self.domains)


def _confirm_enabled() -> bool:
    val = os.environ.get(_BULK_CONFIRM_ENV, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _bulk_one(
    domain: str, pkg: str, modname: str,
    action: str, reason: str,
) -> BulkDomainResult:
    """Pause or resume one domain."""
    result = BulkDomainResult(domain=domain, action=action)
    try:
        mod = import_module(f"engines.{pkg}.{modname}")
    except Exception as exc:  # noqa: BLE001
        result.error = f"import failed: {exc!s:.80}"
        return result
    fn_name = "pause" if action == "pause" else "resume"
    fn = getattr(mod, fn_name, None)
    if fn is None:
        result.error = f"{fn_name!r} not found"
        return result
    try:
        if action == "pause":
            fn(reason=reason)
        else:
            fn()
        result.ok = True
    except Exception as exc:  # noqa: BLE001
        result.error = f"raised: {exc!s:.80}"
    return result


def run_bulk_pause(*, reason: str = "bulk pause") -> BulkReport:
    """Pause every autonomy domain. Requires confirm env var."""
    report = BulkReport(
        action="pause",
        confirm_set=_confirm_enabled(),
        reason=reason,
    )
    if not report.confirm_set:
        for domain, _, _ in _DOMAIN_STATE_MODULES:
            report.domains.append(BulkDomainResult(
                domain=domain,
                ok=False,
                action="skipped",
                error=(
                    f"{_BULK_CONFIRM_ENV}=1 required to "
                    "execute bulk pause"
                ),
            ))
        return report
    for domain, pkg, modname in _DOMAIN_STATE_MODULES:
        report.domains.append(
            _bulk_one(domain, pkg, modname, "pause", reason),
        )
    return report


def run_bulk_resume() -> BulkReport:
    """Resume every autonomy domain. Same confirm gate as pause
    (resuming the empire is also high blast radius -- if the
    operator paused for a reason, accidental resume is bad)."""
    report = BulkReport(
        action="resume",
        confirm_set=_confirm_enabled(),
    )
    if not report.confirm_set:
        for domain, _, _ in _DOMAIN_STATE_MODULES:
            report.domains.append(BulkDomainResult(
                domain=domain,
                ok=False,
                action="skipped",
                error=(
                    f"{_BULK_CONFIRM_ENV}=1 required to "
                    "execute bulk resume"
                ),
            ))
        return report
    for domain, pkg, modname in _DOMAIN_STATE_MODULES:
        report.domains.append(
            _bulk_one(domain, pkg, modname, "resume", ""),
        )
    return report
