"""Pattern AH audit: applier main entry-point export (W277).

Every autonomy domain's applier exposes a single ``apply_X(...)``
function as the engine→Shopify boundary. Callers from
engines/*/flow.py invoke this by name:

    from engines.{pkg}.{prefix}_applier import {apply_fn}
    {apply_fn}(rows)

If the function is renamed and only one of the two sides
updated, the engine's autonomous fire path silently no-ops
(import error swallowed by the flow's try/except).

Pattern AH catalogs every domain's canonical apply function +
verifies it exists as a top-level FunctionDef in the applier
module.

Companion to Pattern AD (bridge fn) + AE (state is_paused) +
AG (health analyze) -- together these 4 audits lock down the
canonical entry points for every autonomy domain's read/write
boundary.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain (applier module path, expected apply function).
_DOMAIN_APPLY_EXPORTS: dict[
    str, tuple[str, str],
] = {
    "customer_support_refund": (
        "engines/returns_management/refund_applier.py",
        "apply_refunds",
    ),
    "marketing_budget": (
        "engines/roas_guardrails/budget_applier.py",
        "apply_budget_changes",
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_applier.py",
        "apply_fulfillment_routes",
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_applier.py",
        "apply_inventory_reorders",
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_applier.py",
        "apply_discount_cleanup",
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_applier.py",
        "apply_order_followups",
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_applier.py",
        "apply_seo_updates",
    ),
    "customer_outreach": (
        "engines/customer_outreach_autonomy/outreach_applier.py",
        "apply_customer_outreach",
    ),
}


@dataclass
class PatternAHViolation:
    domain: str
    module_path: str
    expected_function: str
    reason: str = ""


@dataclass
class PatternAHReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAHViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _has_top_level_function(
    path: Path, name: str,
) -> bool:
    """Strict: only top-level FunctionDef counts. Applier
    entry points are imported by name from engine flow.py;
    Assign re-exports won't survive the from-import."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AH read failed for %s: %s", path, exc,
        )
        return False
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AH parse failed for %s: %s", path, exc,
        )
        return False
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return True
    return False


def run_pattern_ah_audit() -> PatternAHReport:
    """Verify every autonomy domain's applier exports its
    apply_* entry point as a top-level FunctionDef."""
    report = PatternAHReport()
    for domain, (
        module_path, fn_name,
    ) in _DOMAIN_APPLY_EXPORTS.items():
        report.domains_scanned.append(domain)
        path = Path(module_path)
        if not path.exists():
            report.violations.append(PatternAHViolation(
                domain=domain,
                module_path=module_path,
                expected_function=fn_name,
                reason=(
                    f"applier module {module_path} not found"
                ),
            ))
            continue
        if _has_top_level_function(path, fn_name):
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternAHViolation(
                domain=domain,
                module_path=module_path,
                expected_function=fn_name,
                reason=(
                    f"top-level FunctionDef {fn_name!r} not "
                    "found in applier module"
                ),
            ))
    return report
