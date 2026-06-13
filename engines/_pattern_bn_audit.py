"""Pattern BN audit: autonomy-overview output schema (W893).

Verifies the W892 ``autonomy-overview`` CLI produces a
stable output schema. Operators wire this into shell
prompts + monitoring scripts that parse the line.
Regressions would silently break their integrations.

Invariants:

  1. ``OverviewSnapshot`` dataclass exposes all expected
     fields (canonical schema).
  2. CLI ``autonomy-overview`` subparser is registered.
  3. CLI text output includes the canonical ``key=value``
     tokens (verdict, armed, fires, errors, cooldown_blocked,
     alerts).
  4. CLI JSON envelope includes all snapshot fields.

Pattern BN runs the CLI in-process (Pattern J guards in
underlying logs prevent any persistence side effects).
"""
from __future__ import annotations

import contextlib
import io
import json as _json
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

logger = logging.getLogger(__name__)


_EXPECTED_FIELDS = {
    "captured_at", "store_id", "window_hours",
    "armed_total", "armed_engine_mode",
    "armed_substrate_with_discoverer",
    "armed_substrate_no_discoverer",
    "fires_total", "fires_invoked", "fires_errors",
    "cooldown_blocked",
    "alerts_critical", "alerts_warn",
}

_EXPECTED_TOKENS = (
    "verdict=", "armed=", "fires=", "errors=",
    "cooldown_blocked=", "alerts=",
)


@dataclass
class PatternBNViolation:
    invariant: str
    reason: str


@dataclass
class PatternBNReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBNViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBNReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBNViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bn_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBNReport:
    """Verify the autonomy-overview output schema."""
    report = PatternBNReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    # 1: snapshot field shape
    try:
        from core.automation.autonomy_overview import (
            OverviewSnapshot,
        )
        snap_field_names = {f.name for f in fields(
            OverviewSnapshot,
        )}
        missing = _EXPECTED_FIELDS - snap_field_names
        _check(
            report, "snapshot_has_all_fields",
            len(missing) == 0,
            (
                f"OverviewSnapshot missing fields: "
                f"{sorted(missing)}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBNViolation(
            invariant="snapshot_import",
            reason=f"import failed: {exc!s:.150}",
        ))

    # 2: CLI subparser registered
    _check(
        report, "cli_overview_subparser_registered",
        _file_references(
            cli_path,
            "autonomy_overview_p = sub.add_parser",
        ),
        (
            "cli.py does not register autonomy_overview_p "
            "subparser"
        ),
    )

    # 3 + 4: runtime invocation
    try:
        import sys as _sys
        if str(root) not in _sys.path:
            _sys.path.insert(0, str(root))
        try:
            import cli as _cli  # type: ignore
        except Exception:  # noqa: BLE001
            _cli = None
        if _cli is not None and hasattr(
            _cli, "_cmd_autonomy_overview",
        ):
            # Text mode
            class _NS_TEXT:
                window_hours = 24.0
                store = ""
                json = False
            buf_text = io.StringIO()
            with contextlib.redirect_stdout(buf_text):
                _cli._cmd_autonomy_overview(_NS_TEXT())
            text_out = buf_text.getvalue()
            missing_tokens = [
                t for t in _EXPECTED_TOKENS
                if t not in text_out
            ]
            _check(
                report, "text_output_has_all_tokens",
                len(missing_tokens) == 0,
                (
                    f"text output missing tokens: "
                    f"{missing_tokens}"
                ),
            )

            # JSON mode
            class _NS_JSON:
                window_hours = 24.0
                store = ""
                json = True
            buf_json = io.StringIO()
            with contextlib.redirect_stdout(buf_json):
                _cli._cmd_autonomy_overview(_NS_JSON())
            json_out = buf_json.getvalue()
            try:
                envelope = _json.loads(json_out)
                envelope_keys = set(envelope.keys()) | {
                    "verdict",
                }
                missing_json = (
                    (_EXPECTED_FIELDS | {"verdict"})
                    - envelope_keys
                )
                _check(
                    report, "json_envelope_has_all_fields",
                    len(missing_json) == 0,
                    (
                        f"JSON envelope missing fields: "
                        f"{sorted(missing_json)}"
                    ),
                )
            except _json.JSONDecodeError as exc:
                _check(
                    report, "json_envelope_has_all_fields",
                    False,
                    f"JSON parse failed: {exc!s:.100}",
                )
        else:
            _check(
                report, "text_output_has_all_tokens",
                False,
                "cli._cmd_autonomy_overview unreachable",
            )
            _check(
                report, "json_envelope_has_all_fields",
                False,
                "cli._cmd_autonomy_overview unreachable",
            )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBNViolation(
            invariant="runtime_invocation",
            reason=f"runtime smoke raised: {exc!s:.150}",
        ))

    return report
