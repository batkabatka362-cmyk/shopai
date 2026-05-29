"""Pattern W audit: autonomy bridge env-gate enforcement (W223).

Pattern T (W185) verified every autonomy domain's env knobs
are REGISTERED in the canonical catalog. Pattern W closes
the loop: it verifies the bridge function actually CHECKS the
env knob.

Concretely, each domain's ``maybe_auto_pause_X()`` is supposed
to consult ``SHOPAI_AUTO_PAUSE_{PREFIX}_ON_FAILURE`` (via the
shared ``core.automation.health_analyzer.maybe_auto_pause``
helper which is parameterized on env_prefix). Pattern W
AST-walks each domain's health module + asserts the
expected env_prefix string appears as a literal (so a future
PR that hardcodes the env var name instead of using the
helper, or typos the prefix, gets caught at PR time).

The audit catches drift between Pattern T's registry and the
actual code that gates on env vars.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain health module + expected env_prefix the bridge
# should consult.
_DOMAIN_HEALTH_MODULES: dict[
    str, tuple[str, str]
] = {
    "customer_support_refund": (
        "engines/returns_management/refund_health.py",
        "REFUND",
    ),
    "marketing_budget": (
        "engines/roas_guardrails/budget_health.py",
        "BUDGET",
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_health.py",
        "FULFILLMENT",
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_health.py",
        "INVENTORY",
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_health.py",
        "DISCOUNT_CLEANUP",
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_health.py",
        "ORDER_FOLLOWUP",
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_health.py",
        "PRODUCT_SEO",
    ),
    "customer_outreach": (
        "engines/customer_outreach_autonomy/outreach_health.py",
        "CUSTOMER_OUTREACH",
    ),
    "catalog_quality": (
        "engines/catalog_quality_autonomy/quality_health.py",
        "CATALOG_QUALITY",
    ),
    "shipping_alert": (
        "engines/shipping_alert_autonomy/shipping_health.py",
        "SHIPPING_ALERT",
    ),
}


@dataclass
class PatternWViolation:
    domain: str
    expected_prefix: str
    reason: str = ""


@dataclass
class PatternWReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternWViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _module_references_prefix(
    path: Path, prefix: str,
) -> bool:
    """AST-walk the module + look for ``prefix`` either as an
    exact string literal (Phase 12+ template usage:
    env_prefix='X') OR as a substring of any string literal
    (Phase 11.A/B inline usage:
    'SHOPAI_X_PAUSE_FAILURE_RATIO').

    Both forms validly gate on the env knob; we accept either.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern W read failed for %s: %s", path, exc,
        )
        return False
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern W parse failed for %s: %s", path, exc,
        )
        return False
    target_token = f"_{prefix}_"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        ):
            value = node.value
            # Exact match (template usage) OR appears as
            # _PREFIX_ token within an env var name
            if value == prefix:
                return True
            if target_token in value:
                return True
            # Catch the AUTO_PAUSE_PREFIX_ON_FAILURE gate even
            # when "REFUNDS" (plural) is used vs prefix REFUND
            if (
                value.startswith("SHOPAI_AUTO_PAUSE_")
                and value.endswith("_ON_FAILURE")
                and prefix.rstrip("S") in value
            ):
                return True
    return False


def run_pattern_w_audit() -> PatternWReport:
    """Verify every autonomy domain's health module references
    its expected env_prefix as a literal string."""
    report = PatternWReport()
    for domain, (module_path, prefix) in (
        _DOMAIN_HEALTH_MODULES.items()
    ):
        report.domains_scanned.append(domain)
        path = Path(module_path)
        if not path.exists():
            report.violations.append(PatternWViolation(
                domain=domain,
                expected_prefix=prefix,
                reason=f"module {module_path} not found",
            ))
            continue
        if _module_references_prefix(path, prefix):
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternWViolation(
                domain=domain,
                expected_prefix=prefix,
                reason=(
                    f"env_prefix literal {prefix!r} not "
                    "found in module"
                ),
            ))
    return report
