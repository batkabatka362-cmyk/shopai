"""Pattern O audit: every wired engine has a documented opt-in.

Wave 6/7 wireup pattern requires every WIRED engine to be
opt-in (default OFF) via ``data.apply_X=True`` in the engine
input. The pattern keeps autonomous writes off by default,
which is the safety contract.

Pattern O is a runtime audit that AST-scans every wired
engine's writer modules + asserts at least one
``data.get("apply_X")`` reference exists. Engines that ship
a writer module but never gate it on an opt-in are
violations.

Future writer authors who skip the gate get flagged before
their PR lands. CI gate + operator command
``shopai pattern-o-audit`` consume the report.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Writer-module filename suffixes (mirrors Pattern Z)
_WRITER_SUFFIXES = (
    "_applier.py",
    "_minter.py",
    "_payer.py",
)

# Legitimate non-gated writers. These are called from
# different invocation paths (e.g. launch_orchestrator's
# top-level shopai launch CLI) so they don't need a
# data.get("apply_X") gate inside their engine's flow.py --
# the operator invocation itself is the opt-in.
_EXEMPT_WRITERS: frozenset[str] = frozenset({
    "store_setup/page_applier.py",
    "store_setup/policy_applier.py",
    # Pre-existing exemption (email_marketing flow gates via
    # a different mechanism; documented but not in flow.py)
    "email_marketing/discount_minter.py",
    # Wave 126-131: fulfillment_autonomy is substrate not a
    # classical engine -- the applier gates via is_paused() +
    # caller-level opt-in rather than data.get("apply_X").
    "fulfillment_autonomy/fulfillment_applier.py",
    # Wave 132-137: same pattern as fulfillment_autonomy
    "inventory_autonomy/inventory_applier.py",
    # Wave 154-159: 5th autonomy domain, same pattern
    "discount_cleanup_autonomy/cleanup_applier.py",
    # Wave 174-180: 6th autonomy domain
    "order_followup_autonomy/followup_applier.py",
    # Wave 195-202: 7th autonomy domain
    "product_seo_autonomy/seo_applier.py",
    # Wave 379-385: 8th autonomy domain
    "customer_outreach_autonomy/outreach_applier.py",
    # Wave 436-442: 9th autonomy domain
    "catalog_quality_autonomy/quality_applier.py",
})


@dataclass
class PatternOViolation:
    engine: str
    writer_module: str
    reason: str


@dataclass
class PatternOReport:
    scanned_engines: list[str] = field(default_factory=list)
    clean_engines: list[str] = field(default_factory=list)
    violations: list[PatternOViolation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _writer_modules_for_engine(
    engine_dir: Path,
) -> list[Path]:
    """Find all writer modules (per Pattern Z's suffix rule)
    inside one engine's directory."""
    out: list[Path] = []
    if not engine_dir.is_dir():
        return out
    for child in engine_dir.iterdir():
        if not child.is_file():
            continue
        if not child.name.endswith(_WRITER_SUFFIXES):
            continue
        out.append(child)
    return out


def _flow_module(engine_dir: Path) -> Path | None:
    """The engine's flow.py is where opt-in gates live."""
    candidate = engine_dir / "flow.py"
    return candidate if candidate.exists() else None


def _has_apply_gate(source_path: Path) -> bool:
    """AST-scan for ``data.get("apply_X")`` references."""
    try:
        source = source_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern O: read failed for %s: %s",
            source_path, exc,
        )
        return False
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        logger.debug(
            "Pattern O: parse failed for %s: %s",
            source_path, exc,
        )
        return False
    for node in ast.walk(tree):
        # Looking for: data.get("apply_X") or
        # data.get("apply_X") is True
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Name)
                and func.value.id == "data"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("apply_")
            ):
                return True
    return False


def run_pattern_o_audit(
    *,
    engines_dir: str | Path = "engines",
) -> PatternOReport:
    """Audit every engine's writer modules for opt-in gates."""
    report = PatternOReport()
    base = Path(engines_dir)
    if not base.is_dir():
        return report

    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        # Skip private/internal directories
        if child.name.startswith("_"):
            continue
        writers = _writer_modules_for_engine(child)
        if not writers:
            continue
        engine_name = child.name
        report.scanned_engines.append(engine_name)

        flow = _flow_module(child)
        flow_has_gate = (
            _has_apply_gate(flow) if flow else False
        )

        for writer in writers:
            # Either flow.py OR the writer itself references
            # data.get("apply_X")
            writer_has_gate = _has_apply_gate(writer)
            if flow_has_gate or writer_has_gate:
                continue
            # Path used in exemption list uses forward slashes
            rel = writer.relative_to(base).as_posix()
            if rel in _EXEMPT_WRITERS:
                continue
            report.violations.append(PatternOViolation(
                engine=engine_name,
                writer_module=rel,
                reason=(
                    "writer module exists but no "
                    'data.get("apply_X") opt-in gate found '
                    "in flow.py or the writer itself"
                ),
            ))
        if not any(
            v.engine == engine_name for v in report.violations
        ):
            report.clean_engines.append(engine_name)

    return report
