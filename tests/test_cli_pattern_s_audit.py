"""Tests for ``shopai pattern-s-audit``."""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(json=False, strict=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _report(sites):
    from engines._pattern_s_audit import PatternSReport, SilentSite
    return PatternSReport(
        silent_sites=[
            SilentSite(file=f, lineno=ln)
            for f, ln in sites
        ],
        scanned_modules=100,
    )


class TestNoViolations:

    def test_clean_exits_0_text(self, cli):
        with patch(
            "engines._pattern_s_audit.audit_pattern_s",
            return_value=_report([]),
        ):
            out, code = _capture(
                cli._cmd_pattern_s_audit, _ns(),
            )
        assert code == 0
        assert "Pattern S OK" in out
        assert "100 scanned" in out

    def test_clean_exits_0_json(self, cli):
        with patch(
            "engines._pattern_s_audit.audit_pattern_s",
            return_value=_report([]),
        ):
            out, code = _capture(
                cli._cmd_pattern_s_audit, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["silent_count"] == 0


class TestViolations:

    def test_violations_default_exits_0(self, cli):
        """Default behavior is INFORMATIONAL -- exit 0 even
        with violations. ``--strict`` opts in to gating."""
        with patch(
            "engines._pattern_s_audit.audit_pattern_s",
            return_value=_report([
                ("a/b.py", 10), ("a/b.py", 25),
                ("c/d.py", 5),
            ]),
        ):
            out, code = _capture(
                cli._cmd_pattern_s_audit, _ns(),
            )
        assert code == 0  # informational by default
        assert "found" in out.lower()
        # Files grouped, line numbers sorted
        assert "a/b.py: 10, 25" in out
        assert "c/d.py: 5" in out
        # Fix-template hint surfaces
        assert "logger.debug" in out or "logger.warning" in out

    def test_violations_strict_exits_1(self, cli):
        with patch(
            "engines._pattern_s_audit.audit_pattern_s",
            return_value=_report([("x.py", 1)]),
        ):
            out, code = _capture(
                cli._cmd_pattern_s_audit,
                _ns(strict=True),
            )
        assert code == 1
        assert "FAILED" in out

    def test_violations_json_round_trips_sites(self, cli):
        with patch(
            "engines._pattern_s_audit.audit_pattern_s",
            return_value=_report([
                ("api/telegram_bot.py", 75),
                ("api/telegram_bot.py", 99),
            ]),
        ):
            out, code = _capture(
                cli._cmd_pattern_s_audit,
                _ns(json=True),
            )
        # Informational default -- still exit 0
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is False
        assert data["silent_count"] == 2
        files = [s["file"] for s in data["silent_sites"]]
        assert files == [
            "api/telegram_bot.py",
            "api/telegram_bot.py",
        ]

    def test_violations_json_strict_exits_1(self, cli):
        with patch(
            "engines._pattern_s_audit.audit_pattern_s",
            return_value=_report([("x.py", 1)]),
        ):
            out, code = _capture(
                cli._cmd_pattern_s_audit,
                _ns(json=True, strict=True),
            )
        assert code == 1


class TestResilience:

    def test_audit_raise_friendly(self, cli):
        with patch(
            "engines._pattern_s_audit.audit_pattern_s",
            side_effect=RuntimeError("audit broke"),
        ):
            out, code = _capture(
                cli._cmd_pattern_s_audit, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()
