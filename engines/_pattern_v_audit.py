"""Pattern V audit: notify alert kind registration (Wave 207).

Every autonomy domain has 2 alert kinds:
  - {domain}_paused           (critical)
  - {domain}_health_critical  (critical)

Both kinds should be referenced in ``_notify.collect_alerts``
so the notify webhook fans out when the safety loop kicks in.
Pattern V catches missing alert kinds at PR time.

Same AST approach as Pattern U: source-grep the collect_alerts
function body for each expected kind string.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain alert kinds (paused + health_critical)
_DOMAIN_ALERT_KINDS: dict[str, tuple[str, str]] = {
    "customer_support_refund": (
        "refund_paused", "refund_health_critical",
    ),
    "marketing_budget": (
        "budget_paused", "budget_health_critical",
    ),
    "fulfillment": (
        "fulfillment_paused",
        "fulfillment_health_critical",
    ),
    "inventory": (
        "inventory_paused", "inventory_health_critical",
    ),
    "discount_cleanup": (
        "discount_cleanup_paused",
        "discount_cleanup_health_critical",
    ),
    "order_followup": (
        "order_followup_paused",
        "order_followup_health_critical",
    ),
    "product_seo": (
        "product_seo_paused",
        "product_seo_health_critical",
    ),
}


@dataclass
class PatternVViolation:
    domain: str
    missing_kinds: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class PatternVReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternVViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _extract_collect_alerts_body(
    notify_path: Path,
) -> str | None:
    try:
        source = notify_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern V _notify.py read raised: %s", exc,
        )
        return None
    try:
        tree = ast.parse(source, filename=str(notify_path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern V _notify.py parse raised: %s", exc,
        )
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "collect_alerts"
        ):
            try:
                return ast.unparse(node)
            except Exception:  # noqa: BLE001
                return None
    return None


def run_pattern_v_audit(
    *,
    notify_path: str | Path = "engines/_notify.py",
) -> PatternVReport:
    """Audit every autonomy domain's 2 alert kinds are
    referenced in collect_alerts."""
    report = PatternVReport()
    body = _extract_collect_alerts_body(Path(notify_path))
    if body is None:
        for domain, kinds in _DOMAIN_ALERT_KINDS.items():
            report.domains_scanned.append(domain)
            report.violations.append(PatternVViolation(
                domain=domain,
                missing_kinds=list(kinds),
                reason="_notify.collect_alerts unreadable",
            ))
        return report

    for domain, kinds in _DOMAIN_ALERT_KINDS.items():
        report.domains_scanned.append(domain)
        missing = [k for k in kinds if k not in body]
        if not missing:
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternVViolation(
                domain=domain,
                missing_kinds=missing,
                reason=(
                    f"{len(missing)} alert kind(s) not "
                    "referenced in collect_alerts"
                ),
            ))
    return report
