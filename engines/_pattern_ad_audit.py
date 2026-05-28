"""Pattern AD audit: health module exports bridge fn (W256).

Pattern U (W203) verified ``cli.py`` references each domain's
``maybe_auto_pause_X`` bridge symbol from ``_cmd_cycle_run``.
Pattern AD closes the symmetric end: verifies the bridge function
actually EXISTS as a top-level ``FunctionDef`` inside each
domain's health module.

Catches the "renamed the bridge function but only fixed cli.py"
class bug, which Pattern U cannot catch (Pattern U checks the
NAME literal appears in cli.py source, not that it resolves to a
real callable). The matching breakage would be: import error at
cycle fire time, which is too late.

AST approach: walk each domain's health module, look for a
top-level FunctionDef named ``maybe_auto_pause_X`` (where X is
the domain's bridge suffix per the Pattern U catalog).
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain (health module path, expected bridge function name).
# Mirrors Pattern U's catalog but indexed for the symmetric AST
# check on the health module's exports.
_DOMAIN_BRIDGE_EXPORTS: dict[str, tuple[str, str]] = {
    "customer_support_refund": (
        "engines/returns_management/refund_health.py",
        "maybe_auto_pause_refunds",
    ),
    "marketing_budget": (
        "engines/roas_guardrails/budget_health.py",
        "maybe_auto_pause_budget",
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_health.py",
        "maybe_auto_pause_fulfillment",
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_health.py",
        "maybe_auto_pause_inventory",
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_health.py",
        "maybe_auto_pause_cleanup",
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_health.py",
        "maybe_auto_pause_followup",
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_health.py",
        "maybe_auto_pause_seo",
    ),
    "customer_outreach": (
        "engines/customer_outreach_autonomy/outreach_health.py",
        "maybe_auto_pause_outreach",
    ),
    "catalog_quality": (
        "engines/catalog_quality_autonomy/quality_health.py",
        "maybe_auto_pause_quality",
    ),
}


@dataclass
class PatternADViolation:
    domain: str
    expected_function: str
    module_path: str
    reason: str = ""


@dataclass
class PatternADReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternADViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _module_defines_function(
    path: Path, name: str,
) -> bool:
    """Top-level FunctionDef lookup. Doesn't follow imports --
    the function must be defined IN the health module, not
    re-exported from elsewhere."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AD read failed for %s: %s", path, exc,
        )
        return False
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AD parse failed for %s: %s", path, exc,
        )
        return False
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return True
    return False


def run_pattern_ad_audit() -> PatternADReport:
    """Verify every autonomy domain's health module exports
    its bridge function as a top-level FunctionDef."""
    report = PatternADReport()
    for domain, (module_path, fn_name) in (
        _DOMAIN_BRIDGE_EXPORTS.items()
    ):
        report.domains_scanned.append(domain)
        path = Path(module_path)
        if not path.exists():
            report.violations.append(PatternADViolation(
                domain=domain,
                expected_function=fn_name,
                module_path=module_path,
                reason=f"module {module_path} not found",
            ))
            continue
        if _module_defines_function(path, fn_name):
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternADViolation(
                domain=domain,
                expected_function=fn_name,
                module_path=module_path,
                reason=(
                    f"function {fn_name!r} not defined as "
                    "top-level FunctionDef in module"
                ),
            ))
    return report
