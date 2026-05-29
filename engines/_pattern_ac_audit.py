"""Pattern AC audit: autonomy CLI command parity (W232).

Each autonomy domain ships 4 standard operator CLI subcommands:

  - ``{prefix}-status``  empire-wide aggregator report
  - ``{prefix}-health``  health verdict + --apply-bridge
  - ``{prefix}-pause``   manual pause flag set
  - ``{prefix}-resume``  manual pause flag clear

Pattern S (W181) verified every existing autonomy CLI command
accepts ``--json``. Pattern AC closes the upstream contract:
asserts every domain has all 4 commands actually REGISTERED as
subparsers in ``cli.py``.

Catches "added 8th autonomy domain but forgot to register the
-pause subparser" class bugs. Subparser absence is silent at
argparse level (the parent --help just doesn't list it) but
operator commands fail with a confusing parse error at fire
time.

AST approach: walk cli.py + collect every literal first-arg
string passed to ``sub.add_parser(...)``. Then check each
domain's 4 expected command names appear in the collected set.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain CLI command prefix. Each prefix gets the 4 standard
# subcommands appended: -status / -health / -pause / -resume.
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
class PatternACViolation:
    domain: str
    prefix: str
    missing_commands: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class PatternACReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternACViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _collect_subparser_names(cli_path: Path) -> set[str] | None:
    """AST-walk cli.py + return every literal name passed to
    ``add_parser(...)``. Returns None on read/parse failure."""
    try:
        src = cli_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AC read failed for %s: %s", cli_path, exc,
        )
        return None
    try:
        tree = ast.parse(src, filename=str(cli_path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AC parse failed for %s: %s", cli_path, exc,
        )
        return None
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match `something.add_parser(...)` calls; the receiver
        # is typically `sub` but we don't bind to a specific
        # name -- any add_parser counts.
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_parser":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
        ):
            out.add(first.value)
    return out


def run_pattern_ac_audit(
    *,
    cli_path: str | Path = "cli.py",
) -> PatternACReport:
    """Verify every autonomy domain has all 4 standard CLI
    subcommands registered."""
    report = PatternACReport()
    names = _collect_subparser_names(Path(cli_path))
    if names is None:
        for domain, prefix in _DOMAIN_CLI_PREFIXES.items():
            report.domains_scanned.append(domain)
            report.violations.append(PatternACViolation(
                domain=domain,
                prefix=prefix,
                missing_commands=[
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
            if cmd not in names:
                missing.append(cmd)
        if missing:
            report.violations.append(PatternACViolation(
                domain=domain,
                prefix=prefix,
                missing_commands=missing,
                reason=(
                    f"{len(missing)} CLI subcommand(s) not "
                    "registered"
                ),
            ))
        else:
            report.clean_domains.append(domain)
    return report
