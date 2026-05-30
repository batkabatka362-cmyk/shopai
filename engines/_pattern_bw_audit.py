"""Pattern BW audit: per-store thrash guardrail surface (W927).

Companion to [[pattern-bu]] (substrate). BW guards the
W925-926 per-store override layer:

  - thrash_guardrail_enabled accepts ``store_id`` kwarg
  - per-store env var resolves before fleet
  - explicit "0" override force-disables a store
  - explicit "1" override force-enables a store
  - shopai thrash-guardrail CLI registered

Invariants:

  1. ``thrash_guardrail_enabled`` accepts a ``store_id``
     kwarg (inspect-based).
  2. Per-store env var
     ``SHOPAI_THRASH_GUARDRAIL_<STORE>=1`` enables when
     fleet is off.
  3. Per-store env var
     ``SHOPAI_THRASH_GUARDRAIL_<STORE>=0`` disables when
     fleet is on.
  4. CLI ``thrash-guardrail`` subparser registered.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBWViolation:
    invariant: str
    reason: str


@dataclass
class PatternBWReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBWViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBWReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBWViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def _save_env(*keys):
    return {k: os.environ.get(k) for k in keys}


def _restore_env(snap):
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def run_pattern_bw_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBWReport:
    """Verify the W925-926 per-store override layer."""
    report = PatternBWReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    fleet_key = "SHOPAI_THRASH_GUARDRAIL"
    probe_key = "SHOPAI_THRASH_GUARDRAIL_PROBE_STORE"
    snap = _save_env(fleet_key, probe_key)

    try:
        # 1: signature kwarg
        try:
            import inspect
            from engines._agi_context import (
                thrash_guardrail_enabled,
            )
            sig = inspect.signature(thrash_guardrail_enabled)
            _check(
                report, "accepts_store_id_kwarg",
                "store_id" in sig.parameters,
                (
                    "thrash_guardrail_enabled missing "
                    "store_id kwarg"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _check(
                report, "accepts_store_id_kwarg",
                False, f"raised: {exc!s:.100}",
            )

        # 2: per-store ON when fleet OFF
        try:
            from engines._agi_context import (
                thrash_guardrail_enabled,
            )
            os.environ.pop(fleet_key, None)
            os.environ[probe_key] = "1"
            on = thrash_guardrail_enabled("probe-store")
            _check(
                report, "per_store_on_overrides_fleet_off",
                on,
                (
                    "per-store override=1 did not enable "
                    "when fleet was off"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _check(
                report, "per_store_on_overrides_fleet_off",
                False, f"raised: {exc!s:.100}",
            )

        # 3: per-store OFF when fleet ON
        try:
            from engines._agi_context import (
                thrash_guardrail_enabled,
            )
            os.environ[fleet_key] = "1"
            os.environ[probe_key] = "0"
            on = thrash_guardrail_enabled("probe-store")
            _check(
                report, "per_store_off_overrides_fleet_on",
                not on,
                (
                    "per-store override=0 did not disable "
                    "when fleet was on"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _check(
                report, "per_store_off_overrides_fleet_on",
                False, f"raised: {exc!s:.100}",
            )

        # 4: CLI subparser
        _check(
            report, "cli_registers_thrash_guardrail_subparser",
            _file_references(
                cli_path,
                'thrash_guardrail_p = sub.add_parser',
            ),
            (
                "cli.py does not register "
                "thrash_guardrail_p subparser"
            ),
        )
    finally:
        _restore_env(snap)

    return report
