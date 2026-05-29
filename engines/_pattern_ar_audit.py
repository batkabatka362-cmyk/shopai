"""Pattern AR audit: cross-catalog domain parity (W363).

When a new autonomy domain ships, ~17 separate catalogs need to
be updated (the per-audit `_DOMAIN_*` dicts + the substrate
modules' catalogs in `core/automation/*`). Missing even one
results in subtle drift -- the new domain shows up in some
surfaces but not others, silently.

Pattern AR is the meta-audit: it enumerates every known
substrate catalog + asserts each has the same size (currently 7).
If one catalog adds an 8th entry, the others fall short of 8 and
the audit fails -- forcing the symmetric update in the same PR.

This is a CARDINALITY check, not a key-equality check, because
some catalogs use canonical keys (`customer_support_refund`)
while others use short aliases (`refund`). The cardinality
contract is simpler and catches the same drift.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import import_module

logger = logging.getLogger(__name__)


# Canonical autonomy domain count. Bumped 7 -> 8 in W402-422
# when customer_outreach_autonomy (8th domain) shipped. Bumped
# 8 -> 9 in W458-475 when catalog_quality_autonomy (9th
# domain) shipped.
_EXPECTED_DOMAIN_COUNT = 10


# Registered substrate catalogs. Each entry: (module path,
# attribute name, optional "list-of-tuples" flag).
# When the flag is True, the catalog is a list whose first
# tuple element is the domain key (smoke / history have this
# shape); otherwise it's a dict and we read .keys().
_CATALOGS: list[tuple[str, str, bool]] = [
    # Pattern audits (19 -- W226 added U+V to AR catalog
    # when their drift was discovered during Phase 32.C
    # daily-brief integration debugging)
    ("engines._pattern_u_audit", "_DOMAIN_BRIDGES", False),
    ("engines._pattern_v_audit", "_DOMAIN_ALERT_KINDS",
     False),
    ("engines._pattern_w_audit", "_DOMAIN_HEALTH_MODULES",
     False),
    ("engines._pattern_x_audit", "_DOMAIN_SUMMARY_FUNCS",
     False),
    ("engines._pattern_yprime_audit", "_DOMAIN_TEMPLATE",
     False),
    ("engines._pattern_ac_audit", "_DOMAIN_CLI_PREFIXES",
     False),
    ("engines._pattern_ad_audit", "_DOMAIN_BRIDGE_EXPORTS",
     False),
    ("engines._pattern_ae_audit", "_DOMAIN_STATE_MODULES",
     False),
    ("engines._pattern_af_audit", "_DOMAIN_LOG_EXPORTS",
     False),
    ("engines._pattern_ag_audit", "_DOMAIN_ANALYZE_EXPORTS",
     False),
    ("engines._pattern_ah_audit", "_DOMAIN_APPLY_EXPORTS",
     False),
    ("engines._pattern_ai_audit", "_DOMAIN_STATUS_EXPORTS",
     False),
    ("engines._pattern_aj_audit", "_DOMAIN_CLI_PREFIXES",
     False),
    ("engines._pattern_ak_audit", "_DOMAIN_BRIDGES", False),
    ("engines._pattern_al_audit", "_DOMAIN_STATE_MODULES",
     False),
    ("engines._pattern_am_audit", "_DOMAIN_TEST_KEYWORDS",
     False),
    ("engines._pattern_an_audit", "_DOMAIN_ENGINE_NAMES",
     False),
    ("engines._pattern_ao_audit", "_DOMAIN_APPLIERS", False),
    ("engines._pattern_ap_audit", "_DOMAIN_BRIDGES", False),
    # core/automation substrate modules (5)
    ("core.automation.autonomy_smoke", "_DOMAINS", True),
    ("core.automation.autonomy_history", "_DOMAIN_LOGS", True),
    ("core.automation.autonomy_domain_view",
     "_DOMAIN_META", False),
    ("core.automation.autonomy_bench",
     "_DOMAIN_BRIDGES", True),
    ("core.automation.autonomy_bulk",
     "_DOMAIN_STATE_MODULES", True),
]


@dataclass
class PatternARViolation:
    catalog: str
    expected_count: int = _EXPECTED_DOMAIN_COUNT
    actual_count: int = 0
    reason: str = ""


@dataclass
class PatternARReport:
    catalogs_scanned: list[str] = field(default_factory=list)
    clean_catalogs: list[str] = field(default_factory=list)
    violations: list[PatternARViolation] = field(
        default_factory=list,
    )
    sizes_by_catalog: dict[str, int] = field(
        default_factory=dict,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _read_catalog_size(
    mod_name: str, attr: str, is_list: bool,
) -> tuple[int | None, str]:
    """Return (count, reason). count is None on import / type
    failure."""
    try:
        mod = import_module(mod_name)
    except Exception as exc:  # noqa: BLE001
        return None, f"import failed: {exc!s:.80}"
    cat = getattr(mod, attr, None)
    if cat is None:
        return None, (
            f"attribute {attr!r} not found in {mod_name}"
        )
    try:
        if is_list:
            # list of tuples whose first element is the
            # domain key
            return len(cat), ""
        return len(cat.keys()), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"size read failed: {exc!s:.80}"


def run_pattern_ar_audit() -> PatternARReport:
    """Verify every registered substrate catalog has exactly
    EXPECTED_DOMAIN_COUNT entries."""
    report = PatternARReport()
    for mod_name, attr, is_list in _CATALOGS:
        key = f"{mod_name}.{attr}"
        report.catalogs_scanned.append(key)
        count, reason = _read_catalog_size(
            mod_name, attr, is_list,
        )
        if count is None:
            report.violations.append(PatternARViolation(
                catalog=key, reason=reason,
            ))
            continue
        report.sizes_by_catalog[key] = count
        if count == _EXPECTED_DOMAIN_COUNT:
            report.clean_catalogs.append(key)
        else:
            report.violations.append(PatternARViolation(
                catalog=key,
                actual_count=count,
                reason=(
                    f"size={count} != expected "
                    f"{_EXPECTED_DOMAIN_COUNT} -- catalog "
                    "drift, update all catalogs together"
                ),
            ))
    return report
