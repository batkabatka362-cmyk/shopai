"""Tests for ``shopai approvals auto-config`` — auto-approve
allowlist management CLI.

Three modes (mutually exclusive):
  - ``--enable ENGINE`` adds to allowlist
  - ``--disable ENGINE`` removes from allowlist
  - ``--list`` (or no flag) shows current state + thresholds

The persisted config is JSON at SHOPAI_DATA_DIR or data/. Both
text and --json output modes covered.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
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


@pytest.fixture
def auto_approve_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


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
    defaults = dict(enable=None, disable=None, list=False, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestList:

    def test_default_no_flag_shows_state(
        self, cli, auto_approve_data_dir,
    ):
        out, code = _capture(cli._cmd_approvals_auto_config, _ns())
        assert code == 0
        assert "Auto-approve configuration:" in out
        assert "Allowlist" in out
        assert "Thresholds:" in out
        # Empty allowlist → safe-default note
        assert "empty" in out

    def test_explicit_list_flag(self, cli, auto_approve_data_dir):
        out, code = _capture(
            cli._cmd_approvals_auto_config, _ns(list=True),
        )
        assert code == 0
        assert "Auto-approve configuration:" in out

    def test_list_shows_threshold_values(
        self, cli, auto_approve_data_dir,
    ):
        out, _ = _capture(cli._cmd_approvals_auto_config, _ns())
        # Defaults from auto_approve module
        assert "min outcomes observed" in out
        assert "min outcome ratio" in out
        assert "min confidence" in out

    def test_list_includes_enabled_engines(
        self, cli, auto_approve_data_dir,
    ):
        from core.approval.auto_approve import enable_engine
        enable_engine("cart_recovery")
        enable_engine("loyalty")
        out, _ = _capture(cli._cmd_approvals_auto_config, _ns())
        assert "cart_recovery" in out
        assert "loyalty" in out


class TestEnable:

    def test_enable_persists_engine(self, cli, auto_approve_data_dir):
        out, code = _capture(
            cli._cmd_approvals_auto_config,
            _ns(enable="cart_recovery"),
        )
        assert code == 0
        assert "cart_recovery" in out
        # Re-reading the config shows it
        from core.approval.auto_approve import load_config
        assert "cart_recovery" in load_config().allowlist

    def test_enable_json_mode(self, cli, auto_approve_data_dir):
        out, _ = _capture(
            cli._cmd_approvals_auto_config,
            _ns(enable="loyalty", json=True),
        )
        data = json.loads(out)
        assert data["enabled"] == "loyalty"
        assert "loyalty" in data["allowlist"]


class TestDisable:

    def test_disable_removes_engine(self, cli, auto_approve_data_dir):
        from core.approval.auto_approve import enable_engine
        enable_engine("a")
        enable_engine("b")
        out, code = _capture(
            cli._cmd_approvals_auto_config, _ns(disable="a"),
        )
        assert code == 0
        from core.approval.auto_approve import load_config
        cfg = load_config()
        assert "a" not in cfg.allowlist
        assert "b" in cfg.allowlist

    def test_disable_nonexistent_engine_is_noop(
        self, cli, auto_approve_data_dir,
    ):
        """Removing an engine that wasn't in the allowlist is a
        no-op, not an error — keeps the CLI idempotent for
        automation."""
        out, code = _capture(
            cli._cmd_approvals_auto_config, _ns(disable="ghost"),
        )
        assert code == 0


class TestJsonOutput:

    def test_list_json_includes_thresholds(
        self, cli, auto_approve_data_dir,
    ):
        out, _ = _capture(
            cli._cmd_approvals_auto_config, _ns(json=True),
        )
        data = json.loads(out)
        assert "allowlist" in data
        assert "thresholds" in data
        assert "min_outcomes_observed" in data["thresholds"]
        assert "min_outcome_ratio" in data["thresholds"]
        assert "min_confidence" in data["thresholds"]

    def test_list_json_first_char_is_brace(
        self, cli, auto_approve_data_dir,
    ):
        """jq-friendly: no text prefix."""
        out, _ = _capture(
            cli._cmd_approvals_auto_config, _ns(json=True),
        )
        assert out.strip()[0] == "{"
