"""Pattern AE audit: state module is_paused export (W261).

Every autonomy domain's applier gates on
``state_module.is_paused()`` BEFORE invoking the Shopify
mutation. If the state module renames or removes the
``is_paused`` symbol, the applier crashes at fire-time with an
``AttributeError`` -- too late.

Pattern AE catches this at PR-time: verifies each domain's
state module exposes ``is_paused`` either as

  - a top-level ``FunctionDef``  (Phase 11.A/B inline form), OR
  - a top-level ``Assign`` to a name (Phase 12+ template re-
    export pattern: ``is_paused = _pause_state.is_paused``)

Both are valid; the audit accepts either shape.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain state module path. The expected exported symbol
# is always ``is_paused`` -- the SHAPE is what varies.
_DOMAIN_STATE_MODULES: dict[str, str] = {
    "customer_support_refund": (
        "engines/returns_management/refund_state.py"
    ),
    "marketing_budget": (
        "engines/roas_guardrails/budget_state.py"
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_state.py"
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_state.py"
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_state.py"
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_state.py"
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_state.py"
    ),
}


_EXPECTED_SYMBOL = "is_paused"


@dataclass
class PatternAEViolation:
    domain: str
    module_path: str
    reason: str = ""


@dataclass
class PatternAEReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAEViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _module_exports_symbol(
    path: Path, symbol: str,
) -> bool:
    """True if ``symbol`` is exported at module level via
    either a FunctionDef OR a top-level Assign target."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AE read failed for %s: %s", path, exc,
        )
        return False
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AE parse failed for %s: %s", path, exc,
        )
        return False
    for node in tree.body:
        # Form 1: def is_paused(...)
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == symbol
        ):
            return True
        # Form 2: is_paused = ...
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and tgt.id == symbol
                ):
                    return True
        # Form 3: is_paused: Callable = ... (AnnAssign)
        if isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == symbol
            ):
                return True
    return False


def run_pattern_ae_audit() -> PatternAEReport:
    """Verify every autonomy domain's state module exports
    ``is_paused`` at the top level."""
    report = PatternAEReport()
    for domain, module_path in _DOMAIN_STATE_MODULES.items():
        report.domains_scanned.append(domain)
        path = Path(module_path)
        if not path.exists():
            report.violations.append(PatternAEViolation(
                domain=domain,
                module_path=module_path,
                reason=f"state module {module_path} not found",
            ))
            continue
        if _module_exports_symbol(path, _EXPECTED_SYMBOL):
            report.clean_domains.append(domain)
        else:
            report.violations.append(PatternAEViolation(
                domain=domain,
                module_path=module_path,
                reason=(
                    f"top-level {_EXPECTED_SYMBOL!r} symbol "
                    "not found (FunctionDef / Assign / "
                    "AnnAssign)"
                ),
            ))
    return report
