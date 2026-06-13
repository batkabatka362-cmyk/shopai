"""Per-catalog patch specs for autonomy-init --patch-catalogs (W551).

Given a DomainSpec, generate the 22+ catalog edits that need
to land atomically. Each spec produces a (Patcher fn, file,
var_name, payload, skip_if_contains) tuple.

Layered by risk:
  - 17 audit catalogs in engines/_pattern_*_audit.py: simple
    dict_append. Anchor is well-defined (last entry of a
    module-level dict literal).
  - 5 substrate catalogs in core/automation/*: mixed dict +
    list of tuples + multiple dicts in autonomy_smoke.
  - Pattern AR _EXPECTED_DOMAIN_COUNT: constant_set bump.
  - Pattern O _EXEMPT_WRITERS: frozenset set_add.

NOT auto-patched (too anchor-fragile, kept manual):
  - cli.py 4 subparsers + dispatch + handlers
  - engines/_notify.py per-domain probe block
  - core/automation/autonomy_status.py _<domain>_summary
    function + invocation
  - engines/_clusters.py cluster assignment
  - engines/_pattern_t_audit.py env knob registry (per-domain
    extras list is template-fragile)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.automation.autonomy_catalog_patcher import (
    PatchResult,
    patch_constant_set,
    patch_dict_append,
    patch_list_append,
    patch_set_add,
)
from core.automation.autonomy_init import DomainSpec


@dataclass
class CatalogPatch:
    name: str             # human label for reports
    path: Path
    var_name: str
    fn: Callable          # one of the patch_* helpers
    payload: object       # entry to insert OR constant value
    skip_if_contains: str | None = None
    new_count: int = 0    # for constant_set, the new int

    def apply(self, *, dry_run: bool = True) -> PatchResult:
        if self.fn is patch_constant_set:
            return self.fn(
                self.path, self.var_name,
                int(self.payload),
                dry_run=dry_run,
            )
        return self.fn(
            self.path, self.var_name, str(self.payload),
            skip_if_contains=self.skip_if_contains,
            dry_run=dry_run,
        )


def _audit_patches(spec: DomainSpec) -> list[CatalogPatch]:
    """17 Pattern audit catalog edits."""
    d = spec.domain
    p = spec.prefix
    pkg = spec.pkg_name
    env = d.upper()
    out: list[CatalogPatch] = []

    out.append(CatalogPatch(
        name="pattern_u (cycle hook coverage)",
        path=Path("engines/_pattern_u_audit.py"),
        var_name="_DOMAIN_BRIDGES",
        fn=patch_dict_append,
        payload=f'"{d}": "maybe_auto_pause_{p}",',
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_v (notify alert kinds)",
        path=Path("engines/_pattern_v_audit.py"),
        var_name="_DOMAIN_ALERT_KINDS",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "{d}_paused",\n'
            f'    "{d}_health_critical",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_w (env-gate)",
        path=Path("engines/_pattern_w_audit.py"),
        var_name="_DOMAIN_HEALTH_MODULES",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_health.py",\n'
            f'    "{env}",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_x (status rollup)",
        path=Path("engines/_pattern_x_audit.py"),
        var_name="_DOMAIN_SUMMARY_FUNCS",
        fn=patch_dict_append,
        payload=f'"{d}": "_{d}_summary",',
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_yprime (template completeness)",
        path=Path("engines/_pattern_yprime_audit.py"),
        var_name="_DOMAIN_TEMPLATE",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}",\n'
            f'    {{\n'
            f'        "log": "{p}_log.py",\n'
            f'        "state": "{p}_state.py",\n'
            f'        "health": "{p}_health.py",\n'
            f'        "applier": "{p}_applier.py",\n'
            f'        "status": "{p}_status.py",\n'
            f'    }},\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ac (CLI parity)",
        path=Path("engines/_pattern_ac_audit.py"),
        var_name="_DOMAIN_CLI_PREFIXES",
        fn=patch_dict_append,
        payload=f'"{d}": "{d.replace("_", "-")}",',
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ad (health bridge export)",
        path=Path("engines/_pattern_ad_audit.py"),
        var_name="_DOMAIN_BRIDGE_EXPORTS",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_health.py",\n'
            f'    "maybe_auto_pause_{p}",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ae (state is_paused)",
        path=Path("engines/_pattern_ae_audit.py"),
        var_name="_DOMAIN_STATE_MODULES",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_state.py"\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_af (log exports)",
        path=Path("engines/_pattern_af_audit.py"),
        var_name="_DOMAIN_LOG_EXPORTS",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_log.py",\n'
            f'    "record_{p}_event",\n'
            f'    "recent_events",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ag (analyze fn)",
        path=Path("engines/_pattern_ag_audit.py"),
        var_name="_DOMAIN_ANALYZE_EXPORTS",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_health.py",\n'
            f'    "analyze_{d}_health",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ah (applier export)",
        path=Path("engines/_pattern_ah_audit.py"),
        var_name="_DOMAIN_APPLY_EXPORTS",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_applier.py",\n'
            f'    "apply_{d}",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ai (status fn export)",
        path=Path("engines/_pattern_ai_audit.py"),
        var_name="_DOMAIN_STATUS_EXPORTS",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_status.py",\n'
            f'    "get_{d}_status",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_aj (CLI dispatch)",
        path=Path("engines/_pattern_aj_audit.py"),
        var_name="_DOMAIN_CLI_PREFIXES",
        fn=patch_dict_append,
        payload=f'"{d}": "{d.replace("_", "-")}",',
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ak (bridge ast.Call)",
        path=Path("engines/_pattern_ak_audit.py"),
        var_name="_DOMAIN_BRIDGES",
        fn=patch_dict_append,
        payload=f'"{d}": "maybe_auto_pause_{p}",',
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_al (state path uniqueness)",
        path=Path("engines/_pattern_al_audit.py"),
        var_name="_DOMAIN_STATE_MODULES",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "{pkg}", "{p}_state",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_am (test coverage)",
        path=Path("engines/_pattern_am_audit.py"),
        var_name="_DOMAIN_TEST_KEYWORDS",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "{pkg}", "{d}",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_an (writer _ENGINE)",
        path=Path("engines/_pattern_an_audit.py"),
        var_name="_DOMAIN_ENGINE_NAMES",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_applier.py",\n'
            f'    "{spec.engine_name}",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ao (applier docstring)",
        path=Path("engines/_pattern_ao_audit.py"),
        var_name="_DOMAIN_APPLIERS",
        fn=patch_dict_append,
        payload=(
            f'"{d}": (\n'
            f'    "engines/{pkg}/{p}_applier.py"\n'
            f'),'
        ),
        skip_if_contains=f'"{d}":',
    ))

    out.append(CatalogPatch(
        name="pattern_ap (bridge cascade isolation)",
        path=Path("engines/_pattern_ap_audit.py"),
        var_name="_DOMAIN_BRIDGES",
        fn=patch_dict_append,
        payload=f'"{d}": "maybe_auto_pause_{p}",',
        skip_if_contains=f'"{d}":',
    ))

    return out


def _substrate_patches(spec: DomainSpec) -> list[CatalogPatch]:
    """5 core/automation substrate catalogs."""
    d = spec.domain
    p = spec.prefix
    pkg = spec.pkg_name
    out: list[CatalogPatch] = []

    # autonomy_smoke._DOMAINS (list of 4-tuples)
    out.append(CatalogPatch(
        name="autonomy_smoke._DOMAINS",
        path=Path("core/automation/autonomy_smoke.py"),
        var_name="_DOMAINS",
        fn=patch_list_append,
        payload=(
            f'(\n'
            f'    "{d}",\n'
            f'    "{pkg}",\n'
            f'    "{p}",\n'
            f'    "get_{d}_status",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}",',
    ))

    # autonomy_smoke per-prefix dicts (4 of them)
    out.append(CatalogPatch(
        name="autonomy_smoke._APPLY_NAMES",
        path=Path("core/automation/autonomy_smoke.py"),
        var_name="_APPLY_NAMES",
        fn=patch_dict_append,
        payload=f'"{p}": "apply_{d}",',
        skip_if_contains=f'"{p}": "apply_{d}"',
    ))

    out.append(CatalogPatch(
        name="autonomy_smoke._APPLY_EMPTY_PAYLOAD",
        path=Path("core/automation/autonomy_smoke.py"),
        var_name="_APPLY_EMPTY_PAYLOAD",
        fn=patch_dict_append,
        payload=f'"{p}": ([],),',
        skip_if_contains=f'"{p}": ([',
    ))

    out.append(CatalogPatch(
        name="autonomy_smoke._LOG_MODULE_NAMES",
        path=Path("core/automation/autonomy_smoke.py"),
        var_name="_LOG_MODULE_NAMES",
        fn=patch_dict_append,
        payload=f'"{p}": "{p}_log",',
        skip_if_contains=f'"{p}": "{p}_log"',
    ))

    out.append(CatalogPatch(
        name="autonomy_smoke._STATUS_MODULE_NAMES",
        path=Path("core/automation/autonomy_smoke.py"),
        var_name="_STATUS_MODULE_NAMES",
        fn=patch_dict_append,
        payload=f'"{p}": "{p}_status",',
        skip_if_contains=f'"{p}": "{p}_status"',
    ))

    out.append(CatalogPatch(
        name="autonomy_smoke._ANALYZE_NAMES",
        path=Path("core/automation/autonomy_smoke.py"),
        var_name="_ANALYZE_NAMES",
        fn=patch_dict_append,
        payload=f'"{p}": "analyze_{d}_health",',
        skip_if_contains=f'"{p}": "analyze_{d}',
    ))

    # autonomy_history._DOMAIN_LOGS (list of 4-tuples)
    out.append(CatalogPatch(
        name="autonomy_history._DOMAIN_LOGS",
        path=Path("core/automation/autonomy_history.py"),
        var_name="_DOMAIN_LOGS",
        fn=patch_list_append,
        payload=(
            f'(\n'
            f'    "{p}",\n'
            f'    "{pkg}",\n'
            f'    "{p}_log",\n'
            f'    "recent_events",\n'
            f'),'
        ),
        skip_if_contains=f'"{p}",\n        "{pkg}"',
    ))

    # autonomy_domain_view (2 dicts)
    out.append(CatalogPatch(
        name="autonomy_domain_view._DOMAIN_META",
        path=Path("core/automation/autonomy_domain_view.py"),
        var_name="_DOMAIN_META",
        fn=patch_dict_append,
        payload=f'"{d}": ("{d}", "{p}"),',
        skip_if_contains=f'"{d}": ("{d}",',
    ))

    out.append(CatalogPatch(
        name="autonomy_domain_view._DOMAIN_ALIASES",
        path=Path("core/automation/autonomy_domain_view.py"),
        var_name="_DOMAIN_ALIASES",
        fn=patch_dict_append,
        payload=(
            f'"{d}": "{d}",\n'
            f'"{p}": "{d}",'
        ),
        skip_if_contains=f'"{d}": "{d}"',
    ))

    # autonomy_bench._DOMAIN_BRIDGES (list of 4-tuples)
    out.append(CatalogPatch(
        name="autonomy_bench._DOMAIN_BRIDGES",
        path=Path("core/automation/autonomy_bench.py"),
        var_name="_DOMAIN_BRIDGES",
        fn=patch_list_append,
        payload=(
            f'(\n'
            f'    "{d}",\n'
            f'    "{pkg}",\n'
            f'    "{p}_health",\n'
            f'    "maybe_auto_pause_{p}",\n'
            f'),'
        ),
        skip_if_contains=f'"{d}",\n        "{pkg}"',
    ))

    # autonomy_bulk._DOMAIN_STATE_MODULES (list of 3-tuples)
    out.append(CatalogPatch(
        name="autonomy_bulk._DOMAIN_STATE_MODULES",
        path=Path("core/automation/autonomy_bulk.py"),
        var_name="_DOMAIN_STATE_MODULES",
        fn=patch_list_append,
        payload=(
            f'("{d}", "{pkg}",\n'
            f' "{p}_state"),'
        ),
        skip_if_contains=f'("{d}", "{pkg}"',
    ))

    return out


def _meta_patches(
    spec: DomainSpec, expected_count: int,
) -> list[CatalogPatch]:
    """Pattern AR + Pattern O."""
    out: list[CatalogPatch] = []

    # Pattern AR _EXPECTED_DOMAIN_COUNT bump
    out.append(CatalogPatch(
        name="pattern_ar (_EXPECTED_DOMAIN_COUNT)",
        path=Path("engines/_pattern_ar_audit.py"),
        var_name="_EXPECTED_DOMAIN_COUNT",
        fn=patch_constant_set,
        payload=expected_count,
        new_count=expected_count,
    ))

    # Pattern O exempt entry
    out.append(CatalogPatch(
        name="pattern_o (_EXEMPT_WRITERS)",
        path=Path("engines/_pattern_o_audit.py"),
        var_name="_EXEMPT_WRITERS",
        fn=patch_set_add,
        payload=(
            f'"{spec.pkg_name}/{spec.prefix}_applier.py",'
        ),
        skip_if_contains=(
            f'"{spec.pkg_name}/{spec.prefix}_applier.py"'
        ),
    ))

    return out


def all_patches(
    spec: DomainSpec, *, new_domain_count: int,
) -> list[CatalogPatch]:
    """Assemble every catalog patch needed for the new domain.

    Args:
        spec: the DomainSpec being scaffolded
        new_domain_count: target value for Pattern AR's
            _EXPECTED_DOMAIN_COUNT after this domain ships
            (caller computes from current count + 1)
    """
    out: list[CatalogPatch] = []
    out.extend(_audit_patches(spec))
    out.extend(_substrate_patches(spec))
    out.extend(_meta_patches(spec, new_domain_count))
    return out


def apply_all(
    patches: list[CatalogPatch], *, dry_run: bool = True,
) -> list[PatchResult]:
    """Apply every patch in order. Stops at first failure if
    dry_run=False (we don't want partial writes)."""
    results: list[PatchResult] = []
    for patch in patches:
        r = patch.apply(dry_run=dry_run)
        results.append(r)
        if not r.success and not dry_run:
            # Partial-state risk -- bail
            break
    return results
