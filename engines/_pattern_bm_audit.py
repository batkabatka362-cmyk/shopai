"""Pattern BM audit: autonomy-env --store plumbing (W891).

Verifies the W890 ``autonomy-env --store`` flag is registered
on the subparser AND the handler renders per-store env names
when invoked with --store.

Invariants:

  1. ``cli.py autonomy_env_p`` registers ``--store`` flag.
  2. ``cli.py _cmd_autonomy_env`` references ``store_token``
     (the per-store rendering identifier used in the W890
     handler).
  3. ``cli.py _cmd_autonomy_env`` references the per-store
     suffix concatenation pattern (``f"{k.name}_{...}"``).
  4. ``shopai autonomy-env --store STORE_X --domain
     shipping_alert`` runtime call produces output containing
     ``STORE_X`` -- belt-and-braces runtime check on top of
     the AST grep.

Companion to Pattern BG (read-side CLI plumbing breadth) but
specifically for the autonomy-env knob discovery surface,
which serves a different operator workflow (config tuning vs.
status reading).
"""
from __future__ import annotations

import contextlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBMViolation:
    invariant: str
    reason: str


@dataclass
class PatternBMReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBMViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBMReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBMViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bm_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBMReport:
    """Verify autonomy-env --store plumbing."""
    report = PatternBMReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    _check(
        report, "cli_autonomy_env_has_store_flag",
        _file_references(
            cli_path,
            "autonomy_env_p.add_argument",
            '"--store"',
        ),
        (
            "cli.py autonomy_env_p does not register "
            "--store flag"
        ),
    )
    _check(
        report, "handler_references_store_token",
        _file_references(
            cli_path, "_cmd_autonomy_env", "store_token",
        ),
        (
            "cli.py _cmd_autonomy_env does not reference "
            "store_token -- per-store rendering missing"
        ),
    )
    _check(
        report, "handler_renders_per_store_suffix",
        _file_references(
            cli_path,
            "_cmd_autonomy_env",
            'f"{k.name}_{store_token}"',
        ),
        (
            "cli.py _cmd_autonomy_env does not render "
            "per-store suffix via f-string concatenation"
        ),
    )

    # Runtime belt-and-braces: call the handler in-process via
    # the registered command wrapper.
    try:
        # We need to import cli, build argparse for autonomy-env
        # and invoke. To keep the audit lightweight we use a
        # minimal namespace + call the handler function
        # directly.
        import sys as _sys
        sys_path = list(_sys.path)
        if str(root) not in sys_path:
            _sys.path.insert(0, str(root))
        try:
            import cli as _cli  # type: ignore
        except Exception:  # noqa: BLE001
            _cli = None
        if _cli is not None and hasattr(
            _cli, "_cmd_autonomy_env",
        ):
            class _NS:
                store = "STORE_XYZ"
                domain = "shipping_alert"
                set_only = False
                json = False
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    _cli._cmd_autonomy_env(_NS())
                output = buf.getvalue()
                _check(
                    report, "runtime_renders_per_store_suffix",
                    "STORE_XYZ" in output,
                    (
                        "runtime autonomy-env --store=STORE_XYZ "
                        "did NOT include STORE_XYZ in output"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                _check(
                    report, "runtime_renders_per_store_suffix",
                    False,
                    f"handler raised: {exc!s:.150}",
                )
        else:
            _check(
                report, "runtime_renders_per_store_suffix",
                False,
                "cli._cmd_autonomy_env unreachable for runtime "
                "smoke",
            )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBMViolation(
            invariant="runtime_renders_per_store_suffix",
            reason=f"runtime smoke raised: {exc!s:.150}",
        ))

    return report
