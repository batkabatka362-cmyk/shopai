"""Pattern AY audit: discoverer test-file existence (W836).

Mirror of Pattern AM (per-domain test coverage) but for the
payload-discoverer registry. Every registered discoverer must
have a corresponding ``tests/test_discoverer_<domain>.py``
file. Without this audit, scaffolded discoverers can be
merged with zero test coverage and nobody notices until a
production drift.

The audit is intentionally loose:

  1. Existence check on ``tests/test_discoverer_<domain>.py``
  2. File contains at least one ``def test_`` function
     (loose AST check; doesn't verify the test actually
     exercises the discoverer).

If a future test layout uses a different filename pattern,
update the convention here in one place.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternAYViolation:
    domain: str
    reason: str


@dataclass
class PatternAYReport:
    discoverers_scanned: list[str] = field(default_factory=list)
    clean_discoverers: list[str] = field(default_factory=list)
    violations: list[PatternAYViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _has_test_functions(path: Path) -> bool:
    """Loose AST check: any top-level function whose name
    starts with ``test_`` counts."""
    try:
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
    except Exception:  # noqa: BLE001
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and (
            node.name.startswith("test_")
        ):
            return True
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(
                    sub, ast.FunctionDef,
                ) and sub.name.startswith("test_"):
                    return True
    return False


def run_pattern_ay_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternAYReport:
    """For every registered discoverer, assert a matching
    test_discoverer_<domain>.py exists with at least one
    test_ function."""
    report = PatternAYReport()
    root = Path(repo_root).resolve()

    try:
        from core.automation import (  # noqa: F401
            discoverer_registry,
        )
        from core.automation.payload_discoverer import (
            registered_domains,
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAYViolation(
            domain="",
            reason=f"import failed: {exc!s:.150}",
        ))
        return report

    tests_dir = root / "tests"
    for domain in registered_domains():
        report.discoverers_scanned.append(domain)
        path = tests_dir / f"test_discoverer_{domain}.py"
        if not path.exists():
            report.violations.append(PatternAYViolation(
                domain=domain,
                reason=(
                    f"test file missing at {path.relative_to(root).as_posix()}"
                ),
            ))
            continue
        if not _has_test_functions(path):
            report.violations.append(PatternAYViolation(
                domain=domain,
                reason=(
                    f"{path.name} contains no test_* "
                    "function (loose AST scan)"
                ),
            ))
            continue
        report.clean_discoverers.append(domain)

    return report
