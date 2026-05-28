"""Pattern P audit: autonomy substrate adoption (Wave 148).

Wave 117-120 extracted the autonomy boilerplate into
``core/automation/{action_log,pause_state,health_analyzer}.py``.
Wave 126-137 proved the template with fulfillment + inventory
domains. Pattern P prevents drift -- new domains MUST import
from ``core.automation.*`` instead of re-inlining the
boilerplate.

The audit AST-scans every ``*_autonomy/*.py`` module for:
  - ``_log.py`` files must import from core.automation.action_log
  - ``_state.py`` files must import from core.automation.pause_state
  - ``_health.py`` files must import from core.automation.health_analyzer

Existing Phase 11.A/B domains (refund + budget) are GRANDFATHERED
in -- they were written before the template existed and we
deliberately did NOT refactor them. New domains from Wave 126+
must adopt the template.

This audit catches regressions where a future developer copies
the refund_log.py wholesale instead of using the generic
substrate. CI gate + operator command
``shopai pattern-p-audit`` consume the report.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Domains created BEFORE the template extraction. They use the
# inlined-boilerplate pattern by design; not a violation.
_GRANDFATHERED_DOMAINS: frozenset[str] = frozenset({
    "returns_management",   # Phase 11.A (refund_*)
    "roas_guardrails",      # Phase 11.B (budget_*)
})

# Wrapper file suffixes -> required core/automation/ module
_WRAPPER_REQUIREMENTS: dict[str, str] = {
    "_log.py": "core.automation.action_log",
    "_state.py": "core.automation.pause_state",
    "_health.py": "core.automation.health_analyzer",
}


@dataclass
class PatternPViolation:
    domain: str
    file: str
    missing_import: str


@dataclass
class PatternPReport:
    scanned_domains: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternPViolation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _is_autonomy_domain(dir_path: Path) -> bool:
    """Domain directories end in ``_autonomy`` or carry the
    canonical wrapper file suffixes."""
    if dir_path.name.endswith("_autonomy"):
        return True
    # Also accept dirs that have a _log.py + _state.py +
    # _health.py trio (would catch hypothetical
    # "fulfillment" not "fulfillment_autonomy")
    has_log = any(
        f.name.endswith("_log.py")
        for f in dir_path.iterdir() if f.is_file()
    ) if dir_path.is_dir() else False
    has_state = any(
        f.name.endswith("_state.py")
        for f in dir_path.iterdir() if f.is_file()
    ) if dir_path.is_dir() else False
    return has_log and has_state


def _file_imports_from(
    path: Path, module: str,
) -> bool:
    """AST-scan for ``from {module} import ...`` or
    ``import {module}``."""
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern P: read failed for %s: %s",
            path, exc,
        )
        return False
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern P: parse failed for %s: %s",
            path, exc,
        )
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == module:
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module:
                    return True
    return False


def run_pattern_p_audit(
    *,
    engines_dir: str | Path = "engines",
) -> PatternPReport:
    """Audit autonomy domains for substrate adoption."""
    report = PatternPReport()
    base = Path(engines_dir)
    if not base.is_dir():
        return report

    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if not _is_autonomy_domain(child):
            continue
        domain = child.name
        if domain in _GRANDFATHERED_DOMAINS:
            continue
        report.scanned_domains.append(domain)
        domain_violations: list[PatternPViolation] = []
        for f in sorted(child.iterdir()):
            if not f.is_file() or not f.name.endswith(".py"):
                continue
            for suffix, required_module in (
                _WRAPPER_REQUIREMENTS.items()
            ):
                if not f.name.endswith(suffix):
                    continue
                if not _file_imports_from(f, required_module):
                    domain_violations.append(
                        PatternPViolation(
                            domain=domain,
                            file=str(
                                f.relative_to(base).as_posix(),
                            ),
                            missing_import=required_module,
                        ),
                    )
        if domain_violations:
            report.violations.extend(domain_violations)
        else:
            report.clean_domains.append(domain)
    return report
