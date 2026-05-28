"""Pattern AO audit: applier docstring safety gate doc (W338).

Each autonomy domain's applier wraps a Shopify mutation behind
N safety gates. The gate logic itself lives in the applier
function body; the architectural CONTRACT (which gates exist,
in what order) lives in the applier MODULE's docstring. Without
that documentation, future operators auditing safety can't
quickly tell which gates are in place.

Pattern AO heuristically counts numbered list items
(``1. /2. /3. ...``) in each applier module's module-level
docstring + asserts >= 4 (the architectural floor matching
what every domain currently documents).

Threshold rationale: current 7 domains document 4-6 gates each.
A floor of 4 keeps everyone passing today + forces future
domains to at minimum match the simplest existing pattern
(fulfillment with 4 gates) before merging.

The audit is heuristic, not enforcing specific gate content --
the goal is "applier explained itself" not "applier matched a
template".
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain applier path.
_DOMAIN_APPLIERS: dict[str, str] = {
    "customer_support_refund": (
        "engines/returns_management/refund_applier.py"
    ),
    "marketing_budget": (
        "engines/roas_guardrails/budget_applier.py"
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_applier.py"
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_applier.py"
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_applier.py"
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_applier.py"
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_applier.py"
    ),
    "customer_outreach": (
        "engines/customer_outreach_autonomy/outreach_applier.py"
    ),
}


_MIN_GATES = 4

# Regex for detecting numbered list entries at line start
# (allows leading whitespace because docstring indent varies).
_NUMBERED_GATE_RE = re.compile(
    r"^\s*\d+\.\s", re.MULTILINE,
)


@dataclass
class PatternAOViolation:
    domain: str
    applier_path: str
    gates_found: int = 0
    reason: str = ""


@dataclass
class PatternAOReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAOViolation] = field(
        default_factory=list,
    )
    gates_by_domain: dict[str, int] = field(
        default_factory=dict,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _count_gates(path: Path) -> int:
    """Count numbered list entries in the applier module's
    module-level docstring. Returns 0 on any failure."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AO read failed for %s: %s", path, exc,
        )
        return 0
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AO parse failed for %s: %s", path, exc,
        )
        return 0
    docstring = ast.get_docstring(tree) or ""
    return len(_NUMBERED_GATE_RE.findall(docstring))


def run_pattern_ao_audit() -> PatternAOReport:
    """Verify each domain's applier docstring documents >=4
    safety gates."""
    report = PatternAOReport()
    for domain, applier_path in _DOMAIN_APPLIERS.items():
        report.domains_scanned.append(domain)
        path = Path(applier_path)
        if not path.exists():
            report.violations.append(PatternAOViolation(
                domain=domain,
                applier_path=applier_path,
                reason=(
                    f"applier {applier_path} not found"
                ),
            ))
            continue
        n = _count_gates(path)
        report.gates_by_domain[domain] = n
        if n < _MIN_GATES:
            report.violations.append(PatternAOViolation(
                domain=domain,
                applier_path=applier_path,
                gates_found=n,
                reason=(
                    f"docstring has {n} numbered gate(s); "
                    f"floor is {_MIN_GATES}"
                ),
            ))
        else:
            report.clean_domains.append(domain)
    return report
