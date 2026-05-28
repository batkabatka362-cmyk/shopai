"""Pattern AI audit: status module get_X_status export (W286).

Every autonomy domain's status module exposes a
``get_X_status(...)`` function as the read-side empire-aggregator
boundary. The CLI handler for ``shopai {domain}-status`` imports
this by name; if renamed and only the module updated (not the
CLI handler), the operator command fails at fire-time.

Pattern X (W226) verified the per-domain ``_<X>_summary()``
function inside ``autonomy_status.py`` (the rollup boundary).
Pattern AI closes the symmetric end: verifies each domain's
status MODULE exports its canonical ``get_X_status`` function.

Companion to AD (bridge) + AE (state is_paused) + AF (log) +
AG (health analyze) + AH (applier) -- together these 6 audits
lock down EVERY canonical entry-point per autonomy domain's
5-piece template.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain (status module path, expected get_X_status function).
_DOMAIN_STATUS_EXPORTS: dict[
    str, tuple[str, str],
] = {
    "customer_support_refund": (
        "engines/returns_management/refund_status.py",
        "get_refund_status",
    ),
    "marketing_budget": (
        "engines/roas_guardrails/marketing_status.py",
        "get_marketing_status",
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_status.py",
        "get_fulfillment_status",
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_status.py",
        "get_inventory_status",
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_status.py",
        "get_cleanup_status",
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_status.py",
        "get_followup_status",
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_status.py",
        "get_seo_status",
    ),
    "customer_outreach": (
        "engines/customer_outreach_autonomy/outreach_status.py",
        "get_customer_outreach_status",
    ),
}


@dataclass
class PatternAIViolation:
    domain: str
    module_path: str
    expected_function: str
    reason: str = ""


@dataclass
class PatternAIReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAIViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _has_top_level_function(
    path: Path, name: str,
) -> bool:
    """Strict: only top-level FunctionDef. CLI handlers do
    from-import; Assign aliases aren't reliable."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AI read failed for %s: %s", path, exc,
        )
        return False
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AI parse failed for %s: %s", path, exc,
        )
        return False
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return True
    return False


def run_pattern_ai_audit() -> PatternAIReport:
    """Verify every autonomy domain's status module exports
    its get_X_status entry point as a top-level FunctionDef."""
    report = PatternAIReport()
    for domain, (
        module_path, fn_name,
    ) in _DOMAIN_STATUS_EXPORTS.items():
        report.domains_scanned.append(domain)
        path = Path(module_path)
        if not path.exists():
            report.violations.append(PatternAIViolation(
                domain=domain,
                module_path=module_path,
                expected_function=fn_name,
                reason=(
                    f"status module {module_path} not found"
                ),
            ))
            continue
        if _has_top_level_function(path, fn_name):
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternAIViolation(
                domain=domain,
                module_path=module_path,
                expected_function=fn_name,
                reason=(
                    f"top-level FunctionDef {fn_name!r} not "
                    "found in status module"
                ),
            ))
    return report
