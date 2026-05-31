"""Pattern R audit: next_action drill hint presence (Wave 164).

Every status report SHOULD carry a populated ``next_action``
string -- the drill-down hint pattern documented across the
codebase (memory: project_drill_down_hint_pattern.md). An
empty next_action leaves operators staring at a verdict
without a way forward.

Pattern R verifies every autonomy domain's per-domain summary
function returns a DomainSummary with ``next_action`` set to
a non-empty string. Empty strings indicate a missed
opportunity to guide the operator.

Mirrors Pattern Q's runtime probe approach.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PatternRViolation:
    domain: str
    reason: str = ""


@dataclass
class PatternRReport:
    domains_probed: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternRViolation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _domain_probes():
    try:
        from core.automation import autonomy_status as au
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern R autonomy_status import raised: %s", exc,
        )
        return []
    # Wave 937 bugfix: previously hardcoded 7 domains -- 3
    # newer domains (customer_outreach W379, catalog_quality
    # W436, shipping_alert W756) silently skipped DomainSummary
    # next_action checks. Source from the live autonomy_status
    # module's _<domain>_summary attribute set instead.
    probes = (
        ("customer_support", "_customer_support_summary"),
        ("marketing", "_marketing_summary"),
        ("fulfillment", "_fulfillment_summary"),
        ("inventory", "_inventory_summary"),
        ("discount_cleanup", "_discount_cleanup_summary"),
        ("order_followup", "_order_followup_summary"),
        ("product_seo", "_product_seo_summary"),
        ("customer_outreach", "_customer_outreach_summary"),
        ("catalog_quality", "_catalog_quality_summary"),
        ("shipping_alert", "_shipping_alert_summary"),
    )
    out = []
    for domain, fn_name in probes:
        fn = getattr(au, fn_name, None)
        if callable(fn):
            out.append((domain, fn))
    return out


def run_pattern_r_audit() -> PatternRReport:
    """Verify every autonomy DomainSummary populates
    next_action."""
    report = PatternRReport()
    for domain, fn in _domain_probes():
        report.domains_probed.append(domain)
        try:
            result = fn(window_hours=24.0)
        except Exception as exc:  # noqa: BLE001
            report.violations.append(PatternRViolation(
                domain=domain,
                reason=f"{fn.__name__} raised: {exc}",
            ))
            continue
        na = getattr(result, "next_action", "")
        if not isinstance(na, str) or not na.strip():
            report.violations.append(PatternRViolation(
                domain=domain,
                reason=(
                    "next_action is empty -- operator gets "
                    "no drill-down hint"
                ),
            ))
        else:
            report.clean_domains.append(domain)
    return report
