"""Pattern AX audit: discoverer-applier action-string parity (W833).

Each autonomy applier checks ``row.get("action")`` against a
literal string (e.g. ``"tag_quality"``, ``"deactivate"``,
``"update_seo"``). If a discoverer emits a different action
string, the applier silently logs ``not_actionable`` and the
payload row produces no effect. Unit tests don't catch this
because each side is tested in isolation.

Pattern AX is the cross-module audit:

  1. AST-scan each applier for the exact ``action != "<lit>"``
     comparison; collect the expected literal per domain.
  2. Invoke each discoverer (empty payload OK if mocking
     unavailable) and walk a representative payload's
     ``action`` field; flag mismatches.
  3. If a discoverer can't produce a payload in the current
     environment, fall back to AST-scanning the discoverer
     source for the literal it emits.

Caught real bugs: shipping_alert applier expects
``tag_shipping`` (W782), catalog_quality applier expects
``tag_quality`` (W846 -- corrected mid-Phase 46). Without
Pattern AX, future scaffolded discoverers would silently
drift.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path

logger = logging.getLogger(__name__)


# Discoverer module path + applier module path per domain.
# Mirrors autonomy_fire._DOMAIN_APPLIERS + the discovers
# package layout.
_DOMAIN_PAIRS: dict[str, tuple[str, str]] = {
    "shipping_alert": (
        "core.automation.discoverers.shipping_alert",
        "engines/shipping_alert_autonomy/shipping_applier.py",
    ),
    "catalog_quality": (
        "core.automation.discoverers.catalog_quality",
        "engines/catalog_quality_autonomy/quality_applier.py",
    ),
    "order_followup": (
        "core.automation.discoverers.order_followup",
        "engines/order_followup_autonomy/followup_applier.py",
    ),
    "product_seo": (
        "core.automation.discoverers.product_seo",
        "engines/product_seo_autonomy/seo_applier.py",
    ),
    "customer_outreach": (
        "core.automation.discoverers.customer_outreach",
        "engines/customer_outreach_autonomy/outreach_applier.py",
    ),
    "discount_cleanup": (
        "core.automation.discoverers.discount_cleanup",
        "engines/discount_cleanup_autonomy/cleanup_applier.py",
    ),
    "inventory": (
        "core.automation.discoverers.inventory",
        "engines/inventory_autonomy/inventory_applier.py",
    ),
    "fulfillment": (
        "core.automation.discoverers.fulfillment",
        "engines/fulfillment_autonomy/fulfillment_applier.py",
    ),
}


@dataclass
class PatternAXViolation:
    domain: str
    discoverer_action: str
    applier_action: str
    reason: str


@dataclass
class PatternAXReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_pairs: list[str] = field(default_factory=list)
    violations: list[PatternAXViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _applier_expected_actions(
    applier_path: Path,
) -> set[str]:
    """AST-scan an applier for ``action != "<lit>"`` and
    ``action not in (...)`` comparisons. Returns the set of
    accepted actions."""
    expected: set[str] = set()
    try:
        source = applier_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(applier_path))
    except Exception:  # noqa: BLE001
        return expected
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # left is Name 'action' (after our applier convention)
        if not isinstance(node.left, ast.Name):
            continue
        if node.left.id != "action":
            continue
        for op, comparator in zip(
            node.ops, node.comparators,
        ):
            if isinstance(op, ast.NotEq) and isinstance(
                comparator, ast.Constant,
            ) and isinstance(comparator.value, str):
                expected.add(comparator.value)
            elif isinstance(op, ast.NotIn) and isinstance(
                comparator, (ast.Tuple, ast.List, ast.Set),
            ):
                for elt in comparator.elts:
                    if isinstance(
                        elt, ast.Constant,
                    ) and isinstance(elt.value, str):
                        expected.add(elt.value)
    return expected


def _discoverer_emitted_actions(
    mod_path: str,
) -> set[str]:
    """Invoke the discoverer + scan emitted payload. Falls
    back to AST-scanning for ``"action": "<lit>"`` dict
    literals when the live payload is empty."""
    emitted: set[str] = set()
    try:
        mod = import_module(mod_path)
    except Exception:  # noqa: BLE001
        return emitted

    # Try the discoverer's discover_<X> function if present
    fn_name = next(
        (
            n for n in dir(mod)
            if n.startswith("discover_")
        ),
        None,
    )
    if fn_name is not None:
        try:
            fn = getattr(mod, fn_name)
            result = fn()
            payload = getattr(result, "payload", None)
            if isinstance(payload, list):
                for row in payload:
                    if isinstance(row, dict):
                        act = row.get("action")
                        if isinstance(act, str):
                            emitted.add(act)
        except Exception:  # noqa: BLE001
            pass

    # AST fallback: scan the source for
    # '"action": "<literal>"' dict-key constants. Works even
    # when the discoverer can't run (no Shopify available).
    src_path = Path(
        mod.__file__ if hasattr(mod, "__file__") else "",
    )
    if src_path.exists():
        try:
            tree = ast.parse(
                src_path.read_text(encoding="utf-8"),
                filename=str(src_path),
            )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for k, v in zip(node.keys, node.values):
                    if (
                        isinstance(k, ast.Constant)
                        and k.value == "action"
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                    ):
                        emitted.add(v.value)
        except Exception:  # noqa: BLE001
            pass

    return emitted


def run_pattern_ax_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternAXReport:
    """Cross-check every (discoverer, applier) pair's action
    string alignment."""
    report = PatternAXReport()
    root = Path(repo_root).resolve()

    for domain, (mod_path, applier_rel) in (
        _DOMAIN_PAIRS.items()
    ):
        report.domains_scanned.append(domain)
        applier_path = root / applier_rel
        if not applier_path.exists():
            report.violations.append(PatternAXViolation(
                domain=domain,
                discoverer_action="",
                applier_action="",
                reason=(
                    f"applier path missing: {applier_rel}"
                ),
            ))
            continue
        expected = _applier_expected_actions(applier_path)
        emitted = _discoverer_emitted_actions(mod_path)
        if not expected:
            report.violations.append(PatternAXViolation(
                domain=domain,
                discoverer_action=",".join(sorted(emitted)),
                applier_action="",
                reason=(
                    "applier exposed no 'action != \"...\"' "
                    "literal; AST scan inconclusive"
                ),
            ))
            continue
        if not emitted:
            report.violations.append(PatternAXViolation(
                domain=domain,
                discoverer_action="",
                applier_action=",".join(sorted(expected)),
                reason=(
                    "discoverer emits no 'action' literal; "
                    "either no payload + no AST match, or "
                    "the discoverer doesn't write the field"
                ),
            ))
            continue
        # Check every emitted action is accepted by the
        # applier. emitted - expected = drift.
        bad = emitted - expected
        if bad:
            report.violations.append(PatternAXViolation(
                domain=domain,
                discoverer_action=",".join(sorted(emitted)),
                applier_action=",".join(sorted(expected)),
                reason=(
                    "discoverer emits "
                    f"{sorted(bad)!s} not in applier's "
                    "accepted set"
                ),
            ))
            continue
        report.clean_pairs.append(domain)

    return report
