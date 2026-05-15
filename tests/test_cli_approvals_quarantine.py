"""Tests for ``shopai approvals quarantine`` CLI."""
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
def quarantine_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def _ns(**kw):
    defaults = dict(
        release=None, clear_release=None, exempt=None,
        unexempt=None, list=False, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestList:

    def test_default_shows_empty_state(
        self, cli, quarantine_data_dir,
    ):
        out = _capture(cli._cmd_approvals_quarantine, _ns())
        assert "Quarantine state:" in out
        assert "Exemptions (0)" in out
        assert "Released (0)" in out
        assert "Thresholds:" in out

    def test_shows_existing_state(self, cli, quarantine_data_dir):
        from core.approval.quarantine import (
            exempt_engine, release_engine,
        )
        exempt_engine("returns")
        release_engine("loyalty")
        out = _capture(cli._cmd_approvals_quarantine, _ns())
        assert "returns" in out
        assert "loyalty" in out


class TestExempt:

    def test_exempt_persists(self, cli, quarantine_data_dir):
        _capture(
            cli._cmd_approvals_quarantine, _ns(exempt="returns"),
        )
        from core.approval.quarantine import load_state
        assert "returns" in load_state().exemptions

    def test_unexempt_removes(self, cli, quarantine_data_dir):
        from core.approval.quarantine import exempt_engine
        exempt_engine("returns")
        _capture(
            cli._cmd_approvals_quarantine,
            _ns(unexempt="returns"),
        )
        from core.approval.quarantine import load_state
        assert "returns" not in load_state().exemptions


class TestRelease:

    def test_release_persists(self, cli, quarantine_data_dir):
        _capture(
            cli._cmd_approvals_quarantine, _ns(release="loyalty"),
        )
        from core.approval.quarantine import load_state
        assert "loyalty" in load_state().released

    def test_clear_release(self, cli, quarantine_data_dir):
        from core.approval.quarantine import release_engine
        release_engine("loyalty")
        _capture(
            cli._cmd_approvals_quarantine,
            _ns(clear_release="loyalty"),
        )
        from core.approval.quarantine import load_state
        assert "loyalty" not in load_state().released


class TestJsonMode:

    def test_list_json_envelope(self, cli, quarantine_data_dir):
        out = _capture(
            cli._cmd_approvals_quarantine, _ns(json=True),
        )
        data = json.loads(out)
        assert "exemptions" in data
        assert "released" in data
        assert "thresholds" in data
        assert "min_outcomes_observed" in data["thresholds"]
        assert "max_negative_ratio" in data["thresholds"]

    def test_exempt_json(self, cli, quarantine_data_dir):
        out = _capture(
            cli._cmd_approvals_quarantine,
            _ns(exempt="returns", json=True),
        )
        data = json.loads(out)
        assert data["exempted"] == "returns"
        assert "returns" in data["exemptions"]

    def test_release_json(self, cli, quarantine_data_dir):
        out = _capture(
            cli._cmd_approvals_quarantine,
            _ns(release="loyalty", json=True),
        )
        data = json.loads(out)
        assert data["released"] == "loyalty"
        assert "loyalty" in data["released_list"]

    def test_first_char_is_brace_in_json_mode(
        self, cli, quarantine_data_dir,
    ):
        out = _capture(
            cli._cmd_approvals_quarantine, _ns(json=True),
        )
        assert out.strip()[0] == "{"
