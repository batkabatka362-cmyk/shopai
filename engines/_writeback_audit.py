"""Catalog Phase 6 / 7 writeback wireup state across every engine.

Operators want a one-glance answer to: "which engines act
autonomously on Shopify, and which are advisory-only?". This
module computes that catalog by scanning each engine package
for three signals:

  1. ``flow.py`` exists. Engines without a flow file are
     infrastructure (base, _writeback_recorder, helpers) — we
     skip them.
  2. At least one writer module: ``*_applier.py``,
     ``*_minter.py``, ``*_payer.py``, ``*_writer.py``. These
     are the per-engine modules that translate engine output
     into ``ApprovalQueue.enqueue`` calls (Phase 6 / 7 pattern).
  3. An opt-in flag in flow.py — pattern
     ``data.get("apply_*")`` or
     ``data.get("require_approval")``. Without this, the
     writer exists but never runs.

Engines with all three are ``wired`` — fully end-to-end Phase
6/7 writeback. Engines with flow.py but no writer + no opt-in
are ``advisory`` (the engine only emits recommendations).
Engines with one but not the other are ``partial`` —
incomplete wireup, the next thing to fix.

The catalog gives operators visibility on the autonomous
loop's reach: 22/135 engines today is ~16% coverage. Future
Phase 7 candidates will move that needle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_WRITER_PATTERNS = (
    "_applier.py",
    "_minter.py",
    "_payer.py",
)
# ``_writer.py`` is intentionally NOT in the list — every
# engine has ``memory_writer.py`` for internal LearningLoop
# persistence, which is a different concern from Shopify
# writebacks. The Phase 6/7 wireup naming convention is
# strictly ``_applier`` / ``_minter`` / ``_payer``.

# The opt-in pattern that signals the engine's flow.py
# actually routes through the writer. Matches:
#   data.get("apply_X")
#   data.get('apply_X')
#   data.get("require_approval")
_OPT_IN_PATTERN = re.compile(
    r'data\.get\(["\']'
    r'(apply_[a-z_]+|require_approval)'
    r'["\']'
)


@dataclass(frozen=True)
class EngineWritebackStatus:
    """Per-engine writeback wireup status."""

    name: str
    has_flow: bool
    writer_files: list[str]
    opt_in_flags: list[str]
    status: str  # "wired" | "advisory" | "partial" | "non_engine"


@dataclass(frozen=True)
class WritebackCoverageReport:
    """Aggregated catalog."""

    engines: list[EngineWritebackStatus]
    wired_count: int
    advisory_count: int
    partial_count: int
    total_engines: int  # excludes non-engine infra dirs


def _scan_one_engine(engine_dir: Path) -> EngineWritebackStatus:
    """Inspect a single engine directory."""
    name = engine_dir.name
    flow = engine_dir / "flow.py"
    has_flow = flow.is_file()

    if not has_flow:
        return EngineWritebackStatus(
            name=name,
            has_flow=False,
            writer_files=[],
            opt_in_flags=[],
            status="non_engine",
        )

    # Writer files
    writer_files = sorted(
        p.name for pattern in _WRITER_PATTERNS
        for p in engine_dir.glob(f"*{pattern}")
        if p.is_file()
    )

    # Opt-in flags in flow.py
    try:
        flow_src = flow.read_text(encoding="utf-8")
    except OSError:
        flow_src = ""
    opt_in_flags = sorted(set(_OPT_IN_PATTERN.findall(flow_src)))

    has_writer = bool(writer_files)
    has_opt_in = bool(opt_in_flags)

    if has_writer and has_opt_in:
        status = "wired"
    elif not has_writer and not has_opt_in:
        status = "advisory"
    else:
        status = "partial"

    return EngineWritebackStatus(
        name=name,
        has_flow=True,
        writer_files=writer_files,
        opt_in_flags=opt_in_flags,
        status=status,
    )


def audit_writeback_coverage(
    engines_root: Path | str = "engines",
) -> WritebackCoverageReport:
    """Walk every engine directory and aggregate the
    Phase 6 / 7 writeback wireup status.

    Args:
        engines_root: Path to the engines/ directory. Tests
            pass a fixture; production callers use the default.

    Returns:
        :class:`WritebackCoverageReport` with per-engine entries
        plus counts.
    """
    root = Path(engines_root)
    if not root.is_dir():
        return WritebackCoverageReport(
            engines=[],
            wired_count=0,
            advisory_count=0,
            partial_count=0,
            total_engines=0,
        )

    statuses: list[EngineWritebackStatus] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        # Skip private / infra / cache dirs
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        statuses.append(_scan_one_engine(child))

    # Exclude non_engine infra dirs from the engine count
    real_engines = [s for s in statuses if s.status != "non_engine"]
    return WritebackCoverageReport(
        engines=real_engines,
        wired_count=sum(1 for s in real_engines if s.status == "wired"),
        advisory_count=sum(
            1 for s in real_engines if s.status == "advisory"
        ),
        partial_count=sum(
            1 for s in real_engines if s.status == "partial"
        ),
        total_engines=len(real_engines),
    )
