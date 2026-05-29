"""Pattern U audit: cycle hook coverage (Wave 203).

Every autonomy domain has a ``maybe_auto_pause_X()`` bridge
function that ``cycle run --yes`` is supposed to fire post-
cycle. Missing the cycle hook means the auto-pause safety
loop is dead -- adapter_failed ratios can spike without ever
triggering the pause flag.

Pattern U verifies every autonomy domain's bridge symbol is
referenced from cli.py's _cmd_cycle_run body. AST-level check:
walk the function definition + look for Name nodes matching
known bridge functions.

Catches the "forgot to wire 8th domain into cycle" class bug
that's invisible at unit-test level (each domain's tests mock
the bridge but don't verify cli.py actually invokes it).
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain bridge function names. Each entry maps the domain
# label to its maybe_auto_pause_X identifier that should appear
# in cli.py's _cmd_cycle_run.
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
class PatternUViolation:
    domain: str
    bridge_name: str
    reason: str = ""


@dataclass
class PatternUReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternUViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _extract_cycle_run_body(
    cli_path: Path,
) -> str | None:
    """Read cli.py + return _cmd_cycle_run's source body. Returns
    None on parse failure or missing function."""
    try:
        source = cli_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pattern U cli.py read raised: %s", exc)
        return None
    try:
        tree = ast.parse(source, filename=str(cli_path))
    except SyntaxError as exc:
        logger.debug("Pattern U cli.py parse raised: %s", exc)
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_cmd_cycle_run"
        ):
            try:
                return ast.unparse(node)
            except Exception:  # noqa: BLE001
                return None
    return None


def run_pattern_u_audit(
    *,
    cli_path: str | Path = "cli.py",
) -> PatternUReport:
    """Audit every autonomy domain bridge is wired into
    cycle run."""
    report = PatternUReport()
    body = _extract_cycle_run_body(Path(cli_path))
    if body is None:
        # cli.py unreadable -- treat every bridge as a violation
        for domain, bridge in _DOMAIN_BRIDGES.items():
            report.domains_scanned.append(domain)
            report.violations.append(PatternUViolation(
                domain=domain,
                bridge_name=bridge,
                reason="cli.py / _cmd_cycle_run unreadable",
            ))
        return report

    for domain, bridge in _DOMAIN_BRIDGES.items():
        report.domains_scanned.append(domain)
        if bridge in body:
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternUViolation(
                domain=domain,
                bridge_name=bridge,
                reason=(
                    f"bridge function {bridge!r} not "
                    "referenced inside _cmd_cycle_run"
                ),
            ))
    return report
