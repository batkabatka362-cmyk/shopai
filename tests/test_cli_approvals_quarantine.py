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
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit:
        pass
    return buf.getvalue()


def _ns(**kw):
    defaults = dict(
        release=None, clear_release=None, exempt=None,
        unexempt=None, release_alert=None,
        release_alert_store=None, release_alert_all=False,
        apply_bridge=False, list=False, json=False,
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


# ─── alert_paused surface ────────────────────────────────────


class TestAlertPausedSurface:
    """``shopai approvals quarantine`` exposes the alert-paused
    list + the bridge config in both text and JSON modes, plus
    a ``--release-alert`` action to clear the auto-pause."""

    def test_default_list_includes_alert_paused_section(
        self, cli, quarantine_data_dir,
    ):
        out = _capture(cli._cmd_approvals_quarantine, _ns())
        assert "Alert-paused (0)" in out
        assert "Alert-quarantine bridge" in out

    def test_default_list_shows_alert_paused_engines(
        self, cli, quarantine_data_dir,
    ):
        from core.approval.quarantine import add_alert_pause
        add_alert_pause("loyalty")
        add_alert_pause("affiliate")
        out = _capture(cli._cmd_approvals_quarantine, _ns())
        assert "Alert-paused (2)" in out
        # Engines listed alphabetically in the comma-joined line
        assert "affiliate" in out
        assert "loyalty" in out

    def test_json_mode_includes_alert_paused_key(
        self, cli, quarantine_data_dir,
    ):
        from core.approval.quarantine import add_alert_pause
        add_alert_pause("loyalty")
        out = _capture(
            cli._cmd_approvals_quarantine, _ns(json=True),
        )
        data = json.loads(out)
        # New format: list of [engine, store_id] pairs
        assert data["alert_paused"] == [["loyalty", None]]
        assert "alert_quarantine" in data
        assert "enabled" in data["alert_quarantine"]
        assert "threshold_days" in data["alert_quarantine"]

    def test_json_mode_reflects_env_var_enabled(
        self, cli, quarantine_data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        out = _capture(
            cli._cmd_approvals_quarantine, _ns(json=True),
        )
        data = json.loads(out)
        assert data["alert_quarantine"]["enabled"] is True

    def test_release_alert_clears_state(
        self, cli, quarantine_data_dir,
    ):
        from core.approval.quarantine import (
            add_alert_pause, load_state,
        )
        add_alert_pause("loyalty")
        add_alert_pause("affiliate")
        assert load_state().is_alert_paused("loyalty")

        out = _capture(
            cli._cmd_approvals_quarantine,
            _ns(release_alert="loyalty"),
        )
        assert "Cleared alert-pause on 'loyalty'" in out
        s = load_state()
        assert not s.is_alert_paused("loyalty")
        assert s.is_alert_paused("affiliate")

    def test_release_alert_json(
        self, cli, quarantine_data_dir,
    ):
        from core.approval.quarantine import add_alert_pause
        add_alert_pause("loyalty")
        out = _capture(
            cli._cmd_approvals_quarantine,
            _ns(release_alert="loyalty", json=True),
        )
        data = json.loads(out)
        assert data["released_from_alert_pause"] == "loyalty"
        assert data["alert_paused"] == []

    def test_release_alert_with_store_clears_only_that_store(
        self, cli, quarantine_data_dir,
    ):
        """``--release-alert ENGINE --release-alert-store
        STORE_ID`` drops only the per-store pause."""
        from core.approval.quarantine import (
            add_alert_pause, load_state,
        )
        add_alert_pause("loyalty")  # fleet-wide
        add_alert_pause("loyalty", store_id="store_a")
        add_alert_pause("loyalty", store_id="store_b")
        out = _capture(
            cli._cmd_approvals_quarantine,
            _ns(
                release_alert="loyalty",
                release_alert_store="store_a",
            ),
        )
        assert "Cleared alert-pause" in out
        s = load_state()
        # fleet-wide + store_b still paused; store_a released
        assert ("loyalty", None) in s.alert_paused
        assert ("loyalty", "store_a") not in s.alert_paused
        assert ("loyalty", "store_b") in s.alert_paused

    def test_release_alert_all_drops_every_pause(
        self, cli, quarantine_data_dir,
    ):
        """``--release-alert-all`` drops fleet + every store."""
        from core.approval.quarantine import (
            add_alert_pause, load_state,
        )
        add_alert_pause("loyalty")
        add_alert_pause("loyalty", store_id="store_a")
        add_alert_pause("loyalty", store_id="store_b")
        add_alert_pause("affiliate")
        _capture(
            cli._cmd_approvals_quarantine,
            _ns(
                release_alert="loyalty",
                release_alert_all=True,
            ),
        )
        s = load_state()
        # All loyalty pauses gone; affiliate untouched
        assert not any(
            engine == "loyalty"
            for (engine, _store) in s.alert_paused
        )
        assert ("affiliate", None) in s.alert_paused

    def test_release_alert_on_unknown_engine_clean_state(
        self, cli, quarantine_data_dir,
    ):
        """Releasing an engine not in alert_paused is a no-op
        — the set just doesn't gain or lose anything."""
        from core.approval.quarantine import load_state
        # No engines paused
        _capture(
            cli._cmd_approvals_quarantine,
            _ns(release_alert="not_there"),
        )
        assert load_state().alert_paused == frozenset()


class TestApplyBridge:
    """``--apply-bridge`` manually fires the alert-quarantine
    bridge. Normally only daily-brief calls it; this gives
    operators a way to force a run without waiting."""

    def test_disabled_renders_skipped(
        self, cli, quarantine_data_dir, monkeypatch,
    ):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )
        out = _capture(
            cli._cmd_approvals_quarantine,
            _ns(apply_bridge=True),
        )
        assert "Skipped" in out
        assert "bridge disabled" in out

    def test_disabled_json_envelope(
        self, cli, quarantine_data_dir, monkeypatch,
    ):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )
        out = _capture(
            cli._cmd_approvals_quarantine,
            _ns(apply_bridge=True, json=True),
        )
        data = json.loads(out)
        assert data["status"] == "skipped"
        assert data["reason"] == "bridge_disabled"
        assert data["paused"] == []

    def test_enabled_no_candidates_renders_nothing_paused(
        self, cli, quarantine_data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        with patch(
            "core.approval.alert_quarantine."
            "maybe_auto_quarantine_from_alerts",
            return_value=[],
        ):
            out = _capture(
                cli._cmd_approvals_quarantine,
                _ns(apply_bridge=True),
            )
        assert "no engines crossed" in out

    def test_enabled_with_candidates_renders_paused(
        self, cli, quarantine_data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        with patch(
            "core.approval.alert_quarantine."
            "maybe_auto_quarantine_from_alerts",
            return_value=["loyalty", "affiliate"],
        ):
            out = _capture(
                cli._cmd_approvals_quarantine,
                _ns(apply_bridge=True),
            )
        assert "paused 2 engine(s)" in out
        assert "loyalty" in out
        assert "affiliate" in out

    def test_enabled_json_envelope_with_candidates(
        self, cli, quarantine_data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        with patch(
            "core.approval.alert_quarantine."
            "maybe_auto_quarantine_from_alerts",
            return_value=["loyalty"],
        ):
            out = _capture(
                cli._cmd_approvals_quarantine,
                _ns(apply_bridge=True, json=True),
            )
        data = json.loads(out)
        assert data["status"] == "success"
        assert data["count"] == 1
        assert data["newly_paused"] == ["loyalty"]

    def test_bridge_raise_exits_1(
        self, cli, quarantine_data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        with patch(
            "core.approval.alert_quarantine."
            "maybe_auto_quarantine_from_alerts",
            side_effect=RuntimeError("disk corrupt"),
        ):
            out = _capture(
                cli._cmd_approvals_quarantine,
                _ns(apply_bridge=True),
            )
        assert "Error" in out
        assert "disk corrupt" in out
