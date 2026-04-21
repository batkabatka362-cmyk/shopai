"""Argparse help-string safety lint.

argparse's ``HelpFormatter._expand_help`` applies ``%``-formatting
to every help string when rendering. A literal ``%`` in source
(e.g. ``60%``) crashes with ``ValueError: unsupported format
character`` at help-display time. This tripped the CI in PR #21.

This test scans cli.py for every ``help=`` keyword string
literal and asserts no unescaped ``%`` appears. ``%%`` (the
argparse escape that renders as ``%``) is allowed. Non-string
values (f-strings, computed values) are skipped — argparse
doesn't format those.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


def _extract_help_strings(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, text) for every string literal passed
    as a ``help=`` keyword argument to a function call at the
    module's top level or inside a def.

    Multi-part implicit-concatenated string constants (as
    argparse help lines usually are) show up as a single
    ``ast.Constant`` after Python parses them.
    """
    tree = ast.parse(path.read_text())
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "help":
                continue
            v = kw.value
            if isinstance(v, ast.Constant) and isinstance(
                v.value, str,
            ):
                out.append((v.lineno, v.value))
            # Parenthesised multi-line strings show up as
            # a Constant; bare tuple of strings via ("a" "b")
            # also becomes a Constant at parse time.
    return out


# ``%`` followed by a single char that is NOT ``%`` AND is not
# a valid argparse-printf format char is what crashes. The
# simple heuristic: every ``%`` must be immediately followed
# by another ``%`` (the escape) — otherwise the string is
# fragile.
_UNESCAPED_PCT = re.compile(r"%(?!%|\Z)")


class TestArgparseHelpSafety(unittest.TestCase):
    def test_cli_help_strings_escape_percent(self):
        cli_path = Path("cli.py")
        strings = _extract_help_strings(cli_path)
        offenders: list[tuple[int, str]] = []
        for lineno, text in strings:
            # Replace %% with empty string, then any
            # remaining % is unescaped.
            scrubbed = text.replace("%%", "")
            if "%" in scrubbed:
                offenders.append((lineno, text[:80]))
        self.assertEqual(
            offenders, [],
            msg=(
                "argparse help= strings with unescaped %:\n"
                + "\n".join(
                    f"  cli.py:{ln}: {s!r}"
                    for ln, s in offenders
                )
                + "\n\nUse %% if you need a literal percent."
            ),
        )


if __name__ == "__main__":
    unittest.main()
