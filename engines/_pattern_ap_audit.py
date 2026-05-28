"""Pattern AP audit: bridge cascade isolation (W353).

Pattern U / Pattern AK verified each domain's
``maybe_auto_pause_X`` is invoked from cycle_run. Pattern AP
adds the structural check: each invocation must be inside a
``try/except`` so a crash in one domain's bridge doesn't
cascade to abort the other 6 bridges (and the cycle's
post-fire reporting).

The actual cli.py implementation wraps each bridge call in a
``try/except Exception`` -- Pattern AP locks in that structure
so a refactor that removes the try block (because "it never
throws") fails at PR time.

AST approach: walk ``_cmd_cycle_run`` body, find each
``ast.Try`` block, collect the bridge symbols invoked inside
its body. For each expected bridge name, assert it appears in
at least one Try block's body.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Reuse Pattern U / AK catalog.
_DOMAIN_BRIDGES: dict[str, str] = {
    "customer_support_refund": "maybe_auto_pause_refunds",
    "marketing_budget": "maybe_auto_pause_budget",
    "fulfillment": "maybe_auto_pause_fulfillment",
    "inventory": "maybe_auto_pause_inventory",
    "discount_cleanup": "maybe_auto_pause_cleanup",
    "order_followup": "maybe_auto_pause_followup",
    "product_seo": "maybe_auto_pause_seo",
    "customer_outreach": "maybe_auto_pause_outreach",
    "catalog_quality": "maybe_auto_pause_quality",
}


@dataclass
class PatternAPViolation:
    domain: str
    bridge_name: str
    reason: str = ""


@dataclass
class PatternAPReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAPViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _cycle_run_func(
    cli_path: Path,
) -> ast.FunctionDef | None:
    try:
        src = cli_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AP read failed for %s: %s", cli_path, exc,
        )
        return None
    try:
        tree = ast.parse(src, filename=str(cli_path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AP parse failed for %s: %s", cli_path, exc,
        )
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_cmd_cycle_run"
        ):
            return node
    return None


def _bridges_inside_try_blocks(
    func_node: ast.FunctionDef,
) -> set[str]:
    """Collect every ``maybe_auto_pause_X`` symbol invoked
    inside an ``ast.Try`` block within ``_cmd_cycle_run``.
    Symbols invoked OUTSIDE try blocks are intentionally NOT
    counted -- the audit's whole point is to enforce the
    try-wrap."""
    out: set[str] = set()
    for try_node in ast.walk(func_node):
        if not isinstance(try_node, ast.Try):
            continue
        # Walk the try body looking for ast.Call to a Name
        # starting with maybe_auto_pause_
        for inner in ast.walk(try_node):
            if not isinstance(inner, ast.Call):
                continue
            callee = inner.func
            if (
                isinstance(callee, ast.Name)
                and callee.id.startswith("maybe_auto_pause_")
            ):
                out.add(callee.id)
    return out


def run_pattern_ap_audit(
    *,
    cli_path: str | Path = "cli.py",
) -> PatternAPReport:
    """Verify every domain's bridge invocation is wrapped in
    try/except inside _cmd_cycle_run."""
    report = PatternAPReport()
    func = _cycle_run_func(Path(cli_path))
    if func is None:
        for domain, bridge in _DOMAIN_BRIDGES.items():
            report.domains_scanned.append(domain)
            report.violations.append(PatternAPViolation(
                domain=domain,
                bridge_name=bridge,
                reason="cli.py / _cmd_cycle_run not parseable",
            ))
        return report
    inside_try = _bridges_inside_try_blocks(func)
    for domain, bridge in _DOMAIN_BRIDGES.items():
        report.domains_scanned.append(domain)
        if bridge in inside_try:
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternAPViolation(
                domain=domain,
                bridge_name=bridge,
                reason=(
                    f"bridge {bridge!r} invoked but NOT "
                    "wrapped in try/except -- a crash here "
                    "would cascade to subsequent domains"
                ),
            ))
    return report
