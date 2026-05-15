"""Regression test: ``shopai --help`` must not contain characters
that fail to encode on the Windows cp1252 console.

History
  Two subparsers' ``help=`` text contained the U+2192 RIGHTWARDS
  ARROW glyph. Reading ``python cli.py --help`` on Windows
  crashed with::

    UnicodeEncodeError: 'charmap' codec can't encode character
    '\\u2192' in position 5183: character maps to <undefined>

  cp1252 has fallbacks for em-dash (U+2014 -> 0x97), en-dash,
  and curly quotes — but no fallback for arrows or many other
  unicode glyphs. The crash hit on ANY Windows shell without
  ``PYTHONUTF8=1`` set.

This test AST-walks ``cli.py``, finds every
``add_parser``/``add_argument`` call's ``help`` / ``description`` /
``epilog`` keyword, and asserts every string constant in those
values encodes cleanly as cp1252.

Adding a new arrow / arbitrary unicode glyph to a CLI help
string now fails this test instead of crashing Windows users.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _walk_help_strings(src: str):
    """Yield (lineno, arg_name, string_value) for every help /
    description / epilog string literal in an argparse call."""
    tree = ast.parse(src)
    targets = {"add_parser", "add_argument", "ArgumentParser",
               "add_subparsers"}
    fields = {"help", "description", "epilog"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = ""
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id
        if func_name not in targets:
            continue
        for kw in node.keywords:
            if kw.arg not in fields:
                continue
            for sub in ast.walk(kw.value):
                if (
                    isinstance(sub, ast.Constant)
                    and isinstance(sub.value, str)
                ):
                    yield node.lineno, kw.arg, sub.value


def test_every_argparse_help_string_is_cp1252_safe():
    cli_path = Path(__file__).resolve().parent.parent / "cli.py"
    src = cli_path.read_text(encoding="utf-8")
    offenders = []
    for lineno, arg, text in _walk_help_strings(src):
        for ch in text:
            if ord(ch) <= 127:
                continue
            try:
                ch.encode("cp1252")
            except UnicodeEncodeError:
                offenders.append({
                    "line": lineno,
                    "arg": arg,
                    "char": f"U+{ord(ch):04X}",
                    "context": text[:80],
                })
                # one report per string is enough
                break
    if offenders:
        report = "\n".join(
            f"  L{o['line']} {o['arg']}={o['char']}: {o['context']!r}"
            for o in offenders
        )
        pytest.fail(
            "cli.py argparse help/description/epilog strings "
            f"contain {len(offenders)} cp1252-illegal "
            f"character(s):\n{report}\n\nUse ASCII (e.g. '->') "
            "instead of unicode arrows so `python cli.py --help` "
            "works on Windows without PYTHONUTF8=1."
        )


def test_cli_help_does_not_crash_under_cp1252():
    """End-to-end: run ``python cli.py --help`` with the I/O
    encoding forced to cp1252 (matches the default Windows
    console). The process must exit cleanly (returncode 0).

    Catches the exact crash class that motivated this test:
    a U+XXXX char with no cp1252 mapping kills argparse's
    print_help() before any output reaches the user.
    """
    import os
    import subprocess
    import sys
    cli_path = Path(__file__).resolve().parent.parent / "cli.py"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "0"
    env["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, str(cli_path), "--help"],
        capture_output=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        pytest.fail(
            f"`python cli.py --help` exited {result.returncode} "
            f"under cp1252 I/O. stderr:\n{stderr}\n\n"
            "This is the Windows-default failure mode — replace "
            "the offending unicode char with ASCII."
        )
