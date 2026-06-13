"""Pattern AJ audit: CLI dispatch parity (W300).

Pattern AC (W232) verified each autonomy domain has all 4 CLI
subparsers REGISTERED (``sub.add_parser("X-status")`` etc).
Pattern AJ adds the symmetric check: every registered subparser
must have a corresponding DISPATCH branch in main()
(``if args.command == "X-status": _cmd_X_status(args)``).

Caught live during Phase 20 development: when a subparser is
registered without a dispatch branch, argparse parses the
command successfully (no error to operator) but no handler
fires -- the program exits silently. Catastrophic UX, silent
at autoreg level.

AST approach: walk cli.py + collect every literal string
appearing in ``args.command == "X"`` comparisons inside main().
Then for each domain's 4 commands, assert the literal appears
in the dispatch set.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Reuse Pattern AC's catalog: same domain → CLI-prefix mapping.
# Per-domain expected dispatch literals = prefix-{status,health,
# pause,resume}.
_DOMAIN_CLI_PREFIXES: dict[str, str] = {
    "customer_support_refund": "refund",
    "marketing_budget": "marketing",
    "fulfillment": "fulfillment",
    "inventory": "inventory",
    "discount_cleanup": "discount-cleanup",
    "order_followup": "order-followup",
    "product_seo": "product-seo",
    "customer_outreach": "customer-outreach",
    "catalog_quality": "catalog-quality",
    "shipping_alert": "shipping-alert",
}


_REQUIRED_SUFFIXES = ("status", "health", "pause", "resume")


@dataclass
class PatternAJViolation:
    domain: str
    prefix: str
    missing_dispatch: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class PatternAJReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAJViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _collect_dispatch_literals(
    cli_path: Path,
) -> set[str] | None:
    """AST-walk cli.py + collect every literal X appearing in
    ``args.command == "X"`` or ``"X" == args.command``
    comparisons. Returns None on read/parse failure."""
    try:
        src = cli_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AJ read failed for %s: %s", cli_path, exc,
        )
        return None
    try:
        tree = ast.parse(src, filename=str(cli_path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AJ parse failed for %s: %s", cli_path, exc,
        )
        return None
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # Look for ``args.command == "X"`` or ``"X" == args.command``
        sides = [node.left, *node.comparators]
        constants = [
            s for s in sides
            if isinstance(s, ast.Constant)
            and isinstance(s.value, str)
        ]
        attr_command = any(
            isinstance(s, ast.Attribute)
            and s.attr == "command"
            for s in sides
        )
        if attr_command and constants:
            for c in constants:
                out.add(c.value)
    return out


def run_pattern_aj_audit(
    *,
    cli_path: str | Path = "cli.py",
) -> PatternAJReport:
    """Verify every autonomy domain's 4 CLI subcommands have
    a matching dispatch branch in main()."""
    report = PatternAJReport()
    dispatch = _collect_dispatch_literals(Path(cli_path))
    if dispatch is None:
        for domain, prefix in _DOMAIN_CLI_PREFIXES.items():
            report.domains_scanned.append(domain)
            report.violations.append(PatternAJViolation(
                domain=domain,
                prefix=prefix,
                missing_dispatch=[
                    f"{prefix}-{s}" for s in _REQUIRED_SUFFIXES
                ],
                reason="cli.py unreadable / unparseable",
            ))
        return report

    for domain, prefix in _DOMAIN_CLI_PREFIXES.items():
        report.domains_scanned.append(domain)
        missing: list[str] = []
        for suffix in _REQUIRED_SUFFIXES:
            cmd = f"{prefix}-{suffix}"
            if cmd not in dispatch:
                missing.append(cmd)
        if missing:
            report.violations.append(PatternAJViolation(
                domain=domain,
                prefix=prefix,
                missing_dispatch=missing,
                reason=(
                    f"{len(missing)} dispatch branch(es) "
                    "missing"
                ),
            ))
        else:
            report.clean_domains.append(domain)
    return report
