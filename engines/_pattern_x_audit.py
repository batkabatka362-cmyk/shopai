"""Pattern X audit: autonomy_status rollup coverage (W226).

Pattern Q' verifies each domain's summary follows the canonical
DomainSummary shape. Pattern X verifies the OUTER end of the
rollup: that ``core.automation.autonomy_status`` actually defines
+ invokes a per-domain summary function for every autonomy domain.

Concretely, for each domain there must be:
  1. a module-level ``_<expected>_summary`` FunctionDef in
     ``autonomy_status.py``
  2. that function name must appear inside ``get_autonomy_status``'s
     body (so the rollup actually folds it in)

Catches the "I added an 8th autonomy domain but forgot to wire its
summary into get_autonomy_status" class bug. That bug is silent --
the domain ships fine but is invisible to ``shopai autonomy-status``
+ world-model + daily-brief.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain expected ``_<X>_summary`` function name in the
# autonomy_status module. Note the *_refund / *_budget suffixes
# from Pattern T's domain catalog are dropped here -- the summary
# functions were named per-CONCERN not per-bridge (Phase 11.A/B
# legacy that's stuck).
_DOMAIN_SUMMARY_FUNCS: dict[str, str] = {
    "customer_support_refund": "_customer_support_summary",
    "marketing_budget": "_marketing_summary",
    "fulfillment": "_fulfillment_summary",
    "inventory": "_inventory_summary",
    "discount_cleanup": "_discount_cleanup_summary",
    "order_followup": "_order_followup_summary",
    "product_seo": "_product_seo_summary",
    "customer_outreach": "_customer_outreach_summary",
    "catalog_quality": "_catalog_quality_summary",
    "shipping_alert": "_shipping_alert_summary",
}


@dataclass
class PatternXViolation:
    domain: str
    expected_func: str
    reason: str = ""


@dataclass
class PatternXReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternXViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _parse_module(path: Path) -> ast.Module | None:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern X read failed for %s: %s", path, exc,
        )
        return None
    try:
        return ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern X parse failed for %s: %s", path, exc,
        )
        return None


def _has_function_def(tree: ast.Module, name: str) -> bool:
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return True
    return False


def _get_autonomy_status_body(tree: ast.Module) -> str | None:
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "get_autonomy_status"
        ):
            try:
                return ast.unparse(node)
            except Exception:  # noqa: BLE001
                return None
    return None


def run_pattern_x_audit(
    *,
    autonomy_status_path: str | Path = (
        "core/automation/autonomy_status.py"
    ),
) -> PatternXReport:
    """Verify every autonomy domain has a defined + invoked
    summary function in autonomy_status."""
    report = PatternXReport()
    path = Path(autonomy_status_path)
    tree = _parse_module(path)
    if tree is None:
        for domain, expected in (
            _DOMAIN_SUMMARY_FUNCS.items()
        ):
            report.domains_scanned.append(domain)
            report.violations.append(PatternXViolation(
                domain=domain,
                expected_func=expected,
                reason=(
                    f"{autonomy_status_path} unreadable / "
                    "unparseable"
                ),
            ))
        return report

    rollup_body = _get_autonomy_status_body(tree)
    for domain, expected in _DOMAIN_SUMMARY_FUNCS.items():
        report.domains_scanned.append(domain)
        if not _has_function_def(tree, expected):
            report.violations.append(PatternXViolation(
                domain=domain,
                expected_func=expected,
                reason=(
                    f"function {expected!r} not defined in "
                    "autonomy_status module"
                ),
            ))
            continue
        if rollup_body is None or expected not in rollup_body:
            report.violations.append(PatternXViolation(
                domain=domain,
                expected_func=expected,
                reason=(
                    f"function {expected!r} not invoked "
                    "from get_autonomy_status rollup"
                ),
            ))
            continue
        report.clean_domains.append(domain)
    return report
