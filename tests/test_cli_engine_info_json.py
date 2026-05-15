"""Tests for ``shopai engine-info --json``.

The default text view is operator-friendly; the JSON output gives
automation / monitoring tools a parseable representation of the
same fields.

Also includes the fix for the previously-latent bug: passing an
unknown engine name rendered ``Class: NoneType`` instead of
exiting 1.
"""
from __future__ import annotations

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


# ─── text view (backward-compat) ─────────────────────────────────


class TestTextView:

    def test_text_view_renders_basic_fields(self, cli):
        out, code = _capture(
            cli._cmd_engine_info, "cart_recovery",
        )
        assert code == 0
        assert "Engine:" in out
        assert "Class:" in out

    def test_default_json_flag_off(self, cli):
        """Without ``as_json=True``, text view is used."""
        out, code = _capture(
            cli._cmd_engine_info, "cart_recovery", False,
        )
        assert code == 0
        # First char is "E" (Engine), not "{" (JSON)
        assert out.strip()[0] == "E"


# ─── JSON view ───────────────────────────────────────────────────


class TestJsonView:

    def test_json_view_emits_valid_json(self, cli):
        out, code = _capture(
            cli._cmd_engine_info, "cart_recovery", True,
        )
        assert code == 0
        data = json.loads(out)
        assert "name" in data
        assert "class" in data

    def test_json_view_has_inputs_outputs(self, cli):
        """Even when empty, the inputs/outputs keys are present
        so callers can rely on the schema."""
        out, code = _capture(
            cli._cmd_engine_info, "cart_recovery", True,
        )
        data = json.loads(out)
        assert "inputs" in data
        assert "outputs" in data

    def test_json_view_no_text_prefix(self, cli):
        """JSON output is jq-friendly — first non-whitespace char
        is ``{``, no human-readable banner before."""
        out, _ = _capture(
            cli._cmd_engine_info, "cart_recovery", True,
        )
        assert out.strip()[0] == "{"
        assert "Engine: " not in out


# ─── unknown-engine fix ──────────────────────────────────────────


class TestUnknownEngine:

    def test_unknown_engine_text_exits_1(self, cli):
        """Pre-PR latent bug: ``engine-info <unknown>`` would
        render ``Class: NoneType``. Now exits 1 with message."""
        out, code = _capture(
            cli._cmd_engine_info, "definitely_not_a_real_engine_xyz",
        )
        assert code == 1
        assert "Unknown engine" in out

    def test_unknown_engine_json_exits_1(self, cli):
        """Unknown engine in JSON mode → exit 1 with structured
        error payload."""
        out, code = _capture(
            cli._cmd_engine_info,
            "definitely_not_a_real_engine_xyz",
            True,
        )
        assert code == 1
        data = json.loads(out)
        assert "error" in data
        assert "Unknown engine" in data["error"]
