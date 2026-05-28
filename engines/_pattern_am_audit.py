"""Pattern AM audit: per-domain test file coverage (W322).

The autonomy domain template prescribes 5 module files; the
cross-domain integration test (W239-244) exercises the runtime
contract; but nothing enforces that EACH domain ships with at
least one domain-specific test file in ``tests/``.

Without Pattern AM the door is open for a new domain to ship
with zero tests beyond the integration smoke -- catastrophic if
the new domain's safety gates or applier logic regress in a way
the integration test doesn't catch (which is most ways, since
the integration test calls each entry point with empty input).

Pattern AM verifies every domain has at least one ``tests/
test_*.py`` file whose name matches the domain's acceptable
keyword set. Keyword set lives in the catalog (a few common
abbreviations per domain because legacy file naming wasn't
uniform).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain (tuple of acceptable filename keywords). A test
# file qualifies if its name contains ANY of these strings.
_DOMAIN_TEST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "customer_support_refund": ("refund",),
    "marketing_budget": (
        "marketing_autonomy", "budget", "ad_spend",
    ),
    "fulfillment": ("fulfillment_autonomy", "fulfillment",),
    "inventory": ("inventory_autonomy", "inventory_approval"),
    "discount_cleanup": (
        "discount_cleanup_autonomy", "discount_cleanup",
    ),
    "order_followup": (
        "order_followup_autonomy", "order_followup",
        "followup",
    ),
    "product_seo": (
        "product_seo_autonomy", "product_seo",
    ),
}


@dataclass
class PatternAMViolation:
    domain: str
    keywords: tuple[str, ...] = ()
    reason: str = ""


@dataclass
class PatternAMReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAMViolation] = field(
        default_factory=list,
    )
    test_files_by_domain: dict[str, list[str]] = field(
        default_factory=dict,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _matching_test_files(
    tests_dir: Path, keywords: tuple[str, ...],
) -> list[str]:
    """Return sorted test_*.py files in tests_dir matching ANY
    of the keywords."""
    if not tests_dir.exists():
        return []
    try:
        all_files = os.listdir(tests_dir)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AM listdir failed for %s: %s",
            tests_dir, exc,
        )
        return []
    matches: list[str] = []
    for fname in sorted(all_files):
        if not fname.startswith("test_"):
            continue
        if not fname.endswith(".py"):
            continue
        for kw in keywords:
            if kw in fname:
                matches.append(fname)
                break
    return matches


def run_pattern_am_audit(
    *,
    tests_dir: str | Path = "tests",
) -> PatternAMReport:
    """Verify every autonomy domain has at least one test file."""
    report = PatternAMReport()
    tdir = Path(tests_dir)
    for domain, keywords in _DOMAIN_TEST_KEYWORDS.items():
        report.domains_scanned.append(domain)
        matches = _matching_test_files(tdir, keywords)
        report.test_files_by_domain[domain] = matches
        if matches:
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternAMViolation(
                domain=domain,
                keywords=keywords,
                reason=(
                    f"no test_*.py in {tests_dir} matched any "
                    f"of: {keywords}"
                ),
            ))
    return report
