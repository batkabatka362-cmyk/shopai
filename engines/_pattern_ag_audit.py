"""Pattern AG audit: health analyze_X function export (W273).

Every autonomy domain's health module is the READ-side of the
observability loop: ``analyze_{prefix}_health()`` runs the
adapter-failure-ratio analyzer + emits a verdict (healthy /
degraded / critical) that the autonomy-status rollup +
``shopai {domain}-health`` CLI + cycle hook all consume.

Pattern AD (W256) verified the *bridge* function
(``maybe_auto_pause_X``); Pattern AG verifies its *companion*
analyzer function (``analyze_{prefix}_health``). Both live in
the same health module but serve different surfaces: the
analyzer is read-only and operator-facing; the bridge is the
auto-pause trigger called from cycle post-run.

Catches "renamed analyze_X_health but didn't update CLI"
class bug -- the CLI's ``{domain}-health`` subparser handler
imports the function by name, so a rename breaks the operator
command at fire-time (too late).
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain (health module path, expected analyze function).
_DOMAIN_ANALYZE_EXPORTS: dict[
    str, tuple[str, str],
] = {
    "customer_support_refund": (
        "engines/returns_management/refund_health.py",
        "analyze_refund_health",
    ),
    "marketing_budget": (
        "engines/roas_guardrails/budget_health.py",
        "analyze_budget_health",
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_health.py",
        "analyze_fulfillment_health",
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_health.py",
        "analyze_inventory_health",
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_health.py",
        "analyze_cleanup_health",
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_health.py",
        "analyze_followup_health",
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_health.py",
        "analyze_seo_health",
    ),
    "customer_outreach": (
        "engines/customer_outreach_autonomy/outreach_health.py",
        "analyze_customer_outreach_health",
    ),
}


@dataclass
class PatternAGViolation:
    domain: str
    module_path: str
    expected_function: str
    reason: str = ""


@dataclass
class PatternAGReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAGViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _module_exports_callable(
    path: Path, name: str,
) -> bool:
    """Top-level FunctionDef OR Assign/AnnAssign with matching
    name. Accepts the template re-export pattern
    (``analyze_X_health = _analyzer.X``)."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AG read failed for %s: %s", path, exc,
        )
        return False
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AG parse failed for %s: %s", path, exc,
        )
        return False
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return True
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and tgt.id == name
                ):
                    return True
        if isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == name
            ):
                return True
    return False


def run_pattern_ag_audit() -> PatternAGReport:
    """Verify every autonomy domain's health module exports
    its analyze_{prefix}_health function."""
    report = PatternAGReport()
    for domain, (
        module_path, fn_name,
    ) in _DOMAIN_ANALYZE_EXPORTS.items():
        report.domains_scanned.append(domain)
        path = Path(module_path)
        if not path.exists():
            report.violations.append(PatternAGViolation(
                domain=domain,
                module_path=module_path,
                expected_function=fn_name,
                reason=(
                    f"health module {module_path} not found"
                ),
            ))
            continue
        if _module_exports_callable(path, fn_name):
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternAGViolation(
                domain=domain,
                module_path=module_path,
                expected_function=fn_name,
                reason=(
                    f"top-level {fn_name!r} export not found "
                    "(FunctionDef / Assign / AnnAssign)"
                ),
            ))
    return report
