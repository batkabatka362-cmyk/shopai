"""Pattern AN audit: writer _ENGINE constant + usage (W327).

Each autonomy domain's applier module declares an ``_ENGINE``
module-level string constant that gets passed to
``record_writeback(engine=_ENGINE, ...)``. This engine name is
the key under which MemoryIntelligence / DataArchitecture /
LearningLoop file the action's outcome -- a typo here means
the autonomous loop's learning systems can't correlate the
action back to the engine that produced it.

Pattern AN catches the two failure modes:
  1. ``_ENGINE`` constant missing or typo'd
  2. ``_ENGINE`` declared but never passed to record_writeback
     (caller hardcoded a string literal instead, which drifts
     when the constant is later renamed)

The catalog records the expected ``_ENGINE`` value per domain
based on what's currently in production. If a future PR wants
to rename an engine, both the catalog AND the applier change
in the same diff -- which means Pattern AN's CI gate forces
the symmetric update.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain (applier path, expected _ENGINE value).
_DOMAIN_ENGINE_NAMES: dict[
    str, tuple[str, str],
] = {
    "customer_support_refund": (
        "engines/returns_management/refund_applier.py",
        "returns_management",
    ),
    "marketing_budget": (
        "engines/roas_guardrails/budget_applier.py",
        "roas_guardrails",
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_applier.py",
        "order_management",
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_applier.py",
        "inventory",
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_applier.py",
        "discount_cleanup",
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_applier.py",
        "order_followup",
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_applier.py",
        "product_seo",
    ),
}


@dataclass
class PatternANViolation:
    domain: str
    expected_engine: str
    actual_engine: str = ""
    reason: str = ""


@dataclass
class PatternANReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternANViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _extract_engine_constant(
    path: Path,
) -> tuple[str | None, bool]:
    """Return (value, used_in_record_writeback). Value is the
    string assigned to ``_ENGINE`` at module level; None if
    not found. used flag is True iff ``record_writeback`` is
    called with ``engine=_ENGINE``."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AN read failed for %s: %s", path, exc,
        )
        return (None, False)
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AN parse failed for %s: %s", path, exc,
        )
        return (None, False)

    # Step 1: find _ENGINE = "..."
    engine_value: str | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for tgt in node.targets:
            if (
                isinstance(tgt, ast.Name)
                and tgt.id == "_ENGINE"
            ):
                engine_value = node.value.value
                break

    # Step 2: find record_writeback(engine=_ENGINE, ...)
    used = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        callee_name = ""
        if isinstance(callee, ast.Name):
            callee_name = callee.id
        elif isinstance(callee, ast.Attribute):
            callee_name = callee.attr
        if callee_name != "record_writeback":
            continue
        for kw in node.keywords:
            if (
                kw.arg == "engine"
                and isinstance(kw.value, ast.Name)
                and kw.value.id == "_ENGINE"
            ):
                used = True
                break
        if used:
            break
    return (engine_value, used)


def run_pattern_an_audit() -> PatternANReport:
    """Verify each domain's applier has the canonical _ENGINE
    constant + uses it in record_writeback."""
    report = PatternANReport()
    for domain, (
        applier_path, expected,
    ) in _DOMAIN_ENGINE_NAMES.items():
        report.domains_scanned.append(domain)
        path = Path(applier_path)
        if not path.exists():
            report.violations.append(PatternANViolation(
                domain=domain,
                expected_engine=expected,
                reason=(
                    f"applier {applier_path} not found"
                ),
            ))
            continue
        value, used = _extract_engine_constant(path)
        if value is None:
            report.violations.append(PatternANViolation(
                domain=domain,
                expected_engine=expected,
                reason=(
                    "_ENGINE module-level constant not "
                    "declared"
                ),
            ))
            continue
        if value != expected:
            report.violations.append(PatternANViolation(
                domain=domain,
                expected_engine=expected,
                actual_engine=value,
                reason=(
                    f"_ENGINE={value!r} but catalog "
                    f"expects {expected!r}"
                ),
            ))
            continue
        if not used:
            report.violations.append(PatternANViolation(
                domain=domain,
                expected_engine=expected,
                actual_engine=value,
                reason=(
                    "_ENGINE declared but not used in "
                    "record_writeback(engine=_ENGINE, ...)"
                ),
            ))
            continue
        report.clean_domains.append(domain)
    return report
