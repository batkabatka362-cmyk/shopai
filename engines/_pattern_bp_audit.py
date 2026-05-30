"""Pattern BP audit: autonomy-overview output formats (W899).

Companion to [[pattern-bn]]. BN guards the default text +
JSON schema; BP guards the W897-898 alternate formats
(--markdown + --shell-prompt). Niche operator integrations
(PR comments, status pages, shell prompts) parse these
outputs, so silent breakage would corrupt their flows.

Invariants:

  1. ``render_text`` exported by autonomy_overview module.
  2. ``render_markdown`` exported and produces a markdown
     table (contains the ``|---`` separator + the ``verdict``
     header cell).
  3. ``render_shell_prompt`` exported and produces a short
     bracket-marker token (``[.]`` / ``[~]`` / ``[>]`` /
     ``[!]`` prefix).
  4. CLI ``autonomy-overview`` subparser registers the
     ``--markdown`` flag.
  5. CLI ``autonomy-overview`` subparser registers the
     ``--shell-prompt`` flag.

Pattern BP exercises the render functions directly +
text-greps cli.py for the flag registration.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBPViolation:
    invariant: str
    reason: str


@dataclass
class PatternBPReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBPViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBPReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBPViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bp_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBPReport:
    """Verify the autonomy-overview alternate output formats."""
    report = PatternBPReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    # 1: render_text exported + working
    try:
        from core.automation.autonomy_overview import (
            OverviewSnapshot, render_text,
        )
        out = render_text(OverviewSnapshot())
        _check(
            report, "render_text_exports_string",
            isinstance(out, str) and "verdict=" in out,
            "render_text output missing 'verdict=' token",
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "render_text_exports_string", False,
            f"render_text raised: {exc!s:.100}",
        )

    # 2: render_markdown exported + valid markdown
    try:
        from core.automation.autonomy_overview import (
            OverviewSnapshot, render_markdown,
        )
        out = render_markdown(OverviewSnapshot())
        ok = (
            isinstance(out, str)
            and "|---" in out
            and "verdict" in out
        )
        _check(
            report, "render_markdown_exports_table",
            ok,
            (
                "render_markdown output missing markdown "
                "table separator '|---' or 'verdict' header"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "render_markdown_exports_table", False,
            f"render_markdown raised: {exc!s:.100}",
        )

    # 3: render_shell_prompt exported + valid prompt token
    try:
        from core.automation.autonomy_overview import (
            OverviewSnapshot, render_shell_prompt,
        )
        out = render_shell_prompt(OverviewSnapshot())
        ok = (
            isinstance(out, str)
            and any(out.startswith(m) for m in (
                "[.]", "[~]", "[>]", "[!]", "[?]",
            ))
            and not out.endswith("\n")
        )
        _check(
            report, "render_shell_prompt_exports_token",
            ok,
            (
                "render_shell_prompt output missing bracket "
                "marker prefix OR has trailing newline"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "render_shell_prompt_exports_token", False,
            f"render_shell_prompt raised: {exc!s:.100}",
        )

    # 4: --markdown CLI flag
    _check(
        report, "cli_registers_markdown_flag",
        _file_references(
            cli_path,
            'autonomy_overview_p.add_argument(',
            '"--markdown"',
        ),
        (
            "cli.py does not register --markdown on "
            "autonomy_overview_p"
        ),
    )

    # 5: --shell-prompt CLI flag
    _check(
        report, "cli_registers_shell_prompt_flag",
        _file_references(
            cli_path,
            'autonomy_overview_p.add_argument(',
            '"--shell-prompt"',
        ),
        (
            "cli.py does not register --shell-prompt on "
            "autonomy_overview_p"
        ),
    )

    return report
