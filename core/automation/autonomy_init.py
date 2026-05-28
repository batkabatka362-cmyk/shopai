"""Autonomy-init scaffolder (Wave 511).

Takes a small set of identifying parameters + renders the 6
file templates from autonomy_template into a new domain
package + test file. Prints the catalog-update checklist so
the operator can run the standard 22-catalog atomic bump.

Does NOT auto-patch the 22 catalogs (cli.py / _notify.py /
autonomy_status / 17 audit catalogs / 5 substrate catalogs) --
those edits are anchor-fragile and safer for the operator to
do by hand following the printed checklist.

Usage (Python):
  from core.automation.autonomy_init import (
      DomainSpec, render_domain,
  )
  spec = DomainSpec(
      domain="catalog_quality",
      prefix="quality",
      capability="SHOPIFY_TAG_PRODUCT",
      tags=["shopai-quality-needs-images", ...],
      max_per_run=300,
      entity_id="product_id",
      wave_base=436,
  )
  render_domain(spec, dry_run=False, write_to_disk=True)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.automation.autonomy_template import (
    TEMPLATES,
    TEST_TEMPLATE,
)


@dataclass
class DomainSpec:
    """All knobs needed to materialise a new domain from
    templates."""
    domain: str          # canonical key, e.g. "catalog_quality"
    prefix: str          # file prefix, e.g. "quality"
    capability: str      # Shopify capability constant
    tags: list[str] = field(default_factory=list)
    max_per_run: int = 200
    entity_id: str = "product_id"
    wave_base: int = 600
    engine_name: str = ""
    pkg_name: str = ""

    def __post_init__(self) -> None:
        if not self.engine_name:
            self.engine_name = self.domain
        if not self.pkg_name:
            self.pkg_name = f"{self.domain}_autonomy"


@dataclass
class RenderedDomain:
    spec: DomainSpec
    files: dict[str, str] = field(default_factory=dict)
    test_file_name: str = ""
    test_file_content: str = ""

    @property
    def package_dir(self) -> Path:
        return Path("engines") / self.spec.pkg_name

    @property
    def test_path(self) -> Path:
        return Path("tests") / self.test_file_name


def _domain_title(domain: str) -> str:
    return domain.replace("_", " ").title()


def _domain_hyphen(domain: str) -> str:
    return domain.replace("_", "-")


def _action_type(domain: str) -> str:
    return f"apply_{domain}_tag"


def _apply_fn(domain: str) -> str:
    return f"apply_{domain}"


def _analyze_fn(domain: str) -> str:
    return f"analyze_{domain}_health"


def _bridge_fn(prefix: str) -> str:
    return f"maybe_auto_pause_{prefix}"


def _status_fn(domain: str) -> str:
    return f"get_{domain}_status"


def _record_fn(prefix: str) -> str:
    return f"record_{prefix}_event"


def _event_class(domain: str) -> str:
    # snake_case to PascalCase + Event suffix
    pascal = "".join(p.capitalize() for p in domain.split("_"))
    return f"{pascal}Event"


def _status_class(domain: str) -> str:
    pascal = "".join(p.capitalize() for p in domain.split("_"))
    return f"{pascal}StatusReport"


def _tag_list_literal(tags: list[str]) -> str:
    if not tags:
        return "frozenset()"
    lines = ",\n".join(f'    "{t}"' for t in tags)
    return "frozenset({\n" + lines + ",\n})"


def _build_subs(spec: DomainSpec) -> dict[str, str]:
    """All `{...}` placeholders the templates need."""
    return {
        "DOMAIN": spec.domain,
        "DOMAIN_TITLE": _domain_title(spec.domain),
        "DOMAIN_HYPHEN": _domain_hyphen(spec.domain),
        "PREFIX": spec.prefix,
        "PKG": spec.pkg_name,
        "CAPABILITY": spec.capability,
        "ENGINE": spec.engine_name,
        "ACTION": _action_type(spec.domain),
        "ENV_PREFIX": spec.domain.upper(),
        "APPLY_FN": _apply_fn(spec.domain),
        "ANALYZE_FN": _analyze_fn(spec.domain),
        "BRIDGE_FN": _bridge_fn(spec.prefix),
        "STATUS_FN": _status_fn(spec.domain),
        "RECORD_FN": _record_fn(spec.prefix),
        "EVENT_CLASS": _event_class(spec.domain),
        "STATUS_CLASS": _status_class(spec.domain),
        "WAVE_BASE": str(spec.wave_base),
        "WAVE_BASE_PLUS_1": str(spec.wave_base + 1),
        "WAVE_BASE_PLUS_2": str(spec.wave_base + 2),
        "WAVE_BASE_PLUS_3": str(spec.wave_base + 3),
        "WAVE_BASE_PLUS_4": str(spec.wave_base + 4),
        "ENTITY": spec.entity_id,
        "TAG_LIST": _tag_list_literal(spec.tags),
        "MAX_PER_RUN_DEFAULT": str(spec.max_per_run),
    }


def _render(template: str, subs: dict[str, str]) -> str:
    out = template
    # Sort by length descending so longer keys substitute first
    # (avoid partial matches like PREFIX hitting ENV_PREFIX).
    for key in sorted(subs, key=len, reverse=True):
        out = out.replace("{" + key + "}", subs[key])
    return out


def render_domain(spec: DomainSpec) -> RenderedDomain:
    """Render all 6 files for the domain into in-memory
    strings. Caller decides whether to write to disk."""
    subs = _build_subs(spec)
    out = RenderedDomain(spec=spec)
    for template_name, body in TEMPLATES.items():
        fname = _render(template_name, subs)
        out.files[fname] = _render(body, subs)
    out.test_file_name = _render("test_{PKG}.py", subs)
    out.test_file_content = _render(TEST_TEMPLATE, subs)
    return out


def write_to_disk(rendered: RenderedDomain) -> list[Path]:
    """Persist the rendered files. Returns list of written paths.
    Raises FileExistsError if any target already exists -- the
    scaffolder is for NEW domains, not regeneration."""
    written: list[Path] = []
    pkg_dir = rendered.package_dir
    pkg_dir.mkdir(parents=True, exist_ok=False)
    for fname, body in rendered.files.items():
        p = pkg_dir / fname
        if p.exists():
            raise FileExistsError(p)
        p.write_text(body, encoding="utf-8")
        written.append(p)
    test_path = rendered.test_path
    if test_path.exists():
        raise FileExistsError(test_path)
    test_path.write_text(
        rendered.test_file_content, encoding="utf-8",
    )
    written.append(test_path)
    return written


def catalog_checklist(spec: DomainSpec) -> list[str]:
    """Return the operator checklist for the 22 catalogs that
    need manual updates after scaffolding."""
    return [
        f"# Catalog update checklist for {spec.domain}",
        "",
        "Files generated. Now update these catalogs in ONE "
        "commit so Pattern AR's cross-catalog parity stays "
        "green:",
        "",
        "## autonomy_status rollup",
        "  - core/automation/autonomy_status.py:",
        f"    * add _{spec.domain}_summary() function",
        "    * invoke it inside get_autonomy_status()",
        "",
        "## CLI (cli.py)",
        f"  - add 4 subparsers: {_domain_hyphen(spec.domain)}-"
        "{status,health,pause,resume}",
        "  - add 4 dispatch branches in main()",
        "  - add 4 handler functions",
        f"  - add maybe_auto_pause_{spec.prefix}() invocation "
        "in _cmd_cycle_run",
        "",
        "## Notify alerts (engines/_notify.py)",
        f"  - add 2 alert kinds: {spec.domain}_paused + "
        f"{spec.domain}_health_critical",
        f"  - extend autonomy_kinds set with both new kinds",
        "",
        "## Pattern audits (17 catalogs)",
        "  All under engines/_pattern_*_audit.py "
        "(W/X/Y'/AC/AD/AE/AF/AG/AH/AI/AJ/AK/AL/AM/AN/AO/AP/T):",
        f"  - add `{spec.domain}` entry to each catalog dict",
        "",
        "## Substrate catalogs (5)",
        "  - core/automation/autonomy_smoke.py: "
        f"_DOMAINS / _APPLY_NAMES / _APPLY_EMPTY_PAYLOAD / "
        f"_LOG_MODULE_NAMES / _STATUS_MODULE_NAMES / "
        f"_ANALYZE_NAMES",
        "  - core/automation/autonomy_history.py: "
        "_DOMAIN_LOGS",
        "  - core/automation/autonomy_domain_view.py: "
        "_DOMAIN_META + _DOMAIN_ALIASES",
        "  - core/automation/autonomy_bench.py: "
        "_DOMAIN_BRIDGES",
        "  - core/automation/autonomy_bulk.py: "
        "_DOMAIN_STATE_MODULES",
        "",
        "## Meta",
        "  - engines/_pattern_ar_audit.py: bump "
        "_EXPECTED_DOMAIN_COUNT by 1",
        "  - engines/_pattern_o_audit.py: add "
        f"`{spec.pkg_name}/{spec.prefix}_applier.py` to "
        "_EXEMPT_WRITERS",
        "  - core/automation/autonomy_export.py: extend "
        "audits_to_run list",
        "",
        "## Cluster + risk taxonomy",
        f"  - engines/_clusters.py: assign `{spec.pkg_name}` "
        "to a cluster",
        "  - if capability not in _ADDITIVE_HINTS, declare "
        "_WRITEBACK_RISK explicitly in the applier",
        "",
        "## Tests",
        f"  - bulk-rename test_*_N_* -> test_*_N+1_* in audit "
        "test files",
        "  - extend each catalog set-equality assertion to "
        f"include `{spec.domain}` / `{spec.prefix}`",
        "  - test_pattern_t_audit: bump total_knobs by "
        "(5 standard + extras)",
        "",
        "Then verify: `shopai audit` -> all gates pass.",
    ]
