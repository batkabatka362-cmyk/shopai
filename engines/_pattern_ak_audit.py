"""Pattern AK audit: cycle bridge is invoked as ast.Call (W308).

Pattern U (W203) verified each domain's ``maybe_auto_pause_X``
symbol APPEARS in ``_cmd_cycle_run``'s body via text substring
match. Pattern AK upgrades the check to *call-shape*: verifies
each bridge function is invoked as an actual ``ast.Call``
expression (not just referenced as a string literal, comment,
or docstring).

The text-based check passes a refactor that accidentally moves
the bridge symbol into a log message or docstring while
deleting the actual invocation. The runtime symptom is the
SAME as missing the bridge entirely (no auto-pause), but
Pattern U would still report green. Pattern AK closes that
gap.

AST approach: walk cli.py, find ``_cmd_cycle_run`` FunctionDef,
then walk its body looking for ``ast.Call`` nodes whose func is
``ast.Name(id="maybe_auto_pause_X")``.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Reuse Pattern U's catalog: domain → bridge function name.
# Pattern AK reads the same catalog -- the audits are
# complementary, not duplicative.
_DOMAIN_BRIDGES: dict[str, str] = {
    "customer_support_refund": "maybe_auto_pause_refunds",
    "marketing_budget": "maybe_auto_pause_budget",
    "fulfillment": "maybe_auto_pause_fulfillment",
    "inventory": "maybe_auto_pause_inventory",
    "discount_cleanup": "maybe_auto_pause_cleanup",
    "order_followup": "maybe_auto_pause_followup",
    "product_seo": "maybe_auto_pause_seo",
    "customer_outreach": "maybe_auto_pause_outreach",
}


@dataclass
class PatternAKViolation:
    domain: str
    bridge_name: str
    reason: str = ""


@dataclass
class PatternAKReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAKViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _cycle_run_func(
    cli_path: Path,
) -> ast.FunctionDef | None:
    """AST-extract ``_cmd_cycle_run``'s FunctionDef node. Returns
    None on read/parse failure or missing function."""
    try:
        src = cli_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AK read failed for %s: %s", cli_path, exc,
        )
        return None
    try:
        tree = ast.parse(src, filename=str(cli_path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AK parse failed for %s: %s", cli_path, exc,
        )
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_cmd_cycle_run"
        ):
            return node
    return None


def _has_invocation(
    func_node: ast.FunctionDef, name: str,
) -> bool:
    """True if any ast.Call inside func_node has Name(id=name)
    as its callee. Covers direct calls
    ``maybe_auto_pause_X()``."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if (
            isinstance(callee, ast.Name)
            and callee.id == name
        ):
            return True
    return False


def run_pattern_ak_audit(
    *,
    cli_path: str | Path = "cli.py",
) -> PatternAKReport:
    """Verify every autonomy domain's bridge is invoked as a
    real ast.Call inside _cmd_cycle_run."""
    report = PatternAKReport()
    func = _cycle_run_func(Path(cli_path))
    if func is None:
        for domain, bridge in _DOMAIN_BRIDGES.items():
            report.domains_scanned.append(domain)
            report.violations.append(PatternAKViolation(
                domain=domain,
                bridge_name=bridge,
                reason="cli.py / _cmd_cycle_run not parseable",
            ))
        return report

    for domain, bridge in _DOMAIN_BRIDGES.items():
        report.domains_scanned.append(domain)
        if _has_invocation(func, bridge):
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternAKViolation(
                domain=domain,
                bridge_name=bridge,
                reason=(
                    f"bridge {bridge!r} referenced but NOT "
                    "invoked as ast.Call inside cycle_run "
                    "(possible docstring/string-literal "
                    "reference only)"
                ),
            ))
    return report
