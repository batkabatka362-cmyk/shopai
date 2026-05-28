"""Pattern AF audit: log module export interface (W269).

Every autonomy domain's log module is the WRITE-side of the
observability loop -- each applier calls a ``record_X_event``
function on every fire. Operator surfaces (status / health /
daily-brief) call a ``recent_X_events`` function to read back
the last N entries. And every log module exposes ``log_size()``
for diagnostic surfaces.

Pattern AF catches "renamed the record function but only fixed
the applier" / "removed log_size and broke the doctor's
diagnostic readout" class bugs.

Phase 11.A/B inline modules use idiomatic names
(``record_refund`` / ``record_ad_spend_event``); Phase 12+
template-using modules use both the generic ``record_event`` AND
a domain-specific alias. The catalog records the
domain-specific name as the required export -- aliases are
operator-facing while the generic ``record_event`` is template
internal.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-domain (log module path, expected record_*, expected
# recent_*). log_size() is universal so it's checked separately.
_DOMAIN_LOG_EXPORTS: dict[
    str, tuple[str, str, str],
] = {
    "customer_support_refund": (
        "engines/returns_management/refund_log.py",
        "record_refund",
        "recent_refunds",
    ),
    "marketing_budget": (
        "engines/roas_guardrails/ad_spend_log.py",
        "record_ad_spend_event",
        "recent_events",
    ),
    "fulfillment": (
        "engines/fulfillment_autonomy/fulfillment_log.py",
        "record_fulfillment_event",
        "recent_events",
    ),
    "inventory": (
        "engines/inventory_autonomy/inventory_log.py",
        "record_inventory_event",
        "recent_events",
    ),
    "discount_cleanup": (
        "engines/discount_cleanup_autonomy/cleanup_log.py",
        "record_cleanup_event",
        "recent_events",
    ),
    "order_followup": (
        "engines/order_followup_autonomy/followup_log.py",
        "record_followup_event",
        "recent_events",
    ),
    "product_seo": (
        "engines/product_seo_autonomy/seo_log.py",
        "record_seo_event",
        "recent_events",
    ),
    "customer_outreach": (
        "engines/customer_outreach_autonomy/outreach_log.py",
        "record_outreach_event",
        "recent_events",
    ),
    "catalog_quality": (
        "engines/catalog_quality_autonomy/quality_log.py",
        "record_quality_event",
        "recent_events",
    ),
}


_UNIVERSAL_EXPORT = "log_size"


@dataclass
class PatternAFViolation:
    domain: str
    module_path: str
    missing_exports: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class PatternAFReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAFViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _module_top_level_names(path: Path) -> set[str] | None:
    """Collect every top-level FunctionDef / Assign / AnnAssign
    target name. Returns None on read/parse failure."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AF read failed for %s: %s", path, exc,
        )
        return None
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern AF parse failed for %s: %s", path, exc,
        )
        return None
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out.add(tgt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                out.add(node.target.id)
    return out


def run_pattern_af_audit() -> PatternAFReport:
    """Verify every autonomy domain's log module exports the
    expected record_X + recent_X functions + universal log_size."""
    report = PatternAFReport()
    for domain, (
        module_path, record_fn, recent_fn,
    ) in _DOMAIN_LOG_EXPORTS.items():
        report.domains_scanned.append(domain)
        path = Path(module_path)
        if not path.exists():
            report.violations.append(PatternAFViolation(
                domain=domain,
                module_path=module_path,
                missing_exports=[
                    record_fn, recent_fn, _UNIVERSAL_EXPORT,
                ],
                reason=f"log module {module_path} not found",
            ))
            continue
        names = _module_top_level_names(path)
        if names is None:
            report.violations.append(PatternAFViolation(
                domain=domain,
                module_path=module_path,
                missing_exports=[
                    record_fn, recent_fn, _UNIVERSAL_EXPORT,
                ],
                reason="parse failure",
            ))
            continue
        missing: list[str] = []
        for required in (record_fn, recent_fn, _UNIVERSAL_EXPORT):
            if required not in names:
                missing.append(required)
        if missing:
            report.violations.append(PatternAFViolation(
                domain=domain,
                module_path=module_path,
                missing_exports=missing,
                reason=(
                    f"{len(missing)} top-level export(s) "
                    "missing"
                ),
            ))
        else:
            report.clean_domains.append(domain)
    return report
